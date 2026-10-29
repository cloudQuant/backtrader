"""Contracts for the isolated factor-research attribution harness."""

from __future__ import annotations

import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "scripts/benchmark_factor_research_attribution.py measures peak RSS "
        "with the Unix-only resource module"
    ),
)

if sys.platform == "win32":
    # The harness imports ``resource`` at module scope. Supply an inert stub so
    # this module can still be collected and these tests skipped cleanly.
    sys.modules.setdefault("resource", types.ModuleType("resource"))

from scripts.benchmark_factor_research_attribution import (
    FINCORE_ARCHIVE_PATHS,
    KERNEL_BASELINE_REVISION,
    REPO_ROOT,
    _alternating_order,
    _canonical_hash,
    _compare_factor_csvs,
    _effective_groups,
    _extract_html_timestamp,
    _factor_csv_summary,
    _git_text,
    _install_legacy_kernel,
    _kernel_hashes,
    _kernel_method_sources,
    _parser,
    _manifest_actual_symbol_count,
    _read_wide_price_csv,
    _validate_symbol_count,
    main,
)


def test_legacy_archive_contains_only_the_expected_pair_kernels() -> None:
    source = _git_text(REPO_ROOT, KERNEL_BASELINE_REVISION, "backtrader/research/operators.py")
    methods = _kernel_method_sources(source)

    assert set(methods) == {"RollingCovariance", "RollingCorrelation"}
    assert all("Fraction" in body for body in methods.values())
    assert "Decimal" in methods["RollingCorrelation"]
    assert set(_kernel_hashes(source)) == set(methods)


def test_legacy_kernel_patch_changes_only_two_fake_class_methods() -> None:
    source = _git_text(REPO_ROOT, KERNEL_BASELINE_REVISION, "backtrader/research/operators.py")

    class Reason:
        READY = 0
        DOMAIN_ERROR = 4

    class FakePair:
        _period = 3

        def _pair_windows(self):
            return [1.0, 2.0, 3.0], [2.0, 4.0, 6.0], Reason.READY

    class Unrelated:
        def _evaluate(self):
            return "unchanged"

    module = SimpleNamespace(
        RollingCovariance=type("RollingCovariance", (FakePair,), {}),
        RollingCorrelation=type("RollingCorrelation", (FakePair,), {}),
        Unrelated=Unrelated,
        _NAN=float("nan"),
        OperatorReason=Reason,
        _guarded_result=lambda operation: (operation(), Reason.READY),
        math=math,
    )
    unrelated_method = module.Unrelated._evaluate

    hashes = _install_legacy_kernel(module, source)

    covariance, covariance_reason = module.RollingCovariance()._evaluate()
    correlation, correlation_reason = module.RollingCorrelation()._evaluate()
    assert covariance == pytest.approx(4.0 / 3.0)
    assert covariance_reason == Reason.READY
    assert correlation == 1.0
    assert correlation_reason == Reason.READY
    assert module.Unrelated._evaluate is unrelated_method
    assert set(hashes) == {"RollingCovariance", "RollingCorrelation"}


@pytest.mark.parametrize(
    ("group", "expected"),
    ((0, ("old", "new")), (1, ("new", "old")), (2, ("old", "new"))),
)
def test_measurement_groups_alternate_order(group: int, expected: tuple[str, str]) -> None:
    assert _alternating_order(group) == expected


def test_non_smoke_requires_three_measured_groups() -> None:
    assert _effective_groups(3, smoke=False) == 3
    assert _effective_groups(8, smoke=True) == 1
    with pytest.raises(ValueError, match="at least 3"):
        _effective_groups(2, smoke=False)


def test_cli_rejects_under_three_groups_before_creating_output(tmp_path: Path) -> None:
    output = tmp_path / "not-created"

    status = main(["--mode", "kernel", "--symbols", "3", "--groups", "2", "--output", str(output)])

    assert status == 2
    assert not output.exists()


def test_candidate_fincore_ref_defaults_to_current_checkout_head() -> None:
    args = _parser().parse_args(["--mode", "reports", "--output", "unused-output"])

    assert args.fincore_candidate_revision == "HEAD"


