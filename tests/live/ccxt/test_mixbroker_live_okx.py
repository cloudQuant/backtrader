#!/usr/bin/env python
"""Integration test for MixBroker with OKX live data.

Tests multi-symbol live data streaming from OKX exchange using
bt.Strategy + Cerebro:
- BTC-USDT and ETH-USDT perpetual contracts
- Ticker, orderbook, and bar data via WebSocket
- Strategy callbacks: notify_tick, notify_orderbook, notify_bar, next
- No actual trading, just data reception verification

Requirements:
- OKX API credentials in environment variables or .env file
- ccxt.pro installed (pip install ccxt[pro])
- Network access to OKX API

Run:
    pytest tests/integration/test_mixbroker_live_okx.py -v -s
    # -s to see print output from strategy callbacks
"""

import asyncio
import sys
import time
import os
import pytest
from collections import defaultdict
from pathlib import Path

# Windows Python 3.8: asyncio defaults to ProactorEventLoop which is
# incompatible with aiodns/aiohttp. Switch to SelectorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Skip if ccxt.pro not available
pytest.importorskip("ccxt.pro")
import ccxt

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env for proxy config
try:
    from dotenv import load_dotenv

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

import backtrader as bt
from backtrader.brokers.mixbroker import MixBroker

# --------------- lightweight wrapper for async data ---------------


def _wrap(channel, symbol, raw):
    """Create a simple namespace with .symbol and .data."""
    return type("LiveEvent", (), {"symbol": symbol, "data": raw, "channel": channel})()


class MultiSymbolLiveStrategy(bt.Strategy):
    """Strategy that receives live data from multiple symbols.

    Implements callbacks for tick, orderbook, bar events and tracks
    data reception for verification.
    """

    params = (("symbols", []),)

    def __init__(self):
        """Initialize the strategy with tracking dictionaries and counters.

        Sets up empty dictionaries to track received data and counters for
        callback invocations. Records start time for duration calculation.

        Attributes:
            ticks_received: Dict mapping symbol to tick count.
            orderbooks_received: Dict mapping symbol to orderbook count.
            bars_received: Dict mapping symbol to bar count.
            next_calls: Counter for next() invocations.
            latest_tick: Dict storing most recent tick data per symbol.
            latest_orderbook: Dict storing most recent orderbook data per symbol.
            latest_bar: Dict storing most recent bar data per symbol.
            symbols_in_next: Set of symbols that appeared in next().
            start_time: Timestamp when strategy started.
            running: Flag to control strategy execution.
        """
        self.ticks_received = defaultdict(int)
        self.orderbooks_received = defaultdict(int)
        self.bars_received = defaultdict(int)
        self.next_calls = 0

        self.latest_tick = {}
        self.latest_orderbook = {}
        self.latest_bar = {}
        self.symbols_in_next = set()
        self.start_time = time.time()
        self.running = True

    def notify_tick(self, tick):
        """Handle incoming tick data from the exchange.

        Args:
            tick: LiveEvent object containing symbol and tick data with
                bid, ask, and last price fields.

        Updates the internal tick counter and stores the latest tick data.
        Prints summary every 10 ticks per symbol.
        """
        symbol = tick.symbol
        data = tick.data
        self.ticks_received[symbol] += 1
        self.latest_tick[symbol] = data

        if self.ticks_received[symbol] % 10 == 1:
            print(
                f"[on_tick] {symbol}: bid={data.get('bid'):.2f}, "
                f"ask={data.get('ask'):.2f}, "
                f"last={data.get('last'):.2f}"
            )

    def notify_orderbook(self, ob):
        """Handle incoming orderbook data from the exchange.

        Args:
            ob: LiveEvent object containing symbol and orderbook data with
                bids and asks arrays.

        Updates the internal orderbook counter and stores the latest orderbook
        data. Prints summary every 5 orderbooks per symbol including best
        bid/ask and depth information.
        """
        symbol = ob.symbol
        data = ob.data
        self.orderbooks_received[symbol] += 1
        self.latest_orderbook[symbol] = data

        if self.orderbooks_received[symbol] % 5 == 1:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            print(
                f"[on_orderbook] {symbol}: best_bid={best_bid:.2f}, "
                f"best_ask={best_ask:.2f}, depth={len(bids)}/{len(asks)}"
            )

    def notify_bar(self, bar):
        """Handle incoming bar (OHLCV) data from the exchange.

        Args:
            bar: LiveEvent object containing symbol and bar data with open,
                high, low, close, and volume fields.

        Updates the internal bar counter and stores the latest bar data.
        Prints bar summary for each received bar.
        """
        symbol = bar.symbol
        data = bar.data
        self.bars_received[symbol] += 1
        self.latest_bar[symbol] = data

        print(
            f"[on_bar] {symbol}: open={data.get('open'):.2f}, "
            f"high={data.get('high'):.2f}, "
            f"low={data.get('low'):.2f}, "
            f"close={data.get('close'):.2f}, "
            f"volume={data.get('volume'):.2f}"
        )

    def next(self):
        """Called on each iteration to process synchronized data.

        Tracks which symbols have received data and updates the set of symbols
        that have appeared in next(). Prints status summary every 20 calls.

        The method checks each configured symbol for available tick or bar data
        and records symbols that have successfully received market data.
        """
        self.next_calls += 1
        current_symbols = set()
        for symbol in self.p.symbols:
            if symbol in self.latest_tick or symbol in self.latest_bar:
                current_symbols.add(symbol)
                self.symbols_in_next.add(symbol)

        if self.next_calls % 20 == 1:
            print(f"[next] Call #{self.next_calls}, " f"symbols with data: {current_symbols}")
            for symbol in current_symbols:
                if symbol in self.latest_tick:
                    print(f"  {symbol} tick: " f"last={self.latest_tick[symbol].get('last'):.2f}")
                if symbol in self.latest_orderbook:
                    ob = self.latest_orderbook[symbol]
                    spread = (
                        (ob["asks"][0][0] - ob["bids"][0][0])
                        if ob.get("bids") and ob.get("asks")
                        else 0
                    )
                    print(f"  {symbol} orderbook: spread={spread:.2f}")

    def stop(self):
        """Stop the strategy execution.

        Sets the running flag to False to signal that the strategy should
        stop processing data.
        """
        self.running = False

    def get_stats(self):
        """Generate statistics summary from the strategy run.

        Returns:
            dict: Dictionary containing:
                - elapsed_seconds (float): Time since strategy start.
                - ticks_received (dict): Symbol to tick count mapping.
                - orderbooks_received (dict): Symbol to orderbook count mapping.
                - bars_received (dict): Symbol to bar count mapping.
                - next_calls (int): Total number of next() invocations.
                - symbols_in_next (list): Symbols that appeared in next().
        """
        elapsed = time.time() - self.start_time
        return {
            "elapsed_seconds": elapsed,
            "ticks_received": dict(self.ticks_received),
            "orderbooks_received": dict(self.orderbooks_received),
            "bars_received": dict(self.bars_received),
            "next_calls": self.next_calls,
            "symbols_in_next": list(self.symbols_in_next),
        }


