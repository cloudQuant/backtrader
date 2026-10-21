"""Run the twenty diagnostic formulas through both committed installed wheels.

Copy this file and the committed unit reference fixture to an external test
tree before running. This is an acceptance diagnostic, not another example.
"""

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

_WINDOW_START = 116
_WINDOW_END = 251
_IC_METRICS = ("pearson", "spearman")


def _installed(module):
    origin = Path(module.__file__).resolve()
    assert origin.is_relative_to(Path(sys.prefix).resolve())
    assert "site-packages" in origin.parts or "dist-packages" in origin.parts
    return str(origin)


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


def test_twenty_installed_formulas_with_real_labels_and_independent_ic(tmp_path):
    import backtrader as bt
    import fincore
    from backtrader.research import FactorStrategy, ResearchSpec, load_dataset
    from backtrader.research.representative import REPRESENTATIVE_FACTORS

    origins = {"backtrader": _installed(bt), "fincore": _installed(fincore)}
    reference_path = (
        Path(__file__).resolve().parents[1] / "unit" / "test_factor_research_representatives.py"
    )
    loader = importlib.util.spec_from_file_location("installed_factor_reference", reference_path)
    reference = importlib.util.module_from_spec(loader)
    sys.modules[loader.name] = reference
    loader.loader.exec_module(reference)

    frames = reference._frames(286)
    assets = tuple(frames)
    times = next(iter(frames.values())).index.rename("close_time")
    window_offsets = tuple(range(_WINDOW_START, _WINDOW_END + 1))
    window_times = pd.DatetimeIndex(times[list(window_offsets)])

    # This is the shortest continuous interval in the fixed 286-bar fixture
    # that contains an H-eligible finite cell for every formula. Alpha096's
    # last finite point is 116, and Alpha048's first complete finite point is
    # 251, so no interval covering both can be shorter than 136 bars.
    oracle_by_name = {}
    finite_offsets = {}
    for number in REPRESENTATIVE_FACTORS:
        name = "alpha%d" % number
        formula_values, _ = reference._formula_reference(number, frames)
        history = reference._HISTORY[number]
        formula_values = [
            row if offset >= history else [math.nan] * len(assets)
            for offset, row in enumerate(formula_values)
        ]
        oracle_by_name[name] = formula_values
        finite_offsets[number] = tuple(
            offset
            for offset, row in enumerate(formula_values)
            if offset >= history and any(math.isfinite(value) for value in row)
        )

    assert finite_offsets[96][-1] == _WINDOW_START
    assert finite_offsets[48][0] == _WINDOW_END
    for number in REPRESENTATIVE_FACTORS:
        assert any(offset in window_offsets for offset in finite_offsets[number]), (
            "alpha%d has no finite oracle witness in the research window" % number
        )

    # Precompute forward labels and each expected IC outcome before the
    # installed strategy/evaluator runs, so fixture gaps fail cheaply.
    label_values = {
        (pd.Timestamp(times[offset]), asset): (
            frames[asset].open.iloc[offset + 2] / frames[asset].open.iloc[offset + 1] - 1
        )
        for offset in window_offsets
        for asset in assets
    }
    assert all(math.isfinite(value) for value in label_values.values())
    expected_ic = {}
    degeneracy_witnesses = []
    for number in REPRESENTATIVE_FACTORS:
        name = "alpha%d" % number
        formula_values = oracle_by_name[name]
        for offset in window_offsets:
            timestamp = pd.Timestamp(times[offset])
            paired = [
                (formula_values[offset][column], label_values[(timestamp, asset)])
                for column, asset in enumerate(assets)
                if math.isfinite(formula_values[offset][column])
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
                degeneracy_witnesses.append((name, timestamp, reason))

            for metric in _IC_METRICS:
                key = (name, timestamp, metric)
                if reason is not None:
                    expected_ic[key] = (reason, None)
                    continue
                metric_left, metric_right = left, right
                if metric == "spearman":
                    metric_left, metric_right = _ranks(left), _ranks(right)
                expected_ic[key] = (None, _correlation(metric_left, metric_right))
    assert degeneracy_witnesses, "the fixed fixture must contain a degenerate IC witness"

    research = ResearchSpec(
        grid=pd.DataFrame({"open_time": times - pd.Timedelta(hours=6)}, index=times),
        start=times[_WINDOW_START],
        end=times[_WINDOW_END],
        targets=assets,
        source_timezone="UTC",
        feed_time_kind="close_time",
        snapshot_id="installed-alpha101-twenty-independent-v1",
        price_basis="synthetic-unadjusted-USD",
        calendar_id="synthetic-daily-v1",
        frequency="1session",
        classifications=reference._classification_tables(frames),
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
        "alpha%d" % number: reference._factor_spec("alpha%d" % number, indicator)
        for number, indicator in REPRESENTATIVE_FACTORS.items()
    }
    cerebro.addstrategy(FactorStrategy, research=research, factors=factors)
    strategy = cerebro.run()[0]
    assert (broker.submits, broker.cancels) == (0, 0)
    collected = strategy.get_dataset()
    snapshot = tmp_path / "dataset"
    collected.save(snapshot)
    dataset = load_dataset(snapshot)
    assert dataset.dataset_id == collected.dataset_id
    calls_before = {
        name: factor.lifecycle_diagnostics for name, factor in strategy.factor_instances.items()
    }
    result = dataset.evaluate(
        label="next_open_to_open",
        periods=(1,),
        min_assets=2,
        quantiles=2,
        min_quantile_assets=1,
        stability_lags=(1,),
        max_loss=1.0,
    )
    assert calls_before == {
        name: factor.lifecycle_diagnostics for name, factor in strategy.factor_instances.items()
    }
    assert result.manifest["dataset_id"] == dataset.dataset_id
    assert set(result.labels["horizon"]) == {1}
    expected_label_keys = set(label_values)
    actual_label_keys = [(pd.Timestamp(row.time), row.asset) for row in result.labels.itertuples()]
    assert len(actual_label_keys) == len(set(actual_label_keys))
    assert set(actual_label_keys) == expected_label_keys
    assert len(result.labels) == len(window_offsets) * len(assets)
    for row in result.labels.itertuples():
        expected = label_values[(pd.Timestamp(row.time), row.asset)]
        assert row.value == pytest.approx(expected, rel=1e-12, abs=1e-12)

    ic = result.ic.loc[(result.ic.record_type == "period") & (result.ic.variant == "raw")]
    expected_all_ic_keys = {
        ("alpha%d" % number, pd.Timestamp(times[offset]), metric)
        for number in REPRESENTATIVE_FACTORS
        for offset in window_offsets
        for metric in _IC_METRICS
    }
    actual_all_ic_keys = [
        (row.signal, pd.Timestamp(row.time), row.metric) for row in ic.itertuples()
    ]
    assert len(actual_all_ic_keys) == len(set(actual_all_ic_keys))
    assert set(actual_all_ic_keys) == expected_all_ic_keys
    assert len(ic) == len(REPRESENTATIVE_FACTORS) * len(window_offsets) * len(_IC_METRICS)
    report = {}
    total_degeneracies = 0
    for number in REPRESENTATIVE_FACTORS:
        name = "alpha%d" % number
        wanted = oracle_by_name[name]
        observed = (
            dataset.raw_factors[name].unstack("asset").reindex(index=window_times, columns=assets)
        )
        expected = [wanted[offset] for offset in window_offsets]
        reference._assert_matrix(observed.to_numpy().tolist(), expected, assets, label=name)
        finite_count = sum(math.isfinite(value) for row in expected for value in row)
        assert finite_count > 0, name  # checked before Cerebro as well
        rows = ic.loc[ic.signal == name]
        actual_ic_keys = [(pd.Timestamp(row.time), row.metric) for row in rows.itertuples()]
        expected_ic_keys = {
            (pd.Timestamp(times[offset]), metric)
            for offset in window_offsets
            for metric in _IC_METRICS
        }
        assert len(actual_ic_keys) == len(set(actual_ic_keys)), name
        assert set(actual_ic_keys) == expected_ic_keys, name
        assert len(rows) == len(window_offsets) * len(_IC_METRICS), name
        usable = degenerate = 0
        for row in rows.itertuples():
            key = (name, pd.Timestamp(row.time), row.metric)
            expected_reason, expected_value = expected_ic[key]
            if expected_reason is not None:
                assert pd.isna(row.value) and row.status == "UNEVALUABLE"
                assert row.reason == expected_reason
                degenerate += 1
                continue
            assert row.metric in _IC_METRICS
            assert math.isfinite(row.value)
            assert pd.isna(row.reason)
            assert expected_value is not None
            assert abs(row.value - expected_value) <= 1e-12 + 1e-10 * abs(expected_value)
            usable += 1
        total_degeneracies += degenerate
        report[name] = {
            "finite_factor_cells": finite_count,
            "verified_ic": usable,
            "verified_degeneracies": degenerate,
        }
    assert len(report) == 20
    assert total_degeneracies > 0
    result.export(tmp_path / "evaluation", charts=False)
    (tmp_path / "installed-acceptance.json").write_text(
        json.dumps(
            {
                "origins": origins,
                "dataset_id": dataset.dataset_id,
                "result_status": result.status,
                "broker_submits": broker.submits,
                "broker_cancels": broker.cancels,
                "formulas": report,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
