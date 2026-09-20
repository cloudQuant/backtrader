#!/usr/bin/env python
"""T03: Verify that a cancel order instruction can be placed normally"""
from __future__ import annotations

import datetime as dt
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
from common.runtime import (
    started_store,
    run_with_timeout,
    ensure_ctp_trading_admission,
    live_seed_bar,
    resolve_ctp_symbol,
)

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed

CASE_META = {
    "case_id": "T03",
    "case_name": "验证能正常下达撤单指令",
    "category": "基础交易功能",
    "optional": False,
}


def run(report_dir):
    """Run T03 cancel order test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                symbol = resolve_ctp_symbol(store, symbol)
                broker = BtApiBroker(store=store, position_mode=cfg.get_position_mode())
                data = BtApiFeed(
                    store=store,
                    dataname=symbol,
                    timeframe=bt.TimeFrame.Seconds,
                    compression=5,
                    backfill_start=False,
                    historical_bars=[live_seed_bar(store, symbol)],
                )
                cerebro = bt.Cerebro()
                cerebro.setbroker(broker)
                cerebro.adddata(data)
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir,
                    log_format="json",
                )

                class CancelOrderStrategy(bt.Strategy):
                    """Strategy for testing cancel order functionality."""

                    def __init__(self):
                        """Initialize cancel order strategy."""
                        self.bar_count = 0
                        self.order = None
                        self.order_statuses = []
                        self.submit_status = ""
                        self.cancel_called = False
                        self.cancel_status = ""
                        self.counter_accepted = False
                        self.counter_canceled = False

                    def notify_store(self, msg, *args, **kwargs):
                        """Stop only on the counter's own cancel confirmation.

                        The broker marks the order ``Canceled`` locally as soon
                        as the cancel request is enqueued, so that status cannot
                        certify this test.  ``order_status_canceled`` is the
                        counter's order-update event; wait for it (the run
                        timeout is the backstop).
                        """
                        event = kwargs.get("event")
                        if not isinstance(event, dict):
                            return
                        event_type = event.get("event_type")
                        if event_type == "order_status_accepted":
                            self.counter_accepted = True
                        elif event_type == "order_status_canceled":
                            self.counter_canceled = True
                            self.cerebro.runstop()

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        status = order.getstatusname()
                        self.order_statuses.append(status)
                        print(f"  order_notify: ref={order.ref} status={status}")

                    def next(self):
                        """Process bar and submit cancel order."""
                        self.bar_count += 1
                        if self.order is not None:
                            return
                        # Passive price: the order must stay pending so the
                        # cancel path (not a fill) is what this case proves.
                        limit_price = max(float(self.data.close[0]) - 30, 1.0)
                        ensure_ctp_trading_admission(store, symbol)
                        self.order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=limit_price, offset="open", position_side="long",
                        )
                        if self.order is not None:
                            self.submit_status = self.order.getstatusname()
                            print(
                                "  buy() returned:"
                                f" status={self.submit_status}"
                                f" error_code={getattr(self.order.info, 'error_code', '')}"
                                f" error_msg={getattr(self.order.info, 'error_msg', '')}"
                            )
                            print(f"  提交后立即撤单: ref={self.order.ref}")
                            self.cancel_called = True
                            self.cancel(self.order)
                            self.cancel_status = self.order.getstatusname()
                            print(f"  order status after cancel(): {self.cancel_status}")

                cerebro.addstrategy(CancelOrderStrategy)
                # The case stops as soon as the counter's cancel confirmation
                # arrives; the timeout only backstops a missing confirmation.
                results = run_with_timeout(cerebro, timeout_seconds=120)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未能通过种子 bar 触发撤单流程")

                evidence = helpers.collect_evidence_files(log_dir)
                if not strat.cancel_called:
                    return timer.fail_result("撤单路径未执行", evidence=evidence)
                if not strat.counter_canceled:
                    return timer.fail_result(
                        "未收到柜台撤单确认 order_status_canceled",
                        evidence=evidence,
                        details={
                            "counter_accepted": strat.counter_accepted,
                            "submit_status": strat.submit_status,
                            "cancel_status": strat.cancel_status,
                            "order_statuses": strat.order_statuses,
                        },
                    )
                print("✓ 撤单指令已成功下达并收到柜台撤单确认")

                return timer.pass_result(
                    evidence=evidence,
                    details={
                        "counter_accepted": strat.counter_accepted,
                        "submit_status": strat.submit_status,
                        "cancel_status": strat.cancel_status,
                        "order_statuses": strat.order_statuses,
                    },
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
