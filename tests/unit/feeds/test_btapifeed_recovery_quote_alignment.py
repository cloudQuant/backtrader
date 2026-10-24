"""Regression coverage for BtApiFeed's per-bar recovery quote cursor."""

import datetime as dt

import backtrader as bt

from backtrader.events import TickEvent
from backtrader.feeds.btapifeed import BtApiFeed
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


_SYMBOL = "BTC-USDT"
_SOURCE_REF = "btapifeed-recovery-quote-alignment-test"
_GENERATION = "btapifeed-recovery-quote-generation-r1"
_FIRST_TIMESTAMP = 1_797_000_000


def _tick(sequence):
    timestamp = float(_FIRST_TIMESTAMP + sequence - 1)
    event_datetime = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc)
    tick = TickEvent(
        timestamp=timestamp,
        symbol=_SYMBOL,
        exchange="synthetic",
        asset_type="spot",
        local_time=timestamp,
        price=10.0 + sequence,
        volume=1.0,
        direction="buy",
        trade_id=f"recovery-quote-alignment-{sequence}",
        bid_price=9.0 + sequence,
        ask_price=11.0 + sequence,
        bid_volume=5.0,
        ask_volume=5.0,
    )
    tick.datetime = event_datetime.replace(tzinfo=None)
    tick.connection_generation = _GENERATION
    tick.ingest_seq = sequence
    return tick


def test_tick_timeframe_freezes_each_ingested_quote_on_its_own_bar():
    """A queued later tick must not replace the first line bar's quote."""
    client = FakeBtApiClient(live_ticks={_SYMBOL: [_tick(1), _tick(2)]})
    store = make_store(api=client, provider="btapi")
    feed = store.getdata(
        dataname=_SYMBOL,
        timeframe=bt.TimeFrame.Ticks,
        compression=1,
        backfill_start=False,
        service_recovery_quote_binding=True,
        service_recovery_quote_source_ref=_SOURCE_REF,
    )
    assert type(feed) is BtApiFeed

    try:
        feed._start()
        feed._check()
        assert len(feed._live) == 1
        assert len(client.live_ticks[_SYMBOL]) == 1

        observed = []
        for sequence in (1, 2):
            assert feed.load() is True
            binding = feed.service_execution_recovery_quote_binding()
            expected_time = dt.datetime.fromtimestamp(
                _FIRST_TIMESTAMP + sequence - 1, dt.timezone.utc
            ).replace(tzinfo=None)
            assert len(feed) == sequence
            assert feed.datetime.datetime(0) == expected_time
            assert binding == {
                "source_ref": _SOURCE_REF,
                "generation": _GENERATION,
                "cursor": sequence,
                "instrument": _SYMBOL,
                "as_of_ns": (_FIRST_TIMESTAMP + sequence - 1) * 1_000_000_000,
            }
            observed.append((len(feed), feed.datetime.datetime(0), binding))

        assert tuple(client.subscriptions) == (_SYMBOL,)
        assert len(client.live_ticks[_SYMBOL]) == 0
        assert observed[0][2]["cursor"] == 1
        assert observed[1][2]["cursor"] == 2
        assert observed[0][2]["as_of_ns"] < observed[1][2]["as_of_ns"]
    finally:
        feed.stop()
        store.stop()
