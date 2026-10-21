"""Current formula-universe membership is an independent output gate."""

from __future__ import annotations

import math
from types import MappingProxyType
from typing import Any

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research.alpha101 import get_alpha
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.inputs import prealign_bars
from backtrader.research.specs import FactorSpec, ResearchSpec
from tests.test_utils.alpha101_native_harness import alpha_name
from tests.unit.test_factor_research_representatives import (
    _factor_spec,
    _frames,
    _research_spec,
)


_FEED_ALIGNMENT = "_factor_research_alignment_v1"


class _ReadyStateFactor(FactorIndicator):
    """Emit finite, formula-authored READY values to test gate precedence."""

    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")

    def next(self) -> None:
        for data, close in zip(self.target_datas, self._closes):
            self.outputs[data].factor[0] = float(close[0])
            self.record_availability(
                data,
                ready=True,
                valid=True,
                reason="READY",
            )


def _research_fixture() -> tuple[dict[str, Any], ResearchSpec]:
    frames = _frames(periods=48)
    assets = tuple(frames)
    grid = next(iter(frames.values())).index
    formula_membership = pd.Series(
        True,
        index=pd.MultiIndex.from_product([grid, assets], names=("time", "asset")),
        dtype=bool,
    )
    formula_membership.loc[(grid[30], "asset-0")] = False
    formula_membership.loc[(grid[30:33], "asset-1")] = False
    formula_membership.loc[(grid[20], "asset-2")] = False
    formula_membership.loc[(grid[21], "asset-3")] = False
    formula_membership.loc[(grid[22], "asset-4")] = False

    base = _research_spec(frames, formula_universe=formula_membership)
    universe = base.universe
    universe.loc[(grid[39], "asset-5")] = False
    research = ResearchSpec(
        grid=base.grid,
        start=base.start,
        end=base.end,
        targets=base.targets,
        source_timezone=base.source_timezone,
        snapshot_id=base.snapshot_id,
        price_basis=base.price_basis,
        calendar_id=base.calendar_id,
        frequency=base.frequency,
        feed_time_kind=base.feed_time_kind,
        groups=base.groups,
        universe=universe,
        formula_universe=base.formula_universe,
        formula_fields=base.formula_fields,
        classifications=base.classifications,
    )
    return frames, research


