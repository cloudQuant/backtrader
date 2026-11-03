"""Iteration 60 G6: bar finality per producer, through the SDK bar events.

``BtApiFeed`` publishes a bar only with an explicit ``bar_final=True``;
``False`` (still forming) and ``None`` (no completion claim) are dropped and
counted. This is a compatibility change: producers that state no finality
no longer reach the line buffers. Per producer:

* OKX websocket candles carry ``confirm`` (index 8): ``"0"`` -> forming,
  ``"1"`` -> final.
* Binance websocket klines carry ``k.x``: ``false`` -> forming, ``true`` ->
  final.
* CTP has no provider bar stream in this path (``CtpBarData`` states no
  finality and is not a live bar source); CTP bars are synthesized by
  ``BtApiFeed`` from eligible ticks and closed by the event-time watermark,
  which is the only way they become ``bar_final=True``.
* SDK history: ``MarketBar`` is by contract one closed interval (the OKX
  history provider ignores ``confirm="0"`` rows; the collector refuses bars
  closing in the future), so the Store projection marks it final.

The provider containers and the SDK normalizer are real; only the entry-point
discovery of the provider normalization policy is replaced by a direct
import (entry points are not installed in this checkout's environment).
"""

from __future__ import annotations

import collections
import datetime as dt
import importlib
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py._normalization")

import backtrader as bt  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402

OPEN_MS = 1_793_696_400_000  # 2026-11-03 09:00:00 UTC
OPEN = dt.datetime(2026, 11, 3, 9, 0)
_POLICIES = {
    "OKX": "bt_api_okx.normalization_policy",
    "BINANCE": "bt_api_binance.normalization_policy",
    "CTP": "bt_api_ctp.normalization_policy",
}


@pytest.fixture
def normalize(monkeypatch):
    import bt_api_py._normalization as normalization

    def policy(exchange_name):
        module = importlib.import_module(_POLICIES[exchange_name.split("___")[0]])
        return module.normalization_policy(exchange_name)

    monkeypatch.setattr(normalization, "normalization_policy", policy)
    return lambda item, exchange: normalization.normalize_event(item, exchange, kind="bar")


def _feed():
    feed = BtApiFeed(dataname="X", store=None, timeframe=bt.TimeFrame.Minutes, compression=1)
    feed.lines.datetime.forward()
    for line in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(feed.lines, line).forward()
    return feed


def _published(feed, bar):
    return feed._publish_bar(bar)


def _okx(confirm):
    okx = pytest.importorskip("bt_api_okx.containers.bars.okx_bar")
    row = [str(OPEN_MS), "100", "101", "99", "100.5", "12", "4", "5", confirm]
    bar = okx.OkxBarData(row, "BTC-USDT-SWAP", "SWAP", True)
    bar.init_data()
    return bar


def _binance(final):
    binance = pytest.importorskip("bt_api_binance.containers.bars.binance_bar")
    payload = {
        "e": "kline",
        "E": OPEN_MS + 60_000,
        "s": "BTCUSDT",
        "k": {
            "t": OPEN_MS,
            "T": OPEN_MS + 59_999,
            "o": "1",
            "h": "2",
            "l": "1",
            "c": "1.5",
            "v": "3",
            "q": "4",
            "n": 5,
            "V": "1",
            "Q": "1",
            "x": final,
        },
    }
    bar = binance.BinanceWssBarData(payload, "BTCUSDT", "SWAP", True)
    bar.init_data()
    return bar


# -- OKX -------------------------------------------------------------------------


@pytest.mark.parametrize("confirm,final", [("0", False), ("1", True)])
def test_okx_confirm_maps_to_bar_final(normalize, confirm, final):
    event = normalize(_okx(confirm), "OKX___SWAP")
    assert event["bar_final"] is final
    assert event["timestamp"] == OPEN_MS / 1000  # the candle open time
    feed = _feed()
    assert _published(feed, event) is final
    counts = feed.bar_integrity_counts()
    assert counts["unfinished"] == (0 if final else 1)


# -- Binance ---------------------------------------------------------------------


