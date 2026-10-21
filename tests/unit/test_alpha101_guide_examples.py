"""Executable synthetic-data examples for the native Alpha101 guide.

These checks exercise the documented public FactorSpec/ResearchSpec/Cerebro
path.  Synthetic rows are only API smoke inputs; they are not market data or
formula-library acceptance evidence.
"""

import math
import random

import backtrader as bt
import pandas as pd
import pytest

from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec, prealign_bars
from backtrader.research.alpha101 import get_alpha


_ASSETS = tuple("asset-%d" % index for index in range(6))


def _synthetic_frames(periods=260):
    index = pd.date_range("2025-01-01", periods=periods, freq="B", tz="UTC")
    frames = {}
    for asset_index, asset in enumerate(_ASSETS):
        rows = []
        close_noise = random.Random(46_101 + asset_index)
        open_noise = random.Random(46_201 + asset_index)
        volume_noise = random.Random(46_301 + asset_index)
        vwap_noise = random.Random(46_401 + asset_index)
        for point in range(periods):
            base = 20.0 + 0.4 * asset_index
            close = base + 0.0003 * point + close_noise.uniform(-0.35, 0.35)
            open_ = close + open_noise.uniform(-0.29, 0.29)
            volume = 4_200.0 + 130.0 * asset_index + volume_noise.uniform(-850.0, 850.0)
            vwap = base + 0.0004 * point + vwap_noise.uniform(-0.36, 0.36)
            rows.append(
                {
                    "open": open_,
                    "high": max(open_, close) + 0.35,
                    "low": min(open_, close) - 0.28,
                    "close": close,
                    "volume": volume,
                    "openinterest": 0.0,
                    "vwap": vwap,
                }
            )
        frames[asset] = pd.DataFrame(rows, index=index)
    return frames


def _membership(times):
    keys = pd.MultiIndex.from_product([times, _ASSETS], names=("time", "asset"))
    return pd.Series(True, index=keys, dtype=bool)


def _pit_table(frames, field, metadata):
    rows = [
        {
            "time": point,
            "asset": asset,
            "value": float(frame.loc[point, field]),
            "available_at": point,
            "data_version": "alpha101-guide-synthetic-v1",
        }
        for asset, frame in frames.items()
        for point in frame.index
    ]
    table = pd.DataFrame(rows).set_index(["time", "asset"])
    table.attrs["source_metadata"] = dict(metadata)
    return table


