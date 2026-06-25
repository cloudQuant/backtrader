#!/usr/bin/env python
"""E03: 验证系统能接收并展示柜台返回的市场状态错误码"""
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
from common.runtime import started_store

CASE_META = {
    "case_id": "E03",
    "case_name": "验证系统能接收并展示柜台返回的市场状态错误码",
    "category": "错误提示",
    "optional": False,
}


def run(report_dir):
    """Report E03 as blocked unless a real counter-side market-state error exists."""

    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (_store, _config, _ek):
                print("  当前环境未配置可稳定触发市场状态柜台拒单的真实合约/时段")

            return timer.blocked_result(
                "未观察到真实柜台市场状态远端拒单",
                next_action=(
                    "需要在普通仿真环境非交易时段或交易所特定状态下运行，"
                    "并取得 order_reject_remote/ErrorID/ErrorMsg/StatusMsg 证据"
                ),
                evidence=helpers.collect_evidence_files(log_dir),
                details={
                    "events": [],
                    "required_remote_signal": "order_reject_remote",
                    "env": env_key,
                    "symbol": symbol,
                    "probe_result": "no_remote_market_state_error_available",
                },
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main

    case_main(run, CASE_META)
