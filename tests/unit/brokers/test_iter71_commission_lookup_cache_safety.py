"""Safety and freshness regressions for R71-031 commission lookup keys."""

import gc
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import weakref
from types import SimpleNamespace

import pytest

from backtrader.broker import BrokerBase
from backtrader.brokers.bbroker import BackBroker
from backtrader.comminfo import CommInfoBase


_IDENTITY_ATTRIBUTES = ("name", "_name", "_dataname", "symbol")


def _data(**overrides):
    values = dict.fromkeys(_IDENTITY_ATTRIBUTES, "")
    values.update(overrides)
    return SimpleNamespace(**values)


def _commission(value):
    return CommInfoBase(commission=value)


class _CountingBackBroker(BackBroker):
    def __init__(self):
        self.key_builds = 0
        super().__init__()

    def _commission_lookup_keys_from_values(self, values):
        self.key_builds += 1
        return BrokerBase._commission_lookup_keys_from_values(values)


class _BarrierBackBroker(BackBroker):
    def __init__(self):
        self.key_build_barrier = None
        super().__init__()

    def _commission_lookup_keys_from_values(self, values):
        keys = BrokerBase._commission_lookup_keys_from_values(values)
        barrier = self.key_build_barrier
        if barrier is not None:
            barrier.wait(timeout=5)
        return keys


def test_repeated_stable_lookup_reuses_only_normalized_keys():
    broker = _CountingBackBroker()
    data = _data(name="ALPHA")
    alpha = _commission(0.001)
    broker.addcommissioninfo(alpha, name="ALPHA")

    assert broker.getcommissioninfo(data) is alpha
    first_build_count = broker.key_builds
    assert first_build_count == 1

    assert broker.getcommissioninfo(data) is alpha
    assert broker.key_builds == first_build_count


@pytest.mark.parametrize("attribute", _IDENTITY_ATTRIBUTES)
def test_each_identifier_field_change_rebuilds_lookup_keys(attribute):
    broker = _CountingBackBroker()
    alpha = _commission(0.001)
    beta = _commission(0.002)
    broker.addcommissioninfo(alpha, name="ALPHA")
    broker.addcommissioninfo(beta, name="BETA")
    data = _data(**{attribute: "ALPHA"})

    assert broker.getcommissioninfo(data) is alpha
    builds_after_alpha = broker.key_builds

    setattr(data, attribute, "BETA")
    assert broker.getcommissioninfo(data) is beta
    assert broker.key_builds == builds_after_alpha + 1


def test_identifier_priority_and_case_fallback_are_preserved():
    broker = BackBroker()
    alpha = _commission(0.001)
    beta = _commission(0.002)
    broker.addcommissioninfo(alpha, name="ALPHA")
    broker.addcommissioninfo(beta, name="BETA")
    data = _data(name="alpha", _name="BETA")

    assert broker.getcommissioninfo(data) is alpha

    data.name = ""
    assert broker.getcommissioninfo(data) is beta


def test_setcommission_replacement_is_visible_after_cache_warmup():
    broker = BackBroker()
    data = _data(name="ALPHA")
    original = _commission(0.001)
    broker.addcommissioninfo(original, name="ALPHA")
    assert broker.getcommissioninfo(data) is original

    broker.setcommission(commission=0.003, name="ALPHA")
    replacement = broker.comminfo["ALPHA"]

    assert replacement is not original
    assert broker.getcommissioninfo(data) is replacement


def test_addcommissioninfo_replacement_is_visible_after_cache_warmup():
    broker = BackBroker()
    data = _data(name="ALPHA")
    original = _commission(0.001)
    replacement = _commission(0.004)
    broker.addcommissioninfo(original, name="ALPHA")
    assert broker.getcommissioninfo(data) is original

    broker.addcommissioninfo(replacement, name="ALPHA")

    assert broker.getcommissioninfo(data) is replacement


def test_public_commission_mapping_mutations_are_not_cached_as_results():
    broker = BackBroker()
    data = _data(name="ALPHA")
    original = _commission(0.001)
    replacement = _commission(0.005)
    broker.addcommissioninfo(original, name="ALPHA")
    assert broker.getcommissioninfo(data) is original

    broker.comminfo["ALPHA"] = replacement

    assert broker.getcommissioninfo(data) is replacement


def test_default_commission_replacement_is_visible_for_cached_miss():
    broker = BackBroker()
    data = _data(name="NO_MATCH")
    original = broker.comminfo[None]
    assert broker.getcommissioninfo(data) is original

    replacement = _commission(0.006)
    broker.addcommissioninfo(replacement)

    assert broker.getcommissioninfo(data) is replacement


