"""Small public-API examples for ordinary Alpha101 input feed lines."""

from __future__ import annotations

import math

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec, align_to_grid
from backtrader.research.alpha101 import get_alpha


class _GuideFeed(bt.feeds.PandasData):
    lines = ("vwap", "dollar_volume", "subindustry")
    params = tuple((name, name) for name in lines)


def _guide_frames(periods=33):
    index = pd.date_range("2025-06-01", periods=periods, freq="D", tz="UTC")
    frames = {}
    for asset_index in range(6):
        rows = []
        for row in range(periods):
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
            rows,
            columns=("open", "high", "low", "close", "volume", "vwap"),
            index=index,
        )
        frame["openinterest"] = 0.0
        frame["dollar_volume"] = frame["vwap"] * frame["volume"]
        frame["subindustry"] = float(asset_index // 2)
        frames["asset-%d" % asset_index] = frame
    return frames


def _guide_spec(name, alpha_id):
    indicator = get_alpha(alpha_id)
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


def _run_public_example(frames):
    index = next(iter(frames.values())).index
    targets = tuple(frames)
    grid = pd.DataFrame(
        {"open_time": index - pd.Timedelta(hours=1)}, index=index.rename("close_time")
    )
    research = ResearchSpec(
        grid=grid,
        start=index[29],
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
        feed = _GuideFeed(dataname=aligned.feed.p.dataname)
        setattr(
            feed,
            "_factor_research_alignment_v2",
            getattr(aligned.feed, "_factor_research_alignment_v2"),
        )
        cerebro.adddata(feed, name=asset)
    factors = {
        "alpha41": _guide_spec("alpha41", 41),
        "alpha100": _guide_spec("alpha100", 100),
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    return cerebro.run()[0]


def test_guide_runs_vwap_and_industry_codes_as_ordinary_feed_lines():
    frames = _guide_frames()
    strategy = _run_public_example(frames)
    panel = strategy.get_panel()
    last = next(iter(frames.values())).index[-1]

    for factor_name in ("alpha41", "alpha100"):
        values = panel.factors[factor_name].to_numpy(dtype=float)
        assert any(math.isfinite(value) for value in values)
    for asset, frame in frames.items():
        expected = (
            math.sqrt(frame.at[last, "high"] * frame.at[last, "low"]) - frame.at[last, "vwap"]
        )
        assert panel.factors.at[(last, asset), "alpha41"] == pytest.approx(expected, rel=1e-12)

    alpha100_spec = strategy._factor_specs_by_name["alpha100"]
    assert alpha100_spec.field_bindings["subindustry"] == "feed:target:subindustry"
    factor = strategy.factor_instances["alpha100"]
    neutral = factor._nodes["first_subindustry_neutralize"]
    data_by_asset = dict(zip(strategy._research.targets, strategy._target_datas))
    for category in range(3):
        values = [
            neutral.outputs[data_by_asset["asset-%d" % asset_index]].value.array[-1]
            for asset_index in range(6)
            if asset_index // 2 == category
        ]
        assert math.fsum(float(value) for value in values) / len(values) == pytest.approx(
            0.0, abs=1e-12
        )