def _add_feed(cerebro: Any, frame: pd.DataFrame, research: ResearchSpec, asset: str) -> Any:
    aligned = prealign_bars(frame, research, asset)
    feed_frame = aligned.feed.p.dataname
    feed = bt.feeds.PandasData(dataname=feed_frame)
    metadata = dict(getattr(aligned.feed, _FEED_ALIGNMENT))
    if asset == "asset-2":
        present = list(metadata["present"])
        present[20] = False
        metadata["present"] = tuple(present)
    if asset == "asset-3":
        available_at = list(metadata["available_at"])
        available_at[21] = research.grid.index[21].to_pydatetime() + pd.Timedelta(hours=1)
        metadata["available_at"] = tuple(available_at)
    setattr(feed, _FEED_ALIGNMENT, MappingProxyType(metadata))
    cerebro.adddata(feed, name=asset)
    return feed


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_formula_membership_gates_ts_cs_and_authored_ready_outputs(runonce: bool) -> None:
    frames, research = _research_fixture()
    grid = research.calculation_grid.index
    alpha_ids = (1, 3, 9)
    alpha_classes = {alpha_id: get_alpha(alpha_id) for alpha_id in alpha_ids}

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for asset, frame in frames.items():
        _add_feed(cerebro, frame, research, asset)
    factors = {
        alpha_name(alpha_id): _factor_spec(alpha_name(alpha_id), alpha_classes[alpha_id])
        for alpha_id in alpha_ids
    }
    factors["authored_ready"] = FactorSpec(
        name="authored_ready",
        indicator=_ReadyStateFactor,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)

    broker_calls = {"submit": 0, "cancel": 0}

    def counted_submit(*args: Any, **kwargs: Any) -> Any:
        broker_calls["submit"] += 1
        raise AssertionError("FactorStrategy unexpectedly submitted a broker order")

    def counted_cancel(*args: Any, **kwargs: Any) -> Any:
        broker_calls["cancel"] += 1
        raise AssertionError("FactorStrategy unexpectedly cancelled a broker order")

    cerebro.broker.submit = counted_submit
    cerebro.broker.cancel = counted_cancel
    strategy = cerebro.run(runonce=runonce)[0]
    strategy._membership_broker_call_counts = dict(broker_calls)
    dataset = strategy.get_dataset()
    raw = dataset.raw_factors
    availability = dataset.availability

    def state(factor: str, index: int, asset: str) -> pd.Series:
        return availability.loc[(grid[index].to_pydatetime(), asset, factor)]

    def value(factor: str, index: int, asset: str) -> float:
        return float(raw.at[(grid[index].to_pydatetime(), asset), factor])

    # Alpha001's output is otherwise ready at H=24; current exclusion masks it.
    assert state("alpha1", 30, "asset-0")["reason"] == "FORMULA_INELIGIBLE"
    assert not bool(state("alpha1", 30, "asset-0")["ready"])
    assert not bool(state("alpha1", 30, "asset-0")["valid"])
    assert math.isnan(value("alpha1", 30, "asset-0"))
    assert state("alpha1", 31, "asset-0")["reason"] == "READY"
    assert math.isfinite(value("alpha1", 31, "asset-0"))

    # Alpha003's cross-sectional formula is NaN while excluded, then its
    # rolling dependency recovers only after a complete eligible rank window.
    assert state("alpha3", 30, "asset-0")["reason"] == "FORMULA_INELIGIBLE"
    assert math.isnan(value("alpha3", 30, "asset-0"))
    assert state("alpha3", 33, "asset-0")["reason"] != "FORMULA_INELIGIBLE"
    assert state("alpha3", 42, "asset-0")["reason"] == "READY"
    assert math.isfinite(value("alpha3", 42, "asset-0"))
    assert state("alpha3", 42, "asset-1")["reason"] == "READY"
    assert math.isfinite(value("alpha3", 42, "asset-1"))

    # Alpha009 is pure TS: its native line remains finite at an excluded cell,
    # while FactorStrategy's public output is correctly made ineligible.
    alpha9_line = strategy.factor_instances["alpha9"].outputs[strategy._target_datas[0]].factor
    assert math.isfinite(float(alpha9_line.array[30]))
    assert state("alpha9", 30, "asset-0")["reason"] == "FORMULA_INELIGIBLE"
    assert math.isnan(value("alpha9", 30, "asset-0"))

    # Current-bar and input failures retain their concrete reason priority.
    assert state("alpha3", 20, "asset-2")["reason"] == "NO_CURRENT_BAR"
    assert state("alpha3", 21, "asset-3")["reason"] == "NOT_YET_AVAILABLE"

    # Explicit factor-authored READY cannot bypass current formula exclusion.
    ready_state = state("authored_ready", 22, "asset-4")
    assert ready_state["reason"] == "FORMULA_INELIGIBLE"
    assert not bool(ready_state["ready"])
    assert not bool(ready_state["valid"])
    assert math.isnan(value("authored_ready", 22, "asset-4"))

    # ResearchSpec.universe is a separate evaluation mask.
    universe = dataset.universe
    formula_universe = dataset.formula_universe
    universe_key = (grid[39].to_pydatetime(), "asset-5")
    assert not bool(universe.loc[universe_key])
    assert bool(formula_universe.loc[universe_key])
    assert state("alpha9", 39, "asset-5")["reason"] == "READY"
    assert math.isfinite(value("alpha9", 39, "asset-5"))

    # Native roots and their formula trees run on the complete Cerebro grid;
    # the research strategy never submits or cancels broker orders.
    expected_times = tuple(point.to_pydatetime() for point in grid)
    assert strategy._membership_broker_call_counts == {"submit": 0, "cancel": 0}
    assert not strategy.broker.orders
    assert not strategy.broker.pending
    assert not strategy.broker.submitted
    for alpha_id in alpha_ids:
        instance = strategy.factor_instances[alpha_name(alpha_id)]
        assert instance._minperiod == alpha_classes[alpha_id].lookback_h + 1
        for nested in FactorStrategy._factor_tree(instance):
            diagnostics = nested.lifecycle_diagnostics
            assert diagnostics["call_count"] == len(grid)
            assert diagnostics["grid_count"] == len(grid)
            assert diagnostics["grid_matches"]
            assert tuple(diagnostics["call_times"]) == expected_times
