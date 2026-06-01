#!/usr/bin/env python
"""L04: 验证系统日志中会记录错误提示信息"""
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
from common.runtime import started_store, run_with_timeout

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed

CASE_META = {
    "case_id": "L04",
    "case_name": "验证系统日志中会记录错误提示信息",
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
                # Trigger a local rejection via invalid price tick
                broker = BtApiBroker(
                    store=store,
                    contract_metadata={symbol: {"min_price_tick": 1.0}},
                )
                data = BtApiFeed(
                    store=store, dataname=symbol,
                    timeframe=bt.TimeFrame.Seconds, compression=5,
                    backfill_start=False,
                )
                cerebro = bt.Cerebro()
                cerebro.setbroker(broker)
                cerebro.adddata(data)
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir, log_format="json",
                )

                class ErrorTriggerStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.order = None

                    def notify_order(self, order):
                        if order.status == bt.Order.Rejected:
                            self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.order is not None:
                            self.cerebro.runstop()
                            return
                        ref_price = float(self.data.close[0])
                        invalid_price = max(ref_price - 0.5, 0.5)
                        self.order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=invalid_price, offset="open",
                        )

                cerebro.addstrategy(ErrorTriggerStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            error_entries = helpers.read_json_lines(Path(log_dir) / "error.log")
            events = helpers.extract_event_type_set(error_entries)

            if error_entries:
                print(f"  error.log 条目数: {len(error_entries)}")
                print(f"  错误事件: {sorted(events)}")
                if "order_reject_local" in events or "order_rejected" in events:
                    print("✓ error.log 包含错误提示信息")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={"error_events": sorted(events)},
                    )

            return timer.blocked_result(
                "error.log 为空或未包含拒单错误事件",
                next_action="确认 TradeLogger 错误日志输出路径和 BtApiBroker 校验逻辑",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
