"""Runonce and runnext target provenance for PIT-derived Alpha081 inputs."""

from __future__ import annotations

import math
import random
from typing import Any

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.inputs import prealign_bars
from backtrader.research.operators import OperatorInputError, _read_panel_value
from backtrader.research.specs import FactorSpec, ResearchSpec


_ASSETS = tuple("asset-%d" % index for index in range(6))
_PERIODS = 100
_FEED_ALIGNMENT = "_factor_research_alignment_v1"


class _AlphaResearchFeed(bt.feeds.PandasData):
    lines = ("vwap",)
    params = (("vwap", "vwap"),)


def _source_metadata(field: str) -> dict[str, str]:
    if field == "vwap":
        return {
            "name": "vwap",
            "semantic": "volume_weighted_average_price",
            "unit": "USD per share",
            "currency": "USD",
            "adjustment": "synthetic-unadjusted-v1",
            "statistic": "trade_volume_weighted_mean",
            "source_version": "pit-derived-clock-v1",
        }
    if field == "volume":
        return {
            "name": "volume",
            "semantic": "share_volume",
            "unit": "shares",
            "adjustment": "synthetic-unadjusted-v1",
            "source_version": "pit-derived-clock-v1",
        }
    raise AssertionError("unknown fixture field")


def _frames(index: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    frames = {}
    for asset_index, asset in enumerate(_ASSETS):
        noise = random.Random(46_081 + asset_index)
        closes = []
        vwaps = []
        volumes = []
        for row in range(len(index)):
            close = 40.0 + asset_index * 0.8 + 0.025 * row + noise.uniform(-0.4, 0.4)
            vwap = (
                42.0
                + asset_index * 0.7
                + 0.019 * row
                + 2.0 * math.sin(row * 0.16 + asset_index * 1.1)
                + noise.uniform(-0.05, 0.05)
            )
            volume = (
                2_000_000.0
                + asset_index * 160_000.0
                + 600_000.0 * math.sin(row * 0.13 + asset_index * 1.7)
                + noise.uniform(-100_000, 100_000)
            )
            closes.append(close)
            vwaps.append(vwap)
            volumes.append(volume)

        frame = pd.DataFrame(
            {
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": volumes,
                "openinterest": [0.0] * len(index),
                "vwap": vwaps,
            },
            index=index,
        )
        frame.attrs["source_metadata"] = {
            "fields": {
                "vwap": _source_metadata("vwap"),
                "volume": _source_metadata("volume"),
            }
        }
        frames[asset] = frame
    return frames


def _table(
    frames: dict[str, pd.DataFrame], index: pd.DatetimeIndex, field: str, delay_minutes: int
) -> pd.DataFrame:
    table_index = pd.MultiIndex.from_product([index, _ASSETS], names=("time", "asset"))
    values = [
        float(frames[asset][field].iloc[row]) for row in range(len(index)) for asset in _ASSETS
    ]
    available_at = [
        point - pd.Timedelta(minutes=delay_minutes) for point in index for _asset in _ASSETS
    ]
    result = pd.DataFrame(
        {
            "value": values,
            "available_at": available_at,
            "data_version": ["pit-derived-clock-v1"] * len(table_index),
        },
        index=table_index,
    )
    result.attrs["source_metadata"] = _source_metadata(field)
    return result


def _research(index: pd.DatetimeIndex, frames: dict[str, pd.DataFrame]) -> ResearchSpec:
    grid_index = index.rename("close_time")
    grid = pd.DataFrame({"open_time": grid_index - pd.Timedelta(hours=6)}, index=grid_index)
    universe_index = pd.MultiIndex.from_product([grid_index, _ASSETS], names=("time", "asset"))
    return ResearchSpec(
        grid=grid,
        start=grid_index[0],
        end=grid_index[-1],
        targets=_ASSETS,
        source_timezone="UTC",
        snapshot_id="iteration46-pit-derived-clock-v1",
        price_basis="synthetic unadjusted USD fixture",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups=dict.fromkeys(_ASSETS, "market"),
        formula_universe=pd.Series(True, index=universe_index, dtype=bool),
        formula_fields={
            "pit_vwap": _table(frames, grid_index, "vwap", 5),
            "pit_volume": _table(frames, grid_index, "volume", 2),
        },
    )


def _add_feeds(cerebro: Any, research: ResearchSpec, frames: dict[str, pd.DataFrame]) -> None:
    for asset in _ASSETS:
        aligned = prealign_bars(
            frames[asset], research, asset, data_version="pit-derived-clock-bars-v1"
        )
        feed = _AlphaResearchFeed(dataname=aligned.feed.p.dataname)
        setattr(feed, _FEED_ALIGNMENT, getattr(aligned.feed, _FEED_ALIGNMENT))
        cerebro.adddata(feed, name=asset)


def _field_bindings(*, pit: bool) -> dict[str, Any]:
    return {
        "vwap": "table:pit_vwap" if pit else "feed:target:vwap",
        "volume": "table:pit_volume" if pit else "feed:target:volume",
        "dollar_volume": {
            "derive": "vwap_volume",
            "vwap": "vwap",
            "volume": "volume",
        },
        "adv10": {"derive": "adv", "source": "dollar_volume", "window": 10},
    }


def _pearson(left: list[float], right: list[float]) -> float:
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    covariance = math.fsum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_square = math.fsum((value - left_mean) ** 2 for value in left)
    right_square = math.fsum((value - right_mean) ** 2 for value in right)
    return covariance / math.sqrt(left_square * right_square)


def _first_rank_oracle(frames: dict[str, pd.DataFrame]) -> list[list[float]]:
    """Plain-Python Alpha081 first branch: dollar ADV, sum, correlation, CS rank."""
    row_count = len(next(iter(frames.values())))
    correlations = [[math.nan] * len(_ASSETS) for _ in range(row_count)]
    for asset_index, asset in enumerate(_ASSETS):
        vwap = [float(value) for value in frames[asset]["vwap"]]
        volume = [float(value) for value in frames[asset]["volume"]]
        dollar_volume = [price * shares for price, shares in zip(vwap, volume)]
        adv10 = [math.nan] * row_count
        for row in range(9, row_count):
            adv10[row] = math.fsum(dollar_volume[row - 9 : row + 1]) / 10.0
        adv_sum49 = [math.nan] * row_count
        for row in range(57, row_count):
            adv_sum49[row] = math.fsum(adv10[row - 48 : row + 1])
        for row in range(64, row_count):
            correlations[row][asset_index] = _pearson(
                vwap[row - 7 : row + 1], adv_sum49[row - 7 : row + 1]
            )

    ranked = [[math.nan] * len(_ASSETS) for _ in range(row_count)]
    for row, values in enumerate(correlations):
        finite = [value for value in values if math.isfinite(value)]
        if not finite:
            continue
        count = len(finite)
        for column, value in enumerate(values):
            if not math.isfinite(value):
                continue
            below = sum(other < value for other in finite)
            tied = sum(other == value for other in finite)
            ranked[row][column] = (below + (tied + 1) / 2.0) / count
    return ranked


def _assert_matrix_close(actual: list[list[float]], expected: list[list[float]]) -> None:
    assert len(actual) == len(expected)
    for row, expected_row in enumerate(expected):
        assert len(actual[row]) == len(expected_row)
        for column, expected_value in enumerate(expected_row):
            value = float(actual[row][column])
            if math.isnan(expected_value):
                assert math.isnan(value), "unexpected first_rank value at (%d, %d)" % (
                    row,
                    column,
                )
            else:
                assert value == pytest.approx(
                    expected_value, rel=0.0, abs=1e-12
                ), "first_rank mismatch at (%d, %d)" % (row, column)


def _node_matrix(factor: Any, node_name: str) -> list[list[float]]:
    node = factor._nodes[node_name]
    asset_rows = [list(node.outputs[data].value.array) for data in factor.datas]
    return [list(row) for row in zip(*asset_rows)]


def _assert_same_values(left: list[float], right: list[float]) -> None:
    assert len(left) == len(right)
    for row, (left_value, right_value) in enumerate(zip(left, right)):
        if math.isnan(float(left_value)):
            assert math.isnan(float(right_value)), "PIT/direct NaN mismatch at row %d" % row
        else:
            assert float(left_value) == pytest.approx(float(right_value), rel=0.0, abs=1e-12)


@pytest.mark.parametrize("runonce", (False, True))
def test_alpha081_pit_derived_panel_clock_matches_direct_chain_and_oracle(runonce: bool) -> None:
    from backtrader.research.alpha101.promoted import Alpha081Native

    index = pd.date_range("2024-01-01", periods=_PERIODS, freq="D", tz="UTC")
    frames = _frames(index)
    research = _research(index, frames)
    cerebro = bt.Cerebro(stdstats=False, runonce=runonce)
    _add_feeds(cerebro, research, frames)
    factors = {
        "pit": FactorSpec(
            name="pit",
            indicator=Alpha081Native,
            panel_line="factor",
            field_bindings=_field_bindings(pit=True),
        ),
        "direct": FactorSpec(
            name="direct",
            indicator=Alpha081Native,
            panel_line="factor",
            field_bindings=_field_bindings(pit=False),
        ),
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run()[0]

    oracle = _first_rank_oracle(frames)
    for name in ("pit", "direct"):
        factor = strategy.factor_instances[name]
        _assert_matrix_close(_node_matrix(factor, "first_rank"), oracle)

    pit_factor = strategy.factor_instances["pit"]
    direct_factor = strategy.factor_instances["direct"]
    for data in strategy.datas:
        pit_values = list(pit_factor.outputs[data].factor.array)
        direct_values = list(direct_factor.outputs[data].factor.array)
        assert any(math.isfinite(float(value)) for value in pit_values)
        assert any(math.isfinite(float(value)) for value in direct_values)
        _assert_same_values(pit_values, direct_values)

    pit_dollar_volume = pit_factor.field_lines("dollar_volume")
    with pytest.raises(OperatorInputError, match="different target feed"):
        _read_panel_value(pit_dollar_volume[0], strategy.datas[1])
