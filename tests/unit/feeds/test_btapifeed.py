"""Unit tests for the unified BtApiFeed."""

import pytest

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store


@pytest.fixture
def feed_stack():
    """Create a feed with deterministic history and live data."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.5),
            ]
        },
    )
    store = make_store(
        api=client,
        live_bars={DEFAULT_SYMBOL: [make_bar(2, 101.5, 103.0, 101.0, 102.5)]},
    )
    feed = store.getdata(dataname=DEFAULT_SYMBOL)
    feed._start()
    return client, store, feed


def test_feed_loads_history_then_live(feed_stack):
    """Feed should backfill history before consuming live bars."""
    _client, _store, feed = feed_stack

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(100.5)

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(101.5)

    assert feed.load() is True
    assert feed.close[0] == pytest.approx(102.5)

    notifications = feed.get_notifications()
    assert notifications == [(feed.LIVE, (), {})]


def test_feed_subscribes_and_reports_live_data(feed_stack):
    """Feed should register its symbol and detect pending live bars."""
    client, _store, feed = feed_stack

    assert client.subscriptions == [DEFAULT_SYMBOL]
    assert feed.haslivedata() is True
