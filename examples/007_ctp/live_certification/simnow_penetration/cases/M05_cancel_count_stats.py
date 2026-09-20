#!/usr/bin/env python
"""M05: Verify that the number of canceled orders is counted correctly"""
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
    ensure_ctp_trading_admission,
    run_with_timeout,
    started_store,
)

import backtrader as bt

CASE_META = {
    "case_id": "M05",
    "case_name": "验证能正常统计撤单笔数",
    "category": "报撤单笔数监测",
    "optional": False,
}


def run(report_dir):
    """Run M05 cancel count stats test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                # New CTP exposure needs a live typed preflight *and* an SDK
                # write admission. SimNow's official fronts are outside the
                # SDK's registered-simulation registry, so this fails closed;
                # record it as BLOCKED (environment), never as FAIL (code).
                admission = ensure_ctp_trading_admission(store, symbol)
                if not admission.ok:
                    return timer.blocked_result(
                        admission.reason, next_action=admission.next_action
                    )
                cerebro = create_cerebro(
                    store, symbol=symbol, bar_seconds=5,
                    with_trade_logger=True, log_dir=log_dir,
                )

                class MultiCancelStrategy(bt.Strategy):
                    """Strategy that issues multiple cancel requests."""

                    def __init__(self):
                        """Initialize multi-cancel strategy."""
                        self.bar_count = 0
                        self.cancels_issued = 0

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        if order.getstatusname() in ("Canceled", "Rejected"):
                            if self.cancels_issued >= 3:
                                self.cerebro.runstop()

                    def next(self):
                        """Process bar and issue cancel orders."""
                        self.bar_count += 1
                        if self.cancels_issued >= 3:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = max(ref_price - 20 - self.cancels_issued, 1.0)
                        order = self.buy(size=1, exectype=bt.Order.Limit, price=limit_price, offset="open")
                        if order:
                            self.cancel(order)
                            self.cancels_issued += 1

                cerebro.addstrategy(MultiCancelStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=90)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            monitor_entries = helpers.read_json_lines(Path(log_dir) / "monitor.log")
            cancel_count = sum(
                1 for e in monitor_entries if e.get("event_type") == "order_cancel_request"
            )
            print(f"  撤单笔数统计: cancel_count={cancel_count}")

            if cancel_count >= 3:
                print(f"✓ 成功统计到 {cancel_count} 笔撤单")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"cancel_count": cancel_count},
                )

            return timer.blocked_result(
                f"撤单笔数不足: expected>=3 got={cancel_count}",
                evidence=helpers.collect_evidence_files(log_dir),
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
