"""Cross-product checks for the Iteration 41 review-evidence boundary.

The three AI products are independent repositories, so this test deliberately
uses a fresh subprocess and their source roots rather than importing them into
the Backtrader runtime.  It proves that an Agent-produced v1 record has one
digest understood by Skills and MCP, while remaining review-only and offline.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.test_utils.iteration41_source_roots import (
    iteration41_child_pythonpath,
    iteration41_source_paths,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _require_ai_products() -> tuple[str, ...]:
    return iteration41_source_paths("agent", "skills", "mcp")


def test_agent_evidence_is_cross_validated_by_skills_and_mcp_without_authority() -> None:
    _ai_sources = _require_ai_products()
    script = textwrap.dedent(
        """
        import copy
        import json
        import socket
        import sys
        import time

        attempts = []

        def deny_socket(*args, **kwargs):
            attempts.append((args, kwargs))
            raise AssertionError("deployment-evidence validation must not open a socket")

        socket.socket = deny_socket

        from backtrader_agent.deployment_evidence import (
            canonical_json as agent_canonical_json,
            create_deployment_evidence,
            verify_deployment_evidence_digest,
        )
        from backtrader_skills.deployment_evidence import (
            canonical_json as skills_canonical_json,
            validate_deployment_evidence as validate_skills,
        )
        from backtrader_mcp.deployment_evidence import (
            validate_deployment_evidence as validate_mcp,
        )

        now = time.time()
        artifact_sha256 = "a" * 64
        config_effective_digest = "b" * 64
        evidence = create_deployment_evidence(
            artifact_sha256=artifact_sha256,
            config_effective_digest=config_effective_digest,
            producer_product="backtrader-agent",
            producer_version="0.2.0",
            producer_commit="iteration41",
            producer_wheel_sha256="c" * 64,
            tenant_id="tenant-41",
            strategy_id="strategy-41",
            evidence_id="evidence-41",
            metadata={"source": "agent", "unicode": "cafe\\u0301"},
            created_at=now - 1.0,
            expires_at=now + 60.0,
        )
        wire = evidence.to_dict()
        digest = evidence.digest

        assert agent_canonical_json(wire) == skills_canonical_json(wire)
        assert verify_deployment_evidence_digest(wire, digest, now=now).digest == digest

        skills = validate_skills(
            wire,
            expected_tenant_id="tenant-41",
            expected_strategy_id="strategy-41",
            expected_evidence_digest=digest,
            expected_artifact_sha256=artifact_sha256,
            expected_config_effective_digest=config_effective_digest,
            now=now,
        )
        mcp = validate_mcp(
            wire,
            expected_evidence_sha256=digest,
            expected_tenant_id="tenant-41",
            expected_strategy_id="strategy-41",
            expected_artifact_sha256=artifact_sha256,
            expected_config_effective_digest=config_effective_digest,
            now=now,
        )
        assert skills["status"] == "valid"
        assert skills["authorization_granted"] is False
        assert skills["read_only"] is True
        assert skills["promotion_review_eligible"] is False
        assert mcp["status"] == "REQUIRES_INDEPENDENT_REVIEW"
        assert mcp["read_only"] is True
        assert mcp["deployment_authorized"] is False
        assert mcp["execution_authorized"] is False
        assert mcp["control_authorized"] is False

        try:
            validate_skills(
                wire,
                expected_tenant_id="tenant-41",
                expected_strategy_id="strategy-41",
                now=now,
                require_promotion=True,
            )
        except Exception as error:
            assert type(error).__name__ == "DeploymentPromotionRejected"
        else:
            raise AssertionError("review-required evidence passed the promotion gate")

        tampered = copy.deepcopy(wire)
        tampered["config_effective_digest"] = "d" * 64
        for validator in (
            lambda: verify_deployment_evidence_digest(tampered, digest, now=now),
            lambda: validate_skills(
                tampered,
                expected_tenant_id="tenant-41",
                expected_strategy_id="strategy-41",
                expected_evidence_digest=digest,
                expected_artifact_sha256=artifact_sha256,
                expected_config_effective_digest=config_effective_digest,
                now=now,
            ),
            lambda: validate_mcp(
                tampered,
                expected_evidence_sha256=digest,
                expected_tenant_id="tenant-41",
                expected_strategy_id="strategy-41",
                expected_artifact_sha256=artifact_sha256,
                expected_config_effective_digest=config_effective_digest,
                now=now,
            ),
        ):
            try:
                validator()
            except Exception:
                pass
            else:
                raise AssertionError("tampered evidence was accepted")

        assert attempts == []
        assert not any(
            name == "backtrader" or name.startswith("backtrader.")
            or name == "bt_api" or name.startswith("bt_api.")
            or name == "bt_api_py" or name.startswith("bt_api_py.")
            for name in sys.modules
        )
        print(json.dumps({"digest": digest, "skills": skills["status"], "mcp": mcp["status"]}))
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = iteration41_child_pythonpath(_ai_sources)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert len(payload["digest"]) == 64
    assert payload["skills"] == "valid"
    assert payload["mcp"] == "REQUIRES_INDEPENDENT_REVIEW"


