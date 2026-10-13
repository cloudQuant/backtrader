#!/usr/bin/env python
"""Run a local synthetic mixed tick+bar backtest with MixBroker."""

import argparse
import csv
from pathlib import Path
import sys


def _add_checkout_root() -> None:
    """Use the source checkout in place; copied leaves use installed Backtrader."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "backtrader" / "__init__.py").is_file():
            sys.path.insert(0, str(parent))
            return


_add_checkout_root()

import backtrader as bt
from backtrader.channel import StreamingEventQueue
from backtrader.channels.tick import TickChannel
from backtrader.brokers.mixbroker import MixBroker
from backtrader.events import BarEvent


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "output"


class MixedStrategy(bt.Strategy):
    """Strategy using both tick and bar data.

    Uses ticks for precise entry, bars for trend confirmation.
    """

    params = (("symbol", "BTC/USDT"),)

    def __init__(self):
        """Initialize the strategy with tracking variables.

        Sets up lists to track tick prices and bar closes, plus position state.
        """
        self.tick_prices = []
        self.bar_closes = []
        self.pos = 0
        self.trades = 0

    def notify_tick(self, tick):
        """Process incoming tick events for the configured symbol.

        Args:
            tick: Tick event containing symbol and price data.

        Maintains a rolling window of the last 200 tick prices for
        entry signal calculation.
        """
        if tick.symbol != self.p.symbol:
            return
        self.tick_prices.append(tick.price)
        if len(self.tick_prices) > 200:
            self.tick_prices.pop(0)

    def notify_bar(self, bar):
        """Process incoming bar events for the configured symbol.

        Args:
            bar: Bar event containing OHLCV data.

        Implements a mean-reversion strategy: buy when tick price is
        below bar average (suggesting oversold), sell when above.
        Uses bars for trend confirmation via moving average.
        """
        if bar.symbol != self.p.symbol:
            return
        self.bar_closes.append(bar.close)
        if len(self.bar_closes) > 20:
            self.bar_closes.pop(0)

        if len(self.bar_closes) < 10 or len(self.tick_prices) < 50:
            return

        bar_avg = sum(self.bar_closes) / len(self.bar_closes)
        tick_avg = sum(self.tick_prices[-50:]) / 50
        data = self.get_hft_data(self.p.symbol)

        # Trend from bars, entry from tick deviation
        if tick_avg < bar_avg * 0.998 and self.pos <= 0:
            self.buy(data=data, size=0.1, exectype=0)
            self.pos += 1
            self.trades += 1
        elif tick_avg > bar_avg * 1.002 and self.pos >= 1:
            self.sell(data=data, size=0.1, exectype=0)
            self.pos -= 1
            self.trades += 1

    def stop(self):
        """Print final trade count when strategy stops.

        Called when Cerebro finishes running.
        """
        print(f"Strategy finished: {self.trades} trades")


def generate_demo_data(output_dir: Path, symbol: str):
    """Write a small deterministic tick/bar fixture under the ignored output dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    tick_path = output_dir / "tick_demo.csv"
    bar_path = output_dir / "bar_demo.csv"
    start = 1_700_000_000.0

    with tick_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "symbol", "price", "volume", "direction", "trade_id"))
        for index in range(1800):
            timestamp = start + index * 0.5
            price = 99.0 if timestamp < start + 630.0 else 101.0
            writer.writerow((timestamp, symbol, price, 0.05, "buy" if index % 2 else "sell", f"t{index}"))

    with bar_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("timestamp", "symbol", "open", "high", "low", "close", "volume"))
        for index in range(1, 16):
            writer.writerow((start + index * 60.0, symbol, 100.0, 101.0, 99.0, 100.0, 100.0))

    return tick_path, bar_path


def load_bar_events(path: Path):
    """Stream OHLCV rows as the BarEvents consumed by StreamingEventQueue."""
    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            yield BarEvent(
                timestamp=float(row["timestamp"]),
                symbol=row["symbol"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )


def main(argv=None):
    """Generate local inputs and run the tick+bar event loop."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    symbol = "BTC/USDT"
    output_dir = args.output_dir.expanduser().resolve()
    tick_file, bar_file = generate_demo_data(output_dir, symbol)

    # 1. Create channel + event queue
    channel = TickChannel(symbol=symbol, dataname=str(tick_file))
    queue = StreamingEventQueue(
        channels=[channel], bars=[load_bar_events(bar_file)], preload_window=5.0
    )

    # 2. Set up Cerebro with MixBroker
    cerebro = bt.Cerebro()
    cerebro.setbroker(MixBroker(cash=100000.0))
    cerebro.addstrategy(MixedStrategy, symbol=symbol)

    # 3. Run
    print("Running mixed-mode backtest...")
    print(f"Initial cash: {cerebro.broker.getcash():.2f}")

    results = cerebro.run(channel=queue)

    # 4. Report
    strat = results[0]
    broker = cerebro.broker
    print(f"\n{'='*50}")
    print("Mixed Mode Backtest Results")
    print(f"{'='*50}")
    print(f"Events processed: {strat._event_count}")
    print(f"Trades executed:  {strat.trades}")
    print(f"Final cash:       {broker.getcash():.2f}")
    print(f"Portfolio value:  {broker.getvalue():.2f}")
    print(f"Local fixtures:   {tick_file} and {bar_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
