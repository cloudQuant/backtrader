"""Native factor lifecycle and configuration isolation contracts."""

from __future__ import annotations

import math
from typing import Dict, Tuple

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research.errors import ConfigError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.inputs import prealign_bars
from backtrader.research.specs import FactorSpec, ResearchSpec


_ASSETS = ("AAA", "BBB")
_CLOSE = {
    "AAA": (12.0, 18.0, 24.0, 30.0, 36.0, 42.0, 48.0),
    "BBB": (60.0, 54.0, 66.0, 72.0, 78.0, 84.0, 90.0),
}
_RANGE = {
    "AAA": (2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0),
    "BBB": (12.0, 10.0, 8.0, 6.0, 4.0, 2.0, 0.0),
}


class _CloseAverage(FactorIndicator):
    lines = ("value",)
    params = (("period", 3),)
    lookback_h = 2

    def __init__(self) -> None:
        super().__init__()
        self.rolling = {
            data: bt.ind.SMA(data.close, period=self.p.period) for data in self.datas
        }

    def next(self) -> None:
        for data in self.target_datas:
            self.outputs[data].value[0] = self.rolling[data][0]


class _RangeAverage(FactorIndicator):
    lines = ("value",)
    params = (("period", 2),)
    lookback_h = 1

    def __init__(self) -> None:
        super().__init__()
        self.rolling = {
            data: bt.ind.SMA(data.high - data.low, period=self.p.period)
            for data in self.datas
        }

    def next(self) -> None:
        for data in self.target_datas:
            self.outputs[data].value[0] = self.rolling[data][0]


def _research_and_inputs(run_number: int) -> Tuple[ResearchSpec, Dict[str, pd.DataFrame]]:
    grid = pd.date_range(
        "2026-04-06", periods=7, freq="D", tz="UTC", name="close_time"
    )
    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": grid - pd.Timedelta(hours=1)}, index=grid),
        start=grid[0],
        end=grid[-1],
        targets=_ASSETS,
        source_timezone="UTC",
        snapshot_id="factor-isolation-%d" % run_number,
        price_basis="synthetic unadjusted USD close values",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        groups=dict.fromkeys(_ASSETS, "same-group"),
    )
    inputs: Dict[str, pd.DataFrame] = {}
    close_shift = 6.0 * run_number
    range_shift = 2.0 * run_number
    for asset in _ASSETS:
        close = [value + close_shift for value in _CLOSE[asset]]
        ranges = [value + range_shift for value in _RANGE[asset]]
        inputs[asset] = pd.DataFrame(
            {
                "open": [value - 1.0 for value in close],
                "high": [value + width / 2.0 for value, width in zip(close, ranges)],
                "low": [value - width / 2.0 for value, width in zip(close, ranges)],
                "close": close,
                "volume": [1000.0 + i for i in range(len(grid))],
                "openinterest": [0.0] * len(grid),
            },
            index=grid,
        )
    return research, inputs


def _expected_panel(inputs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    grid = inputs[_ASSETS[0]].index
    rows = []
    for position, timestamp in enumerate(grid):
        for asset in _ASSETS:
            closes = inputs[asset]["close"].tolist()
            widths = (inputs[asset]["high"] - inputs[asset]["low"]).tolist()
            close_average = (
                sum(closes[position - 2 : position + 1]) / 3.0 if position >= 2 else math.nan
            )
            range_average = (
                sum(widths[position - 1 : position + 1]) / 2.0 if position >= 1 else math.nan
            )
            rows.append((timestamp, asset, close_average, range_average))
    index = pd.MultiIndex.from_tuples(
        [(time, asset) for time, asset, _, _ in rows], names=("time", "asset")
    )
    return pd.DataFrame(
        [(close_average, range_average) for _, _, close_average, range_average in rows],
        index=index,
        columns=("close_average", "range_average"),
    )


def _run_two_factors(run_number: int, runonce: bool):
    research, inputs = _research_and_inputs(run_number)
    cerebro = bt.Cerebro(stdstats=False)
    feeds = {}
    for asset in _ASSETS:
        feed = prealign_bars(inputs[asset], research, asset).feed
        feeds[asset] = feed
        cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={
            "close_average": FactorSpec(
                name="close_average",
                indicator=_CloseAverage,
                panel_line="value",
                params={"period": 3},
            ),
            "range_average": FactorSpec(
                name="range_average",
                indicator=_RangeAverage,
                panel_line="value",
                params={"period": 2},
            ),
        },
    )
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    return strategy, inputs, feeds


