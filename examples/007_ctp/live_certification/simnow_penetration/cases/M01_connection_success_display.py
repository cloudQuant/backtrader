#!/usr/bin/env python
"""M01: Verify that connection success is properly displayed when the connection succeeds"""
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
from common.runtime import (
    create_cerebro,
    live_seed_bar,
    run_with_timeout,
    started_store,
)

import backtrader as bt

CASE_META = {
    "case_id": "M01",
    "case_name": "验证连接成功时能正常显示连接成功",
    "category": "系统连接异常监测",
    "optional": False,
}


def run(report_dir):
    """Run M01 connection success display test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key) as (store, config, ek):
                assert store.is_connected, "Store did not connect"

                cerebro = create_cerebro(
                    store, bar_seconds=5, with_trade_logger=True, log_dir=log_dir,
                    historical_bars=[live_seed_bar(store, cfg.get_order_symbol())],
                )

                class StopAfterOneBar(bt.Strategy):
                    """Minimal strategy that stops after first bar."""

                    def next(self):
                        """Process bar and immediately stop."""
                        self.cerebro.runstop()

                cerebro.addstrategy(StopAfterOneBar)
                run_with_timeout(cerebro, timeout_seconds=30)

            system_entries = helpers.read_json_lines(Path(log_dir) / "system.log")
            events = helpers.extract_event_type_set(system_entries)

            assert "store_connected" in events, "Missing store_connected"
            assert "store_ready" in events, "Missing store_ready"
            print("✓ system.log 包含 store_connected / store_ready 事件")

            return timer.pass_result(
                evidence=helpers.collect_evidence_files(log_dir),
                details={"system_events": sorted(events)},
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
