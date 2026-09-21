"""Ed25519 demo-approval receipt contract tests for both cross-exchange examples."""

import base64
import builtins
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from tests.test_utils.optional_sdk import optional_sdk

import examples.strategy_candidate_approval as demo_approval
midfreq_demo_approval = importlib.import_module(
    "examples.012_1_midfreq_cross_exchange.strategy_candidate_approval"
)
from examples.strategy_candidate_approval import (
    APPROVAL_ALGORITHM,
    APPROVAL_KEY_ID,
    CANONICAL_MANIFEST_RELATIVE_PATH,
    DemoApprovalVerificationError,
    RUNTIME_SOURCE_MODULES,
    canonical_json_bytes,
    canonical_sha256,
    collect_runtime_source_provenance,
    manifest_binding_sha256,
    verify_demo_approval,
)

RUNNERS = [
    SimpleNamespace(STRATEGY_ID="012_1_midfreq_cross_exchange"),
    SimpleNamespace(STRATEGY_ID="012_2_event_driven_cross_exchange"),
]
NOW = datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc)


def _runtime_runner(runner):
    """Load the SDK only for tests exercising the real example entry point."""
    optional_sdk()
    return importlib.import_module(f"examples.{runner.STRATEGY_ID}.run")


def test_012_1_backtrader_bootstrap_reuses_checkout_and_rejects_foreign_module(monkeypatch):
    runner = _runtime_runner(RUNNERS[0])
    expected_init = Path(runner.__file__).resolve().parents[2] / "backtrader" / "__init__.py"
    checkout_module = runner._load_repo_backtrader_package(runner.__file__)

    assert checkout_module is runner.bt
    assert Path(checkout_module.__file__).resolve() == expected_init.resolve()

    foreign_module = SimpleNamespace(
        __file__="/synthetic/site-packages/backtrader/__init__.py",
        __path__=["/synthetic/site-packages/backtrader"],
    )
    monkeypatch.setitem(runner.sys.modules, "backtrader", foreign_module)
    with pytest.raises(ImportError, match="different checkout"):
        runner._load_repo_backtrader_package(runner.__file__)


def _zulu(value):
    """Format an aware datetime as a UTC Zulu string."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def test_private_json_report_serializes_nested_decimal_exactly_and_stays_private(tmp_path):
    payload = {
        "account": {"equity": Decimal("123.4500000000000000001")},
        "orders": [{"quantity": Decimal("0.00010000")}],
        "history": (Decimal("1E-18"), 2),
    }
    expected = {
        "account": {"equity": "123.4500000000000000001"},
        "orders": [{"quantity": "0.00010000"}],
        "history": ["1E-18", 2],
    }
    path = tmp_path / "private" / "report.json"

    midfreq_demo_approval.write_private_json_report(path, payload)

    assert json.loads(path.read_text(encoding="utf-8")) == expected
    if os.name == "nt":
        acl = subprocess.run(
            ["icacls", str(path)], capture_output=True, check=True, text=True
        ).stdout
        assert f"{os.environ['USERNAME']}:(R,W)" in acl
        assert "BUILTIN\\Users:" not in acl
    else:
        assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(midfreq_demo_approval.serialize_private_json_report(payload)) == expected


def test_private_json_report_rejects_unknown_values_without_stringifying(tmp_path):
    path = tmp_path / "report.json"

    with pytest.raises(TypeError, match="UnsupportedReportValue.*not JSON serializable"):
        midfreq_demo_approval.write_private_json_report(
            path, {"unknown": type("UnsupportedReportValue", (), {})()}
        )

    assert not path.exists()


def _public_key(private_key, path):
    """Write the private key's PEM public key to path and return its bytes."""
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_bytes(raw)
    return raw


def _runtime_source():
    """Build a synthetic bound runtime-source provenance payload."""
    labels = sorted(label for label, _module, _distribution in RUNTIME_SOURCE_MODULES)
    hashes = {label: hashlib.sha256(f"artifact:{label}".encode()).hexdigest() for label in labels}
    provenance = {
        "schema_version": 1,
        "repository_commits": {
            "backtrader": "a" * 40,
            "bt_api_py": "b" * 40,
        },
        "runtime_files": copy.deepcopy(hashes),
        "source_files": copy.deepcopy(hashes),
    }
    provenance["fingerprint_sha256"] = canonical_sha256(provenance)
    return provenance


def _candidate(runner, *, config_sha="1" * 64, runtime_source=None):
    """Build a demo-approved strategy candidate record with all gates passing."""
    runtime_source = runtime_source or _runtime_source()
    candidate = {
        "strategy_id": runner.STRATEGY_ID,
        "research_status": "PASS",
        "allowed_modes": ["demo"],
        "conditional_modes": {},
        "config_sha256": config_sha,
        "repository_commits": copy.deepcopy(runtime_source["repository_commits"]),
        "oos": {
            "status": "OOS_PASS",
            "data_sha256": "c" * 64,
            "report_sha256": "d" * 64,
            "demo_pair_eligible": True,
        },
        "admission_gates": {
            "g4": {"status": "PASS", "receipt_sha256": "e" * 64},
            "g5a": {
                "status": "PASS",
                "okx_receipt_sha256": "f" * 64,
                "binance_receipt_sha256": "9" * 64,
            },
        },
    }
    candidate["candidate_sha256"] = canonical_sha256(candidate)
    return candidate


