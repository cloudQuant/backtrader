"""Conservative shallow-copy contract for normalized Store history rows."""

from __future__ import annotations

import datetime
from copy import deepcopy
from unittest.mock import patch

import pytest

import backtrader.stores._bar_history_cache as history_cache_module
from backtrader.stores._bar_history_cache import StoreBarHistoryCache
from backtrader.utils.bar_projection import normalize_bar


class _FloatSubclass(float):
    pass


class _DictSubclass(dict):
    pass


def _bar(index=0, **updates):
    row = {
        "datetime": datetime.datetime(2025, 1, 1) + datetime.timedelta(days=index),
        "open": float(index + 1),
        "high": float(index + 2),
        "low": float(index),
        "close": float(index + 1.5),
        "volume": float(index + 10),
        "openinterest": float(index + 20),
    }
    row.update(updates)
    return row


def _cache(*, preserve_raw_bars=False):
    return StoreBarHistoryCache(
        preserve_raw_bars=preserve_raw_bars,
        normalize_bar=normalize_bar,
    )


def test_exact_normalized_rows_use_shallow_copy_and_isolate_return_mutations():
    cache = _cache()
    source = [_bar(0), _bar(1, bar_final=True)]

    with patch.object(
        history_cache_module,
        "deepcopy",
        side_effect=AssertionError("normalized fast path must not deepcopy"),
    ):
        copied = cache.copy_history_sequence(source)

    assert copied == source
    assert copied is not source
    assert all(clone is not original for clone, original in zip(copied, source))
    assert copied[0]["datetime"] is source[0]["datetime"]
    assert copied[0]["close"] is source[0]["close"]

    copied.append(_bar(2))
    copied[0]["close"] = -1.0
    copied[1].pop("bar_final")
    assert len(source) == 2
    assert source[0]["close"] == 1.5
    assert source[1]["bar_final"] is True


def test_shallow_fast_path_preserves_deepcopy_aliases_for_repeated_rows():
    cache = _cache()
    repeated = _bar(0)
    source = [repeated, repeated, dict(repeated)]

    old_copy = deepcopy(source)
    assert old_copy[0] is old_copy[1]
    assert old_copy[0] is not old_copy[2]

    with patch.object(
        history_cache_module,
        "deepcopy",
        side_effect=AssertionError("normalized fast path must not deepcopy"),
    ):
        copied = cache.copy_history_sequence(source)

    assert copied[0] is copied[1]
    assert copied[0] is not copied[2]
    assert copied[0] is not repeated
    copied[0]["close"] = -1.0
    assert copied[1]["close"] == -1.0
    assert repeated["close"] == 1.5


def test_default_history_reads_use_the_same_isolated_fast_path():
    cache = _cache()
    cache.set_history("TEST", [_bar(0), _bar(1)])

    with patch.object(
        history_cache_module,
        "deepcopy",
        side_effect=AssertionError("normalized default history must not deepcopy"),
    ):
        result = cache.cached_default_history("TEST")
    result[0]["close"] = 999.0
    result.pop()

    assert [row["close"] for row in cache.cached_default_history("TEST")] == [
        1.5,
        2.5,
    ]


@pytest.mark.parametrize(
    "row",
    [
        _bar(0, metadata={"tags": []}),
        _bar(0, open=1),
        _bar(0, high=_FloatSubclass(2.0)),
        _bar(0, bar_final=1),
        _bar(0, bar_final={"tags": []}),
        _bar(0, datetime=datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)),
        _DictSubclass(_bar(0)),
    ],
)
def test_extra_or_non_exact_rows_fall_back_to_deepcopy(row):
    cache = _cache()

    with patch.object(history_cache_module, "deepcopy", wraps=deepcopy) as clone:
        copied = cache.copy_history_sequence([row])

    assert clone.call_count == 1
    assert copied[0] is not row
    if "metadata" in row:
        copied[0]["metadata"]["tags"].append("returned")
        assert row["metadata"]["tags"] == []
    if type(row.get("bar_final")) is dict:
        copied[0]["bar_final"]["tags"].append("returned")
        assert row["bar_final"]["tags"] == []


def test_mixed_sequence_falls_back_as_one_deepcopy_operation():
    cache = _cache()
    rows = [_bar(0), _bar(1, annotations=["source"])]

    with patch.object(history_cache_module, "deepcopy", wraps=deepcopy) as clone:
        copied = cache.copy_history_sequence(rows)

    assert clone.call_count == 1
    assert copied[0] is not rows[0]
    assert copied[1] is not rows[1]
    copied[1]["annotations"].append("returned")
    assert rows[1]["annotations"] == ["source"]


def test_raw_mode_keeps_its_existing_deep_copy_path():
    cache = _cache(preserve_raw_bars=True)
    source = _bar(0, metadata={"tags": ["source"]})

    copied = cache.copy_history_sequence([source])

    assert copied[0] is not source
    copied[0]["metadata"]["tags"].append("returned")
    assert source["metadata"]["tags"] == ["source"]


def test_copying_does_not_reapply_since_or_limit_filters():
    cache = _cache()
    rows = [_bar(0), _bar(1), _bar(2)]
    key = cache.request_key("TEST", "minutes", 1, "cursor-a", 2)
    cache.cache_result("TEST", key, False, rows)

    hit, found_key, default_request, copied = cache.lookup("TEST", "minutes", 1, "cursor-a", 2)
    assert hit is True
    assert found_key == key
    assert default_request is False
    assert copied == rows

    assert cache.lookup("TEST", "minutes", 1, "cursor-b", 2)[0] is False
    assert cache.lookup("TEST", "minutes", 1, "cursor-a", 1)[0] is False
