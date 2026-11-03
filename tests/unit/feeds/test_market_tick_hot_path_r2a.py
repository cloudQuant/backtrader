"""Iteration 60 R2-A: typed v2 SDK ticks keep the typed gates; hot-path shortcuts.

Since Base moved the tick payload to schema v2 the adapter labels ticks
``sdk.market.tick.v2``, while the feed and SDK classified only ``...v1`` as a
typed SDK tick, so the typed gates (upstream eligibility, clock evidence,
price grid knowledge, decision-boundary reset) were skipped for every adapted
tick. These tests pin the gates on the v2 label.
"""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.market_tick_contracts")

import backtrader as bt  # noqa: E402
from backtrader.feeds import _btapi_cohort  # noqa: E402
from backtrader.feeds.btapifeed import BtApiFeed  # noqa: E402
from backtrader.feeds.market_tick_adapter import adapt_market_tick_event  # noqa: E402
from bt_api_py import market_tick_contracts  # noqa: E402

from tests.unit.feeds import test_market_tick_adapter_baseline as baseline  # noqa: E402


def _event(**overrides):
    return baseline.bind_market_tick_event(
        baseline._payload(**overrides),
        baseline.SOURCE,
        baseline.MarketEventCursor(
            stream_id=baseline.SOURCE.stream_id, epoch=baseline.SOURCE.epoch, sequence=1
        ),
    )


def _feed(**params):
    values = dict(
        dataname="SA609",
        store=None,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        price_tick=1.0,
        event_time_max_age=1e12,
        receive_time_max_age=1e12,
    )
    values.update(params)
    return BtApiFeed(**values)


def test_adapted_ticks_carry_the_current_typed_schema_label() -> None:
    tick = adapt_market_tick_event(_event())
    assert tick.schema_version == "sdk.market.tick.v2"
    assert tick.schema_version in market_tick_contracts.TYPED_MARKET_TICK_SCHEMA_VERSIONS
    assert "sdk.market.tick.v1" in market_tick_contracts.TYPED_MARKET_TICK_SCHEMA_VERSIONS


def test_qualified_v2_tick_passes_the_typed_gates() -> None:
    feed = _feed()
    tick = adapt_market_tick_event(_event())
    feed._prepare_tick(tick)
    assert tick.quality == "GOOD"
    assert tick.quality_flags == ()
    assert tick.execution_eligible is True
    assert tick.bar_eligible is True


def test_v2_tick_without_upstream_eligibility_is_not_promoted_by_the_feed() -> None:
    feed = _feed()
    tick = adapt_market_tick_event(_event(execution_eligible=False))
    feed._prepare_tick(tick)
    assert "UPSTREAM_EXECUTION_INELIGIBLE" in tick.quality_flags
    assert tick.execution_eligible is False
    assert tick.quality == "INVALID"


def test_v2_tick_without_a_known_price_grid_is_flagged() -> None:
    feed = _feed(price_tick=None)
    tick = adapt_market_tick_event(_event())
    feed._prepare_tick(tick)
    assert "PRICE_TICK_UNKNOWN" in tick.quality_flags
    assert tick.execution_eligible is False


def test_v2_tick_resets_decision_boundary_fields() -> None:
    feed = _feed()
    tick = adapt_market_tick_event(_event())
    tick.cohort_decision_now_monotonic_ns = 123  # must never come from the payload
    feed._attach_market_decision_now(tick)
    assert tick.cohort_decision_now_monotonic_ns is None


def test_tick_value_namespace_fast_path_matches_getattr_semantics() -> None:
    rng = random.Random(4)
    names = ("a", "b", "c", "d")
    pool = (None, 0, "", False, 1, "x", (), 2.5)

    def reference(tick, *names, default=None):
        for name in names:
            value = getattr(tick, name, None)
            if value is not None:
                return value
        return default

    for _ in range(3000):
        fields = {name: rng.choice(pool) for name in names if rng.random() < 0.6}
        tick = SimpleNamespace(**fields)
        query = tuple(rng.sample(names, rng.randint(1, 3)))
        default = rng.choice((None, "dflt"))
        expected = reference(tick, *query, default=default)
        assert _btapi_cohort._tick_value(tick, *query, default=default) == expected
        assert market_tick_contracts._tick_value(tick, *query, default=default) == expected

    class Sub(SimpleNamespace):
        a = "class-attr"

    # Subclasses keep the getattr path (class attributes stay visible).
    assert _btapi_cohort._tick_value(Sub(), "a") == "class-attr"
    assert market_tick_contracts._tick_value(Sub(), "a") == "class-attr"
