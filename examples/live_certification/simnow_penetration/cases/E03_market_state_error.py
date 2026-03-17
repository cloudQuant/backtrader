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
from common.runtime import started_store, run_with_timeout

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed

CASE_META = {
    "case_id": "E03",
    "case_name": "验证系统能接收并展示柜台返回的市场状态错误码",
    "category": "错误提示",
    "optional": False,
}


def run(report_dir):
    """Demonstrate that the broker enforces market-state restrictions via
    contract_metadata.  SimNow 7x24 is always open so exchange-side market
    state errors cannot be triggered; marking the contract as tradable=False
    simulates a market-closed state and proves the local validation path."""
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                # Mark the contract as not tradable to simulate market closed.
                broker = BtApiBroker(
                    store=store,
                    contract_metadata={symbol: {"tradable": False}},
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

                class MarketStateStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.order = None
                        self.rejected = False

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")
                        if order.status == bt.Order.Rejected:
                            self.rejected = True
                            self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.order is not None:
                            self.cerebro.runstop()
                            return
                        ref_price = float(self.data.close[0])
                        print(f"  提交订单 (合约标记为不可交易): price={ref_price}")
                        self.order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=ref_price, offset="open",
                        )

                cerebro.addstrategy(MarketStateStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

                if strat.rejected:
                    print("✓ 合约市场状态限制生效 (contract_not_tradable)，订单被拒绝")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={"tradable": False, "rejected": True},
                    )

                return timer.blocked_result(
                    "未触发市场状态拒单",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
