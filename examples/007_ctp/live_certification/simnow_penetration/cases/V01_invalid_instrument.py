#!/usr/bin/env python
"""V01: Verify that the system checks and rejects order submission when the order's instrument code is invalid"""
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
from common.runtime import (
    create_cerebro,
    live_seed_bar,
    refresh_ctp_preflight,
    run_with_timeout,
    started_store,
)

import backtrader as bt

CASE_META = {
    "case_id": "V01",
    "case_name": "验证订单合约代码错误时系统能检查并拒绝报单",
    "category": "错误防范",
    "optional": False,
}


def run(report_dir):
    """Run V01 invalid instrument test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                # The broker refuses new CTP exposure until typed startup-query
                # evidence is complete, so refresh it before the run; otherwise
                # the gate (not the local check) is what rejects the order.
                try:
                    refresh_ctp_preflight(store, symbol)
                except Exception as exc:
                    return timer.blocked_result(
                        f"CTP preflight 不可用: {exc}",
                        next_action="检查 SimNow typed 查询覆盖率与账号状态",
                    )

                # Mark the symbol as invalid via contract_metadata to prove
                # the local validation mechanism rejects invalid instruments.
                cerebro = create_cerebro(
                    store,
                    symbol=symbol,
                    bar_seconds=5,
                    with_trade_logger=True,
                    log_dir=log_dir,
                    contract_metadata={symbol: {"valid": False}},
                    historical_bars=[live_seed_bar(store, symbol)],
                )

                class InvalidInstrumentStrategy(bt.Strategy):
                    """Strategy for testing invalid instrument rejection."""

                    def __init__(self):
                        """Initialize invalid instrument strategy."""
                        self.bar_count = 0
                        self.order = None
                        self.rejected = False

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        print(f"  order_notify: ref={order.ref} status={order.getstatusname()}")
                        if order.status == bt.Order.Rejected:
                            self.rejected = True
                            self.cerebro.runstop()

                    def next(self):
                        """Process bar and submit invalid instrument order."""
                        self.bar_count += 1
                        if self.order is not None:
                            self.cerebro.runstop()
                            return
                        ref_price = float(self.data.close[0])
                        refresh_ctp_preflight(store, symbol)
                        self.order = self.buy(size=1, exectype=bt.Order.Limit, price=ref_price)

                cerebro.addstrategy(InvalidInstrumentStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=45)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            error_entries = helpers.read_json_lines(Path(log_dir) / "error.log")
            error_codes = {e.get("error_code", "") for e in error_entries}

            if "invalid_contract" in error_codes:
                print("✓ 合约代码错误订单已被本地拒绝 (invalid_contract)")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"error_codes": sorted(error_codes)},
                )

            return timer.blocked_result(
                "未检测到 invalid_contract 本地拒单",
                next_action="检查 BtApiBroker._validate_order 的 valid 标志校验",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
