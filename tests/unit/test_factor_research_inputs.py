"""Contract tests for explicit factor-research inputs and specifications."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd
import pytest

from backtrader.errors import ResearchConfigError as ConfigError, DatasetError
from backtrader.research.factor_indicator import FactorIndicator
from backtrader.research.inputs import prealign_bars, prealign_pit_table
from backtrader.research.specs import FactorSpec, ResearchSpec, normalize_factor_specs


def _utc_grid() -> pd.DataFrame:
    close_time = pd.date_range(
        "2024-03-08 21:00:00", periods=5, freq="D", tz="UTC", name="close_time"
    )
    return pd.DataFrame({"open_time": close_time - pd.Timedelta(hours=6)}, index=close_time)


def _research(grid: pd.DataFrame | None = None, **overrides: Any) -> ResearchSpec:
    grid = _utc_grid() if grid is None else grid
    start_index = min(1, len(grid.index) - 1)
    end_index = min(3, len(grid.index) - 1)
    args = {
        "grid": grid,
        "start": grid.index[start_index],
        "end": grid.index[end_index],
        "targets": ("AAA", "BBB"),
        "source_timezone": "America/New_York",
        "snapshot_id": "fixture-snapshot-1",
        "price_basis": "USD spot close, unadjusted",
        "calendar_id": "fixture-calendar-v1",
        "frequency": "1session",
    }
    args.update(overrides)
    return ResearchSpec(**args)


def _bars(index: pd.DatetimeIndex, first_close: float = 10.0) -> pd.DataFrame:
    close = [first_close + 10.0 * offset for offset in range(len(index))]
    return pd.DataFrame(
        {
            "open": [value - 1.0 for value in close],
            "high": [value + 1.0 for value in close],
            "low": [value - 2.0 for value in close],
            "close": close,
            "volume": [100.0 + offset for offset in range(len(index))],
            "openinterest": [0.0] * len(index),
        },
        index=index,
    )


def _expected_keys(times: pd.DatetimeIndex, targets: tuple[str, ...]) -> pd.MultiIndex:
    return pd.MultiIndex.from_product([times, targets], names=("time", "asset"))


def _input_table(index: pd.MultiIndex, values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "value": values,
            "available_at": [key[0] for key in index],
            "data_version": ["fixture-v1"] * len(index),
        },
        index=index,
    )


def test_research_spec_keeps_explicit_utc_grid_and_inclusive_ranges() -> None:
    grid = _utc_grid()
    spec = _research(grid, start=grid.index[1].tz_convert("America/New_York"))

    assert spec.grid.index.equals(grid.index)
    assert spec.grid.index.name == "close_time"
    assert str(spec.grid.index.tz) == "UTC"
    assert spec.start == grid.index[1]
    assert spec.end == grid.index[3]
    assert list(spec.calculation_grid.index) == list(grid.index[:4])
    assert len(spec.grid_sha256) == 64


def test_research_spec_copies_grid_and_pit_inputs_on_both_boundaries() -> None:
    grid = _utc_grid()
    keys = pd.MultiIndex.from_tuples(
        [(grid.index[0], "AAA"), (grid.index[1], "AAA")], names=("time", "asset")
    )
    numeric = _input_table(keys, [1.5, 2.5])
    class_index = pd.MultiIndex.from_tuples(
        [(grid.index[0], "AAA"), (grid.index[1], "AAA")], names=("time", "asset")
    )
    classifications = pd.DataFrame(
        {
            "level": ["sector", "sector"],
            "category": ["old", "new"],
            "effective_at": [grid.index[0], grid.index[1]],
            "available_at": [grid.index[0], grid.index[1]],
            "taxonomy_version": ["tax-v1", "tax-v1"],
        },
        index=class_index,
    )
    spec = _research(
        grid,
        formula_fields={"earnings": numeric},
        classifications={"sector_us": classifications},
    )

    # Mutating constructor inputs cannot mutate the stored snapshot.
    grid.iloc[0, 0] = grid.index[0] + pd.Timedelta(hours=2)
    numeric.loc[keys[0], "value"] = 99.0
    classifications.loc[class_index[0], "category"] = "corrupted"
    assert spec.grid.iloc[0]["open_time"] == _utc_grid().iloc[0]["open_time"]
    assert spec.formula_fields["earnings"].loc[keys[0], "value"] == 1.5
    assert spec.classifications["sector_us"].loc[class_index[0], "category"] == "old"

    # Properties also return fresh data, so callers cannot mutate the spec.
    exposed_grid = spec.grid
    exposed_grid.iloc[0, 0] = exposed_grid.index[0] + pd.Timedelta(hours=3)
    exposed_fields = spec.formula_fields
    exposed_fields["earnings"].loc[keys[0], "value"] = -1.0
    exposed_classes = spec.classifications
    exposed_classes["sector_us"].loc[class_index[0], "category"] = "also-corrupted"
    assert spec.grid.iloc[0]["open_time"] == _utc_grid().iloc[0]["open_time"]
    assert spec.formula_fields["earnings"].loc[keys[0], "value"] == 1.5
    assert spec.classifications["sector_us"].loc[class_index[0], "category"] == "old"


def test_research_spec_rejects_unknown_and_missing_universe_members() -> None:
    grid = _utc_grid()
    study_keys = _expected_keys(grid.index[1:4], ("AAA", "BBB"))
    valid = pd.Series(True, index=study_keys, dtype=bool)

    missing = valid.drop(study_keys[0])
    with pytest.raises(DatasetError) as missing_error:
        _research(grid, universe=missing)
    assert missing_error.value.code == "UNKNOWN_UNIVERSE"
    assert missing_error.value.report["missing_count"] == 1

    extra_keys = study_keys.append(
        pd.MultiIndex.from_tuples([(grid.index[1], "UNKNOWN")], names=("time", "asset"))
    )
    extra = pd.Series(True, index=extra_keys, dtype=bool)
    with pytest.raises(DatasetError) as extra_error:
        _research(grid, universe=extra)
    assert extra_error.value.code == "UNKNOWN_UNIVERSE"
    assert extra_error.value.report["extra_count"] == 1

    formula_keys = _expected_keys(grid.index[:4], ("AAA", "BBB"))
    incomplete_formula = pd.Series(True, index=formula_keys[1:], dtype=bool)
    with pytest.raises(DatasetError) as formula_error:
        _research(grid, formula_universe=incomplete_formula)
    assert formula_error.value.code == "UNKNOWN_UNIVERSE"
    assert formula_error.value.report["missing_count"] == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"targets": ("AAA", "AAA")},
        {"targets": ("AAA", " ")},
        {"source_timezone": "Not/A_Real_Zone"},
        {"snapshot_id": ""},
        {"price_basis": "default"},
        {"calendar_id": ""},
        {"frequency": ""},
        {"feed_time_kind": "open_time"},
        {"groups": {"AAA": "growth"}},
        {"execution": "next"},
    ],
)
def test_research_spec_rejects_duplicate_empty_or_unsupported_config(
    overrides: Mapping[str, Any],
) -> None:
    with pytest.raises(ConfigError):
        _research(**dict(overrides))


def test_research_spec_rejects_naive_range_endpoints_and_non_utc_grid() -> None:
    grid = _utc_grid()
    with pytest.raises(ConfigError, match="timezone"):
        _research(grid, start="2024-03-09 21:00:00")

    local_grid = grid.copy()
    local_grid.index = local_grid.index.tz_convert("America/New_York")
    with pytest.raises(ConfigError, match="UTC"):
        _research(local_grid)


def test_prealign_bars_retains_full_grid_gaps_and_masks_late_rows() -> None:
    grid = _utc_grid()
    research = _research(grid)
    # These local wall times map to t0, t2, and t3 across the spring DST change.
    local_index = pd.DatetimeIndex(
        ["2024-03-08 16:00", "2024-03-10 17:00", "2024-03-11 17:00"],
        name="close_time",
    )
    source = _bars(local_index)
    original_t0_close = source.loc[local_index[0], "close"]
    local_available = [
        pd.Timestamp("2024-03-08 16:00"),
        pd.Timestamp("2024-03-10 17:30"),
        pd.Timestamp("2024-03-11 17:00"),
    ]

    aligned = prealign_bars(
        source, research, "AAA", available_at=local_available, data_version="bars-v1"
    )
    expected_index = grid.index
    result = aligned.frame
    assert result.index.equals(expected_index)
    assert result.index.name == "close_time"
    assert bool(aligned.present.loc[grid.index[1]]) is False
    assert pd.isna(result.loc[grid.index[1], "close"])
    assert result.loc[grid.index[0], "close"] == original_t0_close

    # The source row remains present and its actual availability is retained,
    # while the not-yet-known market values are hidden on the full grid.
    assert bool(aligned.present.loc[grid.index[2]]) is True
    assert aligned.available_at.loc[grid.index[2]] == grid.index[2] + pd.Timedelta(minutes=30)
    assert result.loc[grid.index[2]].isna().all()
    assert result.loc[grid.index[3], "close"] == source.loc[local_index[2], "close"]
    assert aligned.grid_sha256 == research.grid_sha256
    assert aligned.data_version == "bars-v1"

    # Both the original input and returned properties are defensive copies.
    source.loc[local_index[0], "close"] = -500.0
    result.loc[grid.index[0], "close"] = -600.0
    present = aligned.present
    present.iloc[0] = False
    assert aligned.frame.loc[grid.index[0], "close"] == original_t0_close
    assert bool(aligned.present.loc[grid.index[0]]) is True


@pytest.mark.parametrize(
    "local_time",
    ["2024-11-03 01:30", "2024-03-10 02:30"],
)
def test_prealign_bars_rejects_ambiguous_or_nonexistent_local_dst_times(
    local_time: str,
) -> None:
    grid = pd.DataFrame(
        {"open_time": [pd.Timestamp("2024-11-03 00:00", tz="UTC")]},
        index=pd.DatetimeIndex(["2024-11-03 01:00"], tz="UTC", name="close_time"),
    )
    research = _research(
        grid,
        start=grid.index[0],
        end=grid.index[0],
    )
    source = _bars(pd.DatetimeIndex([local_time], name="close_time"))

    with pytest.raises(DatasetError):
        prealign_bars(source, research, "AAA")


def test_prealign_pit_classifications_use_only_visible_and_effective_history() -> None:
    grid = _utc_grid()
    research = _research(grid, end=grid.index[4], targets=("AAA", "BBB", "CCC"))
    rows = [
        # AAA: a later logical version is not visible until t3; at t3 it wins
        # over the older visible row, and t4 then supplies the latest version.
        (grid.index[0], "AAA", "AAA-old", grid.index[0], grid.index[0]),
        (grid.index[1], "AAA", "AAA-late", grid.index[1], grid.index[3]),
        (grid.index[3], "AAA", "AAA-visible-t3", grid.index[2], grid.index[3]),
        (grid.index[4], "AAA", "AAA-latest", grid.index[4], grid.index[4]),
        # BBB: available from t1, but not effective until t4.
        (grid.index[0], "BBB", "BBB-old", grid.index[0], grid.index[0]),
        (grid.index[1], "BBB", "BBB-future-effective", grid.index[4], grid.index[1]),
    ]
    pit_index = pd.MultiIndex.from_tuples(
        [(row[0], row[1]) for row in rows], names=("time", "asset")
    )
    table = pd.DataFrame(
        {
            "level": ["sector"] * len(rows),
            "category": [row[2] for row in rows],
            "effective_at": [row[3] for row in rows],
            "available_at": [row[4] for row in rows],
            "taxonomy_version": ["sector-v1"] * len(rows),
        },
        index=pit_index,
    )

    aligned = prealign_pit_table(table, research, "sector_us", classification=True)
    t1, t2, t3, t4 = grid.index[1:5]

    assert aligned.value_at(t1, "AAA")["category"] == "AAA-old"
    assert aligned.value_at(t2, "AAA")["category"] == "AAA-old"
    assert aligned.value_at(t3, "AAA")["category"] == "AAA-visible-t3"
    assert aligned.value_at(t4, "AAA")["category"] == "AAA-latest"
    assert aligned.value_at(t3, "BBB")["category"] == "BBB-old"
    assert aligned.value_at(t4, "BBB")["category"] == "BBB-future-effective"
    assert aligned.reason.loc[(t3, "BBB")] == "READY"
    assert aligned.available_at.loc[(t3, "AAA")] == t3
    assert aligned.available_at.loc[(t3, "BBB")] == grid.index[0]

    # An asset with no PIT rows remains explicitly unknown rather than
    # receiving a guessed/default classification.
    assert pd.isna(aligned.value_at(t3, "CCC")["category"])
    assert bool(aligned.present.loc[(t3, "CCC")]) is False
    assert aligned.reason.loc[(t3, "CCC")] == "UNKNOWN_CLASSIFICATION"

    exposed_values = aligned.values
    exposed_values.loc[(t3, "AAA"), "category"] = "corrupted"
    exposed_present = aligned.present
    exposed_present.loc[(t3, "AAA")] = False
    exposed_reasons = aligned.reason
    exposed_reasons.loc[(t3, "AAA")] = "corrupted"
    assert aligned.value_at(t3, "AAA")["category"] == "AAA-visible-t3"
    assert bool(aligned.present.loc[(t3, "AAA")]) is True
    assert aligned.reason.loc[(t3, "AAA")] == "READY"


class _SpecFactor(FactorIndicator):
    lines = ("factor",)
    formula_fields = (
        "close",
        "benchmark_close",
        "dollar_volume",
        "vwap",
        "volume",
        "adv20",
    )
    classification_fields = ("sector",)
    classification_levels = ("sector",)
    lookback_h = 2

    def next(self) -> None:
        pass


def _factor_spec(field_bindings: Mapping[str, Any], **overrides: Any) -> FactorSpec:
    args = {
        "name": "fixture_factor",
        "indicator": _SpecFactor,
        "panel_line": "factor",
        "field_bindings": field_bindings,
    }
    args.update(overrides)
    return FactorSpec(**args)


def test_factor_spec_accepts_documented_direct_and_explicit_derivation_bindings() -> None:
    direct = _factor_spec(
        {
            "close": "feed:AAA:close",
            "benchmark_close": {"kind": "direct", "source": "feed:BENCH:close"},
            "adv20": "table:adv20_usd",
        },
        classification_bindings={"sector": "sector_us_v3"},
    )
    assert direct.lookback_h == 2
    assert direct.field_bindings["close"] == "feed:AAA:close"
    assert direct.field_bindings["adv20"] == "table:adv20_usd"
    assert direct.field_bindings["benchmark_close"]["source"] == "feed:BENCH:close"
    assert direct.classification_bindings["sector"] == "sector_us_v3"

    derived = _factor_spec(
        {
            "dollar_volume": {
                "derive": "vwap_volume",
                "vwap": "vwap",
                "volume": "volume",
            },
            "vwap": "feed:AAA:vwap",
            "volume": "feed:AAA:volume",
            "adv20": {"derive": "adv", "source": "dollar_volume", "window": 20},
        }
    )
    assert derived.field_bindings["dollar_volume"]["derive"] == "vwap_volume"
    assert derived.field_bindings["adv20"]["window"] == 20


@pytest.mark.parametrize(
    "bindings",
    [
        {"close": "feed:BENCH"},
        {"close": "feed::close"},
        {"close": {"kind": "direct", "source": "feed:BENCH"}},
        {"close": {"kind": "direct", "source": "feed:"}},
        {"close": {"kind": "direct", "source": "table:"}},
        {"close": {"kind": "unknown", "source": "feed:BENCH:close"}},
        {"close": {"kind": "direct", "source": "feed:BENCH:close", "extra": 1}},
        {"undeclared": "feed:AAA:close"},
        {"adv20": {"derive": "adv", "source": "dollar_volume", "window": True}},
        {"adv20": {"derive": "adv", "source": "dollar_volume", "window": 19}},
        {"adv20": {"derive": "adv", "source": "close", "window": 20}},
        {
            "dollar_volume": {"derive": "vwap_volume", "vwap": "vwap", "volume": "volume"},
            "vwap": "feed:AAA:vwap",
            "volume": "feed:AAA:volume",
            "adv20": {"derive": "adv", "source": "dollar_volume", "window": 20, "extra": True},
        },
        {"dollar_volume": {"derive": "vwap_volume", "vwap": "vwap", "volume": "volume"}},
    ],
)
def test_factor_spec_rejects_malformed_or_unbound_input_descriptors(
    bindings: Mapping[str, Any],
) -> None:
    with pytest.raises(ConfigError):
        _factor_spec(bindings)


def test_factor_spec_freezes_nested_params_and_rejects_legacy_or_duplicate_config() -> None:
    params = {"nested": {"windows": [2, 5]}}
    spec = _factor_spec({"close": "feed:AAA:close"}, params=params)
    params["nested"]["windows"].append(10)
    assert spec.params["nested"]["windows"] == (2, 5)
    with pytest.raises(TypeError):
        spec.params["nested"]["changed"] = True

    with pytest.raises(ConfigError):
        _factor_spec({"close": "feed:AAA:close"}, direction=True)
    with pytest.raises(ConfigError):
        _factor_spec({"close": "feed:AAA:close"}, execution="next")
    with pytest.raises(ConfigError):
        _factor_spec({"close": "feed:AAA:close"}, panel_line="unknown")
    with pytest.raises(ConfigError):
        FactorSpec.from_mapping(
            "fixture_factor",
            {"indicator": _SpecFactor, "panel_line": "factor", "inputs": {}},
        )

    with pytest.raises(ConfigError, match="duplicate factor"):
        normalize_factor_specs(
            [
                ("fixture_factor", spec),
                ("fixture_factor", spec),
            ]
        )