# --------------- async watchers ---------------


async def watch_ticker(exchange, symbol, strategy, start_time, duration):
    """Watch ticker updates from exchange and notify strategy.

    Args:
        exchange: CCXT Pro exchange instance.
        symbol: Trading symbol to watch (e.g., 'BTC/USDT:USDT').
        strategy: Strategy instance to notify with new tick data.
        start_time: Reference time when streaming started.
        duration: Maximum duration to watch for updates.

    The function continuously fetches ticker updates and calls the
    strategy's notify_tick method with wrapped data.
    """
    try:
        while time.time() - start_time < duration:
            ticker = await exchange.watch_ticker(symbol)
            strategy.notify_tick(_wrap("tick", symbol, ticker))
            if len(strategy.latest_tick) >= len(strategy.p.symbols):
                strategy.next()
    except Exception as e:
        print(f"[watch_ticker] {symbol} error: {e}")


async def watch_orderbook(exchange, symbol, strategy, start_time, duration):
    """Watch orderbook updates from exchange and notify strategy.

    Args:
        exchange: CCXT Pro exchange instance.
        symbol: Trading symbol to watch.
        strategy: Strategy instance to notify with new orderbook data.
        start_time: Reference time when streaming started.
        duration: Maximum duration to watch for updates.

    Fetches orderbook snapshots with a depth of 20 levels and calls
    the strategy's notify_orderbook method.
    """
    try:
        while time.time() - start_time < duration:
            orderbook = await exchange.watch_order_book(symbol, limit=20)
            strategy.notify_orderbook(_wrap("orderbook", symbol, orderbook))
    except Exception as e:
        print(f"[watch_orderbook] {symbol} error: {e}")


