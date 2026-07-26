"""Regression tests for the public OKX MixBroker live demo."""

import asyncio
import importlib.util
import sys
from pathlib import Path

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


def test_public_config_ignores_credentials_and_unavailable_proxy(monkeypatch, capsys):
    """A stale developer proxy must not prevent the public demo from starting."""
    monkeypatch.setenv("OKX_API_KEY", "api-key")
    monkeypatch.setenv("OKX_SECRET", "secret")
    monkeypatch.setenv("OKX_PASSWORD", "password")
    monkeypatch.setenv("HTTPS_PROXY", "http://user:password@127.0.0.1:15732")
    monkeypatch.setattr(demo, "_proxy_is_reachable", lambda proxy_url: False)

    config, proxy_url = demo._build_exchange_config()

    assert config == {"enableRateLimit": True, "options": {"defaultType": "swap"}}
    assert proxy_url is None
    output = capsys.readouterr().out
    assert "credentials found but ignored" in output
    assert "user:password" not in output


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
