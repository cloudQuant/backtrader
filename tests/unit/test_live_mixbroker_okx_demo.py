"""Regression tests for the public OKX MixBroker live demo."""

import asyncio
import builtins
import importlib.util
import sys
from pathlib import Path

import pytest

from backtrader_runtime.errors import RuntimeConfigError

_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "010_live_examples"
    / "live_mixbroker_okx_demo.py"
)
_SPEC = importlib.util.spec_from_file_location("live_mixbroker_okx_demo", _EXAMPLE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
demo = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = demo
_SPEC.loader.exec_module(demo)


def test_public_config_is_fixed_and_does_not_read_credentials_or_proxy(monkeypatch, capsys):
    """The retired demo has no environment-driven credential or proxy path."""
    monkeypatch.setenv("OKX_API_KEY", "api-key")
    monkeypatch.setenv("OKX_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSWORD", "password")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:password@127.0.0.1:15732")
    config = demo._build_exchange_config()

    assert config == {"enableRateLimit": True, "options": {"defaultType": "swap"}}
    assert capsys.readouterr().out == ""


def test_imported_network_entry_rejects_before_ccxt_import(monkeypatch):
    """An imported caller cannot reach the old websocket route without registration."""
    original_import = builtins.__import__

    def reject_ccxt(name, *args, **kwargs):
        if name == "ccxt.pro" or name == "ccxt":
            raise AssertionError("the retired route imported CCXT before its runtime gate")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_ccxt)

    with pytest.raises(RuntimeConfigError) as failure:
        asyncio.run(demo.run_live_stream(object(), ["BTC/USDT:USDT"], 1.0))

    assert failure.value.reason == "shadow_dispatch_required"


def test_create_exchange_retries_directly_after_proxy_startup_failure():
    """A reachable-but-broken proxy falls back to a new direct OKX client."""

    class FakeExchange:
        def __init__(self):
            self.httpsProxy = None
            self.wsProxy = None
            self.closed = False

        async def load_markets(self):
            if self.httpsProxy:
                raise RuntimeError("proxy cannot reach OKX")
            self.markets = {"BTC/USDT:USDT": {}}

        async def close(self):
            self.closed = True

    class FakeCcxtPro:
        def __init__(self):
            self.instances = []

        def okx(self, config):
            exchange = FakeExchange()
            self.instances.append(exchange)
            return exchange

    ccxtpro = FakeCcxtPro()
    exchange = asyncio.run(
        demo._create_exchange(
            ccxtpro,
            {"enableRateLimit": True, "options": {"defaultType": "swap"}},
            "http://127.0.0.1:15732",
        )
    )

    assert len(ccxtpro.instances) == 2
    assert ccxtpro.instances[0].closed is True
    assert exchange is ccxtpro.instances[1]
    assert exchange.httpsProxy is None
    assert "BTC/USDT:USDT" in exchange.markets


def test_watch_deadline_stops_a_stalled_websocket_wait():
    """A silent WebSocket cannot keep the fixed-duration demo running forever."""

    async def never_returns():
        await asyncio.Event().wait()

    result = asyncio.run(demo._watch_until_deadline(never_returns, start_time=0.0, duration=0.0))

    assert result is None


def test_orderbook_watcher_uses_okx_public_five_level_depth():
    """The demo must avoid the unsupported 20-level public WebSocket request."""

    class FakeExchange:
        def __init__(self):
            self.calls = []

        async def watch_order_book(self, symbol, limit):
            self.calls.append((symbol, limit))

    exchange = FakeExchange()
    asyncio.run(
        demo.watch_orderbook(
            exchange,
            "BTC/USDT:USDT",
            strategy=object(),
            start_time=demo.time.time(),
            duration=1.0,
        )
    )

    assert exchange.calls == [("BTC/USDT:USDT", 5)]
