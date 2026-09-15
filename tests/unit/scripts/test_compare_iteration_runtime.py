"""Regression coverage for the position-balanced runtime comparator."""

import pytest

from scripts.ci import compare_iteration_runtime as runtime


def test_nine_round_schedule_is_deterministic_and_balances_each_position():
    first = runtime.build_crossover_orders(9)
    second = runtime.build_crossover_orders(9)

    assert first == second
    assert len(set(first[:6])) == 6
    assert set(first[:6]) == set(runtime.BALANCED_CROSSOVER_ORDERS)

    coverage = runtime.summarize_position_coverage(first)
    assert coverage["exactly_balanced"]
    assert coverage["recommended_coverage_met"]
    for source in runtime.SOURCES:
        assert coverage["source_position_counts"][source] == {"1": 3, "2": 3, "3": 3}


@pytest.mark.parametrize("pairs", [0, 1, 2])
def test_schedule_rejects_insufficient_rounds_to_cover_all_positions(pairs):
    with pytest.raises(ValueError, match="at least 3"):
        runtime.build_crossover_orders(pairs)


def test_actual_position_coverage_tracks_partial_execution_records():
    entries = _execution_order(runtime.build_crossover_orders(3))[:2]

    coverage = runtime.summarize_execution_position_coverage(entries)

    assert coverage["completed_execution_records"] == 2
    assert not coverage["all_positions_covered"]
    assert not coverage["gate_eligible"]
    assert coverage["source_position_counts"]["pre28"] == {"1": 1, "2": 0, "3": 0}
    assert coverage["source_position_counts"]["pre29"] == {"1": 0, "2": 1, "3": 0}
    assert coverage["source_position_counts"]["candidate"] == {"1": 0, "2": 0, "3": 0}


def _position_only_samples(orders):
    """Make all sources equal at a position while positions have large bias."""
    raw = {source: [] for source in runtime.SOURCES}
    for round_number, order in enumerate(orders, start=1):
        for position, source in enumerate(order, start=1):
            raw[source].append(
                {
                    "round": round_number,
                    "position": position,
                    "order": list(order),
                    # Position alone determines the duration: source code is
                    # identical, so a valid gate must report zero regression.
                    "samples_s": {"load": float(2**position)},
                    "results": {"load": "same"},
                }
            )
    return raw


def _execution_order(orders):
    return [
        {
            "round": round_number,
            "position": position,
            "source": source,
            "order": list(order),
        }
        for round_number, order in enumerate(orders, start=1)
        for position, source in enumerate(order, start=1)
    ]


def test_position_stratified_gate_removes_constructed_position_only_bias():
    orders = runtime.build_crossover_orders(9)
    raw = _position_only_samples(orders)
    execution_order = _execution_order(orders)
    positions = runtime.execution_position_maps(execution_order)
    for rows in raw.values():
        for row in rows:
            row.pop("round")
            row.pop("position")
            row.pop("order")

    comparison = runtime.compare_load_by_position(
        raw["pre29"],
        raw["candidate"],
        "load",
        baseline_positions=positions["pre29"],
        candidate_positions=positions["candidate"],
    )

    # The legacy within-round comparison crosses execution positions and is
    # deliberately biased here.  It remains in the report as a diagnostic.
    assert comparison["median_delta"] != 0
    assert comparison["unadjusted_paired_median_delta"] == comparison["median_delta"]
    assert not comparison["unadjusted_paired_within_5_percent"]

    # The gate compares like-for-like positions, so it cancels the constructed
    # position effect without changing the 5% regression threshold.
    assert comparison["gate"]["method"] == "median_of_position_median_ratios"
    assert comparison["gate"]["median_ratio"] == 1
    assert comparison["gate"]["median_delta"] == 0
    assert comparison["gate_median_delta"] == 0
    assert comparison["within_5_percent"]
    assert all(stratum["median_delta"] == 0 for stratum in comparison["gate"]["strata"])


def test_source_snapshot_manifest_is_content_bound_and_rejects_bytecode(tmp_path):
    source = tmp_path
    package = source / "backtrader"
    package.mkdir()
    (package / "__init__.py").write_text("VERSION = 'one'\n")
    (package / "module.py").write_text("VALUE = 1\n")

    before = runtime.source_snapshot_manifest(source)
    (package / "module.py").write_text("VALUE = 2\n")
    after = runtime.source_snapshot_manifest(source)

    assert before["file_count"] == 2
    assert before["cache_artifacts"] == []
    assert before["snapshot_root"] == str(source)
    assert before["package_path"] == str(package)
    assert before["tree_sha256"] != after["tree_sha256"]

    cache = package / "__pycache__"
    cache.mkdir()
    (cache / "module.cpython-311.pyc").write_bytes(b"not a real cache")
    with pytest.raises(ValueError, match="bytecode cache artifacts"):
        runtime.source_snapshot_manifest(source)