def test_fincore_archive_is_limited_to_package_and_version_metadata() -> None:
    assert FINCORE_ARCHIVE_PATHS == ("fincore", "pyproject.toml")


def test_requested_and_actual_symbol_counts_must_match() -> None:
    _validate_symbol_count(3, 3)
    with pytest.raises(ValueError, match="requested 3 symbols.*contains 2"):
        _validate_symbol_count(3, 2)


def _write_factor_csv(path: Path, rows: list[tuple[str, str, str, float]]) -> None:
    import pandas as pd

    pd.DataFrame(rows, columns=("time", "asset", "factor", "value")).to_csv(path, index=False)


def test_factor_csv_pair_accepts_local_float64_tolerance(tmp_path: Path) -> None:
    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    _write_factor_csv(
        old_path,
        [("2026-01-01", "A", "alpha003", 0.25), ("2026-01-01", "B", "alpha003", -0.5)],
    )
    _write_factor_csv(
        new_path,
        [
            ("2026-01-01", "A", "alpha003", 0.25 + 1e-12),
            ("2026-01-01", "B", "alpha003", -0.5),
        ],
    )

    comparison = _compare_factor_csvs(old_path, new_path)

    assert comparison["matches"] is True
    assert comparison["keys_match"] is True
    assert comparison["per_factor"]["alpha003"]["finite_pairs"] == 2


def test_factor_csv_pair_detects_values_moved_between_assets(tmp_path: Path) -> None:
    old_path = tmp_path / "old.csv"
    swapped_path = tmp_path / "swapped.csv"
    _write_factor_csv(
        old_path,
        [("t", "A", "alpha003", 1.0), ("t", "B", "alpha003", 2.0)],
    )
    _write_factor_csv(
        swapped_path,
        [("t", "A", "alpha003", 2.0), ("t", "B", "alpha003", 1.0)],
    )

    comparison = _compare_factor_csvs(old_path, swapped_path)

    assert comparison["keys_match"] is True
    assert comparison["matches"] is False
    assert comparison["max_abs_error"] == 1.0
    assert comparison["per_asset"]["A"]["max_abs_error"] == 1.0
    assert comparison["per_asset"]["B"]["max_abs_error"] == 1.0


def test_factor_csv_pair_rejects_nan_mask_changes(tmp_path: Path) -> None:
    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    _write_factor_csv(old_path, [("t", "A", "alpha003", math.nan), ("t", "B", "alpha003", 2.0)])
    _write_factor_csv(new_path, [("t", "A", "alpha003", 1.0), ("t", "B", "alpha003", 2.0)])

    comparison = _compare_factor_csvs(old_path, new_path)

    assert comparison["nan_mask_match"] is False
    assert comparison["matches"] is False


def test_factor_csv_pair_accepts_asset_with_identical_all_nan_mask(tmp_path: Path) -> None:
    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    rows = [("t", "A", "alpha003", math.nan), ("t", "B", "alpha003", 2.0)]
    _write_factor_csv(old_path, rows)
    _write_factor_csv(new_path, rows)

    comparison = _compare_factor_csvs(old_path, new_path)

    assert comparison["matches"] is True
    assert comparison["per_asset"]["A"]["finite_pairs"] == 0
    assert comparison["per_asset"]["A"]["nan_mask_match"] is True
    assert comparison["per_asset"]["A"]["within_tolerance"] is True


def test_factor_csv_pair_rejects_non_near_miss_ordering_difference(tmp_path: Path) -> None:
    old_path = tmp_path / "old.csv"
    new_path = tmp_path / "new.csv"
    _write_factor_csv(old_path, [("t", "A", "alpha003", 0.125)])
    _write_factor_csv(new_path, [("t", "A", "alpha003", 0.12501)])

    comparison = _compare_factor_csvs(old_path, new_path)

    assert comparison["within_tolerance"] is False
    assert comparison["matches"] is False


