#!/usr/bin/env python
"""Example: Dual-side vs net position mode comparison.

Runs the exact same trading signals through both net and dual_side modes to
illustrate how position accounting differs.

In NET mode:
  - buy() increases net position; sell() decreases it.
  - A buy followed by a sell of equal size results in flat.

In DUAL_SIDE mode:
  - buy(position_side="long", offset="open") opens a long leg.
  - sell(position_side="short", offset="open") opens a short leg independently.
  - Both legs coexist; the net view = long_size - short_size.
  - Each leg must be closed explicitly.

Usage:
    python examples/dual_side_vs_net.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backtrader as bt
from backtrader.brokers.bbroker import BackBroker


class NetModeStrategy(bt.Strategy):
    """Standard net-mode strategy: buy and sell reduce each other."""

    def __init__(self):
        self.records = []

    def next(self):
        bar = len(self)
        if bar == 1:
            self.buy(size=10)
        elif bar == 3:
            self.sell(size=10)
        elif bar == 5:
            self.sell(size=5)
        elif bar == 7:
            self.buy(size=5)

        pos = self.position.size
        self.records.append((bar, pos))

    def stop(self):
        print("NET MODE positions per bar (showing bars 1-10 only):")
        for bar_num, pos in self.records[:10]:
            print(f"  bar {bar_num:2d}: net_position = {pos:+.0f}")
        print(f"  ... ({len(self.records) - 10} more bars, all flat)")
        print(f"  final value = {self.broker.getvalue():.2f}")
        print()


class DualSideModeStrategy(bt.Strategy):
    """Dual-side strategy: same logical intent, explicit open/close."""

    def __init__(self):
        self.records = []

    def next(self):
        bar = len(self)
        if bar == 1:
            # Same as net buy(10): open long 10
            self.buy(size=10, position_side="long", offset="open")
        elif bar == 3:
            # Same intent as net sell(10): close the long 10
            self.close(position_side="long")
        elif bar == 5:
            # Same as net sell(5): open short 5
            self.sell(size=5, position_side="short", offset="open")
        elif bar == 7:
            # Same intent as net buy(5): close the short 5
            self.close(position_side="short")

        long_pos = self.getposition(self.data, side="long")
        short_pos = self.getposition(self.data, side="short")
        net = self.position.size
        self.records.append((bar, long_pos.size, short_pos.size, net))

    def stop(self):
        print("DUAL_SIDE MODE positions per bar (showing bars 1-10 only):")
        for bar_num, lp, sp, net in self.records[:10]:
            print(
                f"  bar {bar_num:2d}: long={lp:+.0f}  short={sp:+.0f}  "
                f"net={net:+.0f}"
            )
        print(f"  ... ({len(self.records) - 10} more bars, all flat)")
        print(f"  final value = {self.broker.getvalue():.2f}")
        print()


def run_backtest(strategy_class, position_mode):
    """Run a single backtest and return the strategy result."""
    cerebro = bt.Cerebro()

    datapath = os.path.join(
        os.path.dirname(__file__), "..", "tests", "datas", "2006-day-001.txt"
    )
    data = bt.feeds.BacktraderCSVData(dataname=datapath)
    cerebro.adddata(data)

    broker = BackBroker(position_mode=position_mode)
    broker.setcash(100000.0)
    broker.setcommission(commission=0.0)  # zero commission for clean comparison
    cerebro.setbroker(broker)

    cerebro.addstrategy(strategy_class)
    results = cerebro.run()
    return results[0]


def main():
    print("=" * 60)
    print("Position Mode Comparison: NET vs DUAL_SIDE")
    print("=" * 60)
    print()
    print("Both strategies execute the same logical trades:")
    print("  bar 1: go long  10")
    print("  bar 3: flatten  (close long 10)")
    print("  bar 5: go short  5")
    print("  bar 7: flatten  (close short 5)")
    print()

    run_backtest(NetModeStrategy, "net")
    run_backtest(DualSideModeStrategy, "dual_side")

    print("=" * 60)
    print("Notice: final values match because the logical trades are identical.")
    print("The difference is in how positions are tracked internally.")
    print("=" * 60)


if __name__ == "__main__":
    main()