def test_source_environment_forces_cache_free_deterministic_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPYCACHEPREFIX", "/tmp/unrelated-cache")
    monkeypatch.setenv("PYTHONHOME", "/tmp/unrelated-home")
    environment = runtime.source_environment(tmp_path)

    assert environment["PYTHONPATH"] == str(tmp_path)
    assert "PYTHONPYCACHEPREFIX" not in environment
    assert "PYTHONHOME" not in environment
    assert {
        key: environment[key] for key in runtime.RUNTIME_ENVIRONMENT
    } == runtime.RUNTIME_ENVIRONMENT


def test_is_within_is_python_38_compatible_relative_path_check(tmp_path):
    root = tmp_path / "root"
    child = root / "child" / "module.py"
    other = tmp_path / "other.py"
    child.parent.mkdir(parents=True)
    child.touch()
    other.touch()

    assert runtime.is_within(child, root)
    assert not runtime.is_within(other, root)


def test_cold_import_gate_is_exactly_position_balanced_and_stratified():
    orders = runtime.build_crossover_orders(runtime.COLD_IMPORT_ROUNDS)
    coverage = runtime.summarize_position_coverage(orders)
    raw = {source: [] for source in runtime.SOURCES}
    for order in orders:
        for position, source in enumerate(order, start=1):
            # Position, rather than source, determines the duration.  A
            # source-neutral candidate must therefore pass the stratified gate.
            raw[source].append(float(2**position))
    positions = runtime.execution_position_maps(_execution_order(orders))

    comparison = runtime.compare_cold_import_by_position(
        raw["pre29"],
        raw["candidate"],
        baseline_positions=positions["pre29"],
        candidate_positions=positions["candidate"],
    )

    assert coverage["exactly_balanced"]
    assert coverage["source_position_counts"]["candidate"] == {"1": 4, "2": 4, "3": 4}
    assert comparison["status"] == "PASS"
    assert comparison["median_delta_s"] == 0
    assert comparison["within_budget"]


def test_probe_harness_manifest_binds_probe_and_shared_fixture(tmp_path):
    harness = tmp_path / "harness"
    probe = harness / "scripts" / "iter28_perf_probe.py"
    fixture = harness / "tests" / "datas" / "2006-day-001.txt"
    probe.parent.mkdir(parents=True)
    fixture.parent.mkdir(parents=True)
    probe.write_text("LOADS = {}\n")
    fixture.write_text("date,open\n")

    before = runtime.probe_harness_manifest(probe)
    fixture.write_text("date,open\n2006-01-01,1\n")
    after = runtime.probe_harness_manifest(probe)

    assert before["harness_root"] == str(harness)
    assert before["probe"]["sha256"] == after["probe"]["sha256"]
    assert before["fixture"]["sha256"] != after["fixture"]["sha256"]


def test_release_gate_fails_closed_for_a_runtime_or_cold_regression():
    report = {
        "source_snapshots": {"unchanged": True},
        "probe_harness": {"unchanged": True},
        "comparator": {"unchanged": True},
        "position_balance": {"recommended_coverage_met": True},
        "comparisons": {
            "pre28": {
                "load": {"within_5_percent": True},
                "rss": {"within_budget": True},
            },
            "pre29": {
                "load": {"within_5_percent": True},
                "rss": {"within_budget": True},
            },
        },
        "cold_import": {
            "default": {
                "position_balance": {"exactly_balanced": True},
                "within_budget": {"pre28": True, "pre29": True},
            },
            "light": {
                "position_balance": {"exactly_balanced": True},
                "within_budget": {"pre28": True, "pre29": True},
            },
        },
    }

    assert runtime.release_gate_status(report) == {"status": "PASS", "failures": []}

    report["comparisons"]["pre29"]["load"]["within_5_percent"] = False
    report["cold_import"]["light"]["within_budget"]["pre28"] = False
    failure = runtime.release_gate_status(report)

    assert failure["status"] == "FAIL"
    assert failure["failures"] == ["pre29.load", "cold_import.light.pre28"]
