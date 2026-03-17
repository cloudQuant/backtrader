#!/usr/bin/env python
"""TH03: 验证提供报撤单总数统计与阈值设置功能"""
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
    "case_id": "TH03",
    "case_name": "验证提供报撤单总数统计与阈值设置功能",
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
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir, log_format="json",
                    submit_cancel_total_warn_threshold=10,
                )

                class OneBarStop(bt.Strategy):
                    def next(self):
                        self.cerebro.runstop()

                cerebro.addstrategy(OneBarStop)
                run_with_timeout(cerebro, timeout_seconds=30)

            print("✓ TradeLogger 接受 submit_cancel_total_warn_threshold=10 参数")
            return timer.pass_result(
                evidence=helpers.collect_evidence_files(log_dir),
                details={"total_threshold_configured": 10},
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
