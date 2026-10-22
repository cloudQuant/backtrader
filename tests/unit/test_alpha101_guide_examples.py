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

from backtrader.research import FactorSpec, FactorStrategy, ResearchSpec, align_to_grid
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
        formula_fields=formula_fields or {},
        classifications=all_classifications,
    )


def _run(frames, factors, *, runonce=True, formula_fields=None, classifications=None):
    research = _research(frames, formula_fields=formula_fields, classifications=classifications)
    cerebro = bt.Cerebro(stdstats=False)
    for asset, frame in frames.items():
        aligned = align_to_grid(
            frame.drop(columns=["vwap"]),
            research,
            asset,
            data_version="alpha101-guide-bars-v1",
        )
        cerebro.adddata(aligned.feed, name=asset)
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run(runonce=runonce)[0]
    return strategy.get_panel()


def _feed_bindings(indicator):
    return {field: "feed:target:%s" % field for field in indicator.formula_fields}


def _assert_study_values_are_finite(dataset, names):
    raw = dataset.factors
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








