"""Independent Cerebro checks for DS45-12 PIT field and binding contracts."""

from __future__ import annotations

import math
from typing import Any, Mapping

import backtrader as bt
import pandas as pd
import pytest

from backtrader.errors import ResearchConfigError as ConfigError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.factor_strategy import FactorStrategy
from backtrader.research.specs import FactorSpec, ResearchSpec


class _ResearchFeed(bt.feeds.PandasData):
    lines = ("vwap",)
    params = (("vwap", "vwap"),)


class _DirectAdv(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("adv2",)
    lookback_h = 0

    def __init__(self) -> None:
        super().__init__()
        self._adv_lines = self.field_lines("adv2")

    def next(self) -> None:
        for data, source in zip(self.target_datas, self._adv_lines):
            self.outputs[data].factor[0] = source[0]


class _DerivedAdv(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("adv2", "dollar_volume", "vwap", "volume")
    lookback_h = 1

    def __init__(self) -> None:
        super().__init__()
        self._adv_lines = self.field_lines("adv2")

    def next(self) -> None:
        for data, source in zip(self.target_datas, self._adv_lines):
            self.outputs[data].factor[0] = source[0]


class _FeedClose(FactorIndicator):
    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")

    def next(self) -> None:
        for data, source in zip(self.target_datas, self._closes):
            self.outputs[data].factor[0] = source[0]


class _SectorCode(FactorIndicator):
    lines = ("factor",)
    classification_fields = ("sector",)
    classification_levels = ("sector",)
    lookback_h = 0

    def __init__(self) -> None:
        super().__init__()
        self._sectors = self.classification_lines("sector")

    def next(self) -> None:
        for data, source in zip(self.target_datas, self._sectors):
            self.outputs[data].factor[0] = source[0]


class _GroupCenteredClose(FactorIndicator):
    """Center close within static research groups and current formula members."""

    lines = ("factor",)
    formula_fields = ("close",)
    lookback_h = 0

    def __init__(self) -> None:
        super().__init__()
        self._closes = self.field_lines("close")
        self._members = self.formula_members
        self._groups = self.research_groups

    def next(self) -> None:
        values = [float(line[0]) for line in self._closes]
        members = [bool(line[0]) for line in self._members]
        for index, data in enumerate(self.target_datas):
            if not members[index]:
                self.outputs[data].factor[0] = float("nan")
                self.record_availability(
                    data,
                    ready=False,
                    valid=False,
                    reason="FORMULA_INELIGIBLE",
                )
                continue
            peers = [
                value
                for peer, value in enumerate(values)
                if members[peer]
                and self._groups[peer] == self._groups[index]
                and math.isfinite(value)
            ]
            value = values[index] - math.fsum(peers) / len(peers)
            self.outputs[data].factor[0] = value
            self.record_availability(
                data,
                ready=True,
                valid=math.isfinite(value),
                reason="READY",
            )


def _grid(periods: int) -> pd.DataFrame:
    closes = pd.date_range("2024-04-01 20:00:00", periods=periods, freq="D", tz="UTC")
    return pd.DataFrame(
        {"open_time": closes - pd.Timedelta(hours=6)},
        index=closes.rename("close_time"),
    )


def _table(values: Mapping[tuple[pd.Timestamp, str], float]) -> pd.DataFrame:
    keys = pd.MultiIndex.from_tuples(values, names=("time", "asset"))
    return pd.DataFrame(
        {
            "value": list(values.values()),
            "available_at": [key[0] for key in values],
            "data_version": ["fixture-v1"] * len(values),
        },
        index=keys,
    )


def _source_metadata(**overrides: Any) -> dict[str, Any]:
    result = {
        "name": "vwap",
        "semantic": "volume_weighted_average_price",
        "unit": "USD per share",
        "currency": "USD",
        "adjustment": "split-adjusted-v1",
        "statistic": "trade_volume_weighted_mean",
    }
    result.update(overrides)
    return result


def _attach_source_metadata(frame: pd.DataFrame, **metadata: Any) -> pd.DataFrame:
    frame.attrs["source_metadata"] = metadata
    return frame


def _classification_table(
    grid: pd.DatetimeIndex,
    assets: tuple[str, ...],
    categories: Mapping[str, str],
    *,
    level: str = "sector",
    taxonomy_version: str = "fixture-taxonomy-v1",
) -> pd.DataFrame:
    rows = [
        {
            "time": point,
            "asset": asset,
            "level": level,
            "category": categories[asset],
            "effective_at": point,
            "available_at": point,
            "taxonomy_version": taxonomy_version,
        }
        for point in grid
        for asset in assets
    ]
    return pd.DataFrame(rows).set_index(["time", "asset"])


def _research(
    grid: pd.DataFrame,
    assets: tuple[str, ...],
    *,
    formula_fields: Mapping[str, pd.DataFrame] | None = None,
    classifications: Mapping[str, pd.DataFrame] | None = None,
    groups: Mapping[str, str] | None = None,
    formula_universe: pd.Series | None = None,
    end: pd.Timestamp | None = None,
) -> ResearchSpec:
    return ResearchSpec(
        grid=grid,
        start=grid.index[0],
        end=grid.index[-1] if end is None else end,
        targets=assets,
        source_timezone="UTC",
        snapshot_id="ds45-pit-bindings-fixture-v1",
        price_basis="synthetic unadjusted USD fixture",
        calendar_id="synthetic-calendar-v1",
        frequency="1session",
        groups=groups or dict.fromkeys(assets, "market"),
        formula_universe=formula_universe,
        formula_fields=formula_fields or {},
        classifications=classifications or {},
    )


def _feeds(
    cerebro: bt.Cerebro,
    grid: pd.DataFrame,
    assets: tuple[str, ...],
    *,
    closes: Mapping[str, tuple[float, ...]],
    vwaps: tuple[float, ...] | None = None,
    volumes: tuple[float, ...] | None = None,
    research: ResearchSpec | None = None,
) -> None:
    for asset in assets:
        values = closes[asset]
        frame = pd.DataFrame(
            {
                "open": values,
                "high": values,
                "low": values,
                "close": values,
                "volume": volumes or (1.0,) * len(grid.index),
                "openinterest": (0.0,) * len(grid.index),
                "vwap": vwaps or values,
            },
            index=grid.index,
        )
        if research is None:
            feed = _ResearchFeed(dataname=frame)
        else:
            from backtrader.research.inputs import prealign_bars

            feed = prealign_bars(
                frame,
                research,
                asset,
                data_version="fixture-bars-v1",
            ).feed
        cerebro.adddata(feed, name=asset)


def _factor(name: str, indicator: type[FactorIndicator], **kwargs: Any) -> FactorSpec:
    return FactorSpec(name=name, indicator=indicator, panel_line="factor", **kwargs)


def test_direct_adv_and_explicit_derived_adv_have_distinct_history_and_pit_inputs() -> None:
    grid = _grid(4)
    assets = ("AAA",)
    direct_table = _table({(grid.index[1], "AAA"): 8.0})
    direct_table.loc[(grid.index[1], "AAA"), "available_at"] = grid.index[2]
    direct_table["data_version"] = "adv-source-v7"
    direct_table.attrs["source_metadata"] = {
        "name": "adv2",
        "semantic": "average_daily_dollar_volume",
        "unit": "USD",
        "currency": "USD",
        "adjustment": "split-adjusted-v1",
        "statistic": "mean",
        "window": 2,
        "complete_window": True,
        "source_version": "adv-source-v7",
        "provenance_source_lookback_grid_bars": 1,
    }
    source_index = pd.MultiIndex.from_product([grid.index, assets], names=("time", "asset"))
    vwap_table = _table(
        {(point, "AAA"): value for point, value in zip(grid.index, (2.0, 3.0, 4.0, 5.0))}
    )
    volume_table = _table(
        {(point, "AAA"): value for point, value in zip(grid.index, (10.0, 20.0, 30.0, 40.0))}
    )
    vwap_available = tuple(point - pd.Timedelta(minutes=5) for point in grid.index)
    volume_available = tuple(point - pd.Timedelta(minutes=2) for point in grid.index)
    vwap_table["available_at"] = vwap_available
    volume_table["available_at"] = volume_available
    _attach_source_metadata(vwap_table, **_source_metadata())
    _attach_source_metadata(
        volume_table,
        name="volume",
        semantic="share_volume",
        unit="shares",
        adjustment="split-adjusted-v1",
    )
    # Keep this local assertion independent of the bound helpers' input view.
    assert tuple(vwap_table.index) == tuple(source_index)
    research = _research(
        grid,
        assets,
        end=grid.index[2],
        formula_fields={
            "adv2_usd": direct_table,
            "daily_vwap": vwap_table,
            "daily_volume": volume_table,
        },
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    _feeds(
        cerebro,
        grid,
        assets,
        closes={"AAA": (10.0, 11.0, 12.0, 13.0)},
        research=research,
    )
    factors = {
        "direct": _factor(
            "direct",
            _DirectAdv,
            field_bindings={"adv2": "table:adv2_usd"},
        ),
        "derived": _factor(
            "derived",
            _DerivedAdv,
            field_bindings={
                "adv2": {"derive": "adv", "source": "dollar_volume", "window": 2},
                "dollar_volume": {
                    "derive": "vwap_volume",
                    "vwap": "vwap",
                    "volume": "volume",
                },
                "vwap": "table:daily_vwap",
                "volume": "table:daily_volume",
            },
        ),
        "feed_close": _factor(
            "feed_close",
            _FeedClose,
            field_bindings={"close": "feed:target:close"},
        ),
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run()[0]
    dataset = strategy.get_dataset()
    panel = dataset.raw_factors
    direct = panel["direct"].xs("AAA", level="asset")
    derived = panel["derived"].xs("AAA", level="asset")

    # Direct ADV is already a computed N-grid statistic: it has no second
    # rolling delay. The delayed PIT row stays hidden until its available_at.
    assert math.isnan(direct.iloc[0])
    assert math.isnan(direct.iloc[1])
    assert direct.iloc[2] == pytest.approx(8.0)
    assert [math.isnan(value) for value in derived] == [True, False, False]
    assert derived.iloc[1] == pytest.approx((2.0 * 10.0 + 3.0 * 20.0) / 2.0)
    assert derived.iloc[2] == pytest.approx((3.0 * 20.0 + 4.0 * 30.0) / 2.0)

    direct_spec = strategy._factor_specs_by_name["direct"]
    derived_spec = strategy._factor_specs_by_name["derived"]
    assert direct_spec.lookback_h == 0
    assert derived_spec.lookback_h == 1
    assert direct_spec.field_bindings["adv2"] == "table:adv2_usd"
    assert derived_spec.field_bindings["adv2"]["window"] == 2
    assert direct_table.attrs["source_metadata"]["provenance_source_lookback_grid_bars"] == 1
    stored_metadata = research.formula_fields["adv2_usd"].attrs["source_metadata"]
    assert stored_metadata["source_version"] == "adv-source-v7"
    assert stored_metadata["window"] == 2
    formula_inputs = dataset.formula_inputs
    retained_late_adv = formula_inputs["adv2_usd"].loc[(grid.index[1], "AAA")]
    assert pd.Timestamp(retained_late_adv["available_at"]) == grid.index[2]
    label_tail = formula_inputs["daily_vwap"]
    assert (grid.index[3], "AAA") in label_tail.index
    assert label_tail.loc[(grid.index[3], "AAA"), "value"] == pytest.approx(5.0)
    assert pd.Timestamp(label_tail.loc[(grid.index[3], "AAA"), "available_at"]) == vwap_available[3]
    feed_tail = formula_inputs["feed:target:close"]
    assert (grid.index[3], "AAA") in feed_tail.index
    assert feed_tail.loc[(grid.index[3], "AAA"), "value"] == pytest.approx(13.0)
    assert pd.Timestamp(feed_tail.loc[(grid.index[3], "AAA"), "available_at"]) == grid.index[3]
    assert feed_tail.loc[(grid.index[3], "AAA"), "data_version"] == "fixture-bars-v1"

    availability = dataset.availability
    late = availability.loc[(grid.index[1], "AAA", "direct")]
    assert not bool(late["ready"]), (
        "unpublished direct ADV must remain unready: reason=%r, input_times=%r"
        % (late["reason"], late["input_times"])
    )
    assert late["reason"] == "NOT_YET_AVAILABLE"
    assert pd.isna(late["available_at"])
    assert pd.Timestamp(late["input_times"]["adv2"]) == grid.index[2]
    visible = availability.loc[(grid.index[2], "AAA", "direct")]
    assert bool(visible["ready"])
    assert pd.Timestamp(visible["input_times"]["adv2"]) == grid.index[2]
    derived_inputs = availability.loc[(grid.index[1], "AAA", "derived")]["input_times"]
    assert tuple(pd.Timestamp(value) for value in derived_inputs["vwap"]) == vwap_available[:2]
    assert tuple(pd.Timestamp(value) for value in derived_inputs["volume"]) == volume_available[:2]


def test_vwap_volume_rejects_incompatible_units() -> None:
    grid = _grid(2)
    assets = ("AAA",)
    vwap = _table({(point, "AAA"): value for point, value in zip(grid.index, (2.0, 3.0))})
    volume = _table({(point, "AAA"): value for point, value in zip(grid.index, (10.0, 20.0))})
    _attach_source_metadata(vwap, **_source_metadata())
    _attach_source_metadata(
        volume,
        name="volume",
        semantic="share_volume",
        unit="contracts",
        adjustment="split-adjusted-v1",
    )
    research = _research(
        grid,
        assets,
        formula_fields={"vwap_input": vwap, "volume_input": volume},
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    _feeds(cerebro, grid, assets, closes={"AAA": (10.0, 11.0)})
    factor = _factor(
        "derived",
        _DerivedAdv,
        field_bindings={
            "adv2": {"derive": "adv", "source": "dollar_volume", "window": 2},
            "dollar_volume": {
                "derive": "vwap_volume",
                "vwap": "vwap",
                "volume": "volume",
            },
            "vwap": "table:vwap_input",
            "volume": "table:volume_input",
        },
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"derived": factor})

    with pytest.raises(ConfigError, match="unit|semantic|share|volume"):
        cerebro.run()


def test_direct_adv_source_history_must_match_its_declared_window() -> None:
    grid = _grid(1)
    assets = ("AAA",)
    table = _table({(grid.index[0], "AAA"): 12.0})
    table.attrs["source_metadata"] = {
        "name": "adv2",
        "semantic": "average_daily_dollar_volume",
        "unit": "USD",
        "currency": "USD",
        "adjustment": "split-adjusted-v1",
        "statistic": "mean",
        "window": 2,
        "complete_window": True,
        "source_version": "adv-source-v7",
        "provenance_source_lookback_grid_bars": 0,
    }
    research = _research(grid, assets, formula_fields={"adv2_usd": table})
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    _feeds(cerebro, grid, assets, closes={"AAA": (10.0,)})
    factor = _factor(
        "direct",
        _DirectAdv,
        field_bindings={"adv2": "table:adv2_usd"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"direct": factor})

    with pytest.raises(ConfigError, match="provenance span"):
        cerebro.run()


def test_same_level_named_taxonomies_keep_independent_classification_bindings() -> None:
    grid = _grid(2)
    assets = ("AAA", "BBB")
    primary = _classification_table(
        grid.index,
        assets,
        {"AAA": "energy", "BBB": "technology"},
        taxonomy_version="primary-v1",
    )
    alternative = _classification_table(
        grid.index,
        assets,
        {"AAA": "south", "BBB": "north"},
        taxonomy_version="alternative-v9",
    )
    research = _research(
        grid,
        assets,
        classifications={"sector_primary": primary, "sector_alternative": alternative},
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    _feeds(cerebro, grid, assets, closes={"AAA": (10.0, 11.0), "BBB": (20.0, 21.0)})
    factors = {
        "primary": _factor(
            "primary",
            _SectorCode,
            classification_bindings={"sector": "table:sector_primary"},
        ),
        "alternative": _factor(
            "alternative",
            _SectorCode,
            classification_bindings={"sector": "table:sector_alternative"},
        ),
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run()[0]
    panel = strategy.get_dataset().raw_factors

    for point in grid.index:
        assert panel.at[(point, "AAA"), "primary"] == pytest.approx(1.0)
        assert panel.at[(point, "BBB"), "primary"] == pytest.approx(2.0)
        assert panel.at[(point, "AAA"), "alternative"] == pytest.approx(2.0)
        assert panel.at[(point, "BBB"), "alternative"] == pytest.approx(1.0)
    assert factors["primary"].classification_bindings["sector"] == "table:sector_primary"
    assert factors["alternative"].classification_bindings["sector"] == "table:sector_alternative"


def test_classification_binding_rejects_a_table_at_the_wrong_level() -> None:
    grid = _grid(1)
    assets = ("AAA",)
    wrong_level = _classification_table(
        grid.index,
        assets,
        {"AAA": "software"},
        level="industry",
    )
    research = _research(grid, assets, classifications={"renamed_industry_table": wrong_level})
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    _feeds(cerebro, grid, assets, closes={"AAA": (10.0,)})
    factor = _factor(
        "sector",
        _SectorCode,
        classification_bindings={"sector": "table:renamed_industry_table"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"sector": factor})

    with pytest.raises(ConfigError) as error:
        cerebro.run()
    assert error.value.__cause__ is None
    assert "level" in str(error.value)


def test_formula_membership_changes_current_static_group_result_without_rewriting_history() -> None:
    grid = _grid(3)
    assets = ("AAA", "BBB", "CCC")
    keys = pd.MultiIndex.from_product([grid.index, assets], names=("time", "asset"))
    formula_universe = pd.Series(True, index=keys, dtype=bool)
    formula_universe.loc[(grid.index[1], "AAA")] = False
    formula_universe.loc[(grid.index[2], "AAA")] = False
    research = _research(
        grid,
        assets,
        groups={"AAA": "growth", "BBB": "growth", "CCC": "rates"},
        formula_universe=formula_universe,
    )
    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    _feeds(
        cerebro,
        grid,
        assets,
        closes={"AAA": (10.0, 14.0, 18.0), "BBB": (20.0, 24.0, 30.0), "CCC": (100.0, 110.0, 130.0)},
    )
    factor = _factor(
        "centered",
        _GroupCenteredClose,
        field_bindings={"close": "feed:target:close"},
    )
    cerebro.addstrategy(FactorStrategy, research=research, factors={"centered": factor})
    strategy = cerebro.run()[0]
    dataset = strategy.get_dataset()
    panel = dataset.raw_factors

    # Independent arithmetic: growth is centered over AAA/BBB at t0, then
    # only BBB remains; CCC is always isolated in its static rates group.
    assert panel.at[(grid.index[0], "AAA"), "centered"] == pytest.approx(-5.0)
    assert panel.at[(grid.index[0], "BBB"), "centered"] == pytest.approx(5.0)
    assert panel.at[(grid.index[0], "CCC"), "centered"] == pytest.approx(0.0)
    assert math.isnan(panel.at[(grid.index[1], "AAA"), "centered"])
    assert panel.at[(grid.index[1], "BBB"), "centered"] == pytest.approx(0.0)
    assert panel.at[(grid.index[1], "CCC"), "centered"] == pytest.approx(0.0)
    assert panel.at[(grid.index[0], "AAA"), "centered"] == pytest.approx(-5.0)
    availability = dataset.availability
    excluded = availability.loc[(grid.index[1], "AAA", "centered")]
    assert not bool(excluded["ready"])
    assert excluded["reason"] == "FORMULA_INELIGIBLE"
