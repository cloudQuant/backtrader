from __future__ import annotations

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.inputs import prealign_bars
from backtrader.research.specs import FactorSpec, ResearchSpec


class _BoundClose(FactorIndicator):
    lines = ("factor",)
    panel_mode = "next"
    formula_fields = ("close",)

    @classmethod
    def lookback_h(cls) -> int:
        return 0

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")

    def next(self) -> None:
        for data, close in zip(self.target_datas, self._closes):
            self.outputs[data].factor[0] = close[0]


@pytest.mark.parametrize("runonce", [False, True])
def test_bound_feed_inputs_preserve_declared_full_grid_tail(runonce: bool) -> None:
    grid_index = pd.date_range(
        "2025-01-01 16:00:00", periods=4, freq="D", tz="UTC", name="close_time"
    )
    grid = pd.DataFrame({"open_time": grid_index - pd.Timedelta(hours=6)}, index=grid_index)
    research = ResearchSpec(
        grid=grid,
        start=grid_index[1],
        end=grid_index[2],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="snapshot-v1",
        price_basis="USD close, unadjusted",
        calendar_id="fixture-calendar-v1",
        frequency="1day",
    )
    source = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0, 13.0],
            "high": [11.0, 12.0, 13.0, 14.0],
            "low": [9.0, 10.0, 11.0, 12.0],
            "close": [10.5, 11.5, 12.5, 13.5],
            "volume": [100.0, 110.0, 120.0, 130.0],
        },
        index=grid_index,
    )
    source.attrs["source_metadata"] = {
        "name": "close",
        "unit": "USD/share",
        "source_version": "source-v1",
    }
    actual_tail_available = grid_index[3] + pd.Timedelta(hours=6)
    aligned = prealign_bars(
        source,
        research,
        "AAA",
        available_at=[*grid_index[:3], actual_tail_available],
        data_version="bars-v1",
    )

    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(aligned.feed, name="AAA")
    factor = FactorSpec(
        name="close_factor",
        indicator=_BoundClose,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"close_factor": factor})
    strategy = cerebro.run(runonce=runonce)[0]
    dataset = strategy.get_dataset()

    assert dataset.raw_factors.index.get_level_values("time").unique().tolist() == [
        grid_index[1],
        grid_index[2],
    ]
    inputs = dataset.formula_inputs["feed:target:close"]
    assert inputs.index.get_level_values("time").unique().tolist() == list(grid_index)
    tail = inputs.loc[(grid_index[3], "AAA")]
    assert tail["value"] == pytest.approx(13.5)
    assert tail["available_at"] == actual_tail_available
    assert tail["data_version"] == "bars-v1"
    assert tail["data_version_source"] == "alignment_marker.data_version"
    assert inputs.attrs["source_metadata"]["source_version"] == "source-v1"
    assert inputs.attrs["source_metadata"]["source_binding"] == "feed:target:close"
