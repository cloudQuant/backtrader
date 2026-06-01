#!/usr/bin/env python
"""T03: 验证能正常下达撤单指令"""
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
    "case_id": "T03",
    "case_name": "验证能正常下达撤单指令",
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

                class CancelOrderStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.order = None
                        self.remote_events = set()
                        self.store_events = []

                    def notify_store(self, msg, *args, **kwargs):
                        event = kwargs.get("event")
                        if not isinstance(event, dict):
                            return
                        self.store_events.append(event)
                        et = event.get("event_type", "")
                        if et in ("order_status_canceled", "order_reject_remote"):
                            self.remote_events.add(et)
                            self.cerebro.runstop()

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")

                    def next(self):
                        self.bar_count += 1
                        if self.order is not None:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = max(ref_price - 20, 1.0)
                        self.order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=limit_price, offset="open",
                        )
                        if self.order:
                            print(f"  提交后立即撤单: ref={self.order.ref}")
                            self.cancel(self.order)

                cerebro.addstrategy(CancelOrderStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=60)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

                event_types = {e.get("event_type") for e in strat.store_events}
                assert "order_cancel_request" in event_types, "Missing order_cancel_request"
                print("✓ 撤单指令已成功下达并确认 order_cancel_request")

                evidence = helpers.collect_evidence_files(log_dir)
                return timer.pass_result(
                    evidence=evidence,
                    details={"events": sorted(event_types), "remote": sorted(strat.remote_events)},
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
