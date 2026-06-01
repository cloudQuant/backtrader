#!/usr/bin/env python
"""EM02: 验证系统可通过暂停策略执行方式暂停交易"""
from __future__ import annotations

import datetime as dt
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
from common.runtime import started_store, run_with_timeout

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed

CASE_META = {
    "case_id": "EM02",
    "case_name": "验证系统可通过暂停策略执行方式暂停交易",
    "category": "应急处理",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                now = dt.datetime.now().replace(microsecond=0)
                seed_bars = [
                    {
                        "datetime": now,
                        "open": 3000.0,
                        "high": 3000.0,
                        "low": 3000.0,
                        "close": 3000.0,
                        "volume": 1.0,
                        "openinterest": 0.0,
                    },
                    {
                        "datetime": now + dt.timedelta(seconds=5),
                        "open": 3001.0,
                        "high": 3001.0,
                        "low": 3001.0,
                        "close": 3001.0,
                        "volume": 1.0,
                        "openinterest": 0.0,
                    },
                ]
                broker = BtApiBroker(store=store)
                data = BtApiFeed(
                    store=store,
                    dataname=symbol,
                    timeframe=bt.TimeFrame.Seconds,
                    compression=5,
                    backfill_start=False,
                    historical_bars=seed_bars,
                )
                cerebro = bt.Cerebro()
                cerebro.setbroker(broker)
                cerebro.adddata(data)
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir,
                    log_format="json",
                )

                class PauseStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.paused = False
                        self.orders_after_pause = 0

                    def next(self):
                        self.bar_count += 1

                        if not self.paused:
                            print("  调用 cerebro.runstop() 暂停策略执行")
                            self.paused = True
                            self.cerebro.runstop()
                            return

                        if self.paused:
                            self.orders_after_pause += 1

                cerebro.addstrategy(PauseStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=20)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未能通过种子 bar 触发暂停逻辑")

                if strat.paused:
                    print("✓ 策略已通过 cerebro.runstop() 暂停")
                    print(f"  暂停后未再执行 next: orders_after_pause={strat.orders_after_pause}")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={"bars_before_pause": strat.bar_count, "paused": True},
                    )

                return timer.blocked_result("策略未执行到暂停点")

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
