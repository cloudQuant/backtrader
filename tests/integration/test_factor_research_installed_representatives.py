"""Run twenty production Alpha101 formulas through both committed installed wheels.

Copy this file, the committed unit reference fixture, the full reference
helper, causal trace validator, and pinned formula catalog to an external test tree before
running. The fixture supplies an independent matrix oracle; installed factors
come from the public Alpha101 registry. This is an acceptance diagnostic, not
another example.

Required external inputs:

* ``tests/unit/test_factor_research_representatives.py``
* ``tests/test_utils/alpha101_full_reference.py``
* ``tests/test_utils/alpha101_trace_validation.py``
* ``tests/fixtures/research/alpha101_dependencies.json``
"""

import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys

import pandas as pd
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("BT_FACTOR_RESEARCH_RUN_INSTALLED_INTEGRATION") != "1",
    reason="requires the pinned committed Backtrader and fincore wheels",
)

_INSTALLED_ROOTS_ENV = "BT_FACTOR_RESEARCH_INSTALLED_ROOTS"
_WINDOW_START = 116
_WINDOW_END = 251
_IC_METRICS = ("pearson", "spearman")


def _installed(module):
    origin = Path(module.__file__).resolve()
    roots = [Path(sys.prefix).resolve()]
    configured = os.environ.get(_INSTALLED_ROOTS_ENV)
    if configured:
        roots.extend(Path(value).expanduser().resolve() for value in json.loads(configured))
    for root in roots:
        if origin.is_relative_to(root):
            if root == Path(sys.prefix).resolve():
                assert "site-packages" in origin.parts or "dist-packages" in origin.parts
            return str(origin)
    raise AssertionError("%s did not load from an approved install root" % origin)


def _ranks(values):
    return [
        1
        + sum(other < value for other in values)
        + (sum(other == value for other in values) - 1) / 2
        for value in values
    ]


def _correlation(left, right):
    mx, my = statistics.mean(left), statistics.mean(right)
    dx, dy = [x - mx for x in left], [y - my for y in right]
    denominator = math.sqrt(math.fsum(x * x for x in dx) * math.fsum(y * y for y in dy))
    return math.fsum(x * y for x, y in zip(dx, dy)) / denominator


def _independent_ic_expectations(matrices, label_values, times, assets, offsets):
    expected = {}
    degeneracies = []
    for name, matrix in matrices.items():
        for offset in offsets:
            timestamp = pd.Timestamp(times[offset])
            paired = [
                (float(matrix[offset][column]), label_values[(timestamp, asset)])
                for column, asset in enumerate(assets)
                if math.isfinite(float(matrix[offset][column]))
            ]
            left = [value for value, _ in paired]
            right = [value for _, value in paired]
            if len(paired) < 2:
                reason = "INSUFFICIENT_ASSETS"
            elif len(set(left)) < 2:
                reason = "CONSTANT_FACTOR"
            elif len(set(right)) < 2:
                reason = "CONSTANT_RETURN"
            else:
                reason = None
            if reason is not None:
                degeneracies.append((name, timestamp, reason))
            for metric in _IC_METRICS:
                key = (name, timestamp, metric)
                if reason is not None:
                    expected[key] = (reason, None)
                    continue
                metric_left, metric_right = left, right
                if metric == "spearman":
                    metric_left, metric_right = _ranks(left), _ranks(right)
                expected[key] = (None, _correlation(metric_left, metric_right))
    return expected, degeneracies


def _evaluation_spec(panel):
    from fincore.factor_analysis.research import ResearchEvaluationSpec

    return ResearchEvaluationSpec(
        targets=panel.target_order,
        start=panel.start,
        end=panel.end,
        snapshot_id="installed-alpha101-twenty-independent-v1",
        price_basis="synthetic-unadjusted-USD",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        source_timezone="UTC",
        feed_time_kind="close_time",
        periods=(1,),
        label="next_open_to_open",
        min_assets=2,
        quantiles=1,
        min_quantile_assets=1,
        preprocess="none",
        stability_lags=(1,),
        max_loss=1.0,
    )


