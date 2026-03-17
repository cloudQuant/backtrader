#!/usr/bin/env python
"""O02: 验证能统计重复平仓单报单笔数（选测）"""
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
    "case_id": "O02",
    "case_name": "验证能统计重复平仓单报单笔数",
    "category": "重复报单监测",
    "optional": True,
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

                class RepeatCloseStrategy(bt.Strategy):
                    def __init__(self):
                        self.bar_count = 0
                        self.orders_placed = 0

                    def notify_order(self, order):
                        if order.getstatusname() in ("Accepted", "Canceled", "Rejected"):
                            if self.orders_placed >= 3:
                                self.cerebro.runstop()

                    def next(self):
                        self.bar_count += 1
                        if self.orders_placed >= 3:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = max(ref_price + 20, 1.0)
                        order = self.sell(size=1, exectype=bt.Order.Limit, price=limit_price, offset="close")
                        if order:
                            self.orders_placed += 1
                            self.cancel(order)

                cerebro.addstrategy(RepeatCloseStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=90)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据")

            monitor_entries = helpers.read_json_lines(Path(log_dir) / "monitor.log")
            submit_count = sum(1 for e in monitor_entries if e.get("event_type") == "order_submit_request")
            print(f"  重复平仓单统计: {submit_count} 笔")

            if submit_count >= 3:
                print("✓ 成功统计重复平仓单报单笔数")
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details={"repeat_close_count": submit_count},
                )
            return timer.blocked_result(f"报单笔数不足: {submit_count}")

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
