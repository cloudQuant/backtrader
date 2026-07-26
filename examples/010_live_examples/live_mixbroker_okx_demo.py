#!/usr/bin/env python
"""Live MixBroker demo using OKX public market data.

The example streams tickers, five-level order books, and one-minute bars for
two OKX perpetual contracts.  It never submits orders and therefore does not
load API credentials into the exchange client.

Requirements:
    pip install ccxt[pro]

Usage:
    python examples/010_live_examples/live_mixbroker_okx_demo.py
"""

import asyncio
import os
import socket
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

import backtrader as bt
from backtrader.brokers.mixbroker import MixBroker


def _load_env():
    """Load an optional project-root ``.env`` file."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return False

    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return False
    load_dotenv(dotenv_path=env_path)
    return True


def _proxy_endpoint(proxy_url):
    """Return a display-safe proxy endpoint without credentials."""
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        return "configured proxy"

    scheme = f"{parsed.scheme}://" if parsed.scheme else ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{scheme}{parsed.hostname}{port}"


def _proxy_is_reachable(proxy_url):
    """Check that a configured proxy is listening before using it."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname
    if not host:
        return False

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (OSError, ValueError):
        return False


def _build_exchange_config():
    """Build a public-only CCXT configuration and validate an optional proxy."""
    config = {
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    }

    credentials = (os.getenv("OKX_API_KEY"), os.getenv("OKX_SECRET"), os.getenv("OKX_PASSWORD"))
    if all(credentials):
        print("OKX credentials found but ignored: this public demo never places orders.")

    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if not proxy_url:
        print("No proxy configured; connecting directly to OKX.")
        return config, None

    endpoint = _proxy_endpoint(proxy_url)
    if _proxy_is_reachable(proxy_url):
        print(f"Using reachable proxy at {endpoint}.")
        return config, proxy_url

    print(f"Configured proxy at {endpoint} is unreachable; connecting directly to OKX.")
    return config, None


async def _create_exchange(ccxtpro, config, proxy_url):
    """Create an OKX client, retrying directly if proxy startup fails."""
    exchange = ccxtpro.okx(config)
    if proxy_url:
        exchange.httpsProxy = proxy_url
        exchange.wsProxy = proxy_url

    try:
        await exchange.load_markets()
        return exchange
    except Exception as exc:
        if not proxy_url:
            await exchange.close()
            raise

        print(
            "Proxy connection failed during market initialization "
            f"({type(exc).__name__}); retrying directly."
        )
        await exchange.close()
        exchange = ccxtpro.okx(config)
        try:
            await exchange.load_markets()
        except Exception:
            await exchange.close()
            raise
        return exchange


class LiveMultiSymbolStrategy(bt.Strategy):
    """Receive public data from multiple OKX perpetual contracts."""

    params = (("symbols", []),)

    def __init__(self):
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
        symbol = tick.symbol
        data = tick.data
        self.ticks_received[symbol] += 1
        self.latest_tick[symbol] = data
        if self.ticks_received[symbol] % 10 == 1:
            print(
                f"  [TICK] {symbol:20s} bid={data.get('bid', 0):>10.2f} "
                f"ask={data.get('ask', 0):>10.2f} last={data.get('last', 0):>10.2f}"
            )

    def notify_orderbook(self, orderbook):
        symbol = orderbook.symbol
        data = orderbook.data
        self.orderbooks_received[symbol] += 1
        self.latest_orderbook[symbol] = data
        if self.orderbooks_received[symbol] % 5 == 1:
            bids = data.get("bids", [])
            asks = data.get("asks", [])
            best_bid = bids[0][0] if bids else 0
            best_ask = asks[0][0] if asks else 0
            spread = best_ask - best_bid if best_bid and best_ask else 0
            print(
                f"  [OB]   {symbol:20s} bid={best_bid:>10.2f} "
                f"ask={best_ask:>10.2f} spread={spread:>6.2f} depth={len(bids)}/{len(asks)}"
            )

    def notify_bar(self, bar):
        symbol = bar.symbol
        data = bar.data
        self.bars_received[symbol] += 1
        self.latest_bar[symbol] = data
        print(
            f"  [BAR]  {symbol:20s} O={data.get('open', 0):>10.2f} "
            f"H={data.get('high', 0):>10.2f} L={data.get('low', 0):>10.2f} "
            f"C={data.get('close', 0):>10.2f} V={data.get('volume', 0):>10.2f}"
        )

    def next(self):
        self.next_calls += 1
        current_symbols = {
            symbol
            for symbol in self.p.symbols
            if symbol in self.latest_tick or symbol in self.latest_bar
        }
        self.symbols_in_next.update(current_symbols)
        if self.next_calls % 20 == 1:
            print(f"\n  [NEXT] Call #{self.next_calls}, symbols: {current_symbols}")

    def get_stats(self):
        """Return data-stream counters for the final report."""
        return {
            "elapsed": time.time() - self.start_time,
            "ticks": dict(self.ticks_received),
            "orderbooks": dict(self.orderbooks_received),
            "bars": dict(self.bars_received),
            "next_calls": self.next_calls,
            "symbols_in_next": sorted(self.symbols_in_next),
        }


