"""CLI smoke and fail-closed contracts for the Iteration 50 long-stream tool."""

from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_ROOT / "scripts" / "run_iteration50_live_factor_benchmark.py"


def _load_benchmark_module():
    spec = importlib.util.spec_from_file_location("iteration50_live_factor_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", ("native", "build"))
def test_live_alpha003_smoke_runs_real_composition_and_writes_bounded_noop_evidence(tmp_path, mode):
    output = tmp_path / (mode + ".json")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("BT_BENCHMARK_SOURCE_REVISION", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            mode,
            "--smoke",
            "--warmup-bars",
            "64",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert output.is_file()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["evidence_level"] == "COMPOSITION_SYNTHETIC_SOURCE_STREAM_ONLY"
    assert report["formal_acceptance_claimed"] is False
    assert report["account_or_execution_claimed"] is False
    assert report["profile"]["mode"] == mode
    assert report["profile"]["target_count"] == 20
    assert report["profile"]["evaluation_grids"] == 24
    assert report["profile"]["warmup_bars"] == 64
    assert report["source"]["full_event_tape_materialized"] is False
    assert report["source"]["all_output_arrays_materialized"] is False
    assert report["source"]["raw_numeric_fields"] == [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
    ]
    assert report["source"]["factor_extra_line_fields"] == []
    assert (
        report["source"]["line_fields_registered_per_member"]
        == report["source"]["raw_numeric_fields"]
    )
    assert report["source"]["events_returned"] == 20 * (24 + 64)
    assert report["runtime"]["strategy_next_calls"] == 24 + 64
    assert report["oracle"]["finite_factor_values"] == 20 * 24
    assert report["oracle"]["open_rank_changed_grids"] > 0
    assert report["oracle"]["volume_rank_changed_grids"] > 0
    assert report["oracle"]["distinct_finite_factor_values"] >= 2
    assert report["oracle"]["rank_reason_failures"] == 0
    assert report["oracle"]["correlation_reason_failures"] == 0
    alpha003 = report["oracle"]["per_factor"]["alpha003"]
    assert alpha003["comparisons"] > 0
    assert alpha003["finite_factor_values"] == 20 * 24
    assert alpha003["distinct_finite_factor_values"] >= 2
    assert alpha003["output_reason_failures"] == 0
    assert alpha003["output_unavailable_grids"] == 0
    assert report["durable_noop_journal"]["noop_rows"] == 24
    assert report["durable_noop_journal"]["new_grid_rows"] == 24
    assert report["durable_noop_journal"]["cursor_ordinal"] == 24
    assert report["durable_noop_journal"]["intent_count"] == 0
    physical = report["durable_noop_journal"]["physical_db_wal_observation"]
    assert physical["sampling_interval_grids"] == 256
    assert physical["sample_count"] == 2
    assert physical["first_sample_grid_ordinal"] == 0
    assert physical["last_sample_grid_ordinal"] == 24
    assert (
        physical["sampled_high_water"]["physical_bytes"]
        >= physical["last_sample"]["physical_bytes"]
    )
    assert physical["physical_db_wal_capacity_enforced"] is False
    close_readback = report["durable_noop_journal"]["post_close_readback"]
    assert close_readback["passed"] is True
    assert close_readback["journal_mode_after_close"] == "wal"
    assert close_readback["synchronous_after_close"] == 2
    assert "maintenance connection" in close_readback["synchronous_after_close_scope"]
    assert close_readback["passive_checkpoint"]["mode"] == "PASSIVE"
    assert close_readback["passive_checkpoint"]["complete"] is True
    assert close_readback["physical_bytes_after_checkpoint"] == (
        close_readback["database_bytes_after_checkpoint"]
        + close_readback["wal_bytes_after_checkpoint"]
    )
    assert close_readback["reopen_succeeded"] is True
    assert close_readback["readback_matches_live_close"] is True
    assert close_readback["readback"]["capacity"]["base_record_count"] == 24
    assert close_readback["readback"]["cursor"]["ordinal"] == 24
    assert close_readback["readback"]["capacity"]["base_record_limit"] == 24
    assert report["cleanup"]["synthetic_store_close_returned"] is True
    assert report["latency"]["sample_count"] == 24
    assert math.isfinite(report["latency"]["max_ms"])
    assert math.isfinite(report["latency"]["p99_upper_bound_ms"])
    assert report["latency"]["max_ms"] <= 500
    assert report["latency"]["p99_upper_bound_ms"] <= 100
    phases = report["latency"]["monotonic_phases"]
    assert phases["first_member_available_to_last_member_available"]["sample_count"] == 24
    assert phases["last_member_available_to_factor_snapshot"]["sample_count"] == 24
    assert phases["record_grid_decision_call"]["sample_count"] == 24
    assert report["latency"]["source_clock_bar_close_to_available"]["max_ms"] == 0.0
    assert report["latency"]["rpc"] == {
        "called": False,
        "sample_count": 0,
        "latency_ms": None,
    }
    assert report["environment"]["python_version"]
    assert report["environment"]["os_system"]
    assert type(report["environment"]["logical_cpu_count"]) is int
    assert len(report["provenance"]["script_sha256"]) == 64
    assert len(report["provenance"]["input_generation_sha256"]) == 64
    assert report["provenance"]["actual_argv"]
    source_pins = report["provenance"]["loaded_backtrader_source_pins"]
    assert source_pins["pre_post_match"] is True
    assert source_pins["module_count"] == len(source_pins["pre_run"])
    assert source_pins["pre_run"] == source_pins["post_run"]
    assert source_pins["module_count"] >= 5
    assert all(len(pin["sha256"]) == 64 for pin in source_pins["pre_run"])
    assert any(
        pin["module"] == "backtrader.stores.execution_decision_journal"
        for pin in source_pins["pre_run"]
    )
    assert report["environment"]["source_revision"] is None
    assert report["memory"]["first_window_sample_count"] == report["memory"]["equal_window_samples"]
    assert report["memory"]["last_window_sample_count"] == report["memory"]["equal_window_samples"]
    assert report["memory"]["rss_sampling_method"]
    assert report["memory"]["rss_sampling_scope"] == "benchmark_process"
    assert report["memory"]["process_tree_peak_claimed"] is False
    assert report["memory"]["rss_samples_may_miss_transient_peaks"] is True
    assert report["capacities"]["configured_pending_slots"] == 1
    assert report["capacities"]["source_rows_retained_max"] == 20
    assert report["capacities"]["source_rows_retained_at_end"] == 0
    assert report["capacities"]["diagnostics_bounded"] is True
    first_lines = report["capacities"]["line_capacity_first"]
    last_lines = report["capacities"]["line_capacity_last"]
    assert first_lines["factor_instance_root_count"] == 1
    assert first_lines["owner_count"] > first_lines["factor_instance_root_count"]
    assert first_lines["owner_count"] == last_lines["owner_count"]
    assert first_lines["line_count"] == last_lines["line_count"]
    assert first_lines["value_line_count"] > 0
    assert first_lines["reason_line_count"] > 0
    assert first_lines["line_buffers_full"] is True
    assert first_lines["value_line_count"] == last_lines["value_line_count"]
    assert first_lines["reason_line_count"] == last_lines["reason_line_count"]
    assert last_lines["line_buffers_full"] is True
    assert report["capacities"]["line_capacity_grew_after_warmup"] is False
    assert report["capacities"]["retained_receipts_at_first_sample"] == 20 * 64
    assert report["capacities"]["retained_receipts_at_end"] == 20 * 64
    assert report["capacities"]["receipt_window_full_at_first_sample"] is True
    assert report["capacities"]["receipt_window_full_at_last_sample"] is True


@pytest.mark.parametrize("mode", ("native", "build"))
def test_live_27b_smoke_recovers_same_slot_and_runs_real_backbroker_order_lifecycle(
    tmp_path, mode
):
    output = tmp_path / ("27b-" + mode + ".json")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("BT_BENCHMARK_SOURCE_REVISION", None)
    environment["PYTHONUTF8"] = "1"
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            mode,
            "--factors",
            "representative-six",
            "--scenario",
            "27b",
            "--smoke",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["profile"]["scenario"] == "27b"
    assert report["profile"]["factor_names"] == [
        "alpha001",
        "alpha003",
        "alpha006",
        "alpha048",
        "alpha056",
        "alpha101",
    ]
    assert report["profile"]["warmup_bars"] == 316
    assert report["profile"]["evaluation_grids"] == 100
    assert report["formal_acceptance_claimed"] is False
    assert report["account_or_execution_claimed"] is False
    assert report["source"]["events_returned"] == 20 * (316 + 100)
    assert report["source"]["full_event_tape_materialized"] is False
    assert report["source"]["all_output_arrays_materialized"] is False
    assert report["oracle"]["tolerance"] == (
        "abs(actual-reference) <= 1e-12 + 1e-10*abs(reference)"
    )
    for name in report["profile"]["factor_names"]:
        witness = report["oracle"]["per_factor"][name]
        assert witness["comparisons"] > 0
        assert witness["finite_factor_values"] == 20 * 100
        assert witness["distinct_finite_factor_values"] >= 2
        assert witness["output_reason_failures"] == 0
        assert witness["output_unavailable_grids"] == 0

    recovery = report["runtime"]["source_recovery"]
    assert recovery["disconnect_observed"] is True
    assert recovery["resume_observed"] is True
    assert recovery["same_generation"] is True
    assert recovery["resume_generation"] == recovery["initial_generation"]
    assert recovery["resume_grid_index"] == recovery["disconnect_grid_index"]
    assert recovery["no_feed_strategy_or_factor_advance"] is True
    assert recovery["resume_barrier_observed"] is True
    assert recovery["resume_barrier_timed_out"] is False
    assert recovery["poll_calls_while_disconnected"] == 20
    assert recovery["member_poll_counts_while_disconnected"] == {
        "ASSET%02d" % index: 1 for index in range(20)
    }
    assert recovery["poll_rounds_while_disconnected"] == 1
    assert recovery["idle_callback_count"] >= 1
    assert recovery["wake_wait_count"] >= 1
    assert recovery["wake_wait_count_interrupted"] == 1
    assert math.isfinite(recovery["disconnect_to_recovery_ms"])
    assert recovery["disconnect_to_recovery_ms"] >= 0

    order = report["runtime"]["broker_order_lifecycle"]
    assert order["broker_class"] == "backtrader.brokers.bbroker.BackBroker"
    assert order["next_without_bar_capability"] is False
    assert {"Submitted", "Accepted", "Canceled"}.issubset(
        set(order["notified_statuses"])
    )
    assert order["submit_calls"] == 1
    assert order["cancel_calls"] == 1
    assert order["cancelled_during_idle"] is True
    assert order["final_status"] == "Canceled"
    assert order["executed_size"] == 0.0
    assert order["position_size"] == 0.0
    assert order["fill_notifications"] == 0
    assert report["runtime"]["source_gap_count"] == 0
    assert report["runtime"]["cohort_frozen"] is False
    assert report["soak_coverage"]["ac50_27b_ready"] is False
    assert report["soak_coverage"]["ac50_27b_formal_acceptance_claimed"] is False
    assert report["soak_coverage"]["full_group_rebuild_exercised"] is False
    assert report["soak_coverage"]["ac50_09_or_ac50_11_rebuild_claimed"] is False
    assert report["soak_coverage"]["ac50_25_disk_or_persistent_write_failure_exercised"] is False
    assert report["soak_coverage"]["backbroker_order_lifecycle_journaled_by_noop_decision"] is False
    assert report["durable_noop_journal"]["noop_rows"] == 100
    assert report["durable_noop_journal"]["intent_count"] == 0
    physical = report["durable_noop_journal"]["physical_db_wal_observation"]
    assert physical["sampling_interval_grids"] == 256
    assert physical["sample_count"] >= 2
    assert physical["first_sample"]["grid_ordinal"] == 0
    assert physical["last_sample_grid_ordinal"] == 100
    assert (
        physical["sampled_high_water"]["physical_bytes"]
        >= physical["last_sample"]["physical_bytes"]
    )
    assert physical["physical_db_wal_capacity_enforced"] is False
    close_readback = report["durable_noop_journal"]["post_close_readback"]
    assert close_readback["passed"] is True
    assert close_readback["journal_mode_after_close"] == "wal"
    assert close_readback["synchronous_after_close"] == 2
    assert close_readback["passive_checkpoint"]["mode"] == "PASSIVE"
    assert close_readback["passive_checkpoint"]["complete"] is True
    assert close_readback["reopen_succeeded"] is True
    assert close_readback["readback_matches_live_close"] is True
    assert close_readback["readback"]["capacity"]["base_record_count"] == 100
    assert close_readback["readback"]["cursor"]["ordinal"] == 100
    assert close_readback["readback"]["capacity"]["base_record_limit"] == 100
    assert report["cleanup"]["synthetic_store_close_returned"] is True


@pytest.mark.parametrize(
    "recovery_mode,expected_reason",
    (
        ("changed-generation", "connection_generation_changed"),
        ("missing-deadline", "planned_gap_requires_rebuild"),
    ),
)
def test_live_27b_negative_source_contracts_fail_closed_without_silent_continuation(
    tmp_path, recovery_mode, expected_reason
):
    output = tmp_path / (recovery_mode + ".json")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "native",
            "--factors",
            "representative-six",
            "--scenario",
            "27b",
            "--recovery-mode",
            recovery_mode,
            "--smoke",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )

    assert completed.returncode == 3, completed.stderr + completed.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert report["formal_acceptance_claimed"] is False
    assert report["account_or_execution_claimed"] is False
    assert report["diagnostics"]["cohort_frozen_reason"] == expected_reason
    recovery = report["runtime"]["source_recovery"]
    assert recovery["disconnect_observed"] is True
    assert recovery["no_feed_strategy_or_factor_advance"] is True
    assert recovery["resume_grid_index"] in (None, recovery["disconnect_grid_index"])
    expected_source_rows_before_fault = 20 * recovery["disconnect_grid_index"]
    if recovery_mode == "changed-generation":
        assert recovery["resume_observed"] is True
        assert recovery["same_generation"] is False
        # The first recovered row reaches the feed boundary, where the cohort
        # rejects the changed generation before publishing or advancing it.
        assert report["source"]["events_returned"] == expected_source_rows_before_fault + 1
        assert report["diagnostics"]["cohort_gaps"] == []
    else:
        assert recovery["resume_observed"] is False
        assert recovery["same_generation"] is True
        assert report["source"]["events_returned"] == expected_source_rows_before_fault
        assert report["diagnostics"]["cohort_gaps"] == [
            {
                "slot_index": recovery["disconnect_grid_index"],
                "slot_id": "grid-%06d" % recovery["disconnect_grid_index"],
                "missing_member_count": 20,
                "reason": "planned_slot_incomplete",
            }
        ]


