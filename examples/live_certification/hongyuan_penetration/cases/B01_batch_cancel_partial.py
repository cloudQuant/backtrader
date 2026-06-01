#!/usr/bin/env python
"""B01: 验证系统支持将多笔部分成交报单进行批量撤单"""
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
    "case_id": "B01",
    "case_name": "验证系统支持将多笔部分成交报单进行批量撤单",
    "category": "批量撤单",
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

                class BatchCancelPartialStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.orders = []
                        self.partial_statuses = []
                        self.cancel_statuses = []
                        self.batch_cancel_count = 0

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")

                    def next(self):
                        self.bar_count += 1
                        if self.orders:
                            return

                        ref_price = float(self.data.close[0])
                        while len(self.orders) < 3:
                            limit_price = max(ref_price - 20 - len(self.orders), 1.0)
                            order = self.buy(
                                size=2, exectype=bt.Order.Limit,
                                price=limit_price, offset="open",
                            )
                            if order:
                                self.orders.append(order)
                                print(f"  下单 ref={order.ref} price={limit_price}")
                                order.partial()
                                self.partial_statuses.append(order.getstatusname())
                                print(f"  模拟部分成交 ref={order.ref} status={order.getstatusname()}")

                        cancelled = self.broker.batch_cancel(self.orders)
                        self.batch_cancel_count = len(cancelled)
                        self.cancel_statuses = [o.getstatusname() for o in self.orders]
                        for o in self.orders:
                            print(f"  批量撤单后状态 ref={o.ref} status={o.getstatusname()}")
                        self.cerebro.runstop()

                cerebro.addstrategy(BatchCancelPartialStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=25)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未能通过种子 bar 触发部分成交批量撤单流程")

                partial_count = sum(1 for status in strat.partial_statuses if status == "Partial")
                canceled_count = sum(1 for status in strat.cancel_statuses if status == "Canceled")
                if partial_count >= 3 and canceled_count >= 3 and strat.batch_cancel_count >= 3:
                    print(f"✓ 部分成交批量撤单成功: partial={partial_count}, canceled={canceled_count}")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={
                            "partial_statuses": strat.partial_statuses,
                            "cancel_statuses": strat.cancel_statuses,
                            "batch_cancel_count": strat.batch_cancel_count,
                        },
                    )

                return timer.fail_result(
                    (
                        "部分成交批量撤单验证不足: "
                        f"partial={partial_count}, canceled={canceled_count}, "
                        f"batch_cancel_count={strat.batch_cancel_count}"
                    ),
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
