"""Run a simple moving-average backtest on CryptoHFTData minute bars."""

import argparse
import importlib.util
import os
from datetime import datetime

import backtrader as bt


class MovingAverageCross(bt.Strategy):
    """Trade when the fast moving average crosses the slow average."""

    def __init__(self):
        """Build fast/slow SMAs and the crossover signal driving entries/exits."""
        fast = bt.indicators.SMA(self.data.close, period=10)
        slow = bt.indicators.SMA(self.data.close, period=30)
        self.cross = bt.indicators.CrossOver(fast, slow)

    def next(self):
        """Submit crossover orders."""
        if not self.position and self.cross[0] > 0:
            self.buy()
        elif self.position and self.cross[0] < 0:
            self.close()


def main(argv=None):
    """Run a bounded, read-only historical request only after explicit opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="make the remote historical-data request")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--exchange", default="binance_futures")
    parser.add_argument("--from-date", default="2026-07-01")
    parser.add_argument("--to-date", default="2026-07-02")
    parser.add_argument(
        "--api-key-env",
        default="CRYPTOHFTDATA_API_KEY",
        help="environment variable name holding the provider API key",
    )
    args = parser.parse_args(argv)

    if not args.run:
        print("Blocked: no remote request made. Pass --run to request historical data.")
        return 2

    if importlib.util.find_spec("cryptohftdata") is None:
        print("Blocked: optional SDK missing; install backtrader[cryptohftdata]. No request made.")
        return 2

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"Blocked: API key environment variable {args.api_key_env!r} is unset. No request made.")
        return 2

    cerebro = bt.Cerebro()
    cerebro.adddata(
        bt.feeds.CryptoHFTData(
            dataname=args.symbol,
            exchange=args.exchange,
            api_key=api_key,
            fromdate=datetime.fromisoformat(args.from_date),
            todate=datetime.fromisoformat(args.to_date),
            timeframe=bt.TimeFrame.Minutes,
        )
    )
    cerebro.addstrategy(MovingAverageCross)
    cerebro.run()
    print(f"final portfolio value: {cerebro.broker.getvalue():.2f}")


if __name__ == "__main__":
    raise SystemExit(main())