def test_invalid_or_all_missing_profiles_cannot_report_pass(tmp_path):
    module = _load_benchmark_module()
    invalid_report = {
        "profile": {"total_grid_slots": 3, "evaluation_grids": 2},
        "runtime": {"strategy_next_calls": 3},
        "oracle": {
            "comparisons": 0,
            "finite_factor_values": 0,
            "distinct_finite_factor_values": 0,
        },
    }
    with pytest.raises(module.BenchmarkFailure, match="oracle_produced_no_comparisons"):
        module._require_positive_witnesses(invalid_report)

    output = tmp_path / "invalid-grid.json"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "native",
            "--grids",
            "0",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 2
    assert not output.exists()
    assert "evaluation_grid_count_out_of_range" in completed.stderr


def test_formal_grid_profile_requires_an_explicit_source_revision(tmp_path):
    module = _load_benchmark_module()
    args = module._parse_args(
        ["--mode", "native", "--grids", "100000", "--output", str(tmp_path / "formal.json")]
    )

    with pytest.raises(
        module.BenchmarkFailure, match="formal_source_revision_must_be_full_sha1_or_sha256"
    ):
        module._validate_cli(args)

    args = module._parse_args(
        [
            "--mode",
            "native",
            "--grids",
            "100000",
            "--source-revision",
            "a" * 40,
            "--output",
            str(tmp_path / "formal-with-revision.json"),
        ]
    )
    assert module._validate_cli(args)[0] == 100000


