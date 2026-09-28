"""Offline evidence tests for the historical, non-executable I9 candidate."""

from __future__ import annotations

import os
import inspect
from pathlib import Path

import pytest

import backtrader_runtime.ctp_artifact_provenance as artifact_provenance
from backtrader_runtime import ctp_i9_artifact_candidate as candidate


def test_i9_reproduction_evidence_is_not_an_installed_pin() -> None:
    assert candidate.I9_SOURCE_COMMIT == "157d0c0cffa4c8a86e196159cdf227e9014e9118"
    assert artifact_provenance.CTP_I9_REPRODUCED_WHEEL_SHA256 == (
        "aa094c039788a41adf975cfeee839fa3baf1bcef3878ae53d10eefb44410a4a3"
    )
    embedded_record = artifact_provenance.CTP_I9_EMBEDDED_WHEEL_RECORD_SHA256
    installed_records = artifact_provenance.CTP_I9_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET
    assert embedded_record == "d030ccf23d59a5f77230b490df52aa48c4cbecd67b2a78b7e782600126565841"
    assert installed_records == {
        "a": "1021d0edf7e4aa1f19b86dd5b0140634b19b589773e0aa7b55153c438367d466",
        "b": "0866e6150a881f0eb227fa80dfc215fbab65bb3b6f216be6b10d12c354226089",
    }
    assert len(set(installed_records.values())) == 2
    assert embedded_record not in installed_records.values()
    assert artifact_provenance.CTP_I9_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS == {}


def test_i9_verifier_fails_before_inspecting_an_installed_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_provenance.importlib.metadata,
        "distribution",
        lambda name: pytest.fail("I9 has no installed pin to inspect"),
    )

    with pytest.raises(artifact_provenance.CtpArtifactProvenanceError) as error:
        artifact_provenance.verify_ctp_i9_oneshot_md_diagnostic_artifact_provenance_for_fronts(
            td_front="tcp://example.invalid:1234",
            md_front="tcp://example.invalid:1235",
        )

    assert error.value.reason == "artifact_pin_unavailable"


def test_i9_attempt_marker_is_independent_and_permanently_one_shot(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    _protect_test_directory(state)
    i8_path = state / "i8-readonly-md-supervisor-no-retry.latch"
    i9_path = state / "i9-readonly-md-supervisor-no-retry.latch"
    i8_marker = b"synthetic-i8-marker-must-remain-untouched\n"
    i8_path.write_bytes(i8_marker)

    first = candidate.PersistentI9OneShotAttemptLatch(i9_path)
    assert first.begin_attempt() is True
    assert first.is_tripped() is False
    assert i9_path.read_bytes() == candidate.I9_LATCH_CONTENT
    assert i8_path.read_bytes() == i8_marker

    restarted = candidate.PersistentI9OneShotAttemptLatch(i9_path)
    assert restarted.is_tripped() is True
    assert restarted.begin_attempt() is False
    assert i8_path.read_bytes() == i8_marker


def test_i9_attempt_marker_requires_an_explicit_path() -> None:
    path_parameter = inspect.signature(candidate.PersistentI9OneShotAttemptLatch).parameters["path"]
    assert path_parameter.default is inspect.Parameter.empty


def test_i9_candidate_has_no_executable_provider_entry() -> None:
    assert not hasattr(candidate, "main")
    assert not hasattr(candidate, "supervise_i9_child")
    assert not hasattr(candidate, "_run_child_entry")


def _protect_test_directory(path: Path) -> None:
    path.mkdir()
    if os.name == "nt":
        from backtrader_runtime.ctp_private_config_setup import (
            _protect_target_directory,
            _verified_target_directory,
        )

        with _verified_target_directory(path) as descriptor:
            _protect_target_directory(descriptor)
    else:
        path.chmod(0o700)
