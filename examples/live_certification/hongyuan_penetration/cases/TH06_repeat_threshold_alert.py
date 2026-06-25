#!/usr/bin/env python
"""TH06: 验证重复报单笔数达到或超过阈值时会预警（选测）"""
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
from common.runtime import started_store, create_cerebro, run_with_timeout

import backtrader as bt

CASE_META = {
    "case_id": "TH06",
    "case_name": "验证重复报单笔数达到或超过阈值时会预警",
    "category": "阈值设置及预警",
    "optional": True,
}


def run(report_dir):
    """Run TH06 repeat threshold alert test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                seed_bar = {
                    "datetime": dt.datetime.now().replace(microsecond=0),
                    "open": 3000.0,
                    "high": 3000.0,
                    "low": 3000.0,
                    "close": 3000.0,
                    "volume": 1.0,
                    "openinterest": 0.0,
                }
                cerebro = create_cerebro(
                    store,
                    symbol=symbol,
                    bar_seconds=5,
                    historical_bars=[seed_bar],
                )
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir, log_format="json",
                    duplicate_order_warn_threshold=2,
                )

                class RepeatOrderStrategy(bt.Strategy):
                    """Strategy that triggers repeat order threshold alerts."""

                    def __init__(self):
                        """Initialize repeat order strategy."""
                        self.bar_count = 0
                        self.orders_placed = 0
                        self.limit_price = None

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        if order.getstatusname() in ("Canceled", "Rejected"):
                            if self.orders_placed >= 3:
                                self.cerebro.runstop()

                    def next(self):
                        """Process bar and place repeat orders."""
                        self.bar_count += 1
                        if self.orders_placed >= 3:
                            return
                        ref_price = float(self.data.close[0])
                        if self.limit_price is None:
                            self.limit_price = max(ref_price - 20, 1.0)
                        order = self.buy(size=1, exectype=bt.Order.Limit, price=self.limit_price, offset="open")
                        if order:
                            self.orders_placed += 1
                            self.cancel(order)

                cerebro.addstrategy(RepeatOrderStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=90)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result(
                        "未能通过种子 bar 触发重复报单阈值预警流程",
                        next_action="检查 BtApiFeed 历史 bar 加载流程",
                    )

            monitor_entries = helpers.read_json_lines(Path(log_dir) / "monitor.log")
            submit_count = sum(1 for e in monitor_entries if e.get("event_type") == "order_submit_request")
            event_types = helpers.extract_event_type_set(monitor_entries)
            threshold_events = [
                e for e in monitor_entries
                if e.get("event_type") == "risk_threshold_triggered"
            ]
            threshold_details = threshold_events[-1].get("details", {}) if threshold_events else {}

            if (
                "risk_threshold_triggered" in event_types
                and "duplicate_order_threshold_reached" in event_types
            ):
                print(f"✓ 重复报单 {submit_count} 笔，阈值=2，预警条件已满足")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={
                        "events": sorted(event_types),
                        "submit_count": submit_count,
                        "repeat_threshold": threshold_details.get("threshold"),
                        "repeat_count": threshold_details.get("value"),
                    },
                )
            return timer.blocked_result(
                f"未观察到 risk_threshold_triggered，报单笔数: {submit_count}",
                evidence=helpers.collect_evidence_files(log_dir),
                details={"events": sorted(event_types), "submit_count": submit_count},
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