def test_malformed_source_revision_is_rejected_even_for_smoke(tmp_path):
    module = _load_benchmark_module()
    args = module._parse_args(
        [
            "--mode",
            "native",
            "--smoke",
            "--source-revision",
            "not-a-full-revision",
            "--output",
            str(tmp_path / "bad-revision.json"),
        ]
    )

    with pytest.raises(
        module.BenchmarkFailure, match="source_revision_must_be_full_sha1_or_sha256"
    ):
        module._validate_cli(args)


def test_prejournal_strategy_failure_preserves_original_error_and_closes_store(
    monkeypatch, tmp_path
):
    module = _load_benchmark_module()
    args = module._parse_args(
        ["--mode", "native", "--smoke", "--output", str(tmp_path / "prejournal.json")]
    )
    grids, warmup_bars, profile = module._validate_cli(args)
    original_make_runtime = module._make_runtime
    runtime_holder = {}
    close_calls = []

    def make_runtime(*runtime_args, **runtime_kwargs):
        runtime = original_make_runtime(*runtime_args, **runtime_kwargs)
        runtime_holder["runtime"] = runtime
        store = runtime[4]
        store_type = type(store)
        original_close = store_type.close

        def close_spy(instance, *close_args, **close_kwargs):
            if instance is store:
                close_calls.append(True)
            return original_close(instance, *close_args, **close_kwargs)

        monkeypatch.setattr(store_type, "close", close_spy)
        from backtrader.research.live import LiveFactorSet

        def fail_before_journal(cls, plan, datas, *, cohort):
            raise module.BenchmarkFailure("synthetic_prejournal_bind_failure")

        monkeypatch.setattr(LiveFactorSet, "bind", classmethod(fail_before_journal))
        return runtime

    monkeypatch.setattr(module, "_make_runtime", make_runtime)
    report, database_path = module._build_report(args, grids, warmup_bars, profile)

    assert report["status"] == "FAIL"
    assert report["gate_failures"][0] == "runtime_exception"
    assert "synthetic_prejournal_bind_failure" in report["gate_failures"][-1]
    assert "diagnostic_snapshot_error" not in report
    assert report["cleanup"]["journal_finalization"]["journal_initialized"] is False
    assert report["cleanup"]["journal_finalization"]["failure_codes"] == ["journal_not_initialized"]
    assert report["cleanup"]["synthetic_store_close_returned"] is True
    assert close_calls
    assert not database_path.exists()
    assert runtime_holder["runtime"][4].events_returned == 0


