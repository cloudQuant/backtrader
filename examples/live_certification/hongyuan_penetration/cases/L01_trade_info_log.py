#!/usr/bin/env python
"""L01: 验证系统日志中会记录交易信息"""
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
    "case_id": "L01",
    "case_name": "验证系统日志中会记录交易信息",
    "category": "日志记录",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                seed_bar = {
                    "datetime": dt.datetime.now().replace(microsecond=0),
                    "open": 3000.0,
                    "high": 3000.0,
                    "low": 3000.0,
                    "close": 3000.0,
                    "volume": 1.0,
                    "openinterest": 0.0,
                }
                broker = BtApiBroker(store=store)
                data = BtApiFeed(
                    store=store,
                    dataname=symbol,
                    timeframe=bt.TimeFrame.Seconds,
                    compression=5,
                    backfill_start=False,
                    historical_bars=[seed_bar],
                )
                cerebro = bt.Cerebro()
                cerebro.setbroker(broker)
                cerebro.adddata(data)
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir,
                    log_format="json",
                )

                class TradeLogStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.order = None

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")
                        if order.getstatusname() in ("Accepted", "Canceled", "Rejected"):
                            self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.order is not None:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = max(ref_price - 20, 1.0)
                        self.order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=limit_price, offset="open",
                        )
                        if self.order:
                            self.cancel(self.order)

                cerebro.addstrategy(TradeLogStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=25)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未能通过种子 bar 触发交易日志流程")

            # Verify trading-related logs contain order/signal information
            order_entries = helpers.read_json_lines(Path(log_dir) / "order.log")
            signal_entries = helpers.read_json_lines(Path(log_dir) / "signal.log")
            if order_entries:
                statuses = {e.get("status", "") for e in order_entries}
                print(f"  order.log 条目数: {len(order_entries)}, 状态集: {statuses}")
                print("✓ order.log 中已记录交易信息")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"order_entries": len(order_entries), "statuses": sorted(statuses)},
                )

            if signal_entries:
                actions = {e.get("action", "") for e in signal_entries}
                print(f"  signal.log 条目数: {len(signal_entries)}, 动作集: {actions}")
                print("✓ signal.log 中已记录交易信息")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"signal_entries": len(signal_entries), "actions": sorted(actions)},
                )

            return timer.blocked_result(
                "order.log 与 signal.log 均为空或不存在",
                next_action="确认 TradeLogger 的 order/signal 日志输出路径",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
