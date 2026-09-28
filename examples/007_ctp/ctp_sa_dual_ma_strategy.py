"""Historical SA futures dual moving-average source retained for review.

The direct CTP/SimNow execution route is NOT_SUPPORTED under Iteration 41.
Use ``examples/007_ctp/runtime/config.yaml`` with ``bt-runtime run`` for the
registered configuration-first, zero-I/O replay migration probe.  The legacy
source below remains available for code review only.

Strategy logic:
    - BUY  when fast MA crosses above slow MA (golden cross)
    - SELL when fast MA crosses below slow MA (death cross)
    - Only hold one position direction at a time
    - Account balance is queried and printed each bar

Historical commands and environment settings are intentionally rejected before
Backtrader, CTP, or provider imports.
"""

# This fence must remain before every legacy framework, CTP, or provider import.
import sys as _iteration41_sys
from pathlib import Path as _Iteration41Path

_ITERATION41_RUNTIME_DIR = _Iteration41Path(__file__).resolve().parent / "runtime"
_ITERATION41_REPOSITORY_ROOT = _ITERATION41_RUNTIME_DIR.parents[2]
if str(_ITERATION41_REPOSITORY_ROOT) not in _iteration41_sys.path:
    _iteration41_sys.path.insert(0, str(_ITERATION41_REPOSITORY_ROOT))

from backtrader_runtime.legacy import (  # noqa: E402
    legacy_direct_execution_error as _iteration41_legacy_direct_execution_error,
    run_legacy_config_first_cli as _iteration41_run_legacy_config_first_cli,
)


def _run_config_first_cli(argv=None) -> int:
    return _iteration41_run_legacy_config_first_cli(_ITERATION41_RUNTIME_DIR, argv)


def main(*args, **kwargs):
    del args, kwargs
    raise _iteration41_legacy_direct_execution_error("examples/007_ctp/ctp_sa_dual_ma_strategy.py")


if __name__ == "__main__":
    raise SystemExit(_run_config_first_cli())

import backtrader as bt  # noqa: E402


# ---------------------------------------------------------------------------
# Dual Moving Average Strategy for SA futures
# ---------------------------------------------------------------------------
class DualMAStrategy(bt.Strategy):
    """Dual moving average crossover strategy for SA (soda ash) futures.

    Params:
        fast_period: Period for the fast moving average (default: 5).
        slow_period: Period for the slow moving average (default: 20).
        order_size:  Number of lots per trade (default: 1).
        print_log:   Whether to print detailed logs (default: True).
    """

    params = {
        "fast_period": 5,
        "slow_period": 20,
        "order_size": 1,
        "print_log": True,
    }

    def __init__(self):
        """Initialize the dual MA strategy."""
        self.live_data = False
        self.bar_count = 0
        self.order = None  # pending order tracker

        # Moving averages
        self.fast_ma = bt.ind.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(self.data.close, period=self.p.slow_period)

        # Crossover signal: +1 when fast crosses above slow, -1 when below
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

    def log(self, msg):
        """Log a message with timestamp if print_log is enabled.

        Args:
            msg: The message to log.
        """
        if self.p.print_log:
            dt = self.data.datetime.datetime(0)
            print(f"[{dt}] {msg}")

    def notify_data(self, data, status, *args, **kwargs):
        """Handle data status changes.

        Args:
            data: The data object that changed status.
            status: The new status code.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        status_name = data._getstatusname(status)
        self.log(f"DATA STATUS: {data._name} -> {status_name}")
        self.live_data = status_name == "LIVE"

    def notify_order(self, order):
        """Handle order status changes.

        Args:
            order: The order object that changed status.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return  # wait for further updates

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f"BUY EXECUTED: price={order.executed.price:.2f}, "
                    f"size={order.executed.size}, "
                    f"comm={order.executed.comm:.2f}"
                )
            else:
                self.log(
                    f"SELL EXECUTED: price={order.executed.price:.2f}, "
                    f"size={order.executed.size}, "
                    f"comm={order.executed.comm:.2f}"
                )
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"ORDER FAILED: {order.getstatusname()}")

        self.order = None  # clear pending order

    def notify_trade(self, trade):
        """Handle trade completion.

        Args:
            trade: The trade object that was completed.
        """
        if trade.isclosed:
            self.log(f"TRADE CLOSED: pnl={trade.pnl:.2f}, " f"net_pnl={trade.pnlcomm:.2f}")

    def prenext(self):
        """Called before enough bars for indicators — just log the bar."""
        self.bar_count += 1
        self.log(
            f"[prenext] bar#{self.bar_count} {self.data._name} "
            f"C={self.data.close[0]:.2f} (waiting for MA warmup: "
            f"{len(self)}/{self.p.slow_period})"
        )

    def next(self):
        """Execute trading logic for each new bar.

        Implements the dual moving average crossover strategy:
        - Golden cross (fast MA > slow MA): Open long position
        - Death cross (fast MA < slow MA): Open short position
        - Account balance is queried and printed each bar
        """
        self.bar_count += 1

        # Print bar data
        self.log(
            f"bar#{self.bar_count} {self.data._name} "
            f"O={self.data.open[0]:.2f} H={self.data.high[0]:.2f} "
            f"L={self.data.low[0]:.2f} C={self.data.close[0]:.2f} "
            f"V={self.data.volume[0]:.0f}"
        )
        self.log(
            f"  fast_ma={self.fast_ma[0]:.2f} slow_ma={self.slow_ma[0]:.2f} "
            f"cross={self.crossover[0]:.0f}"
        )

        # Account balance
        cash = self.broker.getcash()
        value = self.broker.getvalue()
        pos = self.getposition(self.data)
        self.log(
            f"  Account: cash={cash:.2f} value={value:.2f} "
            f"pos_size={pos.size} pos_price={pos.price:.2f}"
        )

        # Skip trading until live data
        if not self.live_data:
            return

        # Skip if there's a pending order
        if self.order is not None:
            return

        current_pos = pos.size

        # --- Trading logic ---
        if self.crossover[0] > 0:
            # Golden cross: fast MA crossed above slow MA
            if current_pos < 0:
                # Close short first
                self.log(f"SIGNAL: Golden cross -> close short ({abs(current_pos)} lots)")
                self.order = self.buy(
                    data=self.data,
                    size=abs(current_pos),
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] + 2,
                )
            if current_pos <= 0:
                # Open long
                self.log(f"SIGNAL: Golden cross -> open long ({self.p.order_size} lots)")
                self.order = self.buy(
                    data=self.data,
                    size=self.p.order_size,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] + 2,
                )

        elif self.crossover[0] < 0:
            # Death cross: fast MA crossed below slow MA
            if current_pos > 0:
                # Close long first
                self.log(f"SIGNAL: Death cross -> close long ({current_pos} lots)")
                self.order = self.sell(
                    data=self.data,
                    size=current_pos,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] - 2,
                )
            if current_pos >= 0:
                # Open short
                self.log(f"SIGNAL: Death cross -> open short ({self.p.order_size} lots)")
                self.order = self.sell(
                    data=self.data,
                    size=self.p.order_size,
                    exectype=bt.Order.Limit,
                    price=self.data.close[0] - 2,
                )

    def stop(self):
        """Called when the strategy is stopped."""
        self.log(
            f"Strategy stopped. Total bars: {self.bar_count}, "
            f"Final value: {self.broker.getvalue():.2f}"
        )
