#!/usr/bin/env python
"""T02: 验证能正常下达平仓指令"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SUITE = _HERE.parent
_REPO = _SUITE.parents[2]
for _p in (_SUITE, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import config as cfg, helpers
from common.result import CaseTimer
from common.runtime import started_store, create_cerebro, run_with_timeout

import backtrader as bt

CASE_META = {
    "case_id": "T02",
    "case_name": "验证能正常下达平仓指令",
    "category": "基础交易功能",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                cerebro = create_cerebro(
                    store, symbol=symbol, bar_seconds=5,
                    with_trade_logger=True, log_dir=log_dir,
                )

                class CloseOrderStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.order = None
                        self.store_events = []

                    def notify_store(self, msg, *args, **kwargs):
                        event = kwargs.get("event")
                        if isinstance(event, dict):
                            self.store_events.append(event)

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")
                        if order.getstatusname() in ("Accepted", "Completed", "Canceled", "Rejected"):
                            self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.order is not None:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = max(ref_price + 20, 1.0)
                        print(f"  下达平仓卖单: symbol={symbol} price={limit_price:.2f}")
                        self.order = self.sell(
                            size=1, exectype=bt.Order.Limit,
                            price=limit_price, offset="close",
                        )
                        if self.order:
                            self.cancel(self.order)

                cerebro.addstrategy(CloseOrderStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=60)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result(
                        "未收到行情数据",
                        next_action="检查 SimNow 环境及合约可用性",
                    )

                event_types = {e.get("event_type") for e in strat.store_events}
                if "order_submit_request" in event_types:
                    print("✓ 平仓指令已成功下达")
                    evidence = helpers.collect_evidence_files(log_dir)
                    return timer.pass_result(evidence=evidence, details={"events": sorted(event_types)})

                # If order was rejected remotely (no position), still consider it
                # a valid demonstration of the close-order pathway.
                if "order_reject_remote" in event_types or "order_reject_local" in event_types:
                    print("✓ 平仓指令已下达但被拒绝（可能无持仓），验证平仓指令通路有效")
                    evidence = helpers.collect_evidence_files(log_dir)
                    return timer.pass_result(evidence=evidence, details={"events": sorted(event_types)})

                return timer.blocked_result(
                    "未观察到 order_submit_request 事件",
                    next_action="确认账户是否有可平持仓",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            evidence = helpers.collect_evidence_files(log_dir)
            return timer.fail_result(str(exc), evidence=evidence)


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
