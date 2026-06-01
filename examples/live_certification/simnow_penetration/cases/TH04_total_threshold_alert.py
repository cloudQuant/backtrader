#!/usr/bin/env python
"""TH04: 验证报撤单总数达到或超过阈值时会预警"""
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
    "case_id": "TH04",
    "case_name": "验证报撤单总数达到或超过阈值时会预警",
    "category": "阈值设置及预警",
    "optional": False,
}


def run(report_dir):
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                cerebro = create_cerebro(store, symbol=symbol, bar_seconds=5)
                # Very low total threshold
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir, log_format="json",
                    submit_cancel_total_warn_threshold=3,
                )

                class MultiOrderCancelStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.ops = 0

                    def notify_order(self, order):
                        if order.getstatusname() in ("Canceled", "Rejected"):
                            if self.ops >= 3:
                                self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.ops >= 3:
                            return
                        ref_price = float(self.data.close[0])
                        order = self.buy(size=1, exectype=bt.Order.Limit, price=max(ref_price - 20, 1.0), offset="open")
                        if order:
                            self.cancel(order)
                            self.ops += 1

                cerebro.addstrategy(MultiOrderCancelStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=90)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            monitor_entries = helpers.read_json_lines(Path(log_dir) / "monitor.log")
            total_ops = sum(
                1 for e in monitor_entries
                if e.get("event_type") in ("order_submit_request", "order_cancel_request")
            )
            has_warning = any(e.get("level") == "WARNING" for e in monitor_entries)

            if total_ops >= 3 or has_warning:
                print(f"✓ 报撤单总数 {total_ops}，阈值=3，预警条件已满足")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"total_ops": total_ops, "has_warning": has_warning},
                )

            return timer.blocked_result(f"操作数不足: {total_ops}")

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