def _wrap(channel, symbol, raw):
    """Create the light event wrapper expected by strategy callbacks."""
    return type("LiveEvent", (), {"symbol": symbol, "data": raw, "channel": channel})()


async def _watch_until_deadline(awaitable_factory, start_time, duration):
    """Await one WebSocket update without exceeding the demo deadline."""
    remaining = duration - (time.time() - start_time)
    if remaining <= 0:
        return None
    try:
        return await asyncio.wait_for(awaitable_factory(), timeout=remaining)
    except asyncio.TimeoutError:
        return None


async def watch_ticker(exchange, symbol, strategy, start_time, duration):
    """Forward ticker updates until the configured duration expires."""
    try:
        while True:
            ticker = await _watch_until_deadline(
                lambda: exchange.watch_ticker(symbol), start_time, duration
            )
            if ticker is None:
                return
            strategy.notify_tick(_wrap("tick", symbol, ticker))
            if len(strategy.latest_tick) >= len(strategy.p.symbols):
                strategy.next()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[ERROR] watch_ticker {symbol}: {type(exc).__name__}: {exc}")


async def watch_orderbook(exchange, symbol, strategy, start_time, duration):
    """Forward public five-level order-book snapshots until the deadline."""
    try:
        while True:
            orderbook = await _watch_until_deadline(
                lambda: exchange.watch_order_book(symbol, limit=5), start_time, duration
            )
            if orderbook is None:
                return
            strategy.notify_orderbook(_wrap("orderbook", symbol, orderbook))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[ERROR] watch_orderbook {symbol}: {type(exc).__name__}: {exc}")


async def watch_ohlcv(exchange, symbol, strategy, start_time, duration):
    """Forward completed one-minute bars until the deadline."""
    try:
        while True:
            ohlcv = await _watch_until_deadline(
                lambda: exchange.watch_ohlcv(symbol, "1m"), start_time, duration
            )
            if ohlcv is None:
                return
            latest = ohlcv[-1] if ohlcv else None
            if latest:
                strategy.notify_bar(
                    _wrap(
                        "bar",
                        symbol,
                        {
                            "timestamp": latest[0],
                            "open": latest[1],
                            "high": latest[2],
                            "low": latest[3],
                            "close": latest[4],
                            "volume": latest[5],
                        },
                    )
                )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[ERROR] watch_ohlcv {symbol}: {type(exc).__name__}: {exc}")


async def run_live_stream(strategy, symbols, duration):
    """Connect to OKX and run all public data watchers concurrently."""
    try:
        import ccxt.pro as ccxtpro
    except ImportError:
        print("ERROR: ccxt.pro not installed. Install with: pip install ccxt[pro]")
        return False

    config, proxy_url = _build_exchange_config()
    exchange = None
    try:
        exchange = await _create_exchange(ccxtpro, config, proxy_url)
        missing_symbols = [symbol for symbol in symbols if symbol not in exchange.markets]
        if missing_symbols:
            print(f"ERROR: Symbols not found in OKX markets: {missing_symbols}")
            return False

        print("Connected to OKX exchange")
        print(f"Symbols: {symbols}")
        print(f"Duration: {duration}s")
        print("=" * 80)

        start_time = time.time()
        tasks = []
        for symbol in symbols:
            tasks.extend(
                (
                    watch_ticker(exchange, symbol, strategy, start_time, duration),
                    watch_orderbook(exchange, symbol, strategy, start_time, duration),
                    watch_ohlcv(exchange, symbol, strategy, start_time, duration),
                )
            )
        await asyncio.gather(*tasks)
        return True
    finally:
        if exchange is not None:
            await exchange.close()


def main():
    """Run the public-data MixBroker demo."""
    _load_env()
    symbols = ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    duration = 30

    print("\n" + "=" * 80)
    print("Live MixBroker Demo - OKX Multi-Symbol Data Stream")
    print("=" * 80)

    cerebro = bt.Cerebro()
    cerebro.setbroker(MixBroker(cash=100000.0))
    cerebro.addstrategy(LiveMultiSymbolStrategy, symbols=symbols)
    strategies = cerebro.run(channel=True)
    strategy = strategies[0]

    try:
        connected = asyncio.run(run_live_stream(strategy, symbols, duration))
    except KeyboardInterrupt:
        print("\nStopped by user")
        connected = False
    finally:
        cerebro.runstop()

    stats = strategy.get_stats()
    print("\n" + "=" * 80)
    print("Results")
    print("=" * 80)
    print(f"Duration:           {stats['elapsed']:.1f}s")
    print(f"Ticks received:     {stats['ticks']}")
    print(f"Orderbooks:         {stats['orderbooks']}")
    print(f"Bars:               {stats['bars']}")
    print(f"next() calls:       {stats['next_calls']}")

    received_all = all(
        stats["ticks"].get(symbol, 0) and stats["orderbooks"].get(symbol, 0) for symbol in symbols
    )
    return 0 if connected and received_all and stats["next_calls"] else 1


if __name__ == "__main__":
    sys.exit(main())
