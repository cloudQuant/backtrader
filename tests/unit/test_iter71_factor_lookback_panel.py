"""Declared factor lookback readiness at the public sink/panel boundary."""

from __future__ import annotations

import math

import pandas as pd
import pytest

import backtrader as bt
from backtrader.research import align_to_grid
from backtrader.research.alpha101 import get_alpha
from backtrader.research.sink import MemorySink
from backtrader.research.specs import FactorSpec, ResearchSpec
from backtrader.strategies.factor_strategy import FactorStrategy


class _ResearchData(bt.feeds.PandasData):
    lines = ("dollar_volume",)
    params = (("dollar_volume", "dollar_volume"),)


class _RecordingSink(MemorySink):
    """Custom sink that retains the values received by its public callback."""

    def __init__(self):
        super().__init__()
        self.points = []

    def on_point(self, time, asset, values, open_price, close_price, present):
        self.points.append((time, asset, dict(values)))
        super().on_point(time, asset, values, open_price, close_price, present)


def _frames(periods: int):
    index = pd.date_range("2025-01-01", periods=periods, freq="D", tz="UTC")
    frames = {}
    for asset in range(6):
        close = [
            100.0 + asset * 3.0 + 0.13 * row + 2.0 * math.sin(0.31 * row + asset)
            for row in range(periods)
        ]
        volume = [100.0 + 5.0 * asset + (row % 7) for row in range(periods)]
        dollar_volume = [price * shares for price, shares in zip(close, volume)]
        frames["asset-%d" % asset] = pd.DataFrame(
            {
                "open": [value - 0.2 for value in close],
                "high": [value + 1.0 for value in close],
                "low": [value - 1.0 for value in close],
                "close": close,
                "volume": volume,
                "openinterest": [0.0] * periods,
                "dollar_volume": dollar_volume,
            },
            index=index,
        )
    return frames


def _factor_spec(name, indicator):
    bindings = {}
    for alias in indicator.formula_fields:
        if alias.startswith("adv") and alias[3:].isdigit():
            bindings[alias] = {
                "derive": "adv",
                "source": "dollar_volume",
                "window": int(alias[3:]),
            }
        else:
            bindings[alias] = "feed:target:%s" % alias
    return FactorSpec(
        name=name,
        indicator=indicator,
        panel_line="factor",
        field_bindings=bindings,
    )


def _run(alpha_id: int, periods: int, *, runonce: bool):
    frames = _frames(periods)
    names = tuple(frames)
    index = next(iter(frames.values())).index.rename("close_time")
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(hours=6)},
        index=index,
    )
    research = ResearchSpec(
        grid=grid,
        start=index[0],
        end=index[-1],
        targets=names,
        source_timezone="UTC",
        snapshot_id="iter71-lookback-%d-%d" % (alpha_id, periods),
        price_basis="synthetic unadjusted OHLC and dollar volume",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
    )
    sink = _RecordingSink()
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    for name, frame in frames.items():
        aligned = align_to_grid(frame, research, name)
        feed = _ResearchData(dataname=aligned.feed.p.dataname)
        setattr(
            feed,
            "_factor_research_alignment_v2",
            getattr(aligned.feed, "_factor_research_alignment_v2"),
        )
        cerebro.adddata(feed, name=name)
    factor_name = "alpha%d" % alpha_id
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={factor_name: _factor_spec(factor_name, get_alpha(alpha_id))},
        sink=sink,
    )
    strategy = cerebro.run()[0]
    return strategy, sink, index, names, factor_name


@pytest.mark.parametrize(
    "alpha_id,periods",
    ((1, 12), (1, 30), (7, 48), (7, 72)),
    ids=("alpha1-short", "alpha1-long", "alpha7-short", "alpha7-long"),
)
@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
def test_alpha_lookback_warmup_is_nan_in_custom_sink_and_panel(
    alpha_id: int, periods: int, runonce: bool
) -> None:
    strategy, sink, index, names, factor_name = _run(alpha_id, periods, runonce=runonce)
    lookback = strategy._factor_specs_by_name[factor_name].lookback_h
    panel = strategy.get_panel().factors[factor_name]

    assert len(sink.points) == periods * len(names)
    assert len(panel) == periods * len(names)
    for cursor in range(periods):
        expected_time = index[cursor].to_pydatetime()
        batch = sink.points[cursor * len(names) : (cursor + 1) * len(names)]
        assert [point[1] for point in batch] == list(names)
        assert all(point[0] == expected_time for point in batch)
        values = [float(point[2][factor_name]) for point in batch]
        if cursor < lookback:
            assert all(math.isnan(value) for value in values)
            assert all(
                math.isnan(float(panel.at[(expected_time, asset)])) for asset in names
            )
        elif cursor == lookback:
            assert any(math.isfinite(value) for value in values)
            assert any(
                math.isfinite(float(panel.at[(expected_time, asset)])) for asset in names
            )

    if periods <= lookback:
        assert panel.isna().all()
    else:
        factor = strategy.factor_instances[factor_name]
        assert any(
            math.isfinite(float(factor.outputs[data].factor.array[cursor]))
            for data in strategy.datas
            for cursor in range(lookback)
        ), "the fixture must distinguish formula output from collector readiness"
