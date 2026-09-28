"""Config-v4 bindings for the Iteration 41 AI review-evidence profile."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from backtrader_runtime import (
    PRESET_POLICY_VIOLATION,
    REVIEW_REQUIRED,
    RegisteredRuntime,
    RuntimeConfigError,
    RuntimeRegistry,
)
from backtrader_runtime.review_evidence import (
    Iteration41ReviewEvidenceError,
    evidence_sha256,
    resolve_iteration41_review_evidence_bindings,
    validate_iteration41_review_evidence,
    validate_registered_iteration41_review_evidence,
)


NOW = 1_700_000_100.0


def _write_config(runtime_dir: Path, *, scenario: str = "baseline") -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: example.ai-review\n"
        "runtime:\n"
        "  mode: simulation\n"
        "  preset: replay\n"
        "parameters:\n"
        "  scenario: {0}\n"
        "secrets_ref: none\n".format(scenario),
        encoding="utf-8",
    )


def _registry(runtime_dir: Path) -> RuntimeRegistry:
    return RuntimeRegistry(
        (
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id="example.ai-review",
                allowed_presets=("replay",),
                allowed_parameter_keys=("scenario",),
            ),
        )
    )


def _wire(bindings, *, review_status: str = REVIEW_REQUIRED) -> dict:
    return {
        "artifact_sha256": bindings.artifact_sha256,
        "config_effective_digest": bindings.config_effective_digest,
        "created_at": NOW - 10.0,
        "evidence_id": "evidence-iteration41-config-v4",
        "expires_at": NOW + 60.0,
        "metadata": {"source": "offline-agent", "summary": "review queue only"},
        "producer": {
            "commit": "iteration41",
            "product": "backtrader-agent",
            "version": "0.2.0",
            "wheel_sha256": "a" * 64,
        },
        "review_status": review_status,
        "schema_version": "bt-api-deployment-evidence/v1",
        "strategy_id": bindings.strategy_id,
        "tenant_id": bindings.tenant_id,
    }


def _context(tmp_path: Path):
    runtime_dir = tmp_path / "registered-runtime"
    _write_config(runtime_dir)
    artifact = tmp_path / "strategy.py"
    artifact.write_bytes(b"class Strategy:\n    pass\n")
    registry = _registry(runtime_dir)
    bindings = resolve_iteration41_review_evidence_bindings(
        strategy_dir=runtime_dir,
        tenant_id="tenant-iteration41",
        artifact_path=artifact,
        registry=registry,
    )
    return runtime_dir, artifact, registry, bindings


def test_registered_config_v4_scope_binds_artifact_tenant_and_review_only_evidence(
    tmp_path: Path,
) -> None:
    runtime_dir, artifact, registry, bindings = _context(tmp_path)
    wire = _wire(bindings)

    observation = validate_registered_iteration41_review_evidence(
        wire,
        expected_evidence_sha256=evidence_sha256(wire),
        strategy_dir=runtime_dir,
        tenant_id="tenant-iteration41",
        artifact_path=artifact,
        registry=registry,
        now=NOW,
    )

    assert observation.status == "REVIEW_REQUIRED"
    assert observation.review_status == REVIEW_REQUIRED
    assert observation.read_only is True
    assert observation.deployment_authorized is False
    assert observation.execution_authorized is False
    assert observation.control_authorized is False
    assert dict(bindings.as_consumer_bindings()) == {
        "expected_tenant_id": "tenant-iteration41",
        "expected_strategy_id": "example.ai-review",
        "expected_artifact_sha256": bindings.artifact_sha256,
        "expected_config_effective_digest": bindings.config_effective_digest,
    }


def test_unregistered_config_cannot_supply_iteration41_evidence_bindings(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "not-registered"
    _write_config(runtime_dir)
    artifact = tmp_path / "strategy.py"
    artifact.write_bytes(b"pass\n")

    with pytest.raises(RuntimeConfigError) as caught:
        resolve_iteration41_review_evidence_bindings(
            strategy_dir=runtime_dir,
            tenant_id="tenant-iteration41",
            artifact_path=artifact,
            registry=RuntimeRegistry(()),
        )

    assert caught.value.code == PRESET_POLICY_VIOLATION
    assert caught.value.reason == "runtime_not_registered"


@pytest.mark.parametrize(
    "mutate,reason",
    (
        (lambda wire: wire.update({"tenant_id": "other-tenant"}), "tenant_mismatch"),
        (lambda wire: wire.update({"strategy_id": "other-strategy"}), "strategy_mismatch"),
        (lambda wire: wire.update({"artifact_sha256": "b" * 64}), "artifact_mismatch"),
        (
            lambda wire: wire.update({"config_effective_digest": "c" * 64}),
            "config_effective_digest_mismatch",
        ),
        (
            lambda wire: wire.update({"review_status": "human_reviewed"}),
            "review_status_not_review_required",
        ),
    ),
)
def test_iteration41_profile_rejects_wrong_scope_or_non_review_required_status(
    tmp_path: Path, mutate, reason: str
) -> None:
    _, _, _, bindings = _context(tmp_path)
    wire = _wire(bindings)
    mutate(wire)

    with pytest.raises(Iteration41ReviewEvidenceError) as caught:
        validate_iteration41_review_evidence(
            wire,
            expected_evidence_sha256=evidence_sha256(wire),
            bindings=bindings,
            now=NOW,
        )

    assert caught.value.reason == reason


def test_tampering_expiry_and_authority_shaped_metadata_fail_closed(tmp_path: Path) -> None:
    _, _, _, bindings = _context(tmp_path)
    original = _wire(bindings)
    trusted_digest = evidence_sha256(original)

    tampered = copy.deepcopy(original)
    tampered["metadata"]["source"] = "changed"
    with pytest.raises(Iteration41ReviewEvidenceError) as caught:
        validate_iteration41_review_evidence(
            tampered,
            expected_evidence_sha256=trusted_digest,
            bindings=bindings,
            now=NOW,
        )
    assert caught.value.reason == "evidence_digest_mismatch"

    expired = _wire(bindings)
    expired["expires_at"] = NOW
    with pytest.raises(Iteration41ReviewEvidenceError) as caught:
        validate_iteration41_review_evidence(
            expired,
            expected_evidence_sha256=evidence_sha256(expired),
            bindings=bindings,
            now=NOW,
        )
    assert caught.value.reason == "evidence_expired"

    authority = _wire(bindings)
    authority["metadata"] = {"approval": "not-an-admission"}
    with pytest.raises(Iteration41ReviewEvidenceError) as caught:
        validate_iteration41_review_evidence(
            authority,
            expected_evidence_sha256=evidence_sha256(authority),
            bindings=bindings,
            now=NOW,
        )
    assert caught.value.reason == "authority_shaped_metadata"


def test_config_or_artifact_change_requires_fresh_iteration41_evidence(tmp_path: Path) -> None:
    runtime_dir, artifact, registry, old_bindings = _context(tmp_path)
    old_wire = _wire(old_bindings)
    old_digest = evidence_sha256(old_wire)

    _write_config(runtime_dir, scenario="changed")
    artifact.write_bytes(b"class Strategy:\n    revision = 2\n")

    with pytest.raises(Iteration41ReviewEvidenceError) as caught:
        validate_registered_iteration41_review_evidence(
            old_wire,
            expected_evidence_sha256=old_digest,
            strategy_dir=runtime_dir,
            tenant_id="tenant-iteration41",
            artifact_path=artifact,
            registry=registry,
            now=NOW,
        )

    # Artifact is checked first after the scope fields, so either changed
    # binding remains a deterministic no-admission result.
    assert caught.value.reason == "artifact_mismatch"

    fresh_bindings = resolve_iteration41_review_evidence_bindings(
        strategy_dir=runtime_dir,
        tenant_id="tenant-iteration41",
        artifact_path=artifact,
        registry=registry,
    )
    assert fresh_bindings.config_effective_digest != old_bindings.config_effective_digest
    assert fresh_bindings.artifact_sha256 != old_bindings.artifact_sha256


def test_profile_module_has_no_backtrader_or_bt_api_execution_imports() -> None:
    script = (
        "import sys; import backtrader_runtime.review_evidence; "
        "blocked = ('backtrader', 'bt_api', 'bt_api_py', 'backtrader_agent', "
        "'backtrader_skills', 'backtrader_mcp'); "
        "assert not any(name == item or name.startswith(item + '.') "
        "for item in blocked for name in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
