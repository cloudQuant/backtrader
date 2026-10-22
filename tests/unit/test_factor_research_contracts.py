from __future__ import annotations

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research import align_to_grid
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


def _grid(periods: int) -> pd.DatetimeIndex:
    return pd.date_range("2025-01-01 16:00:00", periods=periods, freq="D", tz="UTC", name="close_time")


def _source(index: pd.DatetimeIndex) -> pd.DataFrame:
    base = [10.5 + offset for offset in range(len(index))]
    return pd.DataFrame(
        {
            "open": [value - 0.5 for value in base],
            "high": [value + 0.5 for value in base],
            "low": [value - 1.0 for value in base],
            "close": base,
            "volume": [100.0 + 10.0 * offset for offset in range(len(index))],
        },
        index=index,
    )


def _research(grid_index: pd.DatetimeIndex, *, start: int, end: int) -> ResearchSpec:
    grid = pd.DataFrame({"open_time": grid_index - pd.Timedelta(hours=6)}, index=grid_index)
    return ResearchSpec(
        grid=grid,
        start=grid_index[start],
        end=grid_index[end],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="snapshot-v1",
        price_basis="USD close, unadjusted",
        calendar_id="fixture-calendar-v1",
        frequency="1day",
    )


def _run(research: ResearchSpec, source: pd.DataFrame, *, runonce: bool):
    aligned = align_to_grid(source, research, "AAA", data_version="bars-v1")
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    cerebro.adddata(aligned.feed, name="AAA")
    factor = FactorSpec(
        name="close_factor",
        indicator=_BoundClose,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"close_factor": factor})
    return cerebro.run(runonce=runonce)[0], aligned




def test_align_to_grid_retains_price_tail_beyond_research_end() -> None:
    """A grid may extend past ``end`` so label tails survive.

    ``calculation_grid`` stops at ``end`` (that is the factor index), while
    ``prices_open``/``prices_close`` and ``grid`` cover the complete grid.
    """
    grid_index = _grid(5)
    research = _research(grid_index, start=0, end=2)
    source = _source(grid_index)
    aligned = align_to_grid(source, research, "AAA")

    assert len(research.calculation_grid) == 3
    assert len(aligned.present) == 3
    assert len(aligned.prices_close) == 5
    assert aligned.prices_close[-1] == pytest.approx(source["close"].iloc[-1])
    assert list(aligned.present) == [True, True, True]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "source defect: align_to_grid() returns a full-grid feed, but FactorIndicator."
        "_record_factor_call raises RuntimeError('factor next() ran more than once for the "
        "requested grid') for the label-tail rows that lie after ResearchSpec.end; "
        "FactorStrategy._collect_current_grid_point already tolerates those rows"
    ),
)
def test_feed_with_label_tail_rows_can_be_added_to_cerebro() -> None:
    """Regression repro for the tail-row defect; remove the xfail when fixed.

    Minimal reproduction (no fixture helpers needed)::

        grid 4 rows, start=row1, end=row2, align_to_grid(frame, research, "AAA")
        cerebro.adddata(aligned.feed); cerebro.addstrategy(FactorStrategy, ...)
        cerebro.run()  ->  FactorComputationError from
                           RuntimeError("factor next() ran more than once ...")
    """
    grid_index = _grid(5)
    research = _research(grid_index, start=0, end=2)
    strategy, _ = _run(research, _source(grid_index), runonce=False)
    panel = strategy.get_panel()
    assert len(panel.factors) == 3
    assert panel.prices_close.loc[grid_index[4], "AAA"] == pytest.approx(14.5)
