#!/usr/bin/env python
"""Live MixBroker demo with OKX exchange.

Demonstrates real-time multi-symbol data streaming from OKX using
bt.Strategy + Cerebro:
- BTC-USDT and ETH-USDT perpetual contracts
- Ticker, orderbook, and bar data via WebSocket
- Strategy callbacks: notify_tick, notify_orderbook, notify_bar, next
- No actual trading

Requirements:
    pip install ccxt[pro]

Usage:
    python examples/live_mixbroker_okx_demo.py
"""

import asyncio
import time
import sys
import os
from collections import defaultdict
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import backtrader as bt
from backtrader.brokers.mixbroker import MixBroker


def _load_env():
    """Load .env from project root for proxy and API config."""
    try:
        from dotenv import load_dotenv
        env_path = PROJECT_ROOT / '.env'
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            return True
    except ImportError:
        pass
    return False


def _build_exchange_config():
    """Build ccxt exchange config with optional proxy from .env.

    Returns:
        Tuple of (config_dict, proxy_url_or_None)
    """
    config = {
        'enableRateLimit': True,
        'options': {'defaultType': 'swap'},
    }

    # API credentials (optional for public data, but load if available)
    api_key = os.getenv('OKX_API_KEY')
    secret = os.getenv('OKX_SECRET')
    password = os.getenv('OKX_PASSWORD')
    if api_key and secret and password:
        config['apiKey'] = api_key
        config['secret'] = secret
        config['password'] = password

    # Proxy (needed for GFW bypass)
    proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
    if proxy_url:
        print(f"Using proxy: {proxy_url}")
    else:
        print("No proxy configured (set HTTPS_PROXY in .env if needed)")

    return config, proxy_url


