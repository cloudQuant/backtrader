"""Local-only contracts for the Iteration 41 metadata evidence collector."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Tuple

import pytest

from backtrader_runtime import RuntimeRegistry
from backtrader_runtime import cli as runtime_cli
from backtrader_runtime.evidence_bundle import collect_iteration41_evidence


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _passing_specs() -> Tuple[Tuple[str, str, str], ...]:
    return (
        ("metadata", "evidence/metadata.json", "json"),
        ("junit", "evidence/results.xml", "junit"),
    )


def _passing_fixture(root: Path) -> None:
    _write(
        root / "evidence" / "metadata.json",
        json.dumps(
            {
                "schema_version": 1,
                "status": "PASS",
                "evidence_kind": "local",
                "secret_value": "must-not-appear-in-output",
            }
        ),
    )
    _write(
        root / "evidence" / "results.xml",
        '<testsuite tests="1"><testcase name="local" /></testsuite>',
    )


def test_collector_returns_only_redacted_structural_metadata_for_code_owned_inputs(
    tmp_path: Path,
) -> None:
    _passing_fixture(tmp_path)

    bundle = collect_iteration41_evidence(tmp_path, _passing_specs())

    assert bundle["status"] == "PASS"
    assert bundle["reason_code"] == "local_metadata_collected"
    assert bundle["actual"] == {
        "artifact_count": 2,
        "pass_count": 2,
        "not_run_count": 0,
        "fail_count": 0,
    }
    assert bundle["network_attempt_count"] == 0
    assert bundle["external_provider_write_count"] == 0
    assert bundle["evidence_boundary"].endswith("NOT_LIVE_ADMISSION")
    assert bundle["artifact_refs"][1]["summary"] == {
        "testcases": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }
    rendered = json.dumps(bundle)
    assert "must-not-appear-in-output" not in rendered
    assert "secret_value" not in rendered


def test_collector_marks_missing_code_owned_artifacts_not_run(tmp_path: Path) -> None:
    bundle = collect_iteration41_evidence(tmp_path, _passing_specs())

    assert bundle["status"] == "NOT_RUN"
    assert bundle["reason_code"] == "required_local_artifact_missing"
    assert [item["reason_code"] for item in bundle["artifact_refs"]] == [
        "required_artifact_missing",
        "required_artifact_missing",
    ]


@pytest.mark.parametrize(
    "path,expected_reason",
    (
        ("../outside.json", "artifact_path_not_code_owned"),
        ("evidence\\outside.json", "artifact_path_not_code_owned"),
    ),
)
def test_collector_rejects_non_code_owned_paths_without_reading_them(
    tmp_path: Path, path: str, expected_reason: str
) -> None:
    _write(tmp_path / "outside.json", "{}")

    bundle = collect_iteration41_evidence(tmp_path, (("bad", path, "json"),))

    assert bundle["status"] == "FAIL"
    assert bundle["artifact_refs"][0]["reason_code"] == expected_reason


def test_collector_rejects_invalid_or_failing_junit_metadata(tmp_path: Path) -> None:
    _write(tmp_path / "evidence" / "metadata.json", "not-json")
    _write(
        tmp_path / "evidence" / "results.xml",
        '<testsuite><testcase name="failure"><failure /></testcase></testsuite>',
    )

    bundle = collect_iteration41_evidence(tmp_path, _passing_specs())

    assert bundle["status"] == "FAIL"
    assert [item["reason_code"] for item in bundle["artifact_refs"]] == [
        "invalid_json_artifact",
        "junit_reports_failures",
    ]


def test_cli_collect_evidence_has_no_runtime_or_provider_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "status": "PASS",
        "reason_code": "local_metadata_collected",
        "evidence_boundary": "LOCAL_METADATA_COLLECTION_ONLY_NOT_LIVE_ADMISSION",
    }
    monkeypatch.setattr(runtime_cli, "collect_iteration41_evidence", lambda: expected)
    stdout = io.StringIO()

    status = runtime_cli.main(
        ["collect-evidence"],
        registry=RuntimeRegistry(()),
        environ={},
        stdout=stdout,
        stderr=io.StringIO(),
    )

    assert status == 0
    assert json.loads(stdout.getvalue()) == expected
