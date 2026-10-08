"""Fake-only checks for the typed C01 Root evidence projection."""
from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SUITE_ROOT = ROOT / "examples" / "000_live_certification" / "simnow_penetration"
BRIDGE_PATH = SUITE_ROOT / "common" / "c01_root_admission_bridge.py"
V3_SOURCE_FAKE_PATH = (
    ROOT / "tests" / "unit" / "runtime" / "test_certification_simnow_c01_native_td_read_v3_source_fake.py"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _candidate():
    old_path = list(sys.path)
    sys.path.insert(0, str(SUITE_ROOT))
    common_modules = (
        "common",
        "common.case_engine",
        "common.certification",
        "common.completion_invariants",
    )
    missing = object()
    saved_modules = {name: sys.modules.get(name, missing) for name in common_modules}
    try:
        v3_tests = _load_module("_c01_root_bridge_v3_public_fixtures", V3_SOURCE_FAKE_PATH)
        bridge = _load_module("_c01_root_admission_bridge_test", BRIDGE_PATH)
        fixtures = v3_tests._load_contract_fixtures()
        with v3_tests._verified_v3_helpers() as (_issuer, owner, helpers):
            protocol = helpers["protocol"]
            contract = helpers["contract"]
            supervisor = helpers["supervisor"]
            pair = protocol.C01PairBinding(
                selected_index=0,
                selection_sha256="a" * 64,
                md_front_sha256="b" * 64,
                td_front_sha256="c" * 64,
                td_front="tcp://192.0.2.2:10002",
                selected_at_utc="2026-10-02T01:02:03Z",
            )
            worker_sha = owner._SOURCE_PINS[
                "backtrader_runtime/certification_simnow_c01_native_v2.py"
            ]
            payload = fixtures._payload()
            payload["pair_binding"] = pair.to_dict()
            payload["worker_source_sha256"] = worker_sha
            payload["parent_pid"] = os.getpid()
            payload["worker_pid"] = os.getpid() + 1
            for callback in payload["callbacks"]:
                if callback["kind"] == "login":
                    callback["session_id"] = "123"
            artifacts, _docs = fixtures._artifact_bundle(payload)
            for index, phase in enumerate(("baseline", "final")):
                ref = f"snapshots/{phase}.json"
                document = protocol.parse_private_snapshot_artifact(artifacts[ref]).to_dict()
                document["scope"]["session_id"] = "123"
                artifacts[ref] = protocol.encode_private_snapshot_artifact(document)
                payload["snapshots"][index]["artifact_sha256"] = protocol.sha256_bytes(
                    artifacts[ref]
                )
                payload["snapshots"][index]["session_id"] = "123"
            worker = protocol.parse_worker_frame(protocol.encode_worker_frame(payload))
            lifecycle = protocol.C01ProcessLifecycleReceipt(
                run_nonce=worker.run_nonce,
                parent_pid=worker.parent_pid,
                worker_pid=worker.worker_pid,
                worker_source_sha256=worker.worker_source_sha256,
                assigned_before_resume=True,
                stdin_fully_sent=True,
                stdout_eof=True,
                stderr_eof=True,
                process_exit_observed=True,
                process_exit_code=0,
                job_active_count=0,
                handles_closed=True,
                timed_out=False,
                forced_kill=False,
                containment="windows_job",
                reason="normal_exit",
                status="BLOCKED",
            )
            process = supervisor.C01SupervisorResult(
                status="BLOCKED",
                reason="candidate_transport_complete",
                worker_receipt=worker,
                process_lifecycle=lifecycle,
            )
            validation = contract.validate_c01_candidate(
                worker,
                lifecycle,
                expected_pair_binding=pair,
                expected_worker_source_sha256=worker_sha,
                expected_account_scope_sha256=fixtures._ACCOUNT_SCOPE_SHA256,
                expected_credential_binding_sha256=fixtures._CREDENTIAL_BINDING_SHA256,
                private_snapshot_artifacts=artifacts,
                expected_broker_id=fixtures._BROKER_ID,
                expected_user_id=fixtures._USER_ID,
            )
            admission = SimpleNamespace(
                bindings={
                    "account_scope_sha256": fixtures._ACCOUNT_SCOPE_SHA256,
                    "credential_binding_sha256": fixtures._CREDENTIAL_BINDING_SHA256,
                }
            )
            yield {
                "bridge": bridge,
                "protocol": protocol,
                "contract": contract,
                "supervisor": supervisor,
                "owner": owner,
                "helpers": helpers,
                "admission": admission,
                "pair": pair,
                "process": process,
                "validation": validation,
                "artifacts": artifacts,
                "worker_sha": worker_sha,
            }
    finally:
        sys.path[:] = old_path
        sys.modules.pop("_c01_root_admission_bridge_test", None)
        sys.modules.pop("_c01_root_bridge_v3_public_fixtures", None)
        sys.modules.pop("_c01_v2_contract_test_fixtures_for_v3", None)
        for name, value in saved_modules.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def _project(candidate, **overrides):
    args = {
        "protocol": candidate["protocol"],
        "contract": candidate["contract"],
        "supervisor": candidate["supervisor"],
        "owner": candidate["owner"],
        "helpers": candidate["helpers"],
        "admission": candidate["admission"],
        "pair_binding": candidate["pair"],
        "process": candidate["process"],
        "validation": candidate["validation"],
        "artifacts": candidate["artifacts"],
        "expected_worker_source_sha256": candidate["worker_sha"],
    }
    args.update(overrides)
    return candidate["bridge"].project_c01_root_candidate(**args)


def test_projection_accepts_only_complete_synthetic_receipt_and_remains_review_only():
    with _candidate() as candidate:
        result = _project(candidate)

    assert result.receipt_auth_login_callback_count == 2
    assert result.receipt_request_count == 8
    assert result.receipt_query_callback_count == 6
    assert result.receipt_snapshot_count == 2
    assert result.worker_reported_write_invocations == 0
    assert result.biz_type_state == "unclassified"
    assert result.completion_report.status.value == "INCOMPLETE"
    assert len(result.completion_report.missing_invariants) == 2
    assert result.completion_report.certification_pass is False
    assert result.completion_report.dispatch_permitted is False
    assert result.completion_report.source_authenticity_verified is False
    assert "private" in repr(result)
    assert "account" not in repr(result).lower()


@pytest.mark.parametrize(
    "mutation, expected_code",
    [
        ("account_binding", "candidate_worker_receipt_binding_invalid"),
        ("worker_pin", "candidate_worker_receipt_binding_invalid"),
        ("candidate_validation", "candidate_validation_ineligible"),
        ("lifecycle", "candidate_lifecycle_incomplete"),
        ("order_write", "candidate_write_activity_present"),
        ("session_binding", "candidate_completion_incomplete"),
    ],
)
def test_projection_rejects_misbinding_and_incomplete_candidates(mutation, expected_code):
    with _candidate() as candidate:
        kwargs = {}
        if mutation == "account_binding":
            kwargs["admission"] = SimpleNamespace(
                bindings={
                    "account_scope_sha256": "f" * 64,
                    "credential_binding_sha256": candidate["admission"].bindings[
                        "credential_binding_sha256"
                    ],
                }
            )
        elif mutation == "worker_pin":
            kwargs["expected_worker_source_sha256"] = "0" * 64
        elif mutation == "candidate_validation":
            kwargs["validation"] = dataclasses.replace(
                candidate["validation"], eligible_for_protected_admission=False
            )
        elif mutation == "order_write":
            payload = candidate["process"].worker_receipt.to_dict()
            payload["write_counters"]["ReqOrderInsert"] = 1
            worker = candidate["protocol"].parse_worker_frame(
                candidate["protocol"].encode_worker_frame(payload)
            )
            kwargs["process"] = dataclasses.replace(
                candidate["process"], worker_receipt=worker
            )
        elif mutation == "session_binding":
            payload = candidate["process"].worker_receipt.to_dict()
            for callback in payload["callbacks"]:
                if callback["kind"] == "login":
                    callback["session_id"] = "456"
            worker = candidate["protocol"].parse_worker_frame(
                candidate["protocol"].encode_worker_frame(payload)
            )
            kwargs["process"] = dataclasses.replace(
                candidate["process"], worker_receipt=worker
            )
        else:
            process = candidate["process"]
            lifecycle = dataclasses.replace(process.process_lifecycle, job_active_count=1)
            kwargs["process"] = dataclasses.replace(process, process_lifecycle=lifecycle)

        with pytest.raises(candidate["bridge"].C01RootBridgeError) as exc:
            _project(candidate, **kwargs)

    assert str(exc.value) == expected_code