def _research(frames, *, formula_fields=None, classifications=None):
    index = next(iter(frames.values())).index.rename("close_time")
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    study_times = index[-16:]
    classification_rows = [
        {
            "time": point,
            "asset": asset,
            "level": "subindustry",
            "category": "subindustry-%d" % (asset_index // 2),
            "effective_at": point,
            "available_at": point,
            "taxonomy_version": "alpha101-guide-taxonomy-v1",
        }
        for point in index
        for asset_index, asset in enumerate(_ASSETS)
    ]
    pit_subindustry = pd.DataFrame(classification_rows).set_index(["time", "asset"])
    all_classifications = {"pit_subindustry": pit_subindustry}
    all_classifications.update(classifications or {})
    return ResearchSpec(
        grid=grid,
        start=study_times[0],
        end=index[-1],
        targets=_ASSETS,
        source_timezone="UTC",
        snapshot_id="alpha101-guide-synthetic-v1",
        price_basis="synthetic unadjusted values",
        calendar_id="synthetic-business-grid-v1",
        frequency="1session",
        feed_time_kind="close_time",
        groups=dict.fromkeys(_ASSETS, "market"),
        universe=_membership(study_times),
        formula_universe=_membership(index),
        formula_fields=formula_fields or {},
        classifications=all_classifications,
    )


def _run(frames, factors, *, runonce=True, formula_fields=None, classifications=None):
    research = _research(frames, formula_fields=formula_fields, classifications=classifications)
    cerebro = bt.Cerebro(stdstats=False)
    for asset, frame in frames.items():
        aligned = prealign_bars(
            frame.drop(columns=["vwap"]),
            research,
            asset,
            data_version="alpha101-guide-bars-v1",
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run(runonce=runonce)[0]
    return strategy.get_dataset()


def _feed_bindings(indicator):
    return {field: "feed:target:%s" % field for field in indicator.formula_fields}


def _assert_study_values_are_finite(dataset, names):
    raw = dataset.raw_factors
    study = raw.loc[raw.index.get_level_values("time") >= dataset.start]
    for name in names:
        values = study[name].to_numpy(dtype=float)
        assert len(values) == 16 * len(_ASSETS)
        finite = any(math.isfinite(float(value)) for value in values)
        assert finite, (
            name,
            values.tolist(),
            dataset.availability.xs(name, level="factor")[["ready", "valid", "reason"]]
            .tail(3)
            .to_dict("records"),
        )


def test_single_alpha003_uses_the_documented_cerebro_path():
    frames = _synthetic_frames()
    indicator = get_alpha(3)
    spec = FactorSpec(
        name="alpha003",
        indicator=indicator,
        panel_line="factor",
        field_bindings={
            "open": "feed:target:open",
            "volume": "feed:target:volume",
        },
    )

    dataset = _run(frames, {"alpha003": spec}, runonce=True)

    _assert_study_values_are_finite(dataset, ("alpha003",))


@pytest.mark.parametrize("runonce", (False, True))
def test_registered_alpha003_alpha009_alpha101_share_one_grid(runonce):
    frames = _synthetic_frames()
    factors = {}
    for alpha_id in (3, 9, 101):
        indicator = get_alpha(alpha_id)
        name = "alpha%03d" % alpha_id
        factors[name] = FactorSpec(
            name=name,
            indicator=indicator,
            panel_line="factor",
            field_bindings=_feed_bindings(indicator),
        )

    dataset = _run(frames, factors, runonce=runonce)

    _assert_study_values_are_finite(dataset, tuple(factors))


def test_multi_factor_vwap_pit_and_subindustry_pit_bindings():
    frames = _synthetic_frames()
    vwap = _pit_table(
        frames,
        "vwap",
        {
            "name": "vwap",
            "semantic": "volume_weighted_average_price",
            "unit": "USD per share",
            "currency": "USD",
            "adjustment": "synthetic-unadjusted-v1",
            "statistic": "trade_volume_weighted_mean",
            "source_version": "alpha101-guide-synthetic-v1",
        },
    )
    direct_adv_values = {
        asset: frame["vwap"].mul(frame["volume"]).rolling(20, min_periods=20).mean()
        for asset, frame in frames.items()
    }
    adv_rows = [
        {
            "time": point,
            "asset": asset,
            "value": float(value) if pd.notna(value) else float("nan"),
            "available_at": point,
            "data_version": "alpha101-guide-adv-v1",
        }
        for asset, values in direct_adv_values.items()
        for point, value in values.items()
    ]
    adv20 = pd.DataFrame(adv_rows).set_index(["time", "asset"])
    adv20.attrs["source_metadata"] = {
        "name": "adv20",
        "semantic": "average_daily_dollar_volume",
        "unit": "USD",
        "currency": "USD",
        "adjustment": "synthetic-unadjusted-v1",
        "statistic": "mean",
        "window": 20,
        "complete_window": True,
        "source_version": "alpha101-guide-adv-v1",
        "provenance_source_lookback_grid_bars": 19,
    }
    dollar_volume = _pit_table(
        frames,
        "vwap",
        {
            "name": "dollar_volume",
            "semantic": "daily_dollar_volume",
            "unit": "USD",
            "currency": "USD",
            "adjustment": "synthetic-unadjusted-v1",
            "source_version": "alpha101-guide-dollar-volume-v1",
        },
    )
    dollar_volume["value"] = [
        float(frame.loc[point, "vwap"] * frame.loc[point, "volume"])
        for asset, frame in frames.items()
        for point in frame.index
    ]

    research_fields = {"pit_vwap": vwap, "pit_adv20": adv20, "pit_dollar_volume": dollar_volume}
    factors = {}
    for alpha_id in (5, 6, 101):
        indicator = get_alpha(alpha_id)
        bindings = _feed_bindings(indicator)
        if "vwap" in indicator.formula_fields:
            bindings["vwap"] = "table:pit_vwap"
        factors["alpha%03d" % alpha_id] = FactorSpec(
            name="alpha%03d" % alpha_id,
            indicator=indicator,
            panel_line="factor",
            field_bindings=bindings,
        )

    alpha7 = get_alpha(7)
    alpha7_bindings = _feed_bindings(alpha7)
    alpha7_bindings["adv20"] = "table:pit_adv20"
    alpha7_bindings["dollar_volume"] = "table:pit_dollar_volume"
    factors["alpha007"] = FactorSpec(
        name="alpha007",
        indicator=alpha7,
        panel_line="factor",
        field_bindings=alpha7_bindings,
    )

    dataset = _run(frames, factors, formula_fields=research_fields)

    _assert_study_values_are_finite(dataset, tuple(factors))


def test_alpha048_reads_the_declared_subindustry_pit_table():
    frames = _synthetic_frames()
    indicator = get_alpha(48)
    spec = FactorSpec(
        name="alpha048",
        indicator=indicator,
        panel_line="factor",
        field_bindings={"close": "feed:target:close"},
        classification_bindings={"subindustry": "table:pit_subindustry"},
    )

    dataset = _run(frames, {"alpha048": spec}, runonce=True)

    _assert_study_values_are_finite(dataset, ("alpha048",))
