#!/usr/bin/env python
"""T02: Verify that a close order instruction can be placed normally"""
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
    started_store,
    run_with_timeout,
    ensure_ctp_trading_admission,
    live_seed_bar,
    close_offset_for,
    resolve_ctp_symbol,
)

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.feeds.btapifeed import BtApiFeed

CASE_META = {
    "case_id": "T02",
    "case_name": "验证能正常下达平仓指令",
    "category": "基础交易功能",
    "optional": False,
}


def run(report_dir):
    """Run T02 close order test case.

    Args:
        report_dir: Directory for test reports and logs.
    """
    env_key = cfg.get_env_key()
    symbol = cfg.get_order_symbol()
    log_dir = str(report_dir / "logs")

    with CaseTimer(CASE_META["case_id"], CASE_META["case_name"], env_key) as timer:
        try:
            with started_store(env_key, stop_on_exit=False) as (store, config, ek):
                symbol = resolve_ctp_symbol(store, symbol)
                broker = BtApiBroker(store=store, position_mode=cfg.get_position_mode())
                data = BtApiFeed(
                    store=store,
                    dataname=symbol,
                    timeframe=bt.TimeFrame.Seconds,
                    compression=5,
                    backfill_start=False,
                    historical_bars=[live_seed_bar(store, symbol)],
                )
                cerebro = bt.Cerebro()
                cerebro.setbroker(broker)
                cerebro.adddata(data)
                cerebro.addobserver(
                    bt.observers.TradeLogger,
                    log_dir=log_dir,
                    log_format="json",
                )

                class CloseOrderStrategy(bt.Strategy):
                    """Open a minimal long leg first, then close it."""

                    def __init__(self):
                        """Initialize close order strategy."""
                        self.bar_count = 0
                        self.open_order = None
                        self.open_order_ref = None
                        self.order = None
                        self.order_ref = None
                        self.order_statuses = []
                        self.submit_status = ""
                        self.close_offset = close_offset_for(symbol)
                        self.close_status = ""

                    def notify_order(self, order):
                        """Handle order status updates.

                        Args:
                            order: Order instance.
                        """
                        status = order.getstatusname()
                        self.order_statuses.append(status)
                        print(f"  order_notify: ref={order.ref} status={status}")
                        # The engine notifies with an order instance that is not
                        # the one returned by buy()/sell(), so match on ref.
                        if order.ref == self.open_order_ref:
                            # The opening leg only funds the position; it must
                            # not end the case.  Once it fills, submit the close
                            # order under test (deterministically, from the
                            # notification rather than waiting for another bar).
                            if status == "Completed" and self.order is None:
                                ref_price = float(self.data.close[0])
                                close_price = max(ref_price - 2, 1.0)
                                print(
                                    "  多头腿已成交，下达平仓卖单: "
                                    f"symbol={symbol} price={close_price:.2f}"
                                    f" offset={self.close_offset}"
                                )
                                ensure_ctp_trading_admission(store, symbol)
                                self.order = self.sell(
                                    size=1, exectype=bt.Order.Limit,
                                    price=close_price, offset=self.close_offset,
                                    position_side="long",
                                )
                                if self.order is not None:
                                    self.order_ref = self.order.ref
                                    self.submit_status = self.order.getstatusname()
                                    print(
                                        "  sell() returned:"
                                        f" status={self.submit_status}"
                                        f" error_code={getattr(self.order.info, 'error_code', '')}"
                                        f" error_msg={getattr(self.order.info, 'error_msg', '')}"
                                    )
                            elif status in ("Rejected", "Canceled", "Expired", "Margin"):
                                self.cerebro.runstop()
                            return
                        if order.ref == self.order_ref and status in (
                            "Submitted", "Accepted", "Completed", "Canceled", "Rejected"
                        ):
                            self.close_status = status
                            self.cerebro.runstop()

                    def next(self):
                        """Build one long lot; the close order follows on fill."""
                        self.bar_count += 1
                        if self.open_order is not None:
                            return
                        ref_price = float(self.data.close[0])
                        # 平仓测试需要先有多头腿：跨价买开通仓，等待成交。
                        print(f"  建立最小多头腿: symbol={symbol} price={ref_price + 20:.2f}")
                        ensure_ctp_trading_admission(store, symbol)
                        self.open_order = self.buy(
                            size=1, exectype=bt.Order.Limit,
                            price=ref_price + 20, offset="open", position_side="long",
                        )
                        if self.open_order is not None:
                            self.open_order_ref = self.open_order.ref

                cerebro.addstrategy(CloseOrderStrategy)
                results = run_with_timeout(cerebro, timeout_seconds=60)

                strat = results[0] if results else None
                if not strat or strat.bar_count <= 0:
                    return timer.blocked_result(
                        "未能通过种子 bar 触发平仓下单",
                        next_action="检查 BtApiFeed 历史 bar 加载流程",
                    )

                system_entries = helpers.read_json_lines(Path(log_dir) / "system.log")
                event_types = {e.get("event_type") for e in system_entries}
                valid_statuses = {"Submitted", "Accepted", "Completed", "Rejected"}
                # Only the close order under test may satisfy the case; the
                # opening leg's statuses must not be able to fake a PASS.
                if strat.order is not None and (
                    strat.submit_status in valid_statuses
                    or strat.close_status in valid_statuses
                ):
                    print("✓ 平仓指令已成功进入有效状态")
                    evidence = helpers.collect_evidence_files(log_dir)
                    return timer.pass_result(
                        evidence=evidence,
                        details={
                            "events": sorted(event_types),
                            "submit_status": strat.submit_status,
                            "close_status": strat.close_status,
                            "close_offset": strat.close_offset,
                            "order_statuses": strat.order_statuses,
                        },
                    )

                return timer.fail_result(
                    f"平仓指令未进入有效状态: submit_status={strat.submit_status}, statuses={strat.order_statuses}",
                    evidence=helpers.collect_evidence_files(log_dir),
                )

        except Exception as exc:
            evidence = helpers.collect_evidence_files(log_dir)
            return timer.fail_result(str(exc), evidence=evidence)


if __name__ == "__main__":
    from common.runtime import case_main
    case_main(run, CASE_META)
