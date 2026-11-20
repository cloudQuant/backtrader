"""Store latest-tick snapshot cache behavior and lifecycle wiring."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")

from bt_api_py.instrument_metadata_aliases import find_alias_match

from backtrader.stores import btapistore as store_module
from backtrader.stores._latest_tick_cache import StoreLatestTickCache
from backtrader.stores.btapistore import BtApiStore
from backtrader.utils.tick_snapshot import snapshot_tick


def _cache():
    return StoreLatestTickCache(
        snapshot_tick=snapshot_tick,
        aliases_for=store_module._contract_metadata_aliases,
    )


def test_latest_tick_cache_copies_both_sides_and_resolves_sdk_aliases():
    cache = _cache()
    source = {"price": 12.5, "levels": [{"size": 3}]}

    cache.store("ES", source)
    source["levels"][0]["size"] = 99

    first = cache.snapshot("ES.CONT", find_alias_match=find_alias_match)
    assert first == {"price": 12.5, "levels": [{"size": 3}]}
    first["levels"][0]["size"] = 77

    second = cache.snapshot("ES", find_alias_match=find_alias_match)
    assert second == {"price": 12.5, "levels": [{"size": 3}]}
    assert second["levels"] is not first["levels"]


def test_latest_tick_cache_preserves_alias_and_copy_lock_scope():
    lock_observations = []
    cache = None

    def aliases_for(name):
        lock_observations.append(("aliases", cache._lock.locked()))
        return store_module._contract_metadata_aliases(name)

    def snapshot(value):
        lock_observations.append(("copy", cache._lock.locked()))
        return snapshot_tick(value)

    cache = StoreLatestTickCache(snapshot_tick=snapshot, aliases_for=aliases_for)
    cache.store("ES", {"price": 1.0})
    lock_observations.clear()

    def matching(values, aliases, *, alias_fn, require_truthy):
        lock_observations.append(("match", cache._lock.locked()))
        return find_alias_match(
            values,
            aliases,
            alias_fn=alias_fn,
            require_truthy=require_truthy,
        )

    assert cache.snapshot("ES", find_alias_match=matching) == {"price": 1.0}
    assert lock_observations == [
        ("aliases", False),
        ("match", True),
        ("copy", True),
    ]


def test_latest_tick_cache_clear_removes_all_alias_readable_values():
    cache = _cache()
    cache.store("ES", {"price": 12.5})

    cache.clear()

    assert cache.snapshot("ES.CONT", find_alias_match=find_alias_match) is None


@pytest.mark.parametrize("sdk_mode", (False, True))
def test_store_poll_keeps_existing_latest_snapshot_contract(sdk_mode):
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        autostart=False,
        preserve_raw_bars=True,
    )
    source = {"price": 12.5, "levels": [{"size": 3}]}
    api = SimpleNamespace(poll_tick=lambda _name: source)

    store._sdk_mode = sdk_mode
    store._connected = True
    store._api = api
    store._sdk_api_activity = lambda: nullcontext(True)
    store._ensure_api_ready = lambda: api
    if sdk_mode:
        store._poll_sdk_market_stream = lambda _name, _api: source
        store._mark_feed_inflight = lambda _tick: None

    assert store.poll_tick("ES") is source
    source["levels"][0]["size"] = 99
    assert store.get_latest_tick_snapshot("ES.CONT") == {
        "price": 12.5,
        "levels": [{"size": 3}],
    }


def test_store_stop_clears_latest_tick_cache():
    store = BtApiStore(
        config={"exchange_kwargs": {"CTP___FUTURE": {}}},
        autostart=False,
        preserve_raw_bars=True,
    )
    store._sdk_mode = False
    store._latest_tick_cache.store("ES", {"price": 12.5})

    store._connected = False
    store._started = False
    store.stop()

    assert store.get_latest_tick_snapshot("ES") is None