def _approval_artifact(
    runner,
    tmp_path,
    *,
    issued_at=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=1),
    signing_key=None,
    trust_key=None,
    config_sha="1" * 64,
    candidate_mutator=None,
    runtime_source=None,
    constraints=None,
):
    """Write a signed demo-approval artifact tree under tmp_path and return its parts."""
    signing_key = signing_key or Ed25519PrivateKey.generate()
    trust_key = trust_key or signing_key
    examples = tmp_path / "examples"
    receipts = examples / "receipts"
    receipts.mkdir(parents=True)
    trust_path = examples / "demo-approval-trust-root.pem"
    trust_raw = _public_key(trust_key, trust_path)

    runtime_source = copy.deepcopy(runtime_source or _runtime_source())
    candidate = _candidate(runner, config_sha=config_sha, runtime_source=runtime_source)
    if candidate_mutator is not None:
        candidate_mutator(candidate)
        candidate["candidate_sha256"] = canonical_sha256(
            {
                key: value
                for key, value in candidate.items()
                if key not in {"candidate_sha256", "demo_approval"}
            }
        )
    manifest = {
        "schema_version": 2,
        "manifest_status": "DEMO_APPROVED",
        "generated_at": "2026-09-08T03:00:00Z",
        "candidates": [candidate],
    }
    receipt = {
        "schema_version": 3,
        "status": "STRATEGY_APPROVED_FOR_DEMO",
        "environment": "demo",
        "strategy_id": runner.STRATEGY_ID,
        "candidate_sha256": candidate["candidate_sha256"],
        "candidate_config_sha256": candidate["config_sha256"],
        "repository_commits": copy.deepcopy(candidate["repository_commits"]),
        "runtime_source": copy.deepcopy(runtime_source),
        "constraints": copy.deepcopy(
            constraints
            or {
                "maximum_duration_seconds": "600",
                "maximum_order_count": 8,
                "maximum_quantity_base": "0.01",
            }
        ),
        "oos": {
            "status": candidate["oos"]["status"],
            "data_sha256": candidate["oos"]["data_sha256"],
            "report_sha256": candidate["oos"]["report_sha256"],
        },
        "g4": copy.deepcopy(candidate["admission_gates"]["g4"]),
        "g5a": copy.deepcopy(candidate["admission_gates"]["g5a"]),
        "manifest": {
            "path": CANONICAL_MANIFEST_RELATIVE_PATH,
            "binding_sha256": manifest_binding_sha256(manifest),
        },
        "issued_at": _zulu(issued_at),
        "expires_at": _zulu(expires_at),
    }
    signature = signing_key.sign(canonical_json_bytes(receipt))
    receipt["signature"] = {
        "algorithm": APPROVAL_ALGORITHM,
        "key_id": APPROVAL_KEY_ID,
        "public_key_sha256": demo_approval._public_key_fingerprint(trust_raw),
        "value": base64.b64encode(signature).decode("ascii"),
    }
    receipt_path = receipts / f"{runner.STRATEGY_ID}.receipt.json"
    receipt_raw = (json.dumps(receipt, sort_keys=True) + "\n").encode()
    receipt_path.write_bytes(receipt_raw)
    candidate["demo_approval"] = {
        "status": "STRATEGY_APPROVED_FOR_DEMO",
        "receipt_path": str(receipt_path.relative_to(examples)),
        "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
    }
    manifest_path = examples / "strategy-candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return {
        "candidate": candidate,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "receipt": receipt,
        "receipt_path": receipt_path,
        "trust_path": trust_path,
        "trust_sha256": hashlib.sha256(trust_raw).hexdigest(),
        "runtime_source": runtime_source,
    }


def _rewrite_receipt(artifact):
    """Re-serialize and re-hash an artifact's receipt and manifest after mutation."""
    raw = (json.dumps(artifact["receipt"], sort_keys=True) + "\n").encode()
    artifact["receipt_path"].write_bytes(raw)
    artifact["candidate"]["demo_approval"]["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    artifact["manifest_path"].write_text(
        json.dumps(artifact["manifest"], sort_keys=True), encoding="utf-8"
    )


