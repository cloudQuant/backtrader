"""Small input-manifest contracts for the DIAGNOSTIC_ONLY pipeline tool."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.diagnose_factor_research_pipeline import (
    DIAGNOSTIC_CLASS,
    _Observer,
    _compare_input_window_contracts,
    _compare_scaling_workloads,
    _input_manifest,
    _load_stage_benchmark,
    _operator_profile_summary,
    _observe_research_window,
    _install_observers,
    _parser,
    _report_profile_summary,
    _group_members,
    _scaling_field_binding,
    _scaling_field_name,
    _scaling_group_assignments,
    _single_worker_example,
    _supports_current_stage,
)


def test_input_manifest_hashes_the_evenly_sampled_symbol_inputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "daily"
    metadata = data_dir / "_metadata"
    metadata.mkdir(parents=True)
    entries = []
    for symbol in ("AAA", "BBB", "CCC", "DDD"):
        relative = "%s.csv" % symbol
        (data_dir / relative).write_text("trade_time,close\n2024-01-02,1\n", encoding="utf-8")
        entries.append({"symbol": symbol, "file": relative})
    (metadata / "manifest.json").write_text(
        json.dumps({"output": {"symbols": entries}}),
        encoding="utf-8",
    )
    (metadata / "observed_calendar.csv").write_text(
        "first_trade_time,last_trade_time\n2024-01-02,2024-01-02\n2024-01-03,2024-01-03\n",
        encoding="utf-8",
    )

    inventory = _input_manifest(data_dir, 2)

    assert inventory["requested_symbols"] == 2
    assert inventory["selected_symbols"] == ["AAA", "CCC"]
    assert inventory["calendar_rows"] == 2
    assert set(inventory["selected_symbol_file_sha256"]) == {"AAA", "CCC"}
    assert len(inventory["manifest_sha256"]) == 64
    assert len(inventory["calendar_sha256"]) == 64
    assert DIAGNOSTIC_CLASS == "DIAGNOSTIC_ONLY"


def test_observer_labels_source_paths_relative_to_the_measured_root(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    observer = _Observer(root)

    assert observer.source_tag(str(root / "backtrader" / "research" / "sink.py")) == (
        "backtrader/research/sink.py"
    )


def test_observer_counts_research_pandas_copy_requests_and_restores_methods() -> None:
    import pandas as pd

    from backtrader.research import ResearchSpec
    from backtrader.research.fincore_adapter import _canonicalize_evaluation_index
    from backtrader.research.panel import _shallow_copy_frame

    root = Path(__file__).resolve().parents[2]
    observer = _Observer(root)
    original_dataframe_copy = pd.DataFrame.copy
    original_series_copy = pd.Series.copy
    _install_observers(root, observer)
    try:
        timestamps = pd.date_range("2025-01-02", periods=2, freq="D", tz="UTC", name="close_time")
        grid = pd.DataFrame({"open_time": timestamps - pd.Timedelta(hours=1)}, index=timestamps)
        universe_index = pd.MultiIndex.from_product([timestamps, ("AAA",)], names=("time", "asset"))
        universe = pd.Series(True, index=universe_index, name="universe")
        research = ResearchSpec(
            grid=grid,
            start=timestamps[0],
            end=timestamps[-1],
            targets=("AAA",),
            source_timezone="Asia/Shanghai",
            snapshot_id="copy-test",
            price_basis="adjusted_close",
            calendar_id="copy-test-calendar",
            frequency="1d",
            groups={"AAA": "fixture"},
            universe=universe,
        )
        _ = research.grid
        _ = research.universe
        _shallow_copy_frame(pd.DataFrame({"value": [1.0]}))
        _canonicalize_evaluation_index(
            pd.Series([1.0], index=pd.date_range("2025-01-02", periods=1, tz="UTC")),
            pd,
            copy=True,
        )
    finally:
        observer.restore()

    assert pd.DataFrame.copy is original_dataframe_copy
    assert pd.Series.copy is original_series_copy
    calls = observer.metrics["pandas_calls"]
    assert calls["dataframe_copy_by_source_and_depth"]["deep"]["backtrader/research/specs.py"] >= 2
    assert (
        calls["dataframe_copy_by_source_and_depth"]["shallow"]["backtrader/research/panel.py"] >= 1
    )
    assert calls["series_copy_by_source_and_depth"]["deep"]["backtrader/research/specs.py"] >= 2
    assert (
        calls["series_copy_by_source_and_depth"]["shallow"][
            "backtrader/research/fincore_adapter.py"
        ]
        >= 1
    )
    assert "not byte-copy or allocation counts" in calls["copy_measurement_semantics"]


def test_runtime_window_observer_records_actual_grid_and_research_bounds(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    observer = _Observer(root)
    research = SimpleNamespace(
        grid=SimpleNamespace(index=["grid-start", "grid-end"]),
        start="research-start",
        end="research-end",
        targets=("AAA", "BBB"),
    )
    stage = SimpleNamespace(_research_spec=lambda *args, **kwargs: research)
    _observe_research_window(stage, observer)

    assert stage._research_spec() is research
    assert observer.metrics["runtime_window"] == {
        "grid_rows": 2,
        "grid_start": "grid-start",
        "grid_end": "grid-end",
        "research_start": "research-start",
        "research_end": "research-end",
        "target_count": 2,
        "targets": ["AAA", "BBB"],
    }
    observer.restore()


def test_side_comparison_requires_same_inputs_window_and_factor_names() -> None:
    runtime_window = {
        "grid_rows": 243,
        "grid_start": "grid-start",
        "grid_end": "grid-end",
        "research_start": "start",
        "research_end": "end",
        "target_count": 2,
        "targets": ["AAA", "BBB"],
    }
    input_manifest = {
        "manifest_sha256": "a" * 64,
        "calendar_sha256": "b" * 64,
        "selected_symbol_file_sha256": {"AAA": "c" * 64, "BBB": "d" * 64},
    }
    baseline = {
        "input_manifest": input_manifest,
        "observers": {
            "runtime_window": runtime_window,
            "factor_spec_configuration": {"factor_names": ["close_ma"]},
        },
    }
    candidate = {
        "input_manifest": input_manifest,
        "observers": {
            "runtime_window": dict(runtime_window),
            "factor_spec_configuration": {"factor_names": ["close_ma"]},
        },
    }

    assert _compare_input_window_contracts(baseline, candidate)["all_match"] is True
    candidate["observers"]["runtime_window"]["research_end"] = "different-end"
    assert _compare_input_window_contracts(baseline, candidate)["all_match"] is False
    del candidate["observers"]["runtime_window"]["grid_start"]
    comparison = _compare_input_window_contracts(baseline, candidate)
    assert comparison["checks"]["candidate_evidence_present"] is False
    assert comparison["all_match"] is False


def test_worker_parser_keeps_append_example_as_a_single_item_list() -> None:
    args = _parser().parse_args(
        [
            "--mode",
            "stage",
            "--_worker",
            "--root",
            "/checkout",
            "--work-dir",
            "/tmp/job",
            "--example",
            "025",
        ]
    )

    assert args.example == ["025"]
    assert _single_worker_example(args.example) == "025"


def test_worker_example_requires_exactly_one_append_value() -> None:
    for value in (None, [], ["025", "026"], ["not-an-example"]):
        try:
            _single_worker_example(value)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid worker example value was accepted: %r" % (value,))


def test_scaling_workload_counterproof_has_alternating_bindings_and_fixed_groups() -> None:
    targets = ["ASSET_%02d" % index for index in range(20)]

    bindings_by_count = {
        count: [_scaling_field_binding(index) for index in range(count)] for count in (1, 3, 10)
    }
    groups = _scaling_group_assignments(targets)
    members = _group_members(groups)

    assert bindings_by_count == {
        1: [{"close": "feed:target:close"}],
        3: [
            {"close": "feed:target:close"},
            {"close": "feed:target:open"},
            {"close": "feed:target:close"},
        ],
        10: [
            {"close": "feed:target:close"},
            {"close": "feed:target:open"},
            {"close": "feed:target:close"},
            {"close": "feed:target:open"},
            {"close": "feed:target:close"},
            {"close": "feed:target:open"},
            {"close": "feed:target:close"},
            {"close": "feed:target:open"},
            {"close": "feed:target:close"},
            {"close": "feed:target:open"},
        ],
    }
    assert groups == {
        target: "scale_a" if index < 10 else "scale_b" for index, target in enumerate(targets)
    }
    assert members == {
        "scale_a": targets[:10],
        "scale_b": targets[10:],
    }


def test_scaling_group_contract_rejects_non_fixed_universe_size() -> None:
    try:
        _scaling_group_assignments(["ASSET_01"])
    except ValueError as exc:
        assert "exactly 20 targets" in str(exc)
    else:
        raise AssertionError("scaling accepted a non-20-asset group layout")


def test_scaling_comparison_requires_identical_inputs_groups_and_actual_counts() -> None:
    targets = ["ASSET_%02d" % index for index in range(20)]
    groups = _scaling_group_assignments(targets)
    members = _group_members(groups)
    input_manifest = {
        "manifest_sha256": "a" * 64,
        "calendar_sha256": "b" * 64,
        "selected_symbol_file_sha256": dict.fromkeys(targets, "c" * 64),
    }
    runs = []
    for count in (1, 3, 10):
        factor_names = [
            "%s_ma_%02d" % (_scaling_field_name(index), index + 1) for index in range(count)
        ]
        bindings = {name: _scaling_field_binding(index) for index, name in enumerate(factor_names)}
        runs.append(
            {
                "mode": "scaling",
                "factor_count": count,
                "status": "OK",
                "worker_returncode": 0,
                "input_manifest": input_manifest,
                "scaling_workload": {
                    "fixed_input_targets": targets,
                    "groups_by_target": groups,
                    "group_members": members,
                    "factor_names": factor_names,
                    "factor_bindings": bindings,
                    "actual_instances_after_run": {
                        "observed_after_run": True,
                        "factor_instance_count": count * 2,
                    },
                },
            }
        )

    serialized_runs = json.dumps(runs, sort_keys=True)
    reloaded_runs = json.loads(serialized_runs)
    assert _compare_scaling_workloads(reloaded_runs, (1, 3, 10))["all_match"] is True

    wrong_binding = json.loads(serialized_runs)
    wrong_binding[1]["scaling_workload"]["factor_bindings"]["open_ma_02"][
        "close"
    ] = "feed:target:close"
    comparison = _compare_scaling_workloads(wrong_binding, (1, 3, 10))
    assert comparison["per_profile_contracts"]["3"]["alternating_binding_order_matches"] is False
    assert comparison["all_match"] is False

    wrong_order = json.loads(serialized_runs)
    wrong_order[2]["scaling_workload"]["factor_names"][:2] = list(
        reversed(wrong_order[2]["scaling_workload"]["factor_names"][:2])
    )
    comparison = _compare_scaling_workloads(wrong_order, (1, 3, 10))
    assert (
        comparison["per_profile_contracts"]["10"]["factor_names_complete_unique_and_ordered"]
        is False
    )
    assert comparison["all_match"] is False

    wrong_groups = json.loads(serialized_runs)
    wrong_groups[1]["scaling_workload"]["group_members"] = {
        "scale_a": targets[:9],
        "scale_b": targets[9:],
    }
    comparison = _compare_scaling_workloads(wrong_groups, (1, 3, 10))
    assert comparison["checks"]["same_two_group_assignment"] is False
    assert comparison["all_match"] is False


def test_current_stage_detection_uses_research_api_without_scripts_directory(
    tmp_path: Path,
) -> None:
    research_dir = tmp_path / "backtrader" / "research"
    research_dir.mkdir(parents=True)
    for name in ("align.py", "panel.py"):
        (research_dir / name).write_text("# fixture\n", encoding="utf-8")
    assert not _supports_current_stage(tmp_path)

    (research_dir / "sink.py").write_text("# fixture\n", encoding="utf-8")
    assert _supports_current_stage(tmp_path)
    assert not (tmp_path / "scripts").exists()


def test_stage_benchmark_is_loaded_from_host_and_bound_to_selected_root(tmp_path: Path) -> None:
    module = _load_stage_benchmark(tmp_path)

    assert tmp_path.resolve() == module.REPO_ROOT
    assert module.EXAMPLES["025"] == (tmp_path / "examples" / "backtest" / "025_factor_single")


def test_operator_profile_keeps_only_selected_functions_from_operators_module(
    tmp_path: Path,
) -> None:
    operator_file = tmp_path / "backtrader" / "research" / "operators.py"
    operator_file.parent.mkdir(parents=True)
    stats = {
        (str(operator_file), 160, "_read_window"): (2, 7, 0.25, 0.5, {}),
        (str(operator_file), 478, "_evaluate"): (1, 3, 0.1, 0.4, {}),
        (str(tmp_path / "other.py"), 12, "_evaluate"): (1, 99, 1.0, 2.0, {}),
        (str(operator_file), 20, "unrelated"): (1, 42, 2.0, 3.0, {}),
    }

    profile = _operator_profile_summary(stats, operator_file)

    assert profile["by_function"] == {
        "_read_window": {"ncalls": 7, "tottime_s": 0.25, "cumtime_s": 0.5},
        "_evaluate": {"ncalls": 3, "tottime_s": 0.1, "cumtime_s": 0.4},
    }
    assert len(profile["rows"]) == 2


def test_report_profile_groups_only_fincore_label_weight_and_position_functions() -> None:
    stats = {
        ("/venv/site-packages/fincore/labels.py", 10, "build_labels"): (1, 4, 0.1, 0.2, {}),
        ("/venv/site-packages/fincore/weights.py", 20, "normalize_weights"): (1, 5, 0.2, 0.3, {}),
        ("/venv/site-packages/fincore/positions.py", 30, "make_positions"): (1, 6, 0.3, 0.4, {}),
        ("/venv/site-packages/fincore/report.py", 40, "render_html"): (1, 7, 0.4, 0.5, {}),
        ("/app/backtrader/report.py", 50, "build_labels"): (1, 8, 0.5, 0.6, {}),
    }

    profile = _report_profile_summary(stats)

    assert profile["by_category"]["labels"]["build_labels"]["ncalls"] == 4
    assert profile["by_category"]["weights"]["normalize_weights"]["ncalls"] == 5
    assert profile["by_category"]["positions"]["make_positions"]["ncalls"] == 6
    assert len(profile["rows"]) == 3


def test_operators_mode_does_not_require_a_market_data_directory() -> None:
    args = _parser().parse_args(
        ["--mode", "operators", "--root", "/checkout", "--output", "/tmp/result"]
    )

    assert args.data_dir is None
    assert args.profile_report is False


def test_legacy_source_without_stage_script_is_routed_to_legacy_entry(tmp_path: Path) -> None:
    root = tmp_path / "archive"
    (root / "backtrader" / "research").mkdir(parents=True)
    (root / "backtrader" / "__init__.py").write_text("", encoding="utf-8")
    for name in ("dataset.py", "inputs.py", "storage.py"):
        (root / "backtrader" / "research" / name).write_text("# legacy API\n", encoding="utf-8")

    assert _supports_current_stage(root) is False
