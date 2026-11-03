"""Tests for the Store's structural-sharing tick snapshot (iteration 60.03)."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from backtrader.utils.tick_snapshot import snapshot_tick


@dataclass
class _MutableRecord:
    values: list = field(default_factory=list)


@dataclass(frozen=True)
class _ForeignFrozen:
    values: list


def _tick(**extra):
    base = dict(
        symbol="SA609",
        price=1500.0,
        volume=3.0,
        datetime=_dt.datetime(2026, 11, 2, 2, 0, tzinfo=_dt.timezone.utc),
        reasons=("A", "B"),
        quality_flags=["X"],
        flags_set={"Y"},
        meta={"k": "v"},
        nested={"inner": ["z"]},
        record=_MutableRecord(["r"]),
    )
    base.update(extra)
    return SimpleNamespace(**base)


def test_snapshot_is_independent_of_source_mutation():
    tick = _tick()
    snap = snapshot_tick(tick)
    tick.price = 0.0
    tick.quality_flags.append("LATE")
    tick.flags_set.add("LATE")
    tick.meta["k"] = "changed"
    tick.nested["inner"].append("late")
    tick.record.values.append("late")
    assert snap.price == 1500.0
    assert snap.quality_flags == ["X"]
    assert snap.flags_set == {"Y"}
    assert snap.meta == {"k": "v"}
    assert snap.nested == {"inner": ["z"]}
    assert snap.record.values == ["r"]


def test_source_is_independent_of_snapshot_mutation():
    tick = _tick()
    snap = snapshot_tick(tick)
    snap.quality_flags.append("CONSUMER")
    snap.nested["inner"].append("consumer")
    assert tick.quality_flags == ["X"]
    assert tick.nested == {"inner": ["z"]}


def test_immutable_values_are_shared_not_copied():
    tick = _tick()
    snap = snapshot_tick(tick)
    assert snap.reasons is tick.reasons
    assert snap.datetime is tick.datetime
    assert snap.quality_flags is not tick.quality_flags


def test_foreign_frozen_dataclass_is_deep_copied():
    # Only bt_api_base / bt_api_py contracts are trusted as deeply immutable.
    tick = _tick(foreign=_ForeignFrozen(["a"]))
    snap = snapshot_tick(tick)
    assert snap.foreign is not tick.foreign
    tick.foreign.values.append("late")
    assert snap.foreign.values == ["a"]


def test_dict_tick_snapshot():
    tick = {"price": 1.0, "flags": ["a"]}
    snap = snapshot_tick(tick)
    tick["flags"].append("b")
    assert snap == {"price": 1.0, "flags": ["a"]}


def test_other_objects_fall_back_to_deepcopy():
    record = _MutableRecord(["r"])
    snap = snapshot_tick(record)
    record.values.append("late")
    assert snap.values == ["r"]


def test_sdk_market_tick_event_is_shared():
    baseline = pytest.importorskip("tests.unit.feeds.test_market_tick_adapter_baseline")
    from backtrader.feeds.market_tick_adapter import adapt_market_tick_event

    fields = adapt_market_tick_event(baseline._event())
    snap = snapshot_tick(fields)
    assert snap.market_tick_event is fields.market_tick_event
    assert vars(snap) == vars(fields)
    fields.quality_flags.append("LOCAL")
    assert snap.quality_flags == []


def test_frozen_contract_with_mutable_fields_is_copied_not_shared():
    import dataclasses
    import types

    # A frozen dataclass from a contract package that still holds a dict and
    # a list: ``frozen`` does not make those immutable.
    module = types.ModuleType("bt_api_base._test_mutable_contract")

    @dataclasses.dataclass(frozen=True)
    class Holder:
        values: dict
        rows: list

    Holder.__module__ = module.__name__
    original = Holder({"bid": 1}, [1, 2])
    tick = {"payload": original}
    copied = snapshot_tick(tick)
    assert copied["payload"] is not original
    original.values["bid"] = 99
    original.rows.append(3)
    assert copied["payload"].values == {"bid": 1}
    assert copied["payload"].rows == [1, 2]
    copied["payload"].values["ask"] = 2
    assert "ask" not in original.values


def test_frozen_contract_with_mapping_proxy_of_scalars_is_shared():
    import dataclasses
    from types import MappingProxyType

    @dataclasses.dataclass(frozen=True)
    class Frozen:
        values: MappingProxyType

    Frozen.__module__ = "bt_api_base._test_frozen_contract"
    payload = Frozen(MappingProxyType({"bid": 1}))
    assert snapshot_tick({"payload": payload})["payload"] is payload
