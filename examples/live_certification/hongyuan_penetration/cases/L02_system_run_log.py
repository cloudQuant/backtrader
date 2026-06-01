#!/usr/bin/env python
"""L02: 验证系统日志中会记录系统运行信息"""
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
    "case_id": "L02",
    "case_name": "验证系统日志中会记录系统运行信息",
    "category": "日志记录",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key) as (store, config, ek):
                cerebro = create_cerebro(
                    store, symbol=symbol, bar_seconds=5,
                    with_trade_logger=True, log_dir=log_dir,
                )

                class OneBarStop(bt.Strategy):
                    def next(self):
                        self.cerebro.runstop()

                cerebro.addstrategy(OneBarStop)
                run_with_timeout(cerebro, timeout_seconds=30)

            system_entries = helpers.read_json_lines(Path(log_dir) / "system.log")
            events = helpers.extract_event_type_set(system_entries)

            required = {"session_started", "store_connected", "store_ready"}
            found = required & events
            missing = required - events

            if not missing:
                print(f"✓ system.log 包含系统运行事件: {sorted(found)}")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"system_events": sorted(events)},
                )

            return timer.fail_result(
                f"system.log 缺少事件: {sorted(missing)}",
                evidence=helpers.collect_evidence_files(log_dir),
                details={"found": sorted(found), "missing": sorted(missing)},
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
