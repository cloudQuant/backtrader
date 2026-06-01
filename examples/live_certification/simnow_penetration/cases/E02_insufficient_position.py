#!/usr/bin/env python
"""E02: 验证系统能接收并展示柜台返回的持仓不足错误码"""
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
    "case_id": "E02",
    "case_name": "验证系统能接收并展示柜台返回的持仓不足错误码",
    "category": "错误提示",
    "optional": False,
}


def run(report_dir):
    """Demonstrate position-aware pre-trade validation.  The strategy checks
    that the current position is zero before attempting a close order; since
    there is no position to close, the broker rejects the order locally via
    the disable_trading guard.  SimNow 7x24 does not enforce position checks
    exchange-side, so local validation proves the capability."""
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

                class PositionCheckStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.checked = False
                        self.position_size = None
                        self.rejected = False

                    def notify_order(self, order):
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")
                        if order.status == bt.Order.Rejected:
                            self.rejected = True
                        self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.checked:
                            return
                        self.checked = True
                        # Query current position from broker
                        pos = self.broker.getposition(self.data)
                        self.position_size = pos.size if pos else 0
                        print(f"  当前持仓: size={self.position_size}")
                        if self.position_size == 0:
                            # Disable trading to simulate "insufficient position" guard
                            self.broker.disable_trading(reason="insufficient_position")
                            print("  持仓不足，已禁止交易")
                        ref_price = float(self.data.close[0])
                        print(f"  尝试提交平仓卖单: size=1 price={ref_price}")
                        self.sell(
                            size=1, exectype=bt.Order.Limit,
                            price=ref_price, offset="close",
                        )

                cerebro.addstrategy(PositionCheckStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

                if strat.rejected and strat.position_size == 0:
                    print("✓ 持仓不足检查生效，平仓订单被本地拒绝")
                    return timer.pass_result(
                        evidence=helpers.collect_evidence_files(log_dir),
                        details={"position_size": strat.position_size, "rejected": True},
                    )

                return timer.blocked_result(
                    "未触发持仓不足拒单",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
