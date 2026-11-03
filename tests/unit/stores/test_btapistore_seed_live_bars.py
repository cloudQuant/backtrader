"""Offline tests for Store initialization of the completed-bar queue."""

import pytest

from backtrader.stores.btapistore import BtApiStore


def _store(**kwargs):
    return BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}, "live_bar_queue_size": 2},
        autostart=False,
        preserve_raw_bars=True,
        **kwargs,
    )


@pytest.mark.parametrize("live_bars", [None, {}, {"SA": []}])
def test_construct_without_live_bars_leaves_queue_empty(live_bars):
    store = _store(live_bars=live_bars)
    assert store._live_bar_queue.snapshot("SA") == (0, 0, "")
    assert store.is_connected is False


def test_seeded_bars_use_bounded_fifo_and_detach_inputs():
    bars = [{"close": 1}, {"close": 2}, {"close": 3}]
    store = _store(live_bars={"SA": iter(bars), "TA": [{"close": 4}]})
    depth, evictions, stale = store._live_bar_queue.snapshot("SA")
    assert (depth, evictions, stale) == (2, 1, "store_live_bar_queue_overflow")
    assert store._live_bar_queue.snapshot("TA") == (1, 0, "")
    assert store.poll_live("SA")["close"] == 2
    retained = store.poll_live("SA")
    assert retained["close"] == 3 and retained["stale"] is True
    assert "stale" not in bars[2]
    assert store.poll_live("TA")["close"] == 4


def test_seeded_bars_use_normal_projection_by_default():
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        autostart=False,
        live_bars={"SA": [["2026-11-03T09:00:00Z", 1, 3, 1, 2, 5]]},
    )
    bar = store.poll_live("SA")
    assert bar["close"] == 2.0 and bar["volume"] == 5.0
    assert bar["datetime"].isoformat() == "2026-11-03T09:00:00"