def test_alpha003_profile_does_not_require_deferred_feed_extra_lines():
    module = _load_benchmark_module()

    assert module._source_fields_for("alpha003") == (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
    )
    assert not set(module._source_fields_for("alpha003")).intersection(module.EXTRA_FACTOR_FIELDS)


def test_synthetic_store_waits_when_next_calendar_grid_is_polled_early(tmp_path):
    module = _load_benchmark_module()
    args = module._parse_args(
        ["--mode", "native", "--smoke", "--output", str(tmp_path / "prefetch.json")]
    )
    runtime = module._make_runtime(
        args,
        grids=2,
        warmup_bars=64,
        rss_sampler=None,
        selected_root=REPOSITORY_ROOT,
    )
    clock, store = runtime[3], runtime[4]
    targets = tuple(store.cursors)

    try:
        store.cursors[targets[0]] = 1
        with pytest.raises(
            module.BenchmarkFailure, match="feed_poll_escaped_current_calendar_grid"
        ):
            store.poll_live(targets[0])
        store.cursors[targets[0]] = 0

        for grid_index in range(2):
            assert clock.grid_index == grid_index
            events = [store.poll_live(target) for target in targets]
            assert len(events) == module.ASSET_COUNT
            assert all(event["bar_sequence"] == grid_index + 1 for event in events)
            assert len(store.current_rows) == module.ASSET_COUNT
            if grid_index == 0:
                store.finish_grid(grid_index)
                clock.advance_grid()

        rows_before_prefetch = dict(store.current_rows)
        arrivals_before_prefetch = dict(store.current_arrivals)
        cursor_before_prefetch = store.cursors[targets[0]]
        returned_before_prefetch = store.events_returned
        polls_before_prefetch = store.poll_calls

        assert clock.grid_index == 1
        assert cursor_before_prefetch == 2
        for prefetch_index in range(2):
            assert store.poll_live(targets[0]) is None
            assert store.poll_calls == polls_before_prefetch + prefetch_index + 1
            assert store.cursors[targets[0]] == cursor_before_prefetch
            assert store.events_returned == returned_before_prefetch
            assert store.current_grid_index == 1
            assert store.current_rows == rows_before_prefetch
            assert store.current_arrivals == arrivals_before_prefetch
        assert store.cursors[targets[0]] == cursor_before_prefetch

        store.finish_grid(1)
        clock.advance_grid()
        next_event = store.poll_live(targets[0])
        assert next_event["bar_sequence"] == 3
        assert store.cursors[targets[0]] == 3
        assert store.events_returned == returned_before_prefetch + 1

        store.cursors[targets[0]] = 4
        with pytest.raises(
            module.BenchmarkFailure, match="feed_poll_escaped_current_calendar_grid"
        ):
            store.poll_live(targets[0])

        store.cursors[targets[0]] = 1
        with pytest.raises(
            module.BenchmarkFailure, match="feed_poll_escaped_current_calendar_grid"
        ):
            store.poll_live(targets[0])
    finally:
        store.close()


