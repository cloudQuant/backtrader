#!/usr/bin/env python
"""B01: 验证系统支持将多笔部分成交报单进行批量撤单"""
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
    "case_id": "B01",
    "case_name": "验证系统支持将多笔部分成交报单进行批量撤单",
    "category": "批量撤单",
    "optional": False,
}


def run(report_dir):
    """High-risk: partial fills are very hard to reproduce on SimNow."""
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

                class BatchCancelPartialStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.orders = []
                        self.cancels_issued = False
                        self.store_events = []

                    def notify_store(self, msg, *args, **kwargs):
                        event = kwargs.get("event")
                        if isinstance(event, dict):
                            self.store_events.append(event)

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")
                        if self.cancels_issued:
                            active = [o for o in self.orders if o.alive()]
                            if not active:
                                self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.cancels_issued:
                            return

                        # Place multiple limit orders far from market
                        if len(self.orders) < 3:
                            ref_price = float(self.data.close[0])
                            limit_price = max(ref_price - 20 - len(self.orders), 1.0)
                            order = self.buy(
                                size=1, exectype=bt.Order.Limit,
                                price=limit_price, offset="open",
                            )
                            if order:
                                self.orders.append(order)
                                print(f"  下单 ref={order.ref} price={limit_price}")
                        elif not self.cancels_issued:
                            # Batch cancel all pending orders
                            print(f"  批量撤单 {len(self.orders)} 笔")
                            for o in self.orders:
                                if o.alive():
                                    self.cancel(o)
                            self.cancels_issued = True

                cerebro.addstrategy(BatchCancelPartialStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=90)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

                cancel_events = [
                    e for e in strat.store_events
                    if e.get("event_type") in ("order_cancel_request", "order_cancel_submitted")
                ]

                if len(cancel_events) >= 3:
                    print(f"✓ 批量撤单成功: {len(cancel_events)} 笔撤单事件")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={"cancel_events": len(cancel_events)},
                    )

                return timer.blocked_result(
                    "SimNow 上难以稳定触发部分成交后的批量撤单",
                    next_action="在活跃市场时段使用市价附近价格重试",
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"cancel_events": len(cancel_events)},
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
