#!/usr/bin/env python
"""V03: 验证订单委托数量超过单笔最大委托数量时系统能检查并拒绝报单"""
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
    "case_id": "V03",
    "case_name": "验证订单委托数量超过单笔最大委托数量时系统能检查并拒绝报单",
    "category": "错误防范",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                broker = BtApiBroker(
                    store=store,
                    contract_metadata={symbol: {"max_order_size": 10}},
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

                class ExceedVolumeStrategy(bt.Strategy):
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
                        print(f"  提交超量订单: size=9999")
                        self.order = self.buy(
                            size=9999, exectype=bt.Order.Limit,
                            price=max(ref_price - 20, 1.0), offset="open",
                        )

                cerebro.addstrategy(ExceedVolumeStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            error_entries = helpers.read_json_lines(Path(log_dir) / "error.log")
            error_codes = {e.get("error_code", "") for e in error_entries}

            if strat.rejected or "exceed_max_volume" in error_codes:
                print("✓ 超量订单已被拒绝")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"error_codes": sorted(error_codes)},
                )

            return timer.blocked_result(
                "未检测到超量拒单",
                next_action="确认 BtApiBroker max_order_volume 校验路径",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
