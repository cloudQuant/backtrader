#!/usr/bin/env python
"""C01: 验证登录测试账号通过柜台认证并完成账号登录"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SUITE = _HERE.parent
_REPO = _SUITE.parents[2]
for _p in (_SUITE, _REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import config as cfg, helpers
from common.result import CaseTimer, save_result
from common.runtime import started_store, create_cerebro, run_with_timeout

import backtrader as bt

CASE_META = {
    "case_id": "C01",
    "case_name": "验证登录测试账号通过柜台认证并完成账号登录",
    "category": "连通性",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        log_dir = str(report_dir / "logs")
        try:
            with started_store(env_key) as (store, config, ek):
                assert store.is_connected, "Store did not connect"
                print("✓ SimNow 连接成功")

                # Run a minimal cerebro to trigger TradeLogger session events
                cerebro = create_cerebro(
                    store, bar_seconds=5, with_trade_logger=True, log_dir=log_dir
                )

                class MinimalStrategy(bt.Strategy):
                    def __init__(self):
                        self.count = 0

                    def next(self):
                        self.count += 1
                        if self.count >= 1:
                            self.cerebro.runstop()

                cerebro.addstrategy(MinimalStrategy)
                run_with_timeout(cerebro, timeout_seconds=30)

            # Verify logs
            system_entries = helpers.read_json_lines(Path(log_dir) / "system.log")
            events = helpers.extract_event_type_set(system_entries)

            assert "store_auth_success" in events, "Missing store_auth_success event"
            assert "store_login_success" in events, "Missing store_login_success event"
            print("✓ system.log 包含 store_auth_success 和 store_login_success")

            evidence = helpers.collect_evidence_files(log_dir)
            return timer.pass_result(evidence=evidence, details={"events": sorted(events)})

        except Exception as exc:
            evidence = helpers.collect_evidence_files(log_dir)
            return timer.fail_result(str(exc), evidence=evidence)


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
