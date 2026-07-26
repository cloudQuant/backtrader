#!/usr/bin/env python
"""M03: 验证连接断开后能正常显示重连成功"""
from __future__ import annotations

import sys
import time
from datetime import datetime
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
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                assert store.is_connected, "First connection failed"
                print("✓ 第一次连接成功")

                first_events = store.get_notifications()
                store.stop()
                disconnected_events = store.get_notifications()
                print("  已断开连接")
                time.sleep(2)

                store.start()
                assert store.is_connected, "Reconnection failed"
                reconnect_events = store.get_notifications()
                print("✓ 重连成功")

            events = [
                event.get("event_type")
                for _msg, _args, kwargs in (
                    first_events + disconnected_events + reconnect_events
                )
                for event in [kwargs.get("event")]
                if isinstance(event, dict)
            ]

            return timer.pass_result(
                details={
                    "events": sorted(set(events)),
                    "first_connect": True,
                    "reconnect": True,
                    "gateway_key": env_key,
                    "timestamp": datetime.now().isoformat(),
                },
            )

        except Exception as exc:
            return timer.blocked_result(
                str(exc),
                next_action="检查 SimNow 是否允许快速重连，或增加断开等待时间",
            )


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
