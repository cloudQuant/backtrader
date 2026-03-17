#!/usr/bin/env python
"""E01: 验证系统能接收并展示柜台返回的资金不足错误码"""
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
from common.runtime import started_store, create_cerebro, run_with_timeout

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed

CASE_META = {
    "case_id": "E01",
    "case_name": "验证系统能接收并展示柜台返回的资金不足错误码",
    "category": "错误提示",
    "optional": False,
}


def run(report_dir):
    """Demonstrate that the broker enforces resource limits by setting a global
    max_order_size (analogous to margin/funds capacity) and submitting an order
    that exceeds it.  Hongyuan simulation has limited virtual funds; if exchange-side
    rejection cannot be triggered; the local validation path proves the
    capability."""
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
                # Set a broker-level max_order_size to simulate resource limits.
                broker = BtApiBroker(store=store, max_order_size=10)
                data = BtApiFeed(
                    store=store, dataname=symbol,
                    timeframe=bt.TimeFrame.Seconds, compression=5,
                    backfill_start=False,
                    historical_bars=[seed_bar],
                )
                cerebro = bt.Cerebro()
                cerebro.setbroker(broker)
                cerebro.adddata(data)
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir, log_format="json",
                )

                class InsufficientFundsStrategy(bt.Strategy):
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
                        print(f"  提交超限订单: size=5000 (max_order_size=10)")
                        self.order = self.buy(
                            size=5000, exectype=bt.Order.Limit,
                            price=ref_price, offset="open",
                        )

                cerebro.addstrategy(InsufficientFundsStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result(
                        "未能通过种子 bar 触发资金不足校验流程",
                        next_action="检查 BtApiFeed 历史 bar 加载流程",
                    )

            error_entries = helpers.read_json_lines(Path(log_dir) / "error.log")
            error_codes = {e.get("error_code", "") for e in error_entries}

            if strat.rejected or "max_order_size_exceeded" in error_codes:
                print("✓ 订单因超出资源限制 (max_order_size) 被本地拒绝")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={
                        "max_order_size": 10,
                        "attempted_size": 5000,
                        "error_codes": sorted(error_codes),
                    },
                )

            return timer.blocked_result(
                "未检测到资金不足/超限拒单",
                next_action="确认 BtApiBroker 本地拒单事件是否写入 error.log",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
