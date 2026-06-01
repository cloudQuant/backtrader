#!/usr/bin/env python
"""EM03: 验证系统可通过强制账号退出方式暂停交易"""
from __future__ import annotations

import sys
import time
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
    "case_id": "EM03",
    "case_name": "验证系统可通过强制账号退出方式暂停交易",
    "category": "应急处理",
    "optional": False,
}


def run(report_dir):
    """High-risk: force-stop store mid-session."""
    env_key = cfg.get_env_key()

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                assert store.is_connected, "Store did not connect"
                print("  连接成功，准备强制退出...")

                # Force logout
                store.stop()
                time.sleep(1)
                print("  store.stop() 已调用")

                # Verify disconnected
                connected_after = getattr(store, "is_connected", False)
                print(f"  断开后 is_connected={connected_after}")

                if not connected_after:
                    print("✓ 强制退出成功，账号已断开")
                    return timer.pass_result(
                        details={"connected_after_logout": connected_after},
                    )

                return timer.blocked_result(
                    "store.stop() 后 is_connected 仍为 True",
                    next_action="检查 BtApiStore.stop() 是否正确重置连接状态",
                )

        except Exception as exc:
            return timer.blocked_result(
                str(exc),
                next_action="CTP native 扩展可能在强制退出时崩溃，需子进程隔离验证",
            )


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