def test_mutable_hashable_identifier_uses_uncached_normalization():
    broker = BackBroker()
    alpha = _commission(0.001)
    beta = _commission(0.002)
    broker.addcommissioninfo(alpha, name="ALPHA")
    broker.addcommissioninfo(beta, name="BETA")

    class MutableSymbol:
        def __init__(self, value):
            self.value = value

        def __hash__(self):
            return 1

        def __str__(self):
            return self.value

    symbol = MutableSymbol("ALPHA")
    data = _data(symbol=symbol)

    assert broker.getcommissioninfo(data) is alpha
    symbol.value = "BETA"
    assert broker.getcommissioninfo(data) is beta


def test_unhashable_identifier_is_skipped_before_later_candidates():
    broker = BackBroker()
    beta = _commission(0.002)
    broker.addcommissioninfo(beta, name="BETA")
    data = _data(name=["ALPHA"], _name="BETA")

    assert broker.getcommissioninfo(data) is beta


def test_custom_identifier_getter_exception_is_not_retried_or_replaced():
    broker = BackBroker()
    expected = LookupError("identity unavailable")

    class ExplodingData:
        @property
        def name(self):
            raise expected

    with pytest.raises(LookupError) as caught:
        broker.getcommissioninfo(ExplodingData())

    assert caught.value is expected


def test_custom_string_conversion_exception_is_preserved():
    broker = BackBroker()
    expected = RuntimeError("identity conversion failed")

    class BadString:
        def __hash__(self):
            return 1

        def __str__(self):
            raise expected

    data = _data(name=BadString())

    with pytest.raises(RuntimeError) as caught:
        broker.getcommissioninfo(data)

    assert caught.value is expected


def test_key_cache_does_not_keep_data_objects_alive():
    broker = BackBroker()
    class WeakData:
        pass

    data = WeakData()
    for attribute in _IDENTITY_ATTRIBUTES:
        setattr(data, attribute, "")
    data.name = "ALPHA"
    data_ref = weakref.ref(data)
    broker.getcommissioninfo(data)

    del data
    gc.collect()

    assert data_ref() is None


def test_key_cache_is_bounded_for_many_distinct_names():
    broker = BackBroker()
    for index in range(200):
        broker.getcommissioninfo(_data(name="symbol-{}".format(index)))

    assert len(broker._commission_lookup_key_cache) <= 128


def test_custom_lookup_hook_remains_authoritative():
    class CustomBackBroker(BackBroker):
        @staticmethod
        def _commission_lookup_keys(data):
            return ["CUSTOM"]

    broker = CustomBackBroker()
    custom = _commission(0.007)
    broker.comminfo["CUSTOM"] = custom

    assert broker.getcommissioninfo(_data(name="IGNORED")) is custom


def test_runtime_monkeypatch_of_base_lookup_hook_remains_authoritative(monkeypatch):
    broker = BackBroker()
    data = _data(name="IGNORED")
    assert broker.getcommissioninfo(data) is broker.comminfo[None]
    custom = _commission(0.008)

    def patched_lookup(data):
        return ["PATCHED"]

    monkeypatch.setattr(
        BrokerBase,
        "_commission_lookup_keys",
        staticmethod(patched_lookup),
    )
    broker.comminfo["PATCHED"] = custom

    assert broker.getcommissioninfo(data) is custom


def test_concurrent_colliding_writes_keep_fixed_capacity_and_correct_results():
    broker = _BarrierBackBroker()
    names_by_slot = {}
    for index in range(10000):
        name = "seed-{}".format(index)
        slot = hash((name, "", "", "")) % 128
        names_by_slot.setdefault(slot, name)
        if len(names_by_slot) == 128:
            break

    assert len(names_by_slot) == 128
    for name in names_by_slot.values():
        broker.getcommissioninfo(_data(name=name))

    target_slot = hash(("race-0", "", "", "")) % 128
    collision_names = []
    for index in range(10000):
        name = "race-{}".format(index)
        if hash((name, "", "", "")) % 128 == target_slot:
            collision_names.append(name)
            if len(collision_names) == 2:
                break

    assert len(collision_names) == 2
    first, second = collision_names
    first_info = _commission(0.009)
    second_info = _commission(0.010)
    broker.addcommissioninfo(first_info, name=first)
    broker.addcommissioninfo(second_info, name=second)
    broker.key_build_barrier = Barrier(2)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(broker.getcommissioninfo, _data(name=first))
        second_future = executor.submit(broker.getcommissioninfo, _data(name=second))
        assert first_future.result(timeout=8) is first_info
        assert second_future.result(timeout=8) is second_info

    broker.key_build_barrier = None
    cache = broker._commission_lookup_key_cache
    assert type(cache) is list
    assert len(cache) == 128
    assert all(entry is not None for entry in cache)
    assert broker.getcommissioninfo(_data(name=first)) is first_info
    assert broker.getcommissioninfo(_data(name=second)) is second_info
