#!/usr/bin/env python
"""B02: Verify that the system supports batch canceling multiple submitted orders"""
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
from common.runtime import started_store, create_cerebro, run_with_timeout, ensure_ctp_trading_admission, live_seed_bar

import backtrader as bt

CASE_META = {
    "case_id": "B02",
    "case_name": "验证系统支持将多笔已报单进行批量撤单",
    "category": "批量撤单",
    "optional": False,
}


def run(report_dir):
    """Run B02 batch cancel pending test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                cerebro = create_cerebro(
                    store,
                    historical_bars=[live_seed_bar(store, symbol)],
                    symbol=symbol,
                    bar_seconds=5,
                    with_trade_logger=True,
                    log_dir=log_dir,
                )

                class BatchCancelPendingStrategy(bt.Strategy):
                    """Strategy for testing batch cancel of pending orders."""

                    TERMINAL = ("Canceled", "Rejected", "Completed", "Expired", "Margin")

                    def __init__(self):
                        """Initialize batch cancel pending strategy."""
                        self.bar_count = 0
                        self.orders = []
                        self.cancels_issued = False
                        self.submit_statuses = []
                        self.cancel_statuses = []
                        self.status_by_ref = {}

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        status = order.getstatusname()
                        self.status_by_ref[order.ref] = status
                        print(f"  order_notify: ref={order.ref} status={status}")
                        if self.cancels_issued and all(
                            self.status_by_ref.get(o.ref) in self.TERMINAL
                            for o in self.orders
                        ):
                            self.cerebro.runstop()

                    def next(self):
                        """Process bar and submit batch cancel orders."""
                        self.bar_count += 1
                        if self.cancels_issued:
                            return

                        ref_price = float(self.data.close[0])
                        while len(self.orders) < 3:
                            limit_price = max(ref_price - 20 - len(self.orders), 1.0)
                            ensure_ctp_trading_admission(store, symbol)
                            order = self.buy(
                                size=1, exectype=bt.Order.Limit,
                                price=limit_price, offset="open", position_side="long",
                            )
                            if order:
                                self.orders.append(order)
                                self.submit_statuses.append(order.getstatusname())
                                print(f"  下单 ref={order.ref} price={limit_price} status={order.getstatusname()}")

                        print(f"  批量撤单 {len(self.orders)} 笔挂单")
                        cancelled = self.broker.batch_cancel(
                            [o for o in self.orders if o.alive()]
                        )
                        self.cancel_statuses.extend(o.getstatusname() for o in cancelled)
                        for o in self.orders:
                            print(f"  批量撤单发起后状态 ref={o.ref} status={o.getstatusname()}")
                        self.cancels_issued = True
                        # Do not stop here: notify_order stops the engine once
                        # every batch member has reached a terminal state.

                cerebro.addstrategy(BatchCancelPendingStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=60)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未能通过种子 bar 触发批量撤单流程")

                cancel_statuses = [strat.status_by_ref.get(o.ref, "Unknown") for o in strat.orders]
                canceled_count = sum(1 for status in cancel_statuses if status == "Canceled")
                if canceled_count >= 3:
                    print(f"✓ 批量撤单成功: {canceled_count} 笔")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={
                            "submit_statuses": strat.submit_statuses,
                            "cancel_statuses": cancel_statuses,
                        },
                    )

                return timer.fail_result(
                    f"撤单成功数量不足: {canceled_count}, cancel_statuses={cancel_statuses}",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