def test_twenty_installed_formulas_with_real_labels_and_independent_ic(tmp_path):
    import backtrader as bt
    import fincore
    from backtrader.research import FactorPanel, FactorStrategy, ResearchSpec, evaluate_frames
    from backtrader.research import alpha101

    origins = {"backtrader": _installed(bt), "fincore": _installed(fincore)}
    reference_path = (
        Path(__file__).resolve().parents[1] / "unit" / "test_factor_research_representatives.py"
    )
    loader = importlib.util.spec_from_file_location("installed_factor_reference", reference_path)
    reference = importlib.util.module_from_spec(loader)
    sys.modules[loader.name] = reference
    loader.loader.exec_module(reference)

    production_ids = tuple(reference._ALPHA_IDS)
    production_factors = {}
    for number in production_ids:
        factor_class = alpha101.get_alpha(number)
        module_name = "backtrader.research.alpha101.alpha%03d" % number
        assert factor_class.__module__ == module_name
        module = importlib.import_module(module_name)
        assert getattr(module, factor_class.__name__) is factor_class
        origins[module_name] = _installed(module)
        production_factors[number] = factor_class

    frames = reference._frames(286)
    assets = tuple(frames)
    times = next(iter(frames.values())).index.rename("close_time")
    window_offsets = tuple(range(_WINDOW_START, _WINDOW_END + 1))
    window_times = pd.DatetimeIndex(times[list(window_offsets)])

    # This is the shortest continuous interval in the fixed 286-bar fixture
    # that contains an H-eligible finite cell for every formula. Alpha096's
    # last finite point is 116, and Alpha048's first complete finite point is
    # 251, so no interval covering both can be shorter than 136 bars.
    # Compute labels independently from the factor outputs.
    label_values = {
        (pd.Timestamp(times[offset]), asset): (
            frames[asset].open.iloc[offset + 2] / frames[asset].open.iloc[offset + 1] - 1
        )
        for offset in window_offsets
        for asset in assets
    }
    assert all(math.isfinite(value) for value in label_values.values())

    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[0],
        end=times[-1],
        targets=assets,
        source_timezone="UTC",
        feed_time_kind="close_time",
        snapshot_id="installed-alpha101-twenty-independent-v1",
        price_basis="synthetic-unadjusted-USD",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        groups=dict.fromkeys(assets, "market"),
    )

    class CountingBroker(bt.brokers.BackBroker):
        def __init__(self):
            super().__init__()
            self.submits = self.cancels = 0

        def submit(self, *args, **kwargs):
            self.submits += 1
            return super().submit(*args, **kwargs)

        def cancel(self, *args, **kwargs):
            self.cancels += 1
            return super().cancel(*args, **kwargs)

    cerebro = bt.Cerebro(stdstats=False, runonce=False)
    broker = CountingBroker()
    cerebro.setbroker(broker)
    for asset, frame in frames.items():
        cerebro.adddata(reference._research_feed(frame, research, asset), name=asset)
    factors = {
        "alpha%d" % number: reference._factor_spec("alpha%d" % number, factor_class)
        for number, factor_class in production_factors.items()
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run()[0]
    assert (broker.submits, broker.cancels) == (0, 0)
    collected = strategy.get_panel()
    assert isinstance(collected, FactorPanel)
    assert tuple(collected.grid.index) == tuple(times)
    assert collected.start == times[0]
    assert collected.end == times[-1]
    assert tuple(collected.factor_order) == tuple("alpha%d" % value for value in production_ids)

    trace_validation = importlib.import_module("tests.test_utils.alpha101_trace_validation")
    trace_results = {}
    for number in production_ids:
        name = "alpha%d" % number
        trace = trace_validation.validate_factor_trace(
            strategy.factor_instances[name],
            number,
            frames,
            assets,
            tuple(times),
            strategy=strategy,
        )
        assert not trace["failures"], "\\n".join(trace["failures"])
        assert trace["finite_witness"]
        assert trace["matched_nodes"] > 0
        trace_results[number] = trace

    finite_offsets = {
        number: tuple(
            offset
            for offset, row in enumerate(trace_results[number]["expected"])
            if any(math.isfinite(float(value)) for value in row)
        )
        for number in production_ids
    }
    assert finite_offsets[96][-1] == _WINDOW_START
    assert finite_offsets[48][0] == _WINDOW_END
    for number in production_ids:
        assert any(offset in window_offsets for offset in finite_offsets[number]), (
            "alpha%d has no finite trace witness in the evaluation interval" % number
        )

    evaluation_times = pd.DatetimeIndex(times[list(window_offsets)])
    factor_times = collected.factors.index.get_level_values("time")
    source_panel = FactorPanel(
        factors=collected.factors.loc[factor_times.isin(evaluation_times)],
        grid=collected.grid,
        prices_open=collected.prices_open,
        prices_close=collected.prices_close,
        universe=collected.universe.loc[evaluation_times],
        groups=collected.groups,
        start=times[_WINDOW_START],
        end=times[_WINDOW_END],
        target_order=collected.target_order,
        factor_order=collected.factor_order,
        directions=collected.directions,
    )
    panel_path = tmp_path / "factor-panel"
    source_panel.to_csv(panel_path)
    panel = FactorPanel.from_csv(
        panel_path,
        start=times[_WINDOW_START],
        end=times[_WINDOW_END],
        directions=collected.directions,
        target_order=assets,
        factor_order=collected.factor_order,
        groups=collected.groups,
    )
    pd.testing.assert_frame_equal(panel.factors, source_panel.factors)
    pd.testing.assert_frame_equal(panel.grid, source_panel.grid)
    pd.testing.assert_frame_equal(panel.prices_open, source_panel.prices_open)
    pd.testing.assert_frame_equal(panel.prices_close, source_panel.prices_close)
    pd.testing.assert_frame_equal(panel.universe, source_panel.universe)

    factor_matrices = {
        number: panel.factors["alpha%d" % number]
        .unstack("asset")
        .reindex(index=times, columns=assets)
        .to_numpy()
        .tolist()
        for number in production_ids
    }
    expected_ic, degeneracy_witnesses = _independent_ic_expectations(
        {
            "alpha%d" % number: [factor_matrices[number][offset] for offset in window_offsets]
            for number in production_ids
        },
        label_values,
        window_times,
        assets,
        range(len(window_times)),
    )
    assert degeneracy_witnesses, "the fixed fixture must contain a degenerate IC witness"

    calls_before = {
        name: factor.lifecycle_diagnostics for name, factor in strategy.factor_instances.items()
    }
    borrowed = {
        name: getattr(panel, name)
        for name in ("factors", "grid", "prices_open", "prices_close", "universe")
    }
    borrowed_snapshot = {name: frame.copy(deep=True) for name, frame in borrowed.items()}
    result = evaluate_frames(panel, _evaluation_spec(panel))
    assert calls_before == {
        name: factor.lifecycle_diagnostics for name, factor in strategy.factor_instances.items()
    }
    for name, frame in borrowed.items():
        pd.testing.assert_frame_equal(frame, borrowed_snapshot[name])
    assert result.status in ("OK", "PARTIAL")
    assert result.manifest["result_fingerprint"]
    assert "dataset_id" not in result.manifest
    assert set(result.labels["period"]) == {"1D"}
    expected_label_keys = set(label_values)
    actual_label_keys = [(pd.Timestamp(row.time), row.asset) for row in result.labels.itertuples()]
    assert len(actual_label_keys) == len(set(actual_label_keys))
    assert set(actual_label_keys) == expected_label_keys
    assert len(result.labels) == len(window_offsets) * len(assets)
    for row in result.labels.itertuples():
        expected = label_values[(pd.Timestamp(row.time), row.asset)]
        assert row.value == pytest.approx(expected, rel=1e-12, abs=1e-12)

    ic = result.ic
    expected_ic_rows = {
        (name, timestamp)
        for name, timestamp, _metric in expected_ic
        if expected_ic[(name, timestamp, "pearson")][0] != "INSUFFICIENT_ASSETS"
    }
    actual_ic_keys = [(row.factor, pd.Timestamp(row.time)) for row in ic.itertuples()]
    assert len(actual_ic_keys) == len(set(actual_ic_keys))
    assert set(actual_ic_keys) == expected_ic_rows
    assert {factor for factor, _ in actual_ic_keys} == {factor for factor, _ in expected_ic_rows}
    report = {}
    total_degeneracies = 0
    for number in production_ids:
        name = "alpha%d" % number
        # The independent AST trace above validates every native node and the
        # collector output. IC expectations intentionally use those validated
        # production float64 signals to preserve exact production ties.
        finite_count = sum(
            math.isfinite(value) for row in trace_results[number]["expected"] for value in row
        )
        assert finite_count > 0, name
        rows = ic.loc[ic.factor == name]
        actual_ic_keys = [pd.Timestamp(row.time) for row in rows.itertuples()]
        expected_ic_keys = {
            pd.Timestamp(times[offset])
            for offset in window_offsets
            if expected_ic[(name, pd.Timestamp(times[offset]), "pearson")][0]
            != "INSUFFICIENT_ASSETS"
        }
        assert len(actual_ic_keys) == len(set(actual_ic_keys)), name
        assert set(actual_ic_keys) == expected_ic_keys, name
        if not expected_ic_keys:
            assert rows.empty, name
            report[name] = {
                "finite_factor_cells": finite_count,
                "verified_ic": 0,
                "verified_degeneracies": 0,
                "ic_unavailable_reason": "fewer than two finite assets in every evaluation cross-section",
            }
            continue
        assert not rows.empty, name
        usable = degenerate = 0
        for row in rows.itertuples():
            timestamp = pd.Timestamp(row.time)
            reason, _ = expected_ic[(name, timestamp, "pearson")]
            if reason is not None:
                assert reason in ("CONSTANT_FACTOR", "CONSTANT_RETURN")
                assert pd.isna(row.ic) and pd.isna(row.rank_ic)
                degenerate += 1
                continue
            expected_asset_count = sum(
                math.isfinite(factor_matrices[number][times.get_loc(timestamp)][column])
                for column in range(len(assets))
            )
            assert row.n_assets == expected_asset_count
            for metric, column in (("pearson", row.ic), ("spearman", row.rank_ic)):
                _, expected_value = expected_ic[(name, timestamp, metric)]
                assert math.isfinite(column)
                assert expected_value is not None
                assert abs(column - expected_value) <= 1e-12 + 1e-10 * abs(
                    expected_value
                ), "%s %s %s differs: actual=%r expected=%r direction=%r" % (
                    name,
                    timestamp,
                    metric,
                    column,
                    expected_value,
                    panel.directions[name],
                )
            usable += 1
        total_degeneracies += degenerate
        report[name] = {
            "finite_factor_cells": finite_count,
            "verified_ic": usable,
            "verified_degeneracies": degenerate,
        }
    assert len(report) == len(production_ids) == 20
    assert total_degeneracies > 0
    result.export(tmp_path / "evaluation", charts=False)
    panel_csv_files = sorted(path.name for path in panel_path.iterdir())
    assert panel_csv_files == [
        "factors.csv",
        "grid.csv",
        "groups.csv",
        "prices_close.csv",
        "prices_open.csv",
        "universe.csv",
    ]
    (tmp_path / "installed-acceptance.json").write_text(
        json.dumps(
            {
                "origins": origins,
                "factor_panel_csv_files": panel_csv_files,
                "evaluation_fingerprint": result.manifest["result_fingerprint"],
                "result_status": result.status,
                "broker_submits": broker.submits,
                "broker_cancels": broker.cancels,
                "formulas": report,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