def test_six_factor_streaming_oracle_has_finite_nontrivial_fixture_witnesses():
    module = _load_benchmark_module()
    targets = tuple("ASSET%02d" % index for index in range(module.ASSET_COUNT))
    oracle = module._StreamingFactorOracle(targets, module.FACTOR_IDS["representative-six"])
    finite_counts = dict.fromkeys(module.FACTOR_NAMES.values(), 0)
    distinct_values = {name: set() for name in finite_counts}
    total_grids = module.DEFAULT_SIX_FACTOR_WARMUP_BARS + 84

    for grid_index in range(total_grids):
        rows = {
            target: module._event_values(asset_index, grid_index)
            for asset_index, target in enumerate(targets)
        }
        outputs = oracle.update(rows)
        if grid_index < module.DEFAULT_SIX_FACTOR_WARMUP_BARS:
            continue
        for name in finite_counts:
            values = outputs[name]
            assert set(values) == set(targets)
            for value in values.values():
                assert math.isfinite(value)
                distinct_values[name].add(value)
            finite_counts[name] += len(values)

    for name in finite_counts:
        assert finite_counts[name] == 84 * module.ASSET_COUNT
        assert len(distinct_values[name]) >= 2


def test_existing_decision_database_is_rejected_before_benchmark_starts(tmp_path):
    output = tmp_path / "already-used.json"
    database = tmp_path / "already-used.decisions.sqlite3"
    sentinel = b"preserve-existing-journal"
    database.write_bytes(sentinel)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONUTF8"] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            "native",
            "--smoke",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 2
    assert not output.exists()
    assert database.read_bytes() == sentinel
    assert "decision_database_path_already_exists" in completed.stderr


