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
from backtrader.research import align_to_grid
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
        formula_fields=base.formula_fields,
        classifications=base.classifications,
    )
    return frames, research


def _add_feed(cerebro: Any, frame: pd.DataFrame, research: ResearchSpec, asset: str) -> Any:
    aligned = align_to_grid(frame, research, asset)
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


