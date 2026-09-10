import base64
import builtins
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
from pathlib import Path
import subprocess

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

import examples.strategy_candidate_approval as demo_approval
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
    importlib.import_module("examples.012_1_midfreq_cross_exchange.run"),
    importlib.import_module("examples.012_2_event_driven_cross_exchange.run"),
]
NOW = datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc)


def _zulu(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _public_key(private_key, path):
    raw = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_bytes(raw)
    return raw


def _runtime_source():
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
        "public_key_sha256": hashlib.sha256(trust_raw).hexdigest(),
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
    raw = (json.dumps(artifact["receipt"], sort_keys=True) + "\n").encode()
    artifact["receipt_path"].write_bytes(raw)
    artifact["candidate"]["demo_approval"]["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    artifact["manifest_path"].write_text(
        json.dumps(artifact["manifest"], sort_keys=True), encoding="utf-8"
    )


def _verify(runner, artifact):
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
    current = datetime.now(timezone.utc)
    artifact = _approval_artifact(
        runner,
        tmp_path,
        issued_at=current - timedelta(hours=1),
        expires_at=current + timedelta(hours=1),
    )
    monkeypatch.setattr(runner, "MANIFEST_PATH", artifact["manifest_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_TRUST_ROOT", artifact["trust_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_PUBLIC_KEY_SHA256", artifact["trust_sha256"])
    monkeypatch.setattr(
        runner,
        "collect_runtime_source_provenance",
        lambda: copy.deepcopy(artifact["runtime_source"]),
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
    manifest_path = tmp_path / "strategy-candidate-manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "build_store", lambda *_args, **_kwargs: calls.append("store"))

    with pytest.raises(runner.DemoApprovalError, match="canonical manifest"):
        runner.run_network("demo", 1000, manifest_path=manifest_path)

    assert calls == []


@pytest.mark.parametrize("runner", RUNNERS)
def test_invalid_signature_stops_before_store_or_write(runner, monkeypatch, tmp_path):
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
    monkeypatch.setattr(runner, "MANIFEST_PATH", artifact["manifest_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_TRUST_ROOT", artifact["trust_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_PUBLIC_KEY_SHA256", artifact["trust_sha256"])
    monkeypatch.setattr(
        runner,
        "collect_runtime_source_provenance",
        lambda: copy.deepcopy(artifact["runtime_source"]),
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
    monkeypatch.setattr(runner, "MANIFEST_PATH", artifact["manifest_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_TRUST_ROOT", artifact["trust_path"])
    monkeypatch.setattr(runner, "DEMO_APPROVAL_PUBLIC_KEY_SHA256", artifact["trust_sha256"])
    monkeypatch.setattr(runner, "collect_runtime_source_provenance", lambda: changed)
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

    assert hashlib.sha256(trust_root.read_bytes()).hexdigest() == (
        "2563eac8a40505f80903dd2659fe8667cafd3b8d0d5290db6620d4b3293e8f98"
    )
