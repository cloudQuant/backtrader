"""Regression coverage for the offline Iteration 41 writer-candidate collector."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "collect_iteration41_writer_inventory.py"


def _collector_module():
    name = "iteration41_writer_inventory_test_module"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_collector_reports_writer_and_dynamic_candidates_without_importing_fixture_code(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    fixture_dir = source_root / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "strategy.py").write_text(
        "import importlib\n"
        "import subprocess\n"
        "class Strategy:\n"
        "    def next(self):\n"
        "        self.buy()\n"
        "        self.store.cancel_order('order')\n"
        "        subprocess.run(['untrusted-command'])\n"
        "        importlib.import_module('untrusted.module')\n",
        encoding="utf-8",
    )
    (fixture_dir / "invalid.py").write_text("def invalid(:\n", encoding="utf-8")
    collector = _collector_module()

    report = collector.collect_inventory(source_root, ("fixture",))

    assert report["schema_version"] == collector.SCHEMA_VERSION
    assert report["status"] == "CANDIDATE_DISCOVERY_ONLY"
    assert report["counts"] == {
        "files_scanned": 2,
        "writer_candidates": 2,
        "dynamic_execution_candidates": 2,
        "parse_errors": 1,
    }
    assert [(row["method"], row["function_name"]) for row in report["writer_candidates"]] == [
        ("buy", "next"),
        ("cancel_order", "next"),
    ]
    assert [row["call"] for row in report["dynamic_execution_candidates"]] == [
        "subprocess.run",
        "importlib.import_module",
    ]
    assert report["parse_errors"] == [
        {"path": "fixture/invalid.py", "error_type": "SyntaxError", "line": 1}
    ]


def test_collector_cli_writes_a_deterministic_review_artifact(tmp_path: Path, capsys) -> None:
    source_root = tmp_path / "source"
    fixture_dir = source_root / "fixture"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "writer.py").write_text("api.submit_order({})\n", encoding="utf-8")
    output = tmp_path / "artifact" / "inventory.json"
    collector = _collector_module()

    status = collector.main(
        [
            "--source-root",
            str(source_root),
            "--output",
            str(output),
            "--include",
            "fixture",
        ]
    )

    assert status == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["status"] == "CANDIDATE_DISCOVERY_ONLY"
    assert stdout["source_path_coverage_status"] == "CUSTOM_SCOPE_NOT_CLASSIFIED"
    assert stdout["unclassified_paths"] == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source_root"] == "."
    assert payload["counts"]["writer_candidates"] == 1
    assert payload["writer_candidates"][0]["call"] == "api.submit_order"
    assert payload["writer_candidates"][0]["review_status"] == "REVIEW_REQUIRED"
    assert payload["source_path_coverage"]["status"] == "CUSTOM_SCOPE_NOT_CLASSIFIED"


def test_collector_rejects_scope_paths_that_escape_the_source_root(tmp_path: Path) -> None:
    collector = _collector_module()
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ValueError, match="must stay below source root"):
        collector.collect_inventory(root, ("../outside",))


def test_default_scope_includes_runtime_dispatch_and_p1b_mechanical_entrypoint() -> None:
    """New reviewed routes cannot silently fall outside the candidate inventory."""

    collector = _collector_module()

    assert "backtrader_runtime" in collector.DEFAULT_SCOPE_PATHS
    assert "examples/ctp_options_simnow_managed_replay_runtime.py" in collector.DEFAULT_SCOPE_PATHS


def test_new_example_directories_and_root_python_scripts_are_unclassified(
    tmp_path: Path,
) -> None:
    collector = _collector_module()
    source_root = tmp_path / "source"
    (source_root / "examples" / "known").mkdir(parents=True)
    (source_root / "examples" / "new-example" / "nested").mkdir(parents=True)
    (source_root / "examples" / "known" / "__pycache__").mkdir()
    (source_root / "known_script.py").write_text("pass\n", encoding="utf-8")
    (source_root / "new_script.py").write_text("pass\n", encoding="utf-8")
    baseline = {
        "examples/known": {
            "kind": "example_directory",
            "classification": "EXAMPLE_SUBDIRECTORY_STATIC_SCAN",
        },
        "known_script.py": {
            "kind": "repository_root_python_script",
            "classification": "REPOSITORY_ROOT_PYTHON_STATIC_SCAN",
        },
    }

    coverage = collector.classify_repository_surface(source_root, baseline)

    assert coverage["status"] == "UNCLASSIFIED_PATHS_PRESENT"
    assert {
        row["path"] for row in coverage["unclassified_paths"]
    } == {"examples/new-example", "examples/new-example/nested", "new_script.py"}
    assert all(
        row["candidate_kind"] == "unclassified_source_path"
        and row["review_status"] == "REVIEW_REQUIRED"
        for row in coverage["unclassified_paths"]
    )
    cache = next(row for row in coverage["paths"] if row["path"] == "examples/known/__pycache__")
    assert cache["classification"] == "GENERATED_PYTHON_CACHE"


def test_generated_logs_and_private_ctp_state_are_reported_without_scanning_contents(
    tmp_path: Path,
) -> None:
    collector = _collector_module()
    source_root = tmp_path / "source"
    logs = source_root / "examples" / "logs"
    private_state = (
        source_root
        / "examples"
        / "013_3_sa_midfreq_simnow"
        / "runtime-ctp-private"
        / "state"
        / "synthetic-private-leaf"
    )
    logs.mkdir(parents=True)
    private_state.mkdir(parents=True)
    (logs / "generated.py").write_text("api.submit_order({})\n", encoding="utf-8")
    (private_state / "private.py").write_text("api.cancel_order('x')\n", encoding="utf-8")

    coverage = collector.classify_repository_surface(source_root, {})
    report = collector.collect_inventory(source_root, ("examples",))

    paths = {row["path"]: row for row in coverage["paths"]}
    assert paths["examples/logs"]["classification"] == "GENERATED_RUNTIME_OUTPUT"
    assert paths[
        "examples/013_3_sa_midfreq_simnow/runtime-ctp-private/state"
    ]["classification"] == "PRIVATE_RUNTIME_STATE_OMITTED"
    assert "examples/013_3_sa_midfreq_simnow/runtime-ctp-private/state/synthetic-private-leaf" not in paths
    assert report["files_scanned"] == []


def test_default_source_surface_matches_controlled_path_baseline() -> None:
    collector = _collector_module()
    report = collector.collect_inventory(REPOSITORY_ROOT)
    coverage = report["source_path_coverage"]

    assert coverage["status"] == "BASELINE_CLASSIFIED"
    assert coverage["unclassified_paths"] == []
    assert coverage["counts"]["unclassified_paths"] == 0
    assert "examples" in report["scope_paths"]
    assert "conftest.py" in report["scope_paths"]
    assert "setup.py" in report["scope_paths"]
    assert "examples/001_multi_extend_data" in {
        row["path"] for row in coverage["paths"]
    }
    assert "examples/007_ctp/ctp_bbroker_5s_examples/live" in {
        row["path"] for row in coverage["paths"]
    }
    assert {"conftest.py", "setup.py"}.issubset(set(report["files_scanned"]))


def test_default_scope_labels_historical_ctp_example_candidates_as_non_authorizing() -> None:
    """Retired CTP examples stay discoverable without implying a runnable route."""

    collector = _collector_module()
    expected = {
        "examples/014_1_ctp_options_lowfreq",
        "examples/014_2_ctp_options_midfreq",
        "examples/015_ctp_options_highfreq",
    }

    assert expected.issubset(set(collector.DEFAULT_SCOPE_PATHS))

    report = collector.collect_inventory(REPOSITORY_ROOT)
    assert report["status"] == "CANDIDATE_DISCOVERY_ONLY"
    assert report["source_path_coverage"]["status"] == "BASELINE_CLASSIFIED"
    scopes = {entry["path"]: entry for entry in report["historical_ctp_candidate_scopes"]}
    assert set(scopes) == expected
    assert scopes["examples/014_1_ctp_options_lowfreq"]["classification"] == (
        "HISTORICAL_CTP_SOURCE_ENTRYPOINTS_FENCED"
    )
    assert scopes["examples/014_2_ctp_options_midfreq"]["classification"] == (
        "HISTORICAL_CTP_SOURCE_ENTRYPOINTS_FENCED"
    )
    assert scopes["examples/015_ctp_options_highfreq"]["classification"] == (
        "HISTORICAL_CTP_SOURCE_REPLAY_ONLY"
    )
    assert all(entry["verification_tests"] for entry in scopes.values())
    assert all(
        candidate["review_status"] == "REVIEW_REQUIRED"
        for candidate in report["writer_candidates"] + report["dynamic_execution_candidates"]
        if candidate["path"].startswith(tuple(sorted(expected)))
    )
    assert (
        "do not prove candidate reachability or authorize a runtime route"
        in report["limitations"][-2]
    )