def test_iteration41_profile_derives_ai_consumer_bindings_from_registered_config_v4(
    tmp_path: Path,
) -> None:
    """Only the config-v4 profile turns portable evidence into a review context.

    The standalone products intentionally retain their broader portable v1
    readers.  This test exercises the one Iteration 41 path that supplies their
    expected fields: Backtrader derives them from a registered local runtime,
    current config, and actual artifact bytes before any AI consumer is called.
    """

    _ai_sources = _require_ai_products()
    runtime_dir = tmp_path / "registered-runtime"
    runtime_dir.mkdir()
    (runtime_dir / "config.yaml").write_text(
        "config_schema_version: 4\n"
        "strategy:\n"
        "  id: example.ai-interop\n"
        "runtime:\n"
        "  mode: simulation\n"
        "  preset: replay\n"
        "parameters:\n"
        "  scenario: review\n"
        "secrets_ref: none\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "strategy.py"
    artifact.write_bytes(b"class Strategy:\n    pass\n")

    script = textwrap.dedent(
        """
        import copy
        import hashlib
        import json
        import socket
        import sys
        import time
        from pathlib import Path

        attempts = []

        def deny_socket(*args, **kwargs):
            attempts.append((args, kwargs))
            raise AssertionError("review-evidence binding must not open a socket")

        socket.socket = deny_socket

        from backtrader_runtime import RegisteredRuntime, RuntimeConfigError, RuntimeRegistry
        from backtrader_runtime.review_evidence import (
            Iteration41ReviewEvidenceError,
            evidence_sha256,
            resolve_iteration41_review_evidence_bindings,
            validate_iteration41_review_evidence,
            validate_registered_iteration41_review_evidence,
        )
        from backtrader_agent.deployment_evidence import create_deployment_evidence
        from backtrader_skills.deployment_evidence import (
            validate_deployment_evidence as validate_skills,
        )
        from backtrader_mcp.deployment_evidence import (
            validate_deployment_evidence as validate_mcp,
        )

        runtime_dir = Path(sys.argv[1])
        artifact = Path(sys.argv[2])
        registry = RuntimeRegistry((
            RegisteredRuntime(
                runtime_dir=runtime_dir,
                strategy_id="example.ai-interop",
                allowed_presets=("replay",),
                allowed_parameter_keys=("scenario",),
            ),
        ))
        now = time.time()
        bindings = resolve_iteration41_review_evidence_bindings(
            strategy_dir=runtime_dir,
            tenant_id="tenant-41",
            artifact_path=artifact,
            registry=registry,
        )
        evidence = create_deployment_evidence(
            artifact_sha256=bindings.artifact_sha256,
            config_effective_digest=bindings.config_effective_digest,
            producer_product="backtrader-agent",
            producer_version="0.2.0",
            producer_commit="iteration41",
            producer_wheel_sha256="c" * 64,
            tenant_id=bindings.tenant_id,
            strategy_id=bindings.strategy_id,
            evidence_id="evidence-41-config-v4",
            metadata={"source": "agent", "unicode": "cafe\\u0301"},
            created_at=now - 1.0,
            expires_at=now + 60.0,
        )
        wire = evidence.to_dict()
        digest = evidence.digest
        expected = dict(bindings.as_consumer_bindings())

        root = validate_registered_iteration41_review_evidence(
            wire,
            expected_evidence_sha256=digest,
            strategy_dir=runtime_dir,
            tenant_id="tenant-41",
            artifact_path=artifact,
            registry=registry,
            now=now,
        )
        assert root.status == "REVIEW_REQUIRED"
        assert root.review_status == "review_required"
        assert root.read_only is True
        assert root.deployment_authorized is False
        assert root.execution_authorized is False
        assert root.control_authorized is False

        skills = validate_skills(
            wire,
            expected_evidence_digest=digest,
            now=now,
            **expected,
        )
        mcp = validate_mcp(
            wire,
            expected_evidence_sha256=digest,
            now=now,
            **expected,
        )
        assert skills["review_status"] == "review_required"
        assert skills["read_only"] is True
        assert skills["authorization_granted"] is False
        assert skills["promotion_review_eligible"] is False
        assert mcp["status"] == "REQUIRES_INDEPENDENT_REVIEW"
        assert mcp["read_only"] is True
        assert mcp["deployment_authorized"] is False
        assert mcp["execution_authorized"] is False
        assert mcp["control_authorized"] is False

        def digest_for(value):
            return hashlib.sha256(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()

        for altered, reason in (
            (lambda item: item.update({"strategy_id": "other-strategy"}), "strategy_mismatch"),
            (lambda item: item.update({"tenant_id": "other-tenant"}), "tenant_mismatch"),
            (lambda item: item.update({"review_status": "human_reviewed"}), "review_status_not_review_required"),
        ):
            candidate = copy.deepcopy(wire)
            altered(candidate)
            try:
                validate_iteration41_review_evidence(
                    candidate,
                    expected_evidence_sha256=digest_for(candidate),
                    bindings=bindings,
                    now=now,
                )
            except Iteration41ReviewEvidenceError as error:
                assert error.reason == reason
            else:
                raise AssertionError("Iteration 41 profile accepted an invalid evidence scope")

        tampered = copy.deepcopy(wire)
        tampered["metadata"]["source"] = "changed"
        try:
            validate_iteration41_review_evidence(
                tampered,
                expected_evidence_sha256=digest,
                bindings=bindings,
                now=now,
            )
        except Iteration41ReviewEvidenceError as error:
            assert error.reason == "evidence_digest_mismatch"
        else:
            raise AssertionError("tampered evidence was accepted")

        expired = copy.deepcopy(wire)
        expired["expires_at"] = now
        try:
            validate_iteration41_review_evidence(
                expired,
                expected_evidence_sha256=digest_for(expired),
                bindings=bindings,
                now=now,
            )
        except Iteration41ReviewEvidenceError as error:
            assert error.reason == "evidence_expired"
        else:
            raise AssertionError("expired evidence was accepted")

        try:
            resolve_iteration41_review_evidence_bindings(
                strategy_dir=runtime_dir,
                tenant_id="tenant-41",
                artifact_path=artifact,
                registry=RuntimeRegistry(()),
            )
        except RuntimeConfigError as error:
            assert error.reason == "runtime_not_registered"
        else:
            raise AssertionError("unregistered config supplied evidence bindings")

        (runtime_dir / "config.yaml").write_text(
            (runtime_dir / "config.yaml").read_text(encoding="utf-8").replace(
                "scenario: review", "scenario: changed"
            ),
            encoding="utf-8",
        )
        try:
            validate_registered_iteration41_review_evidence(
                wire,
                expected_evidence_sha256=digest,
                strategy_dir=runtime_dir,
                tenant_id="tenant-41",
                artifact_path=artifact,
                registry=registry,
                now=now,
            )
        except Iteration41ReviewEvidenceError as error:
            assert error.reason == "config_effective_digest_mismatch"
        else:
            raise AssertionError("evidence survived a changed registered config")

        assert attempts == []
        assert not any(
            name == "backtrader" or name.startswith("backtrader.")
            or name == "bt_api" or name.startswith("bt_api.")
            or name == "bt_api_py" or name.startswith("bt_api_py.")
            for name in sys.modules
        )
        print(json.dumps({"root": root.status, "skills": skills["review_status"], "mcp": mcp["status"]}))
        """
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = iteration41_child_pythonpath(_ai_sources)

    completed = subprocess.run(
        [sys.executable, "-c", script, str(runtime_dir), str(artifact)],
        cwd=str(_PROJECT_ROOT),
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "root": "REVIEW_REQUIRED",
        "skills": "review_required",
        "mcp": "REQUIRES_INDEPENDENT_REVIEW",
    }