async def watch_ohlcv(exchange, symbol, strategy, start_time, duration):
    """Watch OHLCV (candlestick) updates from exchange and notify strategy.

    Args:
        exchange: CCXT Pro exchange instance.
        symbol: Trading symbol to watch.
        strategy: Strategy instance to notify with new bar data.
        start_time: Reference time when streaming started.
        duration: Maximum duration to watch for updates.

    Fetches 1-minute candlestick data and extracts the latest bar's
    OHLCV values to pass to the strategy's notify_bar method.
    """
    try:
        while time.time() - start_time < duration:
            ohlcv = await exchange.watch_ohlcv(symbol, "1m")
            if ohlcv:
                latest = ohlcv[-1]
                bar_data = {
                    "timestamp": latest[0],
                    "open": latest[1],
                    "high": latest[2],
                    "low": latest[3],
                    "close": latest[4],
                    "volume": latest[5],
                }
                strategy.notify_bar(_wrap("bar", symbol, bar_data))
    except Exception as e:
        print(f"[watch_ohlcv] {symbol} error: {e}")


async def run_live_data_stream(strategy, symbols, duration_seconds=30):
    """Run live data streaming from OKX exchange.

    Creates a CCXT Pro exchange instance, configures authentication from
    environment variables if available, and spawns async tasks to watch
    ticker, orderbook, and OHLCV data for each symbol.

    Args:
        strategy: Strategy instance with notify_tick, notify_orderbook, and
            notify_bar callback methods.
        symbols: List of trading symbols in CCXT format (e.g., 'BTC/USDT:USDT').
        duration_seconds: Maximum duration to stream data. Defaults to 30.

    Raises:
        ValueError: If any symbol is not found in OKX markets.

    Environment Variables:
        OKX_API_KEY: API key for authenticated requests.
        OKX_SECRET: API secret for signing requests.
        OKX_PASSWORD: API password for OKX exchange.
        HTTP_PROXY/HTTPS_PROXY: Optional proxy URL for connections.
    """
    import ccxt.pro as ccxtpro

    config = {
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    }
    api_key = os.getenv("OKX_API_KEY")
    secret = os.getenv("OKX_SECRET")
    password = os.getenv("OKX_PASSWORD")
    if api_key and secret and password:
        config["apiKey"] = api_key
        config["secret"] = secret
        config["password"] = password

    exchange = ccxtpro.okx(config)

    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy_url:
        exchange.httpsProxy = proxy_url
        exchange.wsProxy = proxy_url

    try:
        await exchange.load_markets()
        for symbol in symbols:
            if symbol not in exchange.markets:
                raise ValueError(f"Symbol {symbol} not found in OKX markets")

        print(f"Starting live data stream for {symbols}")
        print(f"Duration: {duration_seconds}s")
        print("-" * 60)

        start_time = time.time()
        tasks = []
        for symbol in symbols:
            tasks.append(watch_ticker(exchange, symbol, strategy, start_time, duration_seconds))
            tasks.append(watch_orderbook(exchange, symbol, strategy, start_time, duration_seconds))
            tasks.append(watch_ohlcv(exchange, symbol, strategy, start_time, duration_seconds))

        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await exchange.close()


# --------------- helpers ---------------


def _create_cerebro_and_strategy(symbols):
    """Create Cerebro instance and instantiate the live data strategy.

    Creates a Cerebro instance with a MixBroker and adds the
    MultiSymbolLiveStrategy with the provided symbols. Uses channel=True
    mode to instantiate the strategy without running the backtest loop.

    Args:
        symbols: List of trading symbols to configure in the strategy.

    Returns:
        tuple: (cerebro, strategy) where cerebro is the Cerebro instance and
            strategy is the instantiated MultiSymbolLiveStrategy.
    """
    cerebro = bt.Cerebro()
    cerebro.setbroker(MixBroker(cash=100000.0))
    cerebro.addstrategy(MultiSymbolLiveStrategy, symbols=symbols)
    strategies = cerebro.run(channel=True)  # channel=True → just instantiate
    return cerebro, strategies[0]


