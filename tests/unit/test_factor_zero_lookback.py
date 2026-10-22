"""Current-row and missing-window contracts for declared factor inputs."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research import align_to_grid
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec, ResearchSpec


class _ZeroLookbackConstant(FactorIndicator):
    lines = ("value",)
    panel_mode = "next"
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")

    def next(self) -> None:
        for data, close in zip(self.target_datas, self._closes):
            if math.isfinite(float(close[0])):
                value = 0.0
            else:
                # This branch deliberately returns a finite constant even
                # when the declared current input is non-finite.
                value = 0.0
            self.outputs[data].value[0] = value


class _TwoBarLookbackClose(FactorIndicator):
    lines = ("value",)
    panel_mode = "next"
    formula_fields = ("close",)
    lookback_h = 2

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")

    def next(self) -> None:
        for data, close in zip(self.target_datas, self._closes):
            self.outputs[data].value[0] = close[0]


def _grid(periods: int = 6) -> pd.DatetimeIndex:
    return pd.date_range(
        "2025-01-01 16:00:00",
        periods=periods,
        freq="D",
        tz="UTC",
        name="close_time",
    )


def _research(index: pd.DatetimeIndex) -> ResearchSpec:
    return ResearchSpec(
        grid=pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index),
        start=index[0],
        end=index[-1],
        targets=("AAA",),
        source_timezone="UTC",
        snapshot_id="zero-lookback-fixture-v1",
        price_basis="synthetic unadjusted USD close",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
    )


def _bars(index: pd.DatetimeIndex, closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [value - 0.5 if math.isfinite(value) else math.nan for value in closes],
            "high": [value + 1.0 if math.isfinite(value) else math.nan for value in closes],
            "low": [value - 1.0 if math.isfinite(value) else math.nan for value in closes],
            "close": closes,
            "volume": [100.0] * len(index),
            "openinterest": [0.0] * len(index),
        },
        index=index,
    )


def _run(
    index: pd.DatetimeIndex,
    source: pd.DataFrame,
    indicator: type[FactorIndicator],
    *,
    factor_name: str,
    runonce: bool,
) -> tuple[pd.Series, object, object]:
    research = _research(index)
    aligned = align_to_grid(source, research, "AAA")
    factor = FactorSpec(
        name=factor_name,
        indicator=indicator,
        panel_line="value",
        field_bindings={"close": "feed:target:close"},
    )
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(aligned.feed, name="AAA")
    cerebro.addstrategy(FactorStrategy, research=research, factors={factor_name: factor})
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    values = strategy.get_panel().factors.xs("AAA", level="asset")[factor_name]
    output = strategy.factor_instances[factor_name].outputs[strategy.datas[0]].value
    return values, aligned, output.get(size=len(index))


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_zero_lookback_masks_nonfinite_declared_current_input(runonce: bool) -> None:
    index = _grid()
    source = _bars(index, [10.0, math.nan, 12.0, 13.0, 14.0, 15.0])

    values, aligned, output = _run(
        index,
        source,
        _ZeroLookbackConstant,
        factor_name="constant",
        runonce=runonce,
    )

    assert bool(aligned.present[1])
    assert math.isnan(float(source.loc[index[1], "close"]))
    assert output[1] == 0.0
    assert values.iloc[0] == 0.0
    assert math.isnan(values.iloc[1])
    assert values.iloc[2:].eq(0.0).all()


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_zero_lookback_masks_absent_current_bar(runonce: bool) -> None:
    index = _grid()
    source = _bars(index, [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]).drop(index=index[2])

    values, aligned, _ = _run(
        index,
        source,
        _ZeroLookbackConstant,
        factor_name="constant",
        runonce=runonce,
    )

    assert list(aligned.present) == [True, True, False, True, True, True]
    assert values.iloc[[0, 1, 3, 4, 5]].eq(0.0).all()
    assert math.isnan(values.iloc[2])


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_positive_lookback_masks_missing_window_then_recovers(runonce: bool) -> None:
    index = _grid()
    source = _bars(index, [10.0, math.nan, 12.0, 13.0, 14.0, 15.0])

    values, aligned, _ = _run(
        index,
        source,
        _TwoBarLookbackClose,
        factor_name="close",
        runonce=runonce,
    )

    assert list(aligned.present) == [True] * len(index)
    assert values.iloc[0] == 10.0
    assert values.iloc[1:4].isna().all()
    assert values.iloc[4:].tolist() == [14.0, 15.0]
