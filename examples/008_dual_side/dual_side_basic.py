#!/usr/bin/env python
"""Example: Basic dual-side position mode.

Demonstrates the four fundamental dual-side operations:
  1. Open Long  (buy  + position_side="long"  + offset="open")
  2. Open Short (sell + position_side="short" + offset="open")
  3. Close Long (sell + position_side="long"  + offset="close")  — or close(position_side="long")
  4. Close Short(buy  + position_side="short" + offset="close")  — or close(position_side="short")

Key points:
  - The broker is created with position_mode="dual_side".
  - Long and short legs are independent: opening a short does NOT reduce an existing long.
  - getposition(data, side="long") / side="short" queries individual legs.
  - The net view (self.position.size) equals long_size - short_size.
  - close() auto-detects the leg when only one leg is open; it raises ValueError
    when both legs are open and position_side is not specified.

Usage:
    python examples/008_dual_side/dual_side_basic.py
"""
import datetime
import os
import sys

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, PROJECT_ROOT)

import backtrader as bt


class DualSideBasicStrategy(bt.Strategy):
    """Walk through open/close on both legs, printing state at each bar."""

    def __init__(self):
        """Initialize the strategy with an empty order log."""
        self.order_log = []

    def log(self, txt):
        """Log a message with the current datetime.

        Args:
            txt: Message text to log.
        """
        dt = self.data.datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d %H:%M')}  {txt}")

    def notify_order(self, order):
        """Handle order completion notifications.

        Args:
            order: The order object that was completed.
        """
        if order.status == order.Completed:
            side = getattr(order.info, "position_side", "n/a")
            offset = getattr(order.info, "offset", "n/a")
            action = "BUY" if order.isbuy() else "SELL"
            self.log(
                f"ORDER {action} executed | size={order.executed.size:.0f} "
                f"price={order.executed.price:.2f} | "
                f"position_side={side} offset={offset}"
            )

    def notify_trade(self, trade):
        """Handle trade close notifications.

        Args:
            trade: The trade object that was closed.
        """
        if trade.isclosed:
            self.log(
                f"TRADE CLOSED | tradeid={trade.tradeid} "
                f"pnl={trade.pnl:.2f} pnlcomm={trade.pnlcomm:.2f}"
            )

    def _print_positions(self):
        long_pos = self.getposition(self.data, side="long")
        short_pos = self.getposition(self.data, side="short")
        net_pos = self.position
        self.log(
            f"  positions => long={long_pos.size:.0f}@{long_pos.price:.2f}  "
            f"short={short_pos.size:.0f}@{short_pos.price:.2f}  "
            f"net={net_pos.size:.0f}"
        )

    def next(self):
        """Execute the dual-side position strategy steps on each bar.

        Steps through opening/closing long and short positions independently.
        """
        bar = len(self)
        if bar == 1:
            # Step 1: Open long 10 shares
            self.log(">> Open Long 10 shares")
            self.buy(size=10, position_side="long", offset="open")

        elif bar == 2:
            self._print_positions()

        elif bar == 3:
            # Step 2: Open short 5 shares (long is still held)
            self.log(">> Open Short 5 shares")
            self.sell(size=5, position_side="short", offset="open")

        elif bar == 4:
            self._print_positions()

        elif bar == 5:
            # Step 3: Close long leg using close() helper
            self.log(">> Close Long leg via close(position_side='long')")
            self.close(position_side="long")

        elif bar == 6:
            self._print_positions()

        elif bar == 7:
            # Step 4: Only short leg remains; close() auto-detects it
            self.log(">> Close Short leg via close() — auto-detected")
            self.close()

        elif bar == 8:
            self._print_positions()

    def stop(self):
        """Log the final portfolio value when the strategy ends."""
        self.log(f"Final portfolio value: {self.broker.getvalue():.2f}")


def main():
    """Run the dual-side basic operations example.

    Sets up a BackBroker with dual_side position mode and demonstrates
    opening/closing long and short positions independently.
    """
    cerebro = bt.Cerebro()

    # Use built-in test data
    datapath = os.path.join(
        PROJECT_ROOT, "tests", "datas", "2006-day-001.txt"
    )
    data = bt.feeds.BacktraderCSVData(dataname=datapath)
    cerebro.adddata(data)

    # Create broker with dual-side mode
    from backtrader.brokers.bbroker import BackBroker

    broker = BackBroker(position_mode="dual_side")
    broker.setcash(100000.0)
    broker.setcommission(commission=0.001)
    cerebro.setbroker(broker)

    cerebro.addstrategy(DualSideBasicStrategy)

    print("=" * 60)
    print("Dual-Side Position Mode — Basic Operations")
    print("=" * 60)
    print()

    cerebro.run()


if __name__ == "__main__":
    main()