def _print_and_assert(strategy, symbols):
    """Print test statistics and run verification assertions.

    Retrieves statistics from the strategy, prints them in a formatted
    table, and asserts that all symbols received tick and orderbook data
    and that next() was called.

    Args:
        strategy: Strategy instance with get_stats() method.
        symbols: List of symbols that should have received data.

    Raises:
        AssertionError: If any symbol received no ticks, no orderbooks,
            next() was never called, or not all symbols appeared in next().
    """
    stats = strategy.get_stats()

    print("\n" + "=" * 60)
    print("Test Results")
    print("=" * 60)
    print(f"Duration: {stats['elapsed_seconds']:.1f}s")
    print(f"Ticks received: {stats['ticks_received']}")
    print(f"Orderbooks received: {stats['orderbooks_received']}")
    print(f"Bars received: {stats['bars_received']}")
    print(f"next() calls: {stats['next_calls']}")
    print(f"Symbols in next(): {stats['symbols_in_next']}")

    for symbol in symbols:
        assert stats["ticks_received"].get(symbol, 0) > 0, f"No ticks received for {symbol}"
        assert (
            stats["orderbooks_received"].get(symbol, 0) > 0
        ), f"No orderbooks received for {symbol}"

    assert stats["next_calls"] > 0, "next() was never called"
    assert len(stats["symbols_in_next"]) == len(
        symbols
    ), f"Not all symbols appeared in next(): {stats['symbols_in_next']}"

    print("\n✅ All assertions passed!")


# --------------- skip guard ---------------

_skip_no_okx = pytest.mark.skipif(
    not (os.getenv("OKX_API_KEY") and os.getenv("OKX_SECRET") and os.getenv("OKX_PASSWORD")),
    reason="OKX credentials not set (OKX_API_KEY, OKX_SECRET, OKX_PASSWORD)",
)

# --------------- tests ---------------


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.slow
@_skip_no_okx
def test_mixbroker_live_multi_symbol_okx():
    """Test MixBroker-style live data reception from OKX for multiple symbols.

    Verifies:
    - Ticker data arrives for both BTC-USDT and ETH-USDT
    - Orderbook data arrives for both symbols
    - notify_tick, notify_orderbook, notify_bar callbacks are invoked
    - next() is called with synchronized data
    - Both symbols appear in next() at least once
    """
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    duration = 30
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            cerebro, strategy = _create_cerebro_and_strategy(symbols)
            asyncio.run(run_live_data_stream(strategy, symbols, duration))
            cerebro.runstop()
            break
        except (ccxt.ExchangeNotAvailable, ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            if attempt == max_retries:
                pytest.skip(f"OKX unreachable after {max_retries} attempts: {exc}")
            print(f"\n⚠ Attempt {attempt}/{max_retries} failed ({exc}), retrying in 5s...")
            time.sleep(5)

    _print_and_assert(strategy, symbols)


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.slow
@_skip_no_okx
def test_mixbroker_live_single_symbol_okx():
    """Test live data reception for a single symbol (BTC-USDT)."""
    symbols = ["BTC/USDT:USDT"]
    duration = 20
    max_retries = 3

    for attempt in range(1, max_retries + 1):
        try:
            cerebro, strategy = _create_cerebro_and_strategy(symbols)
            asyncio.run(run_live_data_stream(strategy, symbols, duration))
            cerebro.runstop()
            break
        except (ccxt.ExchangeNotAvailable, ccxt.RequestTimeout, ccxt.NetworkError) as exc:
            if attempt == max_retries:
                pytest.skip(f"OKX unreachable after {max_retries} attempts: {exc}")
            print(f"\n⚠ Attempt {attempt}/{max_retries} failed ({exc}), retrying in 5s...")
            time.sleep(5)

    stats = strategy.get_stats()

    print("\n" + "=" * 60)
    print("Single Symbol Test Results")
    print("=" * 60)
    print(f"Duration: {stats['elapsed_seconds']:.1f}s")
    print(f"Ticks: {stats['ticks_received']}")
    print(f"Orderbooks: {stats['orderbooks_received']}")
    print(f"Bars: {stats['bars_received']}")

    symbol = symbols[0]
    assert stats["ticks_received"].get(symbol, 0) > 0
    assert stats["orderbooks_received"].get(symbol, 0) > 0

    print("\n✅ Single symbol test passed!")


if __name__ == "__main__":
    print("Running MixBroker live OKX test...")
    print("Note: This requires network access to OKX API")
    print("Press Ctrl+C to stop early\n")

    try:
        test_mixbroker_live_multi_symbol_okx()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nTest failed: {e}")
        import traceback

        traceback.print_exc()
