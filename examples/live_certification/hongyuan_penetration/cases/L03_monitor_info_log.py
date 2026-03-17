#!/usr/bin/env python
"""L03: 验证系统日志中会记录监测信息"""
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
    "case_id": "L03",
    "case_name": "验证系统日志中会记录监测信息",
    "category": "日志记录",
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

                class OrderThenStop(bt.Strategy):
                    def __init__(self):
                        self.done = False

                    def notify_order(self, order):
                        if order.getstatusname() in ("Accepted", "Canceled", "Rejected"):
                            self.cerebro.runstop()

                    def next(self):
                        if self.done:
                            return
                        ref_price = float(self.data.close[0])
                        order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=max(ref_price - 20, 1.0), offset="open",
                        )
                        if order:
                            self.cancel(order)
                            self.done = True

                cerebro.addstrategy(OrderThenStop)
                run_with_timeout(cerebro, timeout_seconds=60)

            monitor_entries = helpers.read_json_lines(Path(log_dir) / "monitor.log")
            events = helpers.extract_event_type_set(monitor_entries)

            if monitor_entries:
                print(f"  monitor.log 条目数: {len(monitor_entries)}")
                print(f"  monitor 事件类型: {sorted(events)}")
                has_monitoring = bool(
                    events & {"order_submit_request", "order_cancel_request", "monitoring_summary"}
                )
                if has_monitoring:
                    print("✓ monitor.log 包含监测信息")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={"monitor_events": sorted(events)},
                    )

            return timer.blocked_result(
                "monitor.log 为空或未包含监测事件",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