def test_current_rss_sampler_uses_linux_proc_when_psutil_is_unavailable(monkeypatch):
    module = _load_benchmark_module()
    rss_sequence = iter((100, 1_000_000, 105))

    def missing_psutil():
        raise ImportError("psutil unavailable")

    monkeypatch.setattr(module, "_load_psutil_module", missing_psutil)
    monkeypatch.setattr(module, "_read_linux_proc_rss_bytes", lambda: next(rss_sequence))

    sampler = module._create_rss_sampler(platform_name="linux", os_name="posix")

    assert sampler.method == "Linux /proc/self/statm resident pages"
    assert [sampler.sample_bytes() for _ in range(3)] == [100, 1_000_000, 105]


def test_rss_sampler_fails_closed_without_psutil_or_supported_current_rss_api(monkeypatch):
    module = _load_benchmark_module()

    def missing_psutil():
        raise ImportError("psutil unavailable")

    monkeypatch.setattr(module, "_load_psutil_module", missing_psutil)

    with pytest.raises(module.BenchmarkFailure, match="rss_sampler_unavailable"):
        module._create_rss_sampler(platform_name="freebsd13", os_name="posix")


def test_rss_growth_uses_current_sample_window_medians_not_lifetime_peak():
    module = _load_benchmark_module()

    summary = module._rss_window_summary((100, 1_000_000, 100), (110, 110, 110))

    assert summary["first_window_median_rss_bytes"] == 100
    assert summary["last_window_median_rss_bytes"] == 110
    assert summary["rss_growth_bytes"] == 10
    assert summary["growth_pass"] is True


def test_rss_growth_fails_closed_when_current_sample_window_is_incomplete():
    module = _load_benchmark_module()

    summary = module._rss_window_summary((100,), ())

    assert summary["rss_growth_bytes"] is None
    assert summary["growth_pass"] is False


