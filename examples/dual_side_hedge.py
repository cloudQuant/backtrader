#!/usr/bin/env python
"""Example: Dual-side hedging strategy.

A strategy that holds both long and short positions simultaneously as a hedge.
It opens a core long position and then selectively opens/closes a short hedge
when the market looks overbought.

This pattern is common in futures trading (e.g., CTP, Binance Futures) where
traders want to hedge without closing their core position.

Key concepts demonstrated:
  - Holding long and short legs simultaneously on the same instrument.
  - Querying each leg independently via getposition(side=...).
  - Using tradeid to group trades per leg for PnL tracking.
  - The net position view remains correct throughout.

Usage:
    python examples/dual_side_hedge.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backtrader as bt
import backtrader.indicators as btind


class DualSideHedgeStrategy(bt.Strategy):
    """Hold a core long, hedge with short when RSI signals overbought."""

    params = (
        ("rsi_period", 14),
        ("rsi_overbought", 70),
        ("rsi_oversold", 30),
        ("core_size", 100),
        ("hedge_size", 50),
        ("long_tradeid", 1),
        ("short_tradeid", 2),
    )

    def __init__(self):
        self.rsi = btind.RSI(self.data.close, period=self.p.rsi_period)
        self.core_entered = False
        self.hedge_active = False
        self.total_hedge_trades = 0

    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f"{dt.strftime('%Y-%m-%d')}  {txt}")

    def notify_order(self, order):
        if order.status == order.Completed:
            side = getattr(order.info, "position_side", "?")
            offset = getattr(order.info, "offset", "?")
            action = "BUY" if order.isbuy() else "SELL"
            self.log(
                f"  {action} {order.executed.size:.0f} @ {order.executed.price:.2f} "
                f"[{side}/{offset}]"
            )

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"  TRADE CLOSED tradeid={trade.tradeid} PnL={trade.pnlcomm:.2f}")

    def next(self):
        # Enter core long on first available bar
        if not self.core_entered:
            self.log(">> Opening core LONG position")
            self.buy(
                size=self.p.core_size,
                tradeid=self.p.long_tradeid,
                position_side="long",
                offset="open",
            )
            self.core_entered = True
            return

        long_pos = self.getposition(self.data, side="long")
        short_pos = self.getposition(self.data, side="short")

        # Open hedge short when RSI is overbought
        if self.rsi[0] > self.p.rsi_overbought and not self.hedge_active:
            self.log(
                f">> RSI={self.rsi[0]:.1f} overbought — opening SHORT hedge  "
                f"(long={long_pos.size:.0f})"
            )
            self.sell(
                size=self.p.hedge_size,
                tradeid=self.p.short_tradeid,
                position_side="short",
                offset="open",
            )
            self.hedge_active = True

        # Close hedge short when RSI cools down
        elif self.rsi[0] < self.p.rsi_oversold and self.hedge_active:
            if abs(short_pos.size) > 0:
                self.log(
                    f">> RSI={self.rsi[0]:.1f} oversold — closing SHORT hedge  "
                    f"(short={short_pos.size:.0f})"
                )
                self.close(
                    position_side="short",
                    tradeid=self.p.short_tradeid,
                )
                self.total_hedge_trades += 1
            self.hedge_active = False

    def stop(self):
        long_pos = self.getposition(self.data, side="long")
        short_pos = self.getposition(self.data, side="short")
        net_pos = self.position

        print()
        print("=" * 50)
        print("Strategy Summary")
        print("=" * 50)
        print(f"  Hedge trades completed : {self.total_hedge_trades}")
        print(f"  Final long  leg        : {long_pos.size:.0f} @ {long_pos.price:.2f}")
        print(f"  Final short leg        : {short_pos.size:.0f}")
        print(f"  Net position           : {net_pos.size:.0f}")
        print(f"  Portfolio value        : {self.broker.getvalue():.2f}")


def main():
    cerebro = bt.Cerebro()

    # Use built-in test data (full year for RSI to have enough bars)
    datapath = os.path.join(
        os.path.dirname(__file__), "..", "tests", "datas", "2006-day-001.txt"
    )
    data = bt.feeds.BacktraderCSVData(dataname=datapath)
    cerebro.adddata(data)

    # Create broker with dual-side mode
    from backtrader.brokers.bbroker import BackBroker

    broker = BackBroker(position_mode="dual_side")
    broker.setcash(1000000.0)
    broker.setcommission(commission=0.001)
    cerebro.setbroker(broker)

    cerebro.addstrategy(DualSideHedgeStrategy)

    print("=" * 60)
    print("Dual-Side Position Mode — Hedging Strategy")
    print("=" * 60)
    print()

    cerebro.run()


if __name__ == "__main__":
    main()
