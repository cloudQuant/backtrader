#!/usr/bin/env python
"""L01: 验证系统日志中会记录交易信息"""
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
    "case_id": "L01",
    "case_name": "验证系统日志中会记录交易信息",
    "category": "日志记录",
    "optional": False,
}


def run(report_dir):
    """Run L01 trade info log test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
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

                class TradeLogStrategy(bt.Strategy):
                    """Strategy for testing trade logging."""

                    def __init__(self):
                        """Initialize trade log strategy."""
                        self.bar_count = 0
                        self.open_order = None
                        self.close_order = None
                        self.open_order_ref = None
                        self.close_order_ref = None
                        self.store_events = []
                        self.trade_events = []
                        self.order_statuses = []
                        self.trade_notifications = []
                        self.open_completed = False
                        self.close_completed = False

                    def notify_store(self, msg, *args, **kwargs):
                        """Collect runtime events emitted by the live store."""
                        event = kwargs.get("event")
                        if not isinstance(event, dict):
                            return
                        self.store_events.append(event)
                        if event.get("event_type") == "trade_execution":
                            self.trade_events.append(event)
                            if self.close_order is not None and len(self.trade_events) >= 2:
                                self.cerebro.runstop()

                    def notify_trade(self, trade):
                        """Record Backtrader trade notifications for log verification."""
                        self.trade_notifications.append(
                            {
                                "ref": getattr(trade, "ref", None),
                                "size": getattr(trade, "size", None),
                                "price": getattr(trade, "price", None),
                                "isopen": getattr(trade, "isopen", False),
                                "isclosed": getattr(trade, "isclosed", False),
                            }
                        )

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        status = order.getstatusname()
                        self.order_statuses.append({"ref": order.ref, "status": status})
                        print(f"  order_notify: ref={order.ref} status={status}")

                        if self.open_order_ref == order.ref and status == "Completed":
                            self.open_completed = True
                            fill_size = abs(order.executed.size or order.size or 1)
                            ref_price = float(self.data.close[0])
                            close_price = max(ref_price - 20, 1.0)
                            print(
                                "  开仓成交，立即下达平今卖单: "
                                f"symbol={symbol} size={fill_size} price={close_price:.2f}"
                            )
                            self.close_order = self.sell(
                                size=fill_size,
                                exectype=bt.Order.Limit,
                                price=close_price,
                                offset="close_today",
                            )
                            self.close_order_ref = (
                                self.close_order.ref if self.close_order is not None else None
                            )
                            return

                        if self.close_order_ref == order.ref and status == "Completed":
                            self.close_completed = True
                            self.cerebro.runstop()
                            return

                        if (
                            order.ref in {self.open_order_ref, self.close_order_ref}
                            and status in ("Rejected", "Canceled", "Expired", "Margin")
                        ):
                            self.cerebro.runstop()

                    def next(self):
                        """Process each bar and submit a cross-price open order."""
                        self.bar_count += 1
                        if self.open_order is not None:
                            return
                        ref_price = float(self.data.close[0])
                        limit_price = ref_price + 20
                        print(
                            "  下达真实开仓买单等待成交: "
                            f"symbol={symbol} price={limit_price:.2f}"
                        )
                        self.open_order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=limit_price, offset="open",
                        )
                        self.open_order_ref = (
                            self.open_order.ref if self.open_order is not None else None
                        )

                cerebro.addstrategy(TradeLogStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=120)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result("未收到行情数据，无法触发真实成交验证")

            # Verify trade.log and runtime events contain real execution evidence.
            order_entries = helpers.read_json_lines(Path(log_dir) / "order.log")
            trade_entries = helpers.read_json_lines(Path(log_dir) / "trade.log")
            event_types = {e.get("event_type") for e in strat.store_events}
            trade_ids = [
                item
                for item in (
                    *(e.get("trade_id") for e in trade_entries),
                    *(e.get("ref") for e in trade_entries),
                    *(e.get("trade_id") for e in strat.trade_events),
                    *(e.get("details", {}).get("trade_id") for e in strat.trade_events),
                )
                if item not in (None, "")
            ]
            order_refs = [
                item
                for item in (
                    *(e.get("order_ref") for e in strat.store_events),
                    *(e.get("ref") for e in order_entries),
                )
                if item not in (None, "")
            ]
            details = {
                "events": sorted(event_types),
                "bars": strat.bar_count,
                "order_entries": len(order_entries),
                "trade_entries": len(trade_entries),
                "trade_notifications": strat.trade_notifications,
                "order_statuses": strat.order_statuses,
                "trade_id": trade_ids[0] if trade_ids else "",
                "order_ref": order_refs[0] if order_refs else "",
                "open_completed": strat.open_completed,
                "close_completed": strat.close_completed,
                "cleanup_offset": "close_today",
            }

            if "trade_execution" in event_types and trade_entries and strat.close_completed:
                print(
                    "✓ trade_execution 已观察到，trade.log 已记录真实成交，"
                    "平今单已成交"
                )
                return timer.pass_result(
                    evidence=helpers.collect_evidence_files(log_dir),
                    details=details,
                )

            if not strat.open_completed:
                return timer.blocked_result(
                    "未观察到开仓成交，无法验证真实交易日志",
                    next_action="确认当前合约处于可交易时段，并检查撮合/盘口是否支持跨价成交",
                    evidence=helpers.collect_evidence_files(log_dir),
                    details=details,
                )

            return timer.fail_result(
                "已发生开仓成交，但未同时确认 trade_execution、trade.log 与平今成交",
                evidence=helpers.collect_evidence_files(log_dir),
                details=details,
            )

        except Exception as exc:
            return timer.fail_result(str(exc), evidence=helpers.collect_evidence_files(log_dir))


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