def _valid_gate_report():
    source_pin = {
        "module": "backtrader.strategy",
        "path": "strategy.py",
        "sha256": "c" * 64,
    }
    return {
        "profile": {
            "kind": "SMOKE_COMPOSITION",
            "factor_names": ["alpha003"],
            "total_grid_slots": 3,
            "evaluation_grids": 2,
            "warmup_bars": 1,
            "minimum_wall_clock_duration_seconds": 0,
        },
        "runtime": {"strategy_next_calls": 3, "warmup_complete_grids": 1},
        "oracle": {
            "comparisons": 1,
            "finite_factor_values": 2,
            "distinct_finite_factor_values": 2,
            "rank_reason_failures": 0,
            "correlation_reason_failures": 0,
            "per_factor": {
                "alpha003": {
                    "comparisons": 2,
                    "finite_factor_values": 2,
                    "distinct_finite_factor_values": 2,
                    "output_reason_failures": 0,
                    "output_unavailable_grids": 0,
                }
            },
        },
        "durable_noop_journal": {
            "noop_rows": 2,
            "new_grid_rows": 2,
            "cursor_ordinal": 2,
            "capacity_before": {
                "base_record_count": 0,
                "base_record_limit": 2,
                "base_payload_bytes": 0,
                "base_payload_byte_limit": 512 * 1024 * 1024,
                "settlement_record_count": 0,
                "settlement_record_limit": 4096,
                "settlement_payload_byte_limit": 64 * 1024 * 1024,
                "database_bytes": 0,
                "wal_bytes": 0,
                "physical_bytes": 0,
            },
            "capacity_after": {
                "base_record_count": 2,
                "base_record_limit": 2,
                "base_payload_bytes": 32,
                "base_payload_byte_limit": 512 * 1024 * 1024,
                "settlement_record_count": 0,
                "settlement_record_limit": 4096,
                "settlement_payload_byte_limit": 64 * 1024 * 1024,
                "database_bytes": 8192,
                "wal_bytes": 0,
                "physical_bytes": 8192,
            },
            "physical_db_wal_observation": {
                "sample_count": 2,
                "sampling_interval_grids": 256,
                "first_sample_grid_ordinal": 0,
                "last_sample_grid_ordinal": 2,
                "physical_db_wal_capacity_enforced": False,
                "sampled_high_water": {
                    "database_bytes": 8192,
                    "wal_bytes": 4096,
                    "physical_bytes": 12288,
                },
                "first_sample": {
                    "grid_ordinal": 0,
                    "database_bytes": 0,
                    "wal_bytes": 0,
                    "physical_bytes": 0,
                },
                "last_sample": {
                    "grid_ordinal": 2,
                    "database_bytes": 8192,
                    "wal_bytes": 4096,
                    "physical_bytes": 12288,
                },
            },
            "durability_configuration": {
                "journal_mode": "wal",
                "synchronous": 2,
                "full_synchronous_required": True,
            },
            "post_close_readback": {
                "journal_close_returned": True,
                "journal_closed": True,
                "journal_mode_after_close": "wal",
                "synchronous_after_close": 2,
                "passive_checkpoint": {
                    "mode": "PASSIVE",
                    "busy": 0,
                    "log_frames": 2,
                    "checkpointed_frames": 2,
                    "complete": True,
                },
                "reopen_succeeded": True,
                "readback_matches_live_close": True,
                "readback": {
                    "capacity": {
                        "base_record_count": 2,
                        "base_record_limit": 2,
                        "base_payload_byte_limit": 512 * 1024 * 1024,
                        "settlement_record_limit": 4096,
                        "settlement_payload_byte_limit": 64 * 1024 * 1024,
                    },
                    "cursor": {"ordinal": 2},
                    "intent_count": 0,
                },
                "passed": True,
                "failure_codes": [],
            },
        },
        "environment": {"source_revision": None},
        "provenance": {
            "loaded_backtrader_source_pins": {
                "pre_run": [source_pin],
                "post_run": [source_pin],
                "pre_post_match": True,
            }
        },
        "latency": {"sample_count": 2, "p99_upper_bound_ms": 1.0, "max_ms": 1.0},
        "memory": {
            "rss_sampling_method": "synthetic test reader for current RSS samples",
            "rss_sampling_scope": "benchmark_process",
            "process_tree_peak_claimed": False,
            "rss_samples_may_miss_transient_peaks": True,
            "rss_growth_bytes": 0,
            "rss_growth_limit_bytes": 32,
            "equal_window_samples": 1,
            "first_window_sample_count": 1,
            "last_window_sample_count": 1,
        },
        "capacities": {
            "configured_pending_slots": 1,
            "source_rows_retained_max": 20,
            "source_rows_retained_at_end": 0,
            "cohort_pending_slots_at_end": 0,
            "configured_window_bars_per_member": 64,
            "retained_receipts_at_end": 20,
            "retained_receipts_at_first_sample": 20,
            "receipt_window_full_at_first_sample": True,
            "receipt_window_full_at_last_sample": True,
            "line_capacity_grew_after_warmup": False,
            "line_buffers_full_at_first_sample": True,
            "line_buffers_full_at_last_sample": True,
            "line_capacity_first": {
                "owner_count": 1,
                "factor_instance_root_count": 1,
                "line_count": 1,
                "value_line_count": 1,
                "reason_line_count": 1,
                "line_buffers_full": True,
            },
            "line_capacity_last": {
                "owner_count": 1,
                "factor_instance_root_count": 1,
                "line_count": 1,
                "value_line_count": 1,
                "reason_line_count": 1,
                "line_buffers_full": True,
            },
            "physical_db_wal_capacity_enforced": False,
            "diagnostics_bounded": True,
            "factor_diagnostic_sample_capacity_max": 64,
            "factor_diagnostic_samples_retained_max": 1,
        },
        "elapsed_seconds": 0.0,
    }


