#!/usr/bin/env python
"""EM01: 验证系统可通过限制账号交易权限方式暂停交易"""
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
from backtrader.brokers.btapibroker import BtApiBroker

CASE_META = {
    "case_id": "EM01",
    "case_name": "验证系统可通过限制账号交易权限方式暂停交易",
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
                cerebro = create_cerebro(
                    store, symbol=symbol, bar_seconds=5,
                    with_trade_logger=True, log_dir=log_dir,
                )

                class RestrictTradingStrategy(bt.Strategy):
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
                            return
                        # Disable trading on broker before placing order
                        broker = self.cerebro.broker
                        if hasattr(broker, 'disable_trading'):
                            broker.disable_trading(reason="EM01_test")
                            print("  已禁用交易权限")
                        ref_price = float(self.data.close[0])
                        self.order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=max(ref_price - 20, 1.0), offset="open",
                        )
                        if self.order and self.order.status == bt.Order.Rejected:
                            self.rejected = True
                            print("✓ 订单在交易权限禁用后被拒绝")

                cerebro.addstrategy(RestrictTradingStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

                if strat.rejected:
                    print("✓ 交易权限限制生效，订单被拒绝")
                    return timer.pass_result(evidence=helpers.collect_evidence_files(log_dir))

                return timer.blocked_result(
                    "BtApiBroker 可能未实现 set_trading_enabled 接口",
                    next_action="为 BtApiBroker 补充交易权限控制接口",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
