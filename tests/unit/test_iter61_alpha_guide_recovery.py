"""Synthetic public-feed witnesses recovered from the Alpha101 guide examples."""

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorSpec, ResearchSpec, align_to_grid
from backtrader.research.alpha101 import get_alpha
from backtrader.strategies.factor_strategy import FactorStrategy


class GuideFeed(bt.feeds.PandasData):
    lines = ("vwap", "dollar_volume", "subindustry")
    params = tuple((name, name) for name in lines)


def _guide_frames():
    index = pd.date_range("2025-06-01", periods=33, freq="D", tz="UTC")
    frames = {}
    for asset_index in range(6):
        rows = []
        for row in range(len(index)):
            close = (
                50.0
                + 0.3 * asset_index
                + 0.025 * row
                + (0.5 + 0.02 * asset_index) * math.sin(0.31 * row + asset_index)
            )
            open_ = close + 0.08 * math.cos(0.43 * row + asset_index)
            high = max(open_, close) + 0.8 + 0.03 * math.sin(0.17 * row + asset_index)
            low = min(open_, close) - 0.7 - 0.04 * math.cos(0.23 * row + asset_index)
            volume = (
                1000.0
                + 180.0 * math.sin(row * (0.19 + 0.01 * asset_index) + asset_index)
                + 13.0 * asset_index
            )
            vwap = (open_ + close) / 2.0 + 0.02 * asset_index
            rows.append((open_, high, low, close, volume, vwap))
        frame = pd.DataFrame(
            rows, columns=("open", "high", "low", "close", "volume", "vwap"), index=index
        )
        frame["openinterest"] = 0.0
        frame["dollar_volume"] = frame["vwap"] * frame["volume"]
        frame["subindustry"] = float(asset_index // 2)
        frames["asset-%d" % asset_index] = frame
    return frames


def _spec(name, alpha_id):
    indicator = get_alpha(alpha_id)
    bindings = {}
    for alias in indicator.formula_fields:
        if alias.startswith("adv") and alias[3:].isdigit():
            bindings[alias] = {"derive": "adv", "source": "dollar_volume", "window": int(alias[3:])}
        else:
            bindings[alias] = "feed:target:%s" % alias
    return FactorSpec(name=name, indicator=indicator, panel_line="factor", field_bindings=bindings)


@pytest.mark.parametrize("runonce", (False, True), ids=("runnext", "runonce"))
@pytest.mark.parametrize("research_start", (0, 29), ids=("with-warmup", "guide-window"))
def test_guide_vwap_and_subindustry_feed_lines(runonce, research_start):
    frames = _guide_frames()
    index = next(iter(frames.values())).index
    targets = tuple(frames)
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(hours=1)}, index=index.rename("close_time")
    )
    research = ResearchSpec(
        grid=grid,
        start=index[research_start],
        end=index[-1],
        targets=targets,
        source_timezone="UTC",
        snapshot_id="alpha101-guide-ordinary-feed",
        price_basis="synthetic unadjusted values",
        calendar_id="synthetic-daily-grid",
        frequency="1session",
        groups=dict.fromkeys(targets, "market"),
    )
    cerebro = bt.Cerebro(stdstats=False)
    for asset, frame in frames.items():
        aligned = align_to_grid(frame, research, asset)
        feed = GuideFeed(dataname=aligned.feed.p.dataname)
        feed._factor_research_alignment_v2 = aligned.feed._factor_research_alignment_v2
        cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={"alpha41": _spec("alpha41", 41), "alpha100": _spec("alpha100", 100)},
    )
    strategy = cerebro.run(runonce=runonce, preload=True)[0]
    panel = strategy.get_panel().factors
    assert strategy._factor_specs_by_name["alpha100"].field_bindings["subindustry"] == (
        "feed:target:subindustry"
    )
    assert strategy._factor_specs_by_name["alpha100"].field_bindings["adv20"] == {
        "derive": "adv",
        "source": "dollar_volume",
        "window": 20,
    }

    # The original guide starts after warmup; the expanded window also checks
    # that Alpha100 does not publish values before its 29-bar lookback.
    assert tuple(panel.index.get_level_values("time").unique()) == tuple(index[research_start:])
    assert get_alpha(100).lookback_h == 29
    assert get_alpha(41).lookback_h == 0
    for asset, frame in frames.items():
        if research_start == 0:
            assert panel.xs(asset, level="asset")["alpha100"].iloc[:29].isna().all()
        for when in index[research_start:]:
            expected = (
                math.sqrt(frame.at[when, "high"] * frame.at[when, "low"]) - frame.at[when, "vwap"]
            )
            assert panel.at[(when, asset), "alpha41"] == pytest.approx(
                expected, rel=1e-12, abs=1e-12
            )
    values = panel["alpha100"].to_numpy(dtype=float)
    assert any(math.isfinite(value) and abs(value) > 1e-12 for value in values)

    # Independently rank the six raw range-position times volume inputs, then
    # subtract each two-asset subindustry mean for the first neutralization.
    last = index[-1]
    raw = []
    for frame in frames.values():
        row = frame.loc[last]
        raw.append(
            ((row.close - row.low) - (row.high - row.close)) / (row.high - row.low) * row.volume
        )
    ranked = pd.Series(raw).rank(method="average", pct=True).tolist()
    node = strategy.factor_instances["alpha100"]._nodes["first_subindustry_neutralize"]
    by_asset = dict(zip(targets, strategy._target_datas))
    for group in range(3):
        members = (2 * group, 2 * group + 1)
        group_mean = sum(ranked[i] for i in members) / 2.0
        actual = []
        for i in members:
            value = float(node.outputs[by_asset[targets[i]]].value.array[-1])
            assert math.isfinite(value)
            assert value == pytest.approx(ranked[i] - group_mean, abs=1e-12)
            actual.append(value)
        assert math.fsum(actual) / len(actual) == pytest.approx(0.0, abs=1e-12)


def test_alpha41_missing_vwap_remains_nan():
    frames = _guide_frames()
    asset = "asset-0"
    frame = frames[asset].iloc[:4].copy()
    index = frame.index
    frame.loc[index[2], "vwap"] = math.nan
    research = ResearchSpec(
        grid=pd.DataFrame(
            {"open_time": index - pd.Timedelta(hours=1)}, index=index.rename("close_time")
        ),
        start=index[0],
        end=index[-1],
        targets=(asset,),
        source_timezone="UTC",
        snapshot_id="alpha101-guide-missing-vwap",
        price_basis="synthetic",
        calendar_id="synthetic-daily-grid",
        frequency="1session",
        groups={asset: "market"},
    )
    aligned = align_to_grid(frame, research, asset)
    feed = GuideFeed(dataname=aligned.feed.p.dataname)
    feed._factor_research_alignment_v2 = aligned.feed._factor_research_alignment_v2
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(feed, name=asset)
    cerebro.addstrategy(
        FactorStrategy, research=research, factors={"alpha41": _spec("alpha41", 41)}
    )
    values = cerebro.run(runonce=False, preload=True)[0].get_panel().factors["alpha41"]
    assert math.isnan(values.loc[(index[2], asset)])
    for when in (index[0], index[1], index[3]):
        expected = (
            math.sqrt(frame.at[when, "high"] * frame.at[when, "low"]) - frame.at[when, "vwap"]
        )
        assert values.loc[(when, asset)] == pytest.approx(expected, rel=1e-12, abs=1e-12)
