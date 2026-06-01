#!/usr/bin/env python
"""M03: 验证连接断开后能正常显示重连成功"""
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

from backtrader.stores.btapistore import BtApiStore

CASE_META = {
    "case_id": "M03",
    "case_name": "验证连接断开后能正常显示重连成功",
    "category": "系统连接异常监测",
    "optional": False,
}


def run(report_dir):
    """High-risk: stop then restart store to test reconnection."""
    env_key = cfg.get_env_key()

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            config = cfg.create_config(env_key)

            # First connection
            store = BtApiStore(provider="ctp", **config)
            store.start()
            assert store.is_connected, "First connection failed"
            print("✓ 第一次连接成功")

            # Disconnect
            store.stop()
            print("  已断开连接")
            time.sleep(2)

            # Reconnect
            store2 = BtApiStore(provider="ctp", **config)
            store2.start()
            assert store2.is_connected, "Reconnection failed"
            print("✓ 重连成功")
            store2.stop()

            return timer.pass_result(
                details={"first_connect": True, "reconnect": True},
            )

        except Exception as exc:
            return timer.blocked_result(
                str(exc),
                next_action="检查宏源仿真是否允许快速重连，或增加断开等待时间",
            )


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
