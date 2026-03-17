#!/usr/bin/env python
"""M02: 验证连接断开时能正常显示连接断开"""
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
    "case_id": "M02",
    "case_name": "验证连接断开时能正常显示连接断开",
    "category": "系统连接异常监测",
    "optional": False,
}


def run(report_dir):
    """High-risk: actively disconnects store to verify disconnect display."""
    env_key = cfg.get_env_key()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=True) as (store, config, ek):
                assert store.is_connected, "Store did not connect"

                cerebro = create_cerebro(
                    store, bar_seconds=5, with_trade_logger=True, log_dir=log_dir,
                )

                class StopAfterOneBar(bt.Strategy):
                    def next(self):
                        self.cerebro.runstop()

                cerebro.addstrategy(StopAfterOneBar)
                run_with_timeout(cerebro, timeout_seconds=30)

                # stop_on_exit=True will call store.stop(), triggering disconnect

            system_entries = helpers.read_json_lines(Path(log_dir) / "system.log")
            events = helpers.extract_event_type_set(system_entries)

            if "session_stopped" in events:
                print("✓ system.log 包含 session_stopped 事件（连接断开记录）")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"system_events": sorted(events)},
                )

            return timer.blocked_result(
                "未在 system.log 中观察到 session_stopped 事件",
                next_action="检查 TradeLogger 是否在 store.stop 时记录 disconnect 事件",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
