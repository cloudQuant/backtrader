"""Runtime-artifact governance coverage for the Iteration 30 example.

The example must record which ``backtrader`` implementation produced a report
and must refuse to start a live session against a snapshot it was not built
from, unless the operator explicitly opts into a diagnostic run.
"""

from __future__ import annotations

import importlib

import pytest

runner = importlib.import_module("examples.015_ctp_options_highfreq.run")
launcher = importlib.import_module("examples.015_ctp_options_highfreq.simnow_launcher")

EXTERNAL_SNAPSHOT = "/opt/conda/lib/python3.11/site-packages/backtrader/__init__.py"


def test_evidence_reports_the_loaded_workspace_source() -> None:
    evidence = runner.runtime_artifact_evidence()
    assert evidence["install_kind"] == "workspace_source"
    assert evidence["module_path"].endswith("backtrader/__init__.py")
    assert evidence["version"] == str(runner.bt.__version__)
    assert len(evidence["dependency_sha256"]) == 64
    assert evidence["target_workspace_root"].endswith("/backtrader")


def test_evidence_flags_an_external_snapshot() -> None:
    evidence = runner.runtime_artifact_evidence(module_path=EXTERNAL_SNAPSHOT)
    assert evidence["install_kind"] == "external_artifact"
    assert evidence["module_path"] == EXTERNAL_SNAPSHOT


def test_evidence_hash_tracks_the_loaded_dependency_files() -> None:
    first = runner.runtime_artifact_evidence()["dependency_sha256"]
    second = runner.runtime_artifact_evidence()["dependency_sha256"]
    assert first == second
    assert (
        runner.runtime_artifact_evidence(module_path=EXTERNAL_SNAPSHOT)["dependency_sha256"]
        == first
    )


def test_require_target_artifact_accepts_the_workspace_source() -> None:
    evidence = runner.require_target_backtrader_artifact()
    assert evidence["install_kind"] == "workspace_source"


def test_require_target_artifact_fails_closed_for_an_external_snapshot() -> None:
    with pytest.raises(runner.RunnerConfigurationError) as error:
        runner.require_target_backtrader_artifact(module_path=EXTERNAL_SNAPSHOT)
    assert "BACKTRADER_ARTIFACT_MISMATCH" in str(error.value)


def test_require_target_artifact_allows_an_explicit_diagnostic_override() -> None:
    evidence = runner.require_target_backtrader_artifact(
        module_path=EXTERNAL_SNAPSHOT, allow_external=True
    )
    assert evidence["install_kind"] == "external_artifact"


def test_launcher_refuses_to_build_a_session_on_a_mismatched_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher.run, "bt", _FakeBt(EXTERNAL_SNAPSHOT), raising=True)
    with pytest.raises(SystemExit) as error:
        launcher.require_runtime_artifact()
    assert "BACKTRADER_ARTIFACT_MISMATCH" in str(error.value)


def test_launcher_artifact_check_can_be_relaxed_for_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(launcher.run, "bt", _FakeBt(EXTERNAL_SNAPSHOT), raising=True)
    monkeypatch.setenv(launcher.ARTIFACT_OVERRIDE_ENV, "1")
    evidence = launcher.require_runtime_artifact()
    assert evidence["install_kind"] == "external_artifact"


class _FakeBt:
    """Minimal ``backtrader`` stand-in with a chosen module path."""

    def __init__(self, module_path: str) -> None:
        self.__file__ = module_path
        self.__version__ = "0.0.0-fake"