@pytest.mark.parametrize(
    "field,value,expected_failure",
    (
        ("p99_upper_bound_ms", math.nan, "durable_decision_p99_latency_exceeded_100ms"),
        ("p99_upper_bound_ms", -0.1, "durable_decision_p99_latency_exceeded_100ms"),
        ("max_ms", math.nan, "durable_decision_max_latency_exceeded_500ms"),
        ("max_ms", -0.1, "durable_decision_max_latency_exceeded_500ms"),
    ),
)
def test_latency_gate_rejects_nonfinite_and_negative_values(field, value, expected_failure):
    module = _load_benchmark_module()
    report = _valid_gate_report()
    assert module._check_gates(report)[0] is True
    report["latency"][field] = value

    passed, failures = module._check_gates(report)

    assert passed is False
    assert expected_failure in failures


@pytest.mark.parametrize(
    "field,expected_failure",
    (
        ("rank_reason_failures", "rank_nodes_reported_reason_failures"),
        ("correlation_reason_failures", "correlation_nodes_reported_reason_failures"),
    ),
)
def test_reason_failures_are_a_hard_gate(field, expected_failure):
    module = _load_benchmark_module()
    report = _valid_gate_report()
    assert module._check_gates(report)[0] is True
    report["oracle"][field] = 1

    passed, failures = module._check_gates(report)

    assert passed is False
    assert expected_failure in failures


@pytest.mark.parametrize(
    "evidence_path,expected_failure",
    (
        (
            ("provenance", "loaded_backtrader_source_pins", "post_run"),
            "loaded_backtrader_source_pins_missing_or_changed",
        ),
        (
            ("durable_noop_journal", "physical_db_wal_observation"),
            "journal_physical_size_high_water_unobserved_or_invalid",
        ),
        (
            ("durable_noop_journal", "post_close_readback"),
            "journal_close_checkpoint_reopen_readback_failed",
        ),
    ),
)
def test_source_and_durable_storage_evidence_are_hard_gates(evidence_path, expected_failure):
    module = _load_benchmark_module()
    report = _valid_gate_report()
    assert module._check_gates(report)[0] is True
    target = report
    for key in evidence_path[:-1]:
        target = target[key]
    target.pop(evidence_path[-1])

    passed, failures = module._check_gates(report)

    assert passed is False
    assert expected_failure in failures


def test_formal_report_gate_requires_revision_even_when_source_pins_match():
    module = _load_benchmark_module()
    report = _valid_gate_report()
    report["profile"]["kind"] = "ACCELERATED_LONGSTREAM"

    passed, failures = module._check_gates(report)

    assert passed is False
    assert "formal_source_revision_missing_or_invalid" in failures