def _bind_demo_artifact(runner, monkeypatch, artifact, *, runtime_source=None):
    """Bind one synthetic approval artifact as the runner's demo contract.

    Iteration 30 keeps the demo path bound to the repository-canonical manifest
    (``REPO_CANONICAL_MANIFEST``), so a synthetic artifact must patch that
    constant too; the self-contained folder manifest is only used by the
    replay/shadow/paper-live modes.
    """

    monkeypatch.setattr(runner, "MANIFEST_PATH", artifact["manifest_path"])
    monkeypatch.setattr(runner, "REPO_CANONICAL_MANIFEST", artifact["manifest_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_TRUST_ROOT", artifact["trust_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_PUBLIC_KEY_SHA256", artifact["trust_sha256"])
    if runtime_source is not None:
        monkeypatch.setattr(runner, "collect_runtime_source_provenance", runtime_source)


def _verify(runner, artifact):
    """Verify the artifact's demo approval as the given runner."""
    return verify_demo_approval(
        candidate=artifact["candidate"],
        manifest_path=artifact["manifest_path"],
        canonical_manifest_path=artifact["manifest_path"],
        trust_root_path=artifact["trust_path"],
        expected_strategy_id=runner.STRATEGY_ID,
        runtime_source=artifact["runtime_source"],
        expected_public_key_sha256=artifact["trust_sha256"],
        now=NOW,
    )


@pytest.mark.parametrize("runner", RUNNERS)
def test_valid_ed25519_receipt_is_bound_to_all_admission_evidence(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)

    receipt = _verify(runner, artifact)

    assert receipt["candidate_sha256"] == artifact["candidate"]["candidate_sha256"]
    assert receipt["oos"]["status"] == "OOS_PASS"
    assert receipt["g4"]["status"] == "PASS"
    assert receipt["g5a"]["status"] == "PASS"
    assert receipt["constraints"] == {
        "maximum_duration_seconds": "600",
        "maximum_order_count": 8,
        "maximum_quantity_base": "0.01",
    }


@pytest.mark.parametrize("runner", RUNNERS)
def test_legacy_receipt_without_signed_lease_constraints_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["receipt"]["schema_version"] = 2
    artifact["receipt"].pop("constraints")
    _rewrite_receipt(artifact)

    with pytest.raises(DemoApprovalVerificationError, match="fields are invalid"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize(
    ("constraints", "message"),
    (
        (
            {
                "maximum_duration_seconds": "600.0",
                "maximum_order_count": 8,
                "maximum_quantity_base": "0.01",
            },
            "canonical decimal string",
        ),
        (
            {
                "maximum_duration_seconds": "600",
                "maximum_order_count": True,
                "maximum_quantity_base": "0.01",
            },
            "positive integer",
        ),
        (
            {
                "maximum_duration_seconds": "600",
                "maximum_order_count": 8,
                "maximum_quantity_base": "0",
            },
            "finite and positive",
        ),
    ),
)
def test_signed_lease_constraints_are_strict(runner, tmp_path, constraints, message):
    artifact = _approval_artifact(runner, tmp_path, constraints=constraints)

    with pytest.raises(DemoApprovalVerificationError, match=message):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_signed_maximum_duration_must_fit_receipt_validity_window(runner, tmp_path):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        constraints={
            "maximum_duration_seconds": "7201",
            "maximum_order_count": 8,
            "maximum_quantity_base": "0.01",
        },
    )

    with pytest.raises(DemoApprovalVerificationError, match="exceeds its validity window"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_runner_uses_fixed_trust_root_and_canonical_manifest(runner, monkeypatch, tmp_path):
    runner = _runtime_runner(runner)
    current = datetime.now(timezone.utc)
    artifact = _approval_artifact(
        runner,
        tmp_path,
        issued_at=current - timedelta(hours=1),
        expires_at=current + timedelta(hours=1),
    )
    _bind_demo_artifact(
        runner,
        monkeypatch,
        artifact,
        runtime_source=lambda: copy.deepcopy(artifact["runtime_source"]),
    )

    receipt = runner.require_demo_approval(artifact["candidate"], artifact["manifest_path"])

    assert receipt["strategy_id"] == runner.STRATEGY_ID


@pytest.mark.parametrize("runner", RUNNERS)
def test_unsigned_receipt_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["receipt"].pop("signature")
    _rewrite_receipt(artifact)

    with pytest.raises(DemoApprovalVerificationError, match="fields are invalid"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_signed_payload_tamper_cannot_be_hidden_by_rehashing_receipt(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["receipt"]["issued_at"] = _zulu(NOW - timedelta(minutes=30))
    _rewrite_receipt(artifact)

    with pytest.raises(DemoApprovalVerificationError, match="signature is invalid"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_expired_receipt_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        issued_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(seconds=1),
    )

    with pytest.raises(DemoApprovalVerificationError, match="receipt is expired"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_receipt_signed_by_wrong_key_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        signing_key=Ed25519PrivateKey.generate(),
        trust_key=Ed25519PrivateKey.generate(),
    )

    with pytest.raises(DemoApprovalVerificationError, match="signature is invalid"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_replacing_trust_root_cannot_authorize_a_new_signer(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    _public_key(Ed25519PrivateKey.generate(), artifact["trust_path"])

    with pytest.raises(DemoApprovalVerificationError, match="trust root fingerprint is invalid"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_crlf_checkout_trust_root_keeps_the_pinned_fingerprint(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    trust_root = artifact["trust_path"]
    trust_root.write_bytes(trust_root.read_bytes().replace(b"\n", b"\r\n"))

    receipt = _verify(runner, artifact)

    assert receipt["signature"]["public_key_sha256"] == artifact["trust_sha256"]


def test_missing_cryptography_dependency_fails_closed(monkeypatch, tmp_path):
    runner = RUNNERS[0]
    artifact = _approval_artifact(runner, tmp_path)
    real_import = builtins.__import__

    def deny_cryptography(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", deny_cryptography)
    with pytest.raises(DemoApprovalVerificationError, match=r"install backtrader\[live\]"):
        _verify(runner, artifact)


def _set_candidate_value(path, value):
    """Return a mutator that sets a nested candidate field to value."""

    def mutate(candidate):
        target = candidate
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize(
    ("path", "value", "message"),
    (
        (("research_status",), "INCOMPLETE", "research_status PASS"),
        (("oos", "status"), "INCOMPLETE", "oos.status OOS_PASS"),
        (("oos", "demo_pair_eligible"), False, "demo_pair_eligible true"),
        (("admission_gates", "g4", "status"), "FAIL", "g4.status PASS"),
        (("admission_gates", "g5a", "status"), "FAIL", "g5a.status PASS"),
    ),
)
def test_candidate_admission_statuses_must_all_pass(runner, tmp_path, path, value, message):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        candidate_mutator=_set_candidate_value(path, value),
    )

    with pytest.raises(DemoApprovalVerificationError, match=message):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_repository_commit_must_be_full_hex(runner, tmp_path):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        candidate_mutator=_set_candidate_value(("repository_commits", "bt_api_py"), "not-a-commit"),
    )

    with pytest.raises(DemoApprovalVerificationError, match="full lowercase Git commit SHA"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_signed_format_valid_but_false_repository_commit_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        candidate_mutator=_set_candidate_value(("repository_commits", "bt_api_py"), "f" * 40),
    )

    with pytest.raises(DemoApprovalVerificationError, match="actual runtime revisions"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize(
    "field,label",
    (
        ("runtime_files", "backtrader.cerebro"),
        ("runtime_files", "backtrader.package_api"),
        ("source_files", "backtrader.strategy"),
        ("source_files", "backtrader.order"),
        ("source_files", "backtrader.comminfo"),
        ("source_files", "backtrader.parameters"),
        ("source_files", "backtrader.lineiterator"),
        ("source_files", "backtrader.trade_logger"),
        ("runtime_files", "backtrader.store"),
        ("runtime_files", "backtrader.live_store"),
        ("runtime_files", "backtrader.feed"),
        ("runtime_files", "backtrader.live_feed"),
        ("runtime_files", "backtrader.broker"),
        ("runtime_files", "backtrader.hft_matching"),
        ("runtime_files", "examples.strategy_candidate_approval"),
        ("runtime_files", "bt_api_py.cross_venue"),
        ("source_files", "bt_api_py.public_api"),
        ("source_files", "bt_api_py.execution_session"),
        ("source_files", "bt_api_py.normalization"),
        ("source_files", "bt_api_base.event_bus"),
        ("source_files", "bt_api_okx.market_ws"),
        ("source_files", "bt_api_okx.gateway"),
        ("source_files", "bt_api_binance.market_ws"),
        ("source_files", "bt_api_binance.execution"),
    ),
)
def test_any_bound_runtime_or_dirty_source_change_fails_closed(runner, tmp_path, field, label):
    artifact = _approval_artifact(runner, tmp_path)
    current = copy.deepcopy(artifact["runtime_source"])
    current[field][label] = "8" * 64
    fingerprint_payload = {
        key: value for key, value in current.items() if key != "fingerprint_sha256"
    }
    current["fingerprint_sha256"] = canonical_sha256(fingerprint_payload)
    artifact["runtime_source"] = current

    with pytest.raises(DemoApprovalVerificationError, match="runtime.*source|actual runtime"):
        _verify(runner, artifact)


def test_runtime_source_collector_covers_every_required_framework_sdk_and_venue_file():
    optional_sdk()
    try:
        provenance = collect_runtime_source_provenance()
    except DemoApprovalVerificationError as exc:
        # A wheel installed without a VCS build attestation is deliberately
        # ineligible for a demo approval receipt.  Preserve that fail-closed
        # property when this suite is run against site-packages; source-tree
        # execution continues below and must provide the complete manifest.
        assert str(exc) == "bt_api_py installed artifact has no verifiable Git commit"
        return
    expected = {label for label, _module, _distribution in RUNTIME_SOURCE_MODULES}

    assert set(provenance["runtime_files"]) == expected
    assert set(provenance["source_files"]) == expected
    assert {
        "backtrader.cerebro",
        "backtrader.package_api",
        "backtrader.strategy",
        "backtrader.order",
        "backtrader.comminfo",
        "backtrader.parameters",
        "backtrader.lineiterator",
        "backtrader.trade_logger",
        "backtrader.store",
        "backtrader.feed",
        "backtrader.broker",
        "backtrader.hft_matching",
        "examples.strategy_candidate_approval",
        "bt_api_py.cross_venue",
        "bt_api_py.public_api",
        "bt_api_py.execution_session",
        "bt_api_okx.gateway",
        "bt_api_binance.gateway",
    } <= expected
    assert provenance["runtime_files"] == provenance["source_files"]
    assert provenance["repository_commits"]["backtrader"]
    assert provenance["repository_commits"]["bt_api_py"]
    assert provenance["fingerprint_sha256"] == canonical_sha256(
        {key: value for key, value in provenance.items() if key != "fingerprint_sha256"}
    )


def test_local_wheel_archive_is_not_bound_to_an_unrelated_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "unrelated-checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    archive = checkout / ".git" / "evidence" / "bt_api_base.whl"
    archive.parent.mkdir()
    archive.write_bytes(b"not-a-real-wheel")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    monkeypatch.setattr(
        demo_approval,
        "_distribution_direct_url",
        lambda _name: {
            "url": archive.as_uri(),
            "archive_info": {"hashes": {"sha256": digest}},
        },
    )

    assert demo_approval._local_distribution_root("bt_api_base") is None
    (checkout / "bt_api_base").mkdir()
    (checkout / "bt_api_base" / "__init__.py").write_text("", encoding="utf-8")

    assert demo_approval._local_distribution_root("bt_api_base") == checkout


@pytest.mark.parametrize("runner", RUNNERS)
def test_placeholder_zero_evidence_hash_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(
        runner,
        tmp_path,
        candidate_mutator=_set_candidate_value(
            ("admission_gates", "g4", "receipt_sha256"), "0" * 64
        ),
    )

    with pytest.raises(DemoApprovalVerificationError, match="lowercase SHA-256"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_missing_oos_report_hash_fails_closed(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["candidate"]["oos"].pop("report_sha256")
    artifact["candidate"]["candidate_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in artifact["candidate"].items()
            if key not in {"candidate_sha256", "demo_approval"}
        }
    )
    artifact["manifest_path"].write_text(
        json.dumps(artifact["manifest"], sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(DemoApprovalVerificationError, match="oos.report_sha256"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_manifest_mutation_invalidates_signed_binding(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["manifest"]["manifest_status"] = "MUTATED_AFTER_APPROVAL"
    artifact["manifest_path"].write_text(
        json.dumps(artifact["manifest"], sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(DemoApprovalVerificationError, match="manifest binding is invalid"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_candidate_mutation_invalidates_receipt(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["candidate"]["config_sha256"] = "9" * 64
    artifact["candidate"]["candidate_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in artifact["candidate"].items()
            if key not in {"candidate_sha256", "demo_approval"}
        }
    )
    artifact["manifest_path"].write_text(
        json.dumps(artifact["manifest"], sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(DemoApprovalVerificationError, match="candidate_sha256 is not bound"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("algorithm", "sha256", "algorithm is invalid"),
        ("key_id", "attacker-key", "key_id is invalid"),
        ("public_key_sha256", "1" * 64, "public key fingerprint is invalid"),
        ("value", "not base64!", "not valid base64"),
    ),
)
def test_signature_contract_rejects_algorithm_key_and_base64_tamper(
    runner, tmp_path, field, value, message
):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["receipt"]["signature"][field] = value
    _rewrite_receipt(artifact)

    with pytest.raises(DemoApprovalVerificationError, match=message):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_receipt_path_cannot_escape_examples_boundary(runner, tmp_path):
    artifact = _approval_artifact(runner, tmp_path)
    artifact["candidate"]["demo_approval"]["receipt_path"] = "../../outside.receipt.json"
    artifact["manifest_path"].write_text(
        json.dumps(artifact["manifest"], sort_keys=True), encoding="utf-8"
    )

    with pytest.raises(DemoApprovalVerificationError, match="must stay under examples"):
        _verify(runner, artifact)


@pytest.mark.parametrize("runner", RUNNERS)
def test_demo_noncanonical_manifest_stops_before_store(runner, monkeypatch, tmp_path):
    runner = _runtime_runner(runner)
    manifest_path = tmp_path / "strategy-candidate-manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.DemoApprovalError, match="canonical manifest"):
        runner.run_network("demo", 1000, manifest_path=manifest_path)

    assert calls == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_invalid_signature_stops_before_store_or_write(runner, monkeypatch, tmp_path):
    runner = _runtime_runner(runner)
    config_sha = hashlib.sha256(Path(runner.DEFAULT_CONFIG).read_bytes()).hexdigest()
    current = datetime.now(timezone.utc)
    artifact = _approval_artifact(
        runner,
        tmp_path,
        config_sha=config_sha,
        issued_at=current - timedelta(hours=1),
        expires_at=current + timedelta(hours=1),
    )
    artifact["receipt"]["issued_at"] = _zulu(current - timedelta(minutes=30))
    _rewrite_receipt(artifact)
    _bind_demo_artifact(
        runner,
        monkeypatch,
        artifact,
        runtime_source=lambda: copy.deepcopy(artifact["runtime_source"]),
    )
    monkeypatch.setattr(
        runner,
        "load_candidate",
        lambda _path: (artifact["manifest"], artifact["candidate"], artifact["manifest_path"]),
    )
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.DemoApprovalError, match="signature is invalid"):
        runner.run_network("demo", 100, manifest_path=artifact["manifest_path"])

    assert calls == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_runtime_source_change_stops_before_store_or_write(runner, monkeypatch, tmp_path):
    runner = _runtime_runner(runner)
    config_sha = hashlib.sha256(Path(runner.DEFAULT_CONFIG).read_bytes()).hexdigest()
    current = datetime.now(timezone.utc)
    artifact = _approval_artifact(
        runner,
        tmp_path,
        config_sha=config_sha,
        issued_at=current - timedelta(hours=1),
        expires_at=current + timedelta(hours=1),
    )
    changed = copy.deepcopy(artifact["runtime_source"])
    changed["source_files"]["bt_api_py.execution_session"] = "8" * 64
    changed["fingerprint_sha256"] = canonical_sha256(
        {key: value for key, value in changed.items() if key != "fingerprint_sha256"}
    )
    _bind_demo_artifact(runner, monkeypatch, artifact, runtime_source=lambda: changed)
    monkeypatch.setattr(
        runner,
        "load_candidate",
        lambda _path: (artifact["manifest"], artifact["candidate"], artifact["manifest_path"]),
    )
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.DemoApprovalError, match="runtime.*source|actual runtime"):
        runner.run_network("demo", 100, manifest_path=artifact["manifest_path"])

    assert calls == []


@pytest.mark.parametrize("runner", RUNNERS)
@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("strategy_sha256", "strategy source fingerprint mismatch"),
        ("config_sha256", "candidate config fingerprint mismatch"),
    ),
)
def test_candidate_source_or_config_tamper_stops_before_store(
    runner, monkeypatch, tmp_path, field, message
):
    runner = _runtime_runner(runner)
    manifest = json.loads(Path(runner.MANIFEST_PATH).read_text(encoding="utf-8"))
    candidate = next(
        row for row in manifest["candidates"] if row["strategy_id"] == runner.STRATEGY_ID
    )
    resolved = Path(runner.__file__).parent
    candidate["resolved_example_path"] = str(resolved)
    candidate["runner_sha256"] = hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()
    candidate["strategy_sha256"] = hashlib.sha256(
        (resolved / "strategy.py").read_bytes()
    ).hexdigest()
    candidate["config_sha256"] = hashlib.sha256((resolved / "config.yaml").read_bytes()).hexdigest()
    candidate[field] = "0" * 64
    candidate["candidate_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in candidate.items()
            if key not in {"candidate_sha256", "demo_approval"}
        }
    )
    manifest_path = tmp_path / "strategy-candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.RunnerConfigurationError, match=message):
        runner.run_network("shadow", 1000, manifest_path=manifest_path)

    assert calls == []


def test_repository_trust_root_has_expected_fingerprint():
    trust_root = Path(__file__).parents[2] / "examples" / "demo-approval-trust-root.pem"
    # Normalize first so the fixture starts from the committed LF bytes on
    # every platform; a CRLF checkout must not double-convert the artifact.
    raw = trust_root.read_bytes().replace(b"\r\n", b"\n")

    assert demo_approval._public_key_fingerprint(raw) == demo_approval.APPROVAL_PUBLIC_KEY_SHA256
    assert (
        demo_approval._public_key_fingerprint(raw.replace(b"\n", b"\r\n"))
        == demo_approval.APPROVAL_PUBLIC_KEY_SHA256
    )
    # A checkout that was converted twice (e.g. CRLF materialized as \r\n and
    # then newline-converted again) yields \r\r\n; the fingerprint must still
    # match the pinned digest.
    assert (
        demo_approval._public_key_fingerprint(raw.replace(b"\n", b"\r\r\n"))
        == demo_approval.APPROVAL_PUBLIC_KEY_SHA256
    )


def _mock_demo_run_inputs(runner, monkeypatch, store, events):
    config = runner.load_config()
    candidate = {
        "strategy_id": runner.STRATEGY_ID,
        "research_status": "RESEARCH_REJECTED",
        "candidate_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "strategy_sha256": "c" * 64,
    }
    manifest_path = runner.REPO_CANONICAL_MANIFEST.resolve()
    admission = {
        "operator_override": True,
        "research_status": "RESEARCH_REJECTED",
        "execution_admitted": True,
    }
    monkeypatch.setattr(runner, "load_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        runner,
        "load_candidate",
        lambda _path: ({}, candidate, manifest_path),
    )
    monkeypatch.setattr(runner, "_file_sha256", lambda *_args, **_kwargs: "b" * 64)
    monkeypatch.setattr(
        runner,
        "_validate_network_admission",
        lambda *_args, **_kwargs: dict(admission),
    )
    monkeypatch.setattr(
        runner,
        "_operator_demo_calibration_contract_mismatch_enabled",
        lambda *_args: False,
    )
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(runner, "_demo_broker_kwargs", lambda *_args: {})
    monkeypatch.setattr(
        runner,
        "_rules_from_store",
        lambda *_args: (runner.replay_rules(), {venue: "mock" for venue in runner.VENUE_SYMBOLS}),
    )
    funding_time = datetime.now(timezone.utc) + timedelta(hours=1)
    monkeypatch.setattr(
        runner,
        "_funding_from_store",
        lambda *_args: {
            venue: (Decimal("0"), funding_time, Decimal("28800"), "mock")
            for venue in runner.VENUE_SYMBOLS
        },
    )
    monkeypatch.setattr(
        runner,
        "_bounded_requested_duration",
        lambda duration, _config: runner.decimal_value(duration, "duration"),
    )
    monkeypatch.setattr(runner, "validate_duration", lambda *_args, **_kwargs: {"status": "PASS"})

    def load_qualification(*_args, **_kwargs):
        events.append("qualification")
        return {}, {"status": "MOCKED"}

    monkeypatch.setattr(runner, "_load_model_qualification", load_qualification)
    return config, candidate, manifest_path


@pytest.mark.parametrize(
    "transient_stage",
    ("readiness", "reconciliation", "post_initialization_reconciliation"),
)
def test_012_1_active_demo_retries_transient_evidence_and_initializes_before_broker(
    monkeypatch, transient_stage
):
    runner = _runtime_runner(RUNNERS[0])
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    events = []
    identity = "d" * 64
    pid = os.getpid()

    def execution_summary(generation, *, baseline_required=False):
        return {
            "active_orders": 0,
            "generation": generation,
            "fencing_epoch": generation,
            "as_of_monotonic_ns": time.monotonic_ns(),
            "session_enabled": True,
            "identity_binding_sha256": identity,
            "evidence_complete": True,
            "trading_blocked": baseline_required,
            "unknown_ids": [],
            "fee_unresolved_orders": [],
            "funding_unresolved_orders": [],
            "evidence_errors": ["account_risk_baseline_required"] if baseline_required else [],
            "error_code": None,
        }

    account_risk = {
        "generation": 2,
        "fencing_epoch": 2,
        "as_of_monotonic_ns": time.monotonic_ns(),
        "owner_pid": pid,
        "clock_domain_id": f"process:{pid}:monotonic",
        "baseline_equity": "1000",
        "current_equity": "1000",
        "configured_venues": list(runner.VENUE_SYMBOLS),
        "durable": True,
        "trading_blocked": False,
        "evidence_complete": True,
        "evidence_errors": [],
        "error_code": None,
        "identity_binding_sha256": identity,
        "loss_limit_breached": False,
    }

    class StopBeforeBroker(Exception):
        pass

    class Store:
        initialized = False
        readiness_calls = 0
        reconcile_calls = 0
        post_initialization_reconcile_calls = 0

        def start(self):
            events.append("store_start")

        def stop(self, timeout):
            events.append("store_stop")
            return {
                "shutdown_state": "PASS",
                "queue_depth": 0,
                "inflight": [],
                "worker_alive": False,
                "close_thread_alive": False,
                "broker_update_conservation": True,
                "last_error_code": None,
            }

        def get_environment_info(self, _symbol):
            return {"environment": "demo"}

        def get_account_config(self, _symbol):
            return {"position_mode": "dual_side", "can_trade": True}

        def get_order_readiness(self, _symbol, _quantity, position_mode):
            assert position_mode == "dual_side"
            self.readiness_calls += 1
            if transient_stage == "readiness" and self.readiness_calls == 1:
                return {"ready": False, "definite_failure": False}
            return {"ready": True}

        def get_account_risk_snapshot(self):
            events.append("account_risk_read")
            if self.initialized:
                return account_risk
            return {
                "baseline_equity": None,
                "loss_limit_breached": False,
                "blocked_reasons": ["baseline_missing"],
            }

        def get_reconcile_snapshot(self):
            events.append("reconcile_read")
            self.reconcile_calls += 1
            if transient_stage == "reconciliation" and self.reconcile_calls == 1:
                return {
                    "configured_venues": list(runner.VENUE_SYMBOLS),
                    "reconciled_venues": list(runner.VENUE_SYMBOLS),
                    "positions": [],
                    "open_orders": [],
                    "execution_summary": {},
                    "identity_binding_sha256": identity,
                    "evidence_complete": False,
                    "evidence_errors": ["startup_evidence_pending"],
                }
            if self.initialized:
                self.post_initialization_reconcile_calls += 1
                if (
                    transient_stage == "post_initialization_reconciliation"
                    and self.post_initialization_reconcile_calls == 1
                ):
                    return {
                        "configured_venues": list(runner.VENUE_SYMBOLS),
                        "reconciled_venues": list(runner.VENUE_SYMBOLS),
                        "positions": [],
                        "open_orders": [],
                        "execution_summary": {},
                        "identity_binding_sha256": identity,
                        "evidence_complete": False,
                        "evidence_errors": ["startup_evidence_pending"],
                    }
            summary = execution_summary(
                2 if self.initialized else 1,
                baseline_required=not self.initialized,
            )
            return {
                "configured_venues": list(runner.VENUE_SYMBOLS),
                "reconciled_venues": list(runner.VENUE_SYMBOLS),
                "positions": [],
                "open_orders": [],
                "execution_summary": summary,
                "identity_binding_sha256": identity,
                "evidence_complete": True,
                "evidence_errors": [],
            }

        def initialize_account_risk_baseline(self):
            events.append("initialize_account_risk_baseline")
            self.initialized = True
            return account_risk

        def getbroker(self, **_kwargs):
            events.append("getbroker")
            raise StopBeforeBroker

    store = Store()
    _config, _candidate, manifest_path = _mock_demo_run_inputs(
        runner, monkeypatch, store, events
    )

    with pytest.raises(StopBeforeBroker):
        runner.run_network("demo", 100, manifest_path=manifest_path)

    assert events.count("initialize_account_risk_baseline") == 1
    assert events.index("qualification") < events.index("initialize_account_risk_baseline")
    assert events.index("initialize_account_risk_baseline") < events.index("getbroker")
    if transient_stage == "readiness":
        assert store.readiness_calls >= 3
    elif transient_stage == "reconciliation":
        assert store.reconcile_calls >= 3
    else:
        assert store.post_initialization_reconcile_calls == 2


@pytest.mark.parametrize(
    ("transient_stage", "expected_message"),
    (
        ("readiness", "okx order readiness is false"),
        ("reconciliation", "demo reconciliation evidence is incomplete"),
    ),
)
def test_012_1_startup_evidence_retry_exhaustion_fails_closed(
    monkeypatch, transient_stage, expected_message
):
    runner = _runtime_runner(RUNNERS[0])
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

    class Store:
        readiness_calls = 0
        reconcile_calls = 0

        def get_environment_info(self, _symbol):
            return {"environment": "demo"}

        def get_account_config(self, _symbol):
            return {"position_mode": "dual_side", "can_trade": True}

        def get_order_readiness(self, _symbol, _quantity, position_mode):
            assert position_mode == "dual_side"
            self.readiness_calls += 1
            if transient_stage == "readiness":
                return {"ready": False, "definite_failure": False}
            return {"ready": True}

        def get_account_risk_snapshot(self):
            return {
                "baseline_equity": None,
                "loss_limit_breached": False,
                "blocked_reasons": ["baseline_missing"],
            }

        def get_reconcile_snapshot(self):
            self.reconcile_calls += 1
            return {"positions": [], "open_orders": [], "evidence_complete": False}

        def initialize_account_risk_baseline(self):
            raise AssertionError("incomplete startup evidence must not initialize risk baseline")

    store = Store()

    with pytest.raises(runner.RunnerConfigurationError, match=expected_message):
        runner._readiness(
            store,
            runner.replay_rules(),
            runner.risk_from_config(runner.load_config()),
        )

    expected_readiness_calls_per_attempt = (
        1 if transient_stage == "readiness" else len(runner.VENUE_SYMBOLS)
    )
    assert store.readiness_calls == (
        runner.STARTUP_EVIDENCE_MAX_ATTEMPTS * expected_readiness_calls_per_attempt
    )
    if transient_stage == "reconciliation":
        assert store.reconcile_calls == runner.STARTUP_EVIDENCE_MAX_ATTEMPTS


def test_012_1_demo_preflight_does_not_initialize_account_risk_baseline(monkeypatch):
    runner = _runtime_runner(RUNNERS[0])
    events = []

    class Store:
        def start(self):
            events.append("store_start")

        def stop(self, timeout):
            events.append("store_stop")
            return {
                "shutdown_state": "PASS",
                "queue_depth": 0,
                "inflight": [],
                "worker_alive": False,
                "close_thread_alive": False,
                "broker_update_conservation": True,
                "last_error_code": None,
            }

        def initialize_account_risk_baseline(self):
            events.append("initialize_account_risk_baseline")
            raise AssertionError("preflight must not initialize the account-risk baseline")

    store = Store()
    _config, _candidate, manifest_path = _mock_demo_run_inputs(
        runner, monkeypatch, store, events
    )

    def readiness(_store, _rules, _risk, *, initialize_account_risk_baseline=True):
        events.append(("readiness", initialize_account_risk_baseline))
        assert initialize_account_risk_baseline is False
        return {"status": "PASS", "venues": {venue: {} for venue in runner.VENUE_SYMBOLS}}

    monkeypatch.setattr(runner, "_readiness", readiness)

    report = runner.run_network("demo", 100, preflight=True, manifest_path=manifest_path)

    assert report["status"] == "PREFLIGHT_PASS"
    assert ("readiness", False) in events
    assert "initialize_account_risk_baseline" not in events
    assert "qualification" not in events
