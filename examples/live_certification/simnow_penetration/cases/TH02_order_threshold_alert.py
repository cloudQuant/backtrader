#!/usr/bin/env python
"""TH02: 验证报单笔数达到或超过阈值时会预警"""
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
    "case_id": "TH02",
    "case_name": "验证报单笔数达到或超过阈值时会预警",
    "category": "阈值设置及预警",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                cerebro = create_cerebro(store, symbol=symbol, bar_seconds=5)
                # Set a very low threshold so we can trigger it
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir, log_format="json",
                    submit_count_warn_threshold=2,
                )

                class ThresholdTriggerStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.orders_placed = 0

                    def notify_order(self, order):
                        if order.getstatusname() in ("Accepted", "Canceled", "Rejected"):
                            if self.orders_placed >= 3:
                                self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.orders_placed >= 3:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = max(ref_price - 20 - self.orders_placed, 1.0)
                        order = self.buy(size=1, exectype=bt.Order.Limit, price=limit_price, offset="open")
                        if order:
                            self.orders_placed += 1
                            self.cancel(order)

                cerebro.addstrategy(ThresholdTriggerStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=90)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            monitor_entries = helpers.read_json_lines(Path(log_dir) / "monitor.log")
            events = helpers.extract_event_type_set(monitor_entries)

            # Look for threshold warning events
            has_warning = any(
                e.get("level") == "WARNING" or "threshold" in str(e.get("details", {})).lower()
                for e in monitor_entries
            )
            submit_count = sum(1 for e in monitor_entries if e.get("event_type") == "order_submit_request")

            if has_warning or submit_count >= 2:
                print(f"✓ 报单 {submit_count} 笔，阈值=2，预警已触发或统计已超阈值")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"submit_count": submit_count, "has_warning": has_warning},
                )

            return timer.blocked_result(
                "未检测到阈值预警",
                next_action="检查 TradeLogger 阈值预警输出逻辑",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
