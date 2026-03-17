#!/usr/bin/env python
"""T02: 验证能正常下达平仓指令"""
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
    "case_id": "T02",
    "case_name": "验证能正常下达平仓指令",
    "category": "基础交易功能",
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

                class CloseOrderStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.order = None
                        self.order_statuses = []
                        self.submit_status = ""

                    def notify_order(self, order):
                        status = order.getstatusname()
                        self.order_statuses.append(status)
                        print(f"  order_notify: ref={order.ref} status={status}")
                        if status in ("Submitted", "Accepted", "Completed", "Canceled", "Rejected"):
                            self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.order is not None:
                            return
                        limit_price = float(self.data.close[0])
                        print(f"  下达平仓卖单: symbol={symbol} price={limit_price:.2f}")
                        self.order = self.sell(
                            size=1, exectype=bt.Order.Limit,
                            price=limit_price, offset="close",
                        )
                        if self.order is not None:
                            print(
                                "  sell() returned:"
                                f" status={self.order.getstatusname()}"
                                f" error_code={getattr(self.order.info, 'error_code', '')}"
                                f" error_msg={getattr(self.order.info, 'error_msg', '')}"
                            )
                            self.submit_status = self.order.getstatusname()

                cerebro.addstrategy(CloseOrderStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=25)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result(
                        "未能通过种子 bar 触发平仓下单",
                        next_action="检查 BtApiFeed 历史 bar 加载流程",
                    )

                system_entries = helpers.read_json_lines(Path(log_dir) / "system.log")
                event_types = {e.get("event_type") for e in system_entries}
                valid_statuses = {"Submitted", "Accepted", "Completed", "Rejected"}
                if (
                    strat.submit_status in valid_statuses
                    or any(status in valid_statuses for status in strat.order_statuses)
                ):
                    print("✓ 平仓指令已成功进入有效状态")
                    evidence = helpers.collect_evidence_files(log_dir)
                    return timer.pass_result(
                        evidence=evidence,
                        details={
                            "events": sorted(event_types),
                            "submit_status": strat.submit_status,
                            "order_statuses": strat.order_statuses,
                        },
                    )

                return timer.fail_result(
                    f"平仓指令未进入有效状态: submit_status={strat.submit_status}, statuses={strat.order_statuses}",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            evidence = helpers.collect_evidence_files(log_dir)
            return timer.fail_result(str(exc), evidence=evidence)


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
