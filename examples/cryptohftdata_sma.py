"""Run a simple moving-average backtest on CryptoHFTData minute bars."""

from datetime import datetime

import backtrader as bt


class MovingAverageCross(bt.Strategy):
    """Trade when the fast moving average crosses the slow average."""

    def __init__(self):
        fast = bt.indicators.SMA(self.data.close, period=10)
        slow = bt.indicators.SMA(self.data.close, period=30)
        self.cross = bt.indicators.CrossOver(fast, slow)

    def next(self):
        """Submit crossover orders."""
        if not self.position and self.cross[0] > 0:
            self.buy()
        elif self.position and self.cross[0] < 0:
            self.close()


def main():
    """Configure CryptoHFTData and run the example backtest."""
    cerebro = bt.Cerebro()
    cerebro.adddata(
        bt.feeds.CryptoHFTData(
            dataname="BTCUSDT",
            exchange="binance_futures",
            fromdate=datetime(2026, 7, 1),
            todate=datetime(2026, 7, 2),
            timeframe=bt.TimeFrame.Minutes,
        )
    )
    cerebro.addstrategy(MovingAverageCross)
    cerebro.run()
    print(f"final portfolio value: {cerebro.broker.getvalue():.2f}")


if __name__ == "__main__":
    main()