class LiveMultiSymbolStrategy(bt.Strategy):
    """Strategy receiving live data from multiple symbols.

    In live/async mode the ``notify_tick``, ``notify_orderbook``, and
    ``notify_bar`` callbacks receive a simple wrapper object whose
    ``.symbol`` attribute identifies the source and ``.data`` carries
    the raw exchange dict.
    """

    params = (
        ('symbols', []),
    )

    def __init__(self):
        """Initialize the strategy with tracking structures.

        Sets up counters for ticks, orderbooks, and bars received from each
        symbol, along with tracking for next() calls and timing.
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

    def notify_tick(self, tick):
        """Callback when ticker data arrives."""
        symbol = tick.symbol
        data = tick.data
        self.ticks_received[symbol] += 1
        self.latest_tick[symbol] = data

        if self.ticks_received[symbol] % 10 == 1:
            print(f"  [TICK] {symbol:20s} bid={data.get('bid', 0):>10.2f}  "
                  f"ask={data.get('ask', 0):>10.2f}  "
                  f"last={data.get('last', 0):>10.2f}")

    def notify_orderbook(self, ob):
        """Callback when orderbook snapshot arrives."""
        symbol = ob.symbol
        data = ob.data
        self.orderbooks_received[symbol] += 1
        self.latest_orderbook[symbol] = data

        if self.orderbooks_received[symbol] % 5 == 1:
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            spread = best_ask - best_bid if best_bid and best_ask else 0
            print(f"  [OB]   {symbol:20s} bid={best_bid:>10.2f}  "
                  f"ask={best_ask:>10.2f}  spread={spread:>6.2f}  "
                  f"depth={len(bids)}/{len(asks)}")

    def notify_bar(self, bar):
        """Callback when OHLCV bar completes."""
        symbol = bar.symbol
        data = bar.data
        self.bars_received[symbol] += 1
        self.latest_bar[symbol] = data

        print(f"  [BAR]  {symbol:20s} O={data.get('open', 0):>10.2f}  "
              f"H={data.get('high', 0):>10.2f}  "
              f"L={data.get('low', 0):>10.2f}  "
              f"C={data.get('close', 0):>10.2f}  "
              f"V={data.get('volume', 0):>10.2f}")

    def next(self):
        """Called when all symbols have synchronized data."""
        self.next_calls += 1
        current_symbols = set()
        for symbol in self.p.symbols:
            if symbol in self.latest_tick or symbol in self.latest_bar:
                current_symbols.add(symbol)
                self.symbols_in_next.add(symbol)

        if self.next_calls % 20 == 1:
            print(f"\n  [NEXT] Call #{self.next_calls}, symbols: {current_symbols}")
            for symbol in current_symbols:
                if symbol in self.latest_tick:
                    print(f"    {symbol} tick: last="
                          f"{self.latest_tick[symbol].get('last', 0):.2f}")
                if symbol in self.latest_orderbook:
                    ob = self.latest_orderbook[symbol]
                    if ob.get('bids') and ob.get('asks'):
                        spread = ob['asks'][0][0] - ob['bids'][0][0]
                        print(f"    {symbol} orderbook: spread={spread:.2f}")
            print()

    def get_stats(self):
        """Get statistics collected during the live stream.

        Returns:
            dict: Dictionary containing elapsed time, tick/orderbook/bar counts
                per symbol, next() call count, and symbols that appeared in next().
        """
        elapsed = time.time() - self.start_time
        return {
            'elapsed': elapsed,
            'ticks': dict(self.ticks_received),
            'orderbooks': dict(self.orderbooks_received),
            'bars': dict(self.bars_received),
            'next_calls': self.next_calls,
            'symbols_in_next': list(self.symbols_in_next),
        }


# --------------- lightweight wrappers for async data ---------------

def _wrap(channel, symbol, raw):
    """Create a simple namespace with .symbol and .data."""
    return type('LiveEvent', (), {
        'symbol': symbol, 'data': raw, 'channel': channel})()


async def watch_ticker(exchange, symbol, strategy, start_time, duration):
    """Watch ticker updates from exchange and notify strategy.

    Args:
        exchange: CCXT Pro exchange instance.
        symbol: Trading symbol to watch (e.g., 'BTC/USDT:USDT').
        strategy: Strategy instance to receive tick notifications.
        start_time: Epoch time when watching started.
        duration: Maximum duration to watch in seconds.

    The function loops until duration expires, calling strategy.notify_tick()
    for each received ticker update.
    """
    try:
        while time.time() - start_time < duration:
            ticker = await exchange.watch_ticker(symbol)
            strategy.notify_tick(_wrap('tick', symbol, ticker))
            if len(strategy.latest_tick) >= len(strategy.p.symbols):
                strategy.next()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[ERROR] watch_ticker {symbol}: {e}")


async def watch_orderbook(exchange, symbol, strategy, start_time, duration):
    """Watch orderbook snapshots from exchange and notify strategy.

    Args:
        exchange: CCXT Pro exchange instance.
        symbol: Trading symbol to watch (e.g., 'BTC/USDT:USDT').
        strategy: Strategy instance to receive orderbook notifications.
        start_time: Epoch time when watching started.
        duration: Maximum duration to watch in seconds.

    The function loops until duration expires, calling
    strategy.notify_orderbook() for each received orderbook snapshot.
    """
    try:
        while time.time() - start_time < duration:
            orderbook = await exchange.watch_order_book(symbol, limit=20)
            strategy.notify_orderbook(_wrap('orderbook', symbol, orderbook))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[ERROR] watch_orderbook {symbol}: {e}")


async def watch_ohlcv(exchange, symbol, strategy, start_time, duration):
    """Watch OHLCV bar data from exchange and notify strategy.

    Args:
        exchange: CCXT Pro exchange instance.
        symbol: Trading symbol to watch (e.g., 'BTC/USDT:USDT').
        strategy: Strategy instance to receive bar notifications.
        start_time: Epoch time when watching started.
        duration: Maximum duration to watch in seconds.

    The function loops until duration expires, calling strategy.notify_bar()
    for each completed OHLCV bar. Uses 1-minute timeframe.
    """
    try:
        while time.time() - start_time < duration:
            ohlcv = await exchange.watch_ohlcv(symbol, '1m')
            if ohlcv:
                latest = ohlcv[-1]
                bar_data = {
                    'timestamp': latest[0], 'open': latest[1],
                    'high': latest[2], 'low': latest[3],
                    'close': latest[4], 'volume': latest[5],
                }
                strategy.notify_bar(_wrap('bar', symbol, bar_data))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[ERROR] watch_ohlcv {symbol}: {e}")


async def run_live_stream(strategy, symbols, duration):
    """Run live data streaming from OKX."""
    try:
        import ccxt.pro as ccxtpro
    except ImportError:
        print("ERROR: ccxt.pro not installed. Install with: pip install ccxt[pro]")
        return

    config, proxy_url = _build_exchange_config()
    exchange = ccxtpro.okx(config)

    if proxy_url:
        exchange.httpsProxy = proxy_url
        exchange.wsProxy = proxy_url

    try:
        await exchange.load_markets()
        for symbol in symbols:
            if symbol not in exchange.markets:
                print(f"ERROR: Symbol {symbol} not found in OKX markets")
                return

        print(f"Connected to OKX exchange")
        print(f"Symbols: {symbols}")
        print(f"Duration: {duration}s")
        print("=" * 80)

        start_time = time.time()
        tasks = []
        for symbol in symbols:
            tasks.append(watch_ticker(exchange, symbol, strategy,
                                      start_time, duration))
            tasks.append(watch_orderbook(exchange, symbol, strategy,
                                         start_time, duration))
            tasks.append(watch_ohlcv(exchange, symbol, strategy,
                                     start_time, duration))
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await exchange.close()


def main():
    """Main entry point."""
    _load_env()

    print("\n" + "=" * 80)
    print("Live MixBroker Demo - OKX Multi-Symbol Data Stream")
    print("=" * 80)

    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT']
    duration = 30

    # --- Cerebro setup ---
    cerebro = bt.Cerebro()
    cerebro.setbroker(MixBroker(cash=100000.0))
    cerebro.addstrategy(LiveMultiSymbolStrategy, symbols=symbols)

    # Instantiate strategies without entering event loop (channel=True)
    strategies = cerebro.run(channel=True)
    strategy = strategies[0]

    # --- async event loop ---
    print("\nStarting live data stream...")
    print("Press Ctrl+C to stop early\n")

    try:
        asyncio.run(run_live_stream(strategy, symbols, duration))
    except KeyboardInterrupt:
        print("\n\nStopped by user")

    # --- teardown ---
    cerebro.runstop()

    # --- report ---
    stats = strategy.get_stats()

    print("\n" + "=" * 80)
    print("Results")
    print("=" * 80)
    print(f"Duration:           {stats['elapsed']:.1f}s")
    print(f"Ticks received:     {stats['ticks']}")
    print(f"Orderbooks:         {stats['orderbooks']}")
    print(f"Bars:               {stats['bars']}")
    print(f"next() calls:       {stats['next_calls']}")
    print(f"Symbols in next():  {stats['symbols_in_next']}")
    print("=" * 80)

    success = True
    for symbol in symbols:
        if stats['ticks'].get(symbol, 0) == 0:
            print(f"❌ No ticks received for {symbol}")
            success = False
        if stats['orderbooks'].get(symbol, 0) == 0:
            print(f"❌ No orderbooks received for {symbol}")
            success = False
    if stats['next_calls'] == 0:
        print("❌ next() was never called")
        success = False
    if len(stats['symbols_in_next']) != len(symbols):
        print(f"❌ Not all symbols appeared in next(): "
              f"{stats['symbols_in_next']}")
        success = False

    if success:
        print("\n✅ All checks passed!")
    else:
        print("\n❌ Some checks failed")

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