@pytest.mark.parametrize("x,final", [(False, False), (True, True)])
def test_binance_kline_x_maps_to_bar_final(normalize, x, final):
    event = normalize(_binance(x), "BINANCE___SWAP")
    assert event["bar_final"] is final
    feed = _feed()
    assert _published(feed, event) is final
    assert feed.bar_integrity_counts()["unfinished"] == (0 if final else 1)


def test_binance_kline_timestamp_is_the_open_time(normalize):
    """The kline open time ``k.t``, not the stream event time ``E``, is the bar time."""
    event = normalize(_binance(True), "BINANCE___SWAP")
    assert event["timestamp"] == OPEN_MS / 1000


# -- CTP -------------------------------------------------------------------------


def test_ctp_provider_bar_shape_states_no_finality_and_is_not_published():
    """A CTP-style bar row without a completion claim never reaches the lines."""
    feed = _feed()
    row = {"datetime": OPEN, "open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5, "volume": 3.0}
    assert _published(feed, row) is False
    assert feed.bar_integrity_counts()["unknown_finality"] == 1


def _ctp_tick(seconds, price, *, flags=()):
    when = (OPEN + dt.timedelta(seconds=seconds)).replace(tzinfo=dt.timezone.utc)
    return SimpleNamespace(
        price=price,
        volume=1.0,
        timestamp=when.timestamp(),
        datetime=when,
        bar_eligible=True,
        volume_complete=True,
        quality="GOOD",
        quality_flags=tuple(flags),
        exchange="SHFE",
        asset_type="futures",
    )


@pytest.mark.parametrize(
    "flags,source", [((), "local_aggregation"), (("LEGACY_SCHEMA",), "local_aggregation_legacy")]
)
def test_ctp_bars_are_synthesized_final_by_the_event_time_watermark(flags, source):
    feed = BtApiFeed(dataname="rb2601", store=None, timeframe=bt.TimeFrame.Minutes, compression=1)
    feed.p.dispatch_bars = False
    feed._ingest_tick(_ctp_tick(5, 3500.0, flags=flags))
    feed._ingest_tick(_ctp_tick(30, 3502.0, flags=flags))
    assert not feed._live  # the bucket is still open: nothing is final yet
    bucket_end = (OPEN + dt.timedelta(minutes=1)).replace(tzinfo=dt.timezone.utc)
    feed._max_event_timestamp = bucket_end.timestamp() + 1.0
    feed._last_ingest_monotonic_ns = None
    assert feed._flush_ready_bars(reason="tick") == 1
    (bar,) = feed._live
    assert bar["bar_final"] is True and bar["bar_source"] == source
    assert (bar["datetime"], bar["close"], bar["volume"]) == (OPEN, 3502.0, 2.0)


# -- SDK history -----------------------------------------------------------------


def test_okx_history_provider_ignores_unconfirmed_candles():
    provider = pytest.importorskip("bt_api_okx.market_history_provider")
    forming = [str(OPEN_MS), "1", "2", "1", "1.5", "3", "1", "1", "0"]
    closed = [str(OPEN_MS), "1", "2", "1", "1.5", "3", "1", "1", "1"]
    assert provider._parse_row(forming) == (OPEN_MS, None)
    assert provider._parse_row(closed)[1] is not None


def test_sdk_history_bars_are_projected_final_and_published():
    from bt_api_base.market_history_protocol import MarketBar
    from backtrader.stores._bar_history_cache import StoreBarHistoryCache
    from backtrader.utils.bar_projection import normalize_bar

    cache = StoreBarHistoryCache(preserve_raw_bars=False, normalize_bar=normalize_bar)
    bars = cache.project_market_bars(
        [
            MarketBar(
                open_time_utc="2026-11-03T09:00:00Z",
                close_time_utc="2026-11-03T09:01:00Z",
                open="1",
                high="2",
                low="1",
                close="1.5",
                volume="3",
            )
        ]
    )
    assert [bar["bar_final"] for bar in bars] == [True]
    feed = BtApiFeed(
        dataname="X", store=None, timeframe=bt.TimeFrame.Minutes, historical_bars=bars
    )
    feed.lines.datetime.forward()
    for line in ("open", "high", "low", "close", "volume", "openinterest"):
        getattr(feed.lines, line).forward()
    assert feed._load_history() is True
    assert feed.lines.close[0] == 1.5
    assert isinstance(feed._history, collections.deque)