def test_factor_csv_with_no_finite_factor_cells_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "empty-factor.csv"
    _write_factor_csv(path, [("t", "A", "alpha003", math.nan)])

    with pytest.raises(ValueError, match="no finite output cells"):
        _factor_csv_summary(path)


def _make_csv_panel():
    import numpy as np
    import pandas as pd

    from backtrader.research.panel import FactorPanel

    index = pd.date_range("2025-01-01", periods=3, freq="D", tz="UTC", name="close_time")
    assets = ("000001", "600000")
    multi = pd.MultiIndex.from_product([index, assets], names=("time", "asset"))
    factors = pd.DataFrame({"alpha003": np.arange(6, dtype="float64")}, index=multi)
    grid = pd.DataFrame({"open_time": index - pd.Timedelta(hours=6)}, index=index)
    prices = pd.DataFrame([[10.0, 20.0], [11.0, 22.0], [12.0, 24.0]], index=index, columns=assets)
    return FactorPanel(
        factors=factors,
        grid=grid,
        prices_open=prices,
        prices_close=prices + 0.5,
        start=index[0],
        end=index[-1],
        target_order=assets,
        factor_order=("alpha003",),
        directions={"alpha003": 1},
    )


def test_wide_prices_from_factor_panel_csv_keep_utc_order_and_report_values(
    tmp_path: Path,
) -> None:
    import pandas as pd

    panel = _make_csv_panel()
    panel_dir = tmp_path / "panel"
    panel.to_csv(panel_dir)
    prices, assets = _read_wide_price_csv(
        panel_dir / "prices_open.csv", expected_assets=panel.target_order
    )

    assert assets == ["000001", "600000"]
    assert prices.columns.tolist() == ["000001", "600000"]
    assert prices.index.tz is not None and str(prices.index.tz) == "UTC"
    pd.testing.assert_frame_equal(prices, panel.prices_open, check_freq=False)
    pd.testing.assert_frame_equal(prices.shift(-1), panel.prices_open.shift(-1), check_freq=False)
    assert (
        _manifest_actual_symbol_count(
            {
                "panel_csv_dir": str(panel_dir),
                "actual_symbols": 2,
                "requested_symbols": 2,
                "asset_order": ["000001", "600000"],
            }
        )
        == 2
    )


def test_wide_price_asset_column_reduction_is_rejected(tmp_path: Path) -> None:
    import pandas as pd

    panel = _make_csv_panel()
    panel_dir = tmp_path / "panel"
    panel.to_csv(panel_dir)
    path = panel_dir / "prices_open.csv"
    truncated = pd.read_csv(path).drop(columns=["600000"])
    truncated.to_csv(path, index=False)

    with pytest.raises(ValueError, match="changed order or count"):
        _read_wide_price_csv(path, expected_assets=panel.target_order)
    with pytest.raises(ValueError, match="requested 2 symbols.*contains 1"):
        _manifest_actual_symbol_count({"panel_csv_dir": str(panel_dir), "requested_symbols": 2})


def test_html_normalization_removes_only_generated_time() -> None:
    first = '<body><span class="time">2026-10-22 12:30 UTC</span><b>same</b></body>'
    second = '<body><span class="time">2026-10-22 12:31 UTC</span><b>same</b></body>'

    normalized_first, timestamp_first = _extract_html_timestamp(first)
    normalized_second, timestamp_second = _extract_html_timestamp(second)

    assert normalized_first == normalized_second
    assert timestamp_first == "2026-10-22 12:30 UTC"
    assert timestamp_second == "2026-10-22 12:31 UTC"
    assert _extract_html_timestamp("<body>no generated clock</body>") == (
        "<body>no generated clock</body>",
        None,
    )


def test_semantic_hash_is_stable_and_sensitive_to_complete_payload() -> None:
    payload = {"model": "model-fingerprint", "report": "report-digest", "direction": 1}

    digest = _canonical_hash(payload)

    assert digest == _canonical_hash(
        {"direction": 1, "report": "report-digest", "model": "model-fingerprint"}
    )
    assert digest != _canonical_hash({**payload, "direction": -1})