@pytest.mark.parametrize("runonce", (False, True))
def test_two_native_rolling_factors_are_isolated_across_complete_runs(runonce: bool) -> None:
    runs = [_run_two_factors(number, runonce) for number in (0, 1)]
    contexts = []
    output_lines = []

    for strategy, inputs, feeds in runs:
        actual = strategy.get_dataset().raw_factors
        expected = _expected_panel(inputs)
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
        assert tuple(actual.index.names) == ("time", "asset")
        assert actual.index.is_unique
        assert tuple(actual.columns) == ("close_average", "range_average")
        assert len(actual) == len(inputs[_ASSETS[0]]) * len(_ASSETS)

        assert tuple(strategy.factor_instances) == ("close_average", "range_average")
        for factor_name, factor in strategy.factor_instances.items():
            context = factor._factor_strict_context
            contexts.append(context)
            assert context.factor == factor_name
            assert factor.lifecycle_diagnostics["call_count"] == len(inputs[_ASSETS[0]])
            assert factor.lifecycle_diagnostics["grid_matches"]
            assert tuple(data._name for data in factor.datas) == _ASSETS
            assert tuple(data._name for data in factor.target_datas) == _ASSETS
            assert factor.getindicators()
            assert all(child._owner is factor for child in factor.getindicators())
            assert all(child._factor_strict_context is context for child in factor.getindicators())

            for asset in _ASSETS:
                data = feeds[asset]
                line = factor.output_for(data, "value")
                assert line is factor.outputs[data].value
                assert line._factor_strict_context is context
                assert len(line) == len(inputs[asset])
                assert line.buflen() == len(inputs[asset])
                output_lines.append(line)

    # Each factor has its own context, and every independent Cerebro run gets
    # new contexts, real Lines, and rolling Indicator instances.
    assert len({id(context) for context in contexts}) == 4
    assert len({id(line) for line in output_lines}) == 8
    for strategy, _, _ in runs:
        for factor in strategy.factor_instances.values():
            with pytest.raises(ConfigError, match="FactorIndicator subclasses"):
                FactorSpec(
                    name="prior_run_instance",
                    indicator=factor,
                    panel_line="value",
                )
            with pytest.raises(ConfigError, match="unbound concrete FactorIndicator"):
                FactorSpec(
                    name="prior_run_bound_class",
                    indicator=type(factor),
                    panel_line="value",
                )


def test_ordinary_indicator_is_not_a_research_factor() -> None:
    with pytest.raises(ConfigError, match="FactorIndicator subclasses"):
        FactorSpec(name="ordinary", indicator=bt.ind.SMA, panel_line="sma")


def test_duplicate_feed_names_fail_before_factor_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    research, inputs = _research_and_inputs(0)
    cerebro = bt.Cerebro(stdstats=False)
    for asset in _ASSETS:
        cerebro.adddata(prealign_bars(inputs[asset], research, asset).feed, name="duplicate")

    constructions = []
    original_init = _CloseAverage.__init__

    def observed_init(self: _CloseAverage) -> None:
        constructions.append(self)
        original_init(self)

    monkeypatch.setattr(_CloseAverage, "__init__", observed_init)
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={
            "close_average": FactorSpec(
                name="close_average",
                indicator=_CloseAverage,
                panel_line="value",
                params={"period": 3},
            )
        },
    )

    with pytest.raises(ConfigError, match="feed names must be unique"):
        cerebro.run(runonce=False, preload=True)
    assert constructions == []
