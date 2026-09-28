#!/usr/bin/env python
"""Retired OKX MixBroker demo, pending a reviewed Iteration 41 shadow route.

The historical example streamed public market data for two OKX perpetual
contracts. Its direct network route is paused. Run it only through a future
registered schema-v4 ``simulation/shadow`` runtime; the current registered
profile is a local no-action replay probe.

Requirements:
    pip install ccxt[pro]

Usage:
    bt-runtime run --strategy-dir examples/010_live_examples/runtime
"""

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backtrader_runtime.legacy import run_legacy_config_first_cli  # noqa: E402

RUNTIME_DIR = PROJECT_ROOT / "examples" / "010_live_examples" / "runtime"


def main(argv=None):
    """Route the old command through its registered config-first replay gate."""
    return run_legacy_config_first_cli(RUNTIME_DIR, argv)


if __name__ == "__main__":
    raise SystemExit(main())

import backtrader as bt  # noqa: E402


def _build_exchange_config():
    """Return the fixed public-only CCXT options without reading environment state."""
    return {
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},
    }


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
        """Initialize per-symbol event counters and latest-payload caches."""
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
        """Count and cache every live tick; print a one-line quote snapshot."""
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
        """Count orderbook updates; print best bid/ask and spread every 5th event."""
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
        """Count bars and print a one-line OHLCV summary for each closed bar."""
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
        """Aggregate per-strategy-clock statistics over symbols with live data."""
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
    """Reject the retired direct network route before importing a provider."""
    from backtrader_runtime.errors import PRESET_POLICY_VIOLATION, RuntimeConfigError
    from backtrader_runtime.inventory import iteration41_runtime_registry

    registry = iteration41_runtime_registry()
    shadow_runtime_dir = PROJECT_ROOT / "examples" / "010_live_examples" / "runtime-okx-shadow"
    try:
        registration = registry.require_runtime_dir(shadow_runtime_dir)
    except RuntimeConfigError:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the public OKX demo requires a separately reviewed simulation/shadow runtime",
            field_path="runtime.preset",
            reason="shadow_registration_required",
        ) from None

    # This historical helper accepts caller-supplied strategy objects and
    # settings, so it cannot dispatch the separately registered sealed runner.
    if "shadow" not in registration.allowed_presets:
        raise RuntimeConfigError(
            PRESET_POLICY_VIOLATION,
            "the public OKX demo requires a separately reviewed simulation/shadow runtime",
            field_path="runtime.preset",
            reason="shadow_registration_required",
        )

    # Keep this legacy function closed; operators use bt-runtime dispatch for
    # the independent config-first observer.
    raise RuntimeConfigError(
        PRESET_POLICY_VIOLATION,
        "the historical OKX helper cannot dispatch the sealed shadow runtime",
        field_path="runtime.runner",
        reason="shadow_dispatch_required",
    )
