"""Tests for the CryptoHFTData historical feed."""

from datetime import datetime, timezone

import pandas as pd
import pytest

import backtrader as bt


class StubClient:
    """Return deterministic CryptoHFTData SDK-shaped trades."""

    def __init__(self, trades):
        self.trades = trades
        self.calls = []

    def get_trades(self, **kwargs):
        """Record the query and return a copy of the fixture."""
        self.calls.append(kwargs)
        return self.trades.copy()


def _trades():
    start = datetime(2026, 7, 11, tzinfo=timezone.utc)
    return pd.DataFrame(
        [
            _trade(start, 1, "10", "2"),
            _trade(start.replace(second=20), 2, "12", "3"),
            _trade(start.replace(second=40), 3, "9", "4"),
            _trade(start.replace(minute=1), 4, "11", "5"),
        ]
    )


def _trade(timestamp, trade_id, price, quantity):
    return {
        "trade_time": int(timestamp.timestamp() * 1000),
        "trade_id": trade_id,
        "price": price,
        "quantity": quantity,
        "is_buyer_maker": False,
    }


def _load_feed(client, **kwargs):
    data = bt.feeds.CryptoHFTData(
        dataname="KAVAUSDT",
        exchange="binance_futures",
        fromdate=datetime(2026, 7, 11),
        todate=datetime(2026, 7, 11, 0, 2),
        client=client,
        **kwargs,
    )
    data._start()
    rows = []
    while data.load():
        rows.append(
            {
                "datetime": data.datetime.datetime(0),
                "open": data.open[0],
                "high": data.high[0],
                "low": data.low[0],
                "close": data.close[0],
                "volume": data.volume[0],
            }
        )
    return data, rows


def test_minute_feed_downloads_and_aggregates_trades():
    """Minute bars preserve UTC OHLCV semantics and query parameters."""
    client = StubClient(_trades())
    _data, rows = _load_feed(client, timeframe=bt.TimeFrame.Minutes)

    assert client.calls == [
        {
            "symbol": "KAVAUSDT",
            "exchange": "binance_futures",
            "start_date": "2026-07-11",
            "end_date": "2026-07-11",
        }
    ]
    assert len(rows) == 2
    assert rows[0] == {
        "datetime": datetime(2026, 7, 11),
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 9.0,
        "volume": 9.0,
    }


def test_tick_feed_emits_one_bar_per_trade():
    """Tick mode exposes every historical trade without aggregation."""
    _data, rows = _load_feed(StubClient(_trades()), timeframe=bt.TimeFrame.Ticks)

    assert len(rows) == 4
    assert rows[0]["open"] == rows[0]["close"] == 10.0
    assert rows[0]["volume"] == 2.0


def test_feed_requires_bounded_dates():
    """A bounded range is mandatory for high-frequency downloads."""
    data = bt.feeds.CryptoHFTData(
        dataname="BTCUSDT", exchange="binance_futures", client=StubClient(_trades())
    )

    with pytest.raises(ValueError, match="both fromdate and todate"):
        data._start()


def test_feed_rejects_unsupported_timeframe():
    """Weekly requests fail clearly instead of silently misaggregating."""
    data = bt.feeds.CryptoHFTData(
        dataname="BTCUSDT",
        exchange="binance_futures",
        fromdate=datetime(2026, 7, 11),
        todate=datetime(2026, 7, 12),
        timeframe=bt.TimeFrame.Weeks,
        client=StubClient(_trades()),
    )

    with pytest.raises(ValueError, match="does not support"):
        data._start()
