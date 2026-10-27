"""Feed leaves and production Alpha003 graphs in capacity snapshots."""

from collections import deque
from types import SimpleNamespace

import pytest

from backtrader.research.alpha101 import get_alpha
from backtrader.research.live_capacity import (
    LiveCapacitySampler,
    _graph_capacity_facts,
)
from tests.unit.research.test_live_capacity import _registered_store
from tests.unit.research.test_live_factor_binding import _make_inputs


def _real_alpha003_case(mode="native"):
    cerebro, cohort, feed, _plan, _values, _clock = _make_inputs(
        count=40, mode=mode, indicator=get_alpha(3)
    )
    strategy = cerebro.run()[0]
    strategy.order_events = deque(maxlen=8)
    strategy.trade_events = deque(maxlen=8)
    store, _api = _registered_store()
    return strategy, feed, cohort, store


@pytest.mark.parametrize("mode", ("native", "build"))
def test_real_feed_lines_and_alpha003_diagnostics_are_observed(mode):
    strategy, feed, cohort, store = _real_alpha003_case(mode)
    assert strategy.snapshots[-1].readiness.name == "LIVE_READY"

    row = LiveCapacitySampler("alpha003-capacity-run", (39,), max_samples=1).sample(
        39, strategy=strategy, cohort=cohort, store=store
    )
    assert row["status"] == "OBSERVED", row
    assert row["acceptance_evaluated"] is False
    assert row["lines"]["status"] == "OBSERVED"
    assert row["diagnostics"]["status"] == "OBSERVED"
    assert "indicator_graph_edge_unavailable" not in row["lines"]["issues"]
    assert "factor_diagnostics_unavailable" not in row["diagnostics"]["issues"]

    original_datas = strategy.datas
    baseline, _nodes = _graph_capacity_facts(
        strategy,
        strategy.live_factors,
        max_graph_nodes=100_000,
        max_graph_references=200_000,
    )
    unique_feed_lines = len({id(line) for line in feed.lines.lines})
    try:
        strategy.datas = ()
        without_feed, _nodes = _graph_capacity_facts(
            strategy,
            strategy.live_factors,
            max_graph_nodes=100_000,
            max_graph_references=200_000,
        )
        strategy.datas = original_datas + original_datas
        duplicate_feed_refs, _nodes = _graph_capacity_facts(
            strategy,
            strategy.live_factors,
            max_graph_nodes=100_000,
            max_graph_references=200_000,
        )
    finally:
        strategy.datas = original_datas

    assert baseline["line_buffer_count"] - without_feed["line_buffer_count"] == unique_feed_lines
    assert baseline["line_buffer_count"] == duplicate_feed_refs["line_buffer_count"]


def test_real_feed_filter_state_and_unknown_owner_fail_closed():
    strategy, feed, cohort, store = _real_alpha003_case()

    feed._filters.append((object(), (), {}))
    filtered, _nodes = _graph_capacity_facts(
        strategy,
        strategy.live_factors,
        max_graph_nodes=100_000,
        max_graph_references=200_000,
    )
    assert filtered["status"] == "INCOMPLETE"
    assert "feed_filter_or_resampling_state_unsupported" in filtered["issues"]
    feed._filters.clear()

    unknown = SimpleNamespace(lines=SimpleNamespace(lines=[]), getindicators=None)
    strategy.datas = tuple(strategy.datas) + (unknown,)
    row = LiveCapacitySampler("alpha003-capacity-run", (39,), max_samples=1).sample(
        39, strategy=strategy, cohort=cohort, store=store
    )
    assert row["status"] == "INCOMPLETE"
    assert "indicator_graph_edge_unavailable" in row["lines"]["issues"]
