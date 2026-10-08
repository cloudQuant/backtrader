"""Source-fake checks for the V16 C01 Root staging boundary."""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
BRIDGE_TEST_PATH = (
    ROOT
    / "tests"
    / "unit"
    / "runtime"
    / "test_certification_simnow_c01_root_admission_bridge_source_fake.py"
)
V16_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_root_v16.py"
V18_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v18.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def _candidate_scope():
    old_path = list(sys.path)
    root_module_names = (
        "backtrader_runtime.certification_simnow_c01_front_transport_v12",
        "backtrader_runtime.certification_simnow_c01_root_v16",
        "backtrader_runtime._c01_front_transport_v12_v18_source",
        "backtrader_runtime._c01_native_td_read_v7_owner",
        "common.certification",
    )
    missing = object()
    saved = {name: sys.modules.get(name, missing) for name in root_module_names}
    certification_module = None
    old_certification_marker = missing
    try:
        fixture_tests = _load_module("_c01_v16_bridge_fixture_tests", BRIDGE_TEST_PATH)
        v16 = _load_module("backtrader_runtime.certification_simnow_c01_root_v16", V16_PATH)
        front = importlib.import_module(
            "backtrader_runtime.certification_simnow_c01_front_transport_v12"
        )
        front.__c01_source_sha256__ = hashlib.sha256(
            ROOT.joinpath(
                "backtrader_runtime", "certification_simnow_c01_front_transport_v12.py"
            ).read_bytes()
        ).hexdigest()
        with fixture_tests._candidate() as candidate:
            certification_module = importlib.import_module("common.certification")
            old_certification_marker = getattr(
                certification_module, "__c01_source_sha256__", missing
            )
            certification_module.__c01_source_sha256__ = hashlib.sha256(
                ROOT.joinpath(
                    "examples",
                    "000_live_certification",
                    "simnow_penetration",
                    "common",
                    "certification.py",
                ).read_bytes()
            ).hexdigest()
            bridge = candidate["bridge"]
            bridge.__name__ = "common.c01_root_admission_bridge"
            bridge.__c01_source_sha256__ = hashlib.sha256(
                BRIDGE_TEST_PATH.parents[3]
                .joinpath(
                    "examples",
                    "000_live_certification",
                    "simnow_penetration",
                    "common",
                    "c01_root_admission_bridge.py",
                )
                .read_bytes()
            ).hexdigest()

            owner = candidate["owner"]
            owner.__name__ = "backtrader_runtime._c01_native_td_read_v7_owner"
            sys.modules[owner.__name__] = owner
            admission_type = type(
                "FakeC01V18Admission",
                (),
                {
                    "__init__": lambda self, bindings: setattr(self, "bindings", bindings),
                    "active": lambda self: True,
                },
            )
            issuer = ModuleType(front._V18_MODULE_NAME)
            issuer.__c01_source_sha256__ = front._V18_SHA256
            issuer.PROFILE_ID = "C01_NATIVE_TD_READ_V18"
            issuer._WORKER_SHA256 = candidate["worker_sha"]
            issuer._OWNER_MODULE_NAME = owner.__name__
            issuer._C01V18Admission = admission_type

            class FakeIssuerResult:
                status = "PASS"
                reason = "read_only_candidate_complete"
                profile = "C01_NATIVE_TD_READ_V18"
                case_id = "C01"
                writes = 0
                admission_failure_stage = "none"
                admission_failure_class = "none"
                post_worker_failure_stage = "none"
                post_worker_failure_code = "none"

            issuer.C01NativeTdReadV18Result = FakeIssuerResult
            helpers = dict(candidate["helpers"])
            helpers["owner_now_utc"] = owner._now_utc
            bundle = front.VerifiedC01V18SourceBundle(
                ROOT,
                issuer,
                owner,
                helpers,
                _factory=front._BUNDLE_FACTORY,
            )
            bindings = candidate["admission"].bindings
            candidate["admission"] = admission_type(bindings)
            root_custody = ModuleType(
                "backtrader_runtime.certification_simnow_c01_root_custody_v16"
            )
            root_custody.__c01_source_sha256__ = "b" * 64
            yield v16, front, candidate, bundle, bridge, certification_module, root_custody
    finally:
        sys.path[:] = old_path
        sys.modules.pop("_c01_v16_bridge_fixture_tests", None)
        if certification_module is not None:
            if old_certification_marker is missing:
                try:
                    delattr(certification_module, "__c01_source_sha256__")
                except AttributeError:
                    pass
            else:
                certification_module.__c01_source_sha256__ = old_certification_marker
        for name, value in saved.items():
            if value is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def _stage(v16, candidate):
    return v16.stage_current_c01_candidate(
        admission=candidate["admission"],
        pair_binding=candidate["pair"],
        process=candidate["process"],
        validation=candidate["validation"],
        artifacts=candidate["artifacts"],
    )


def test_stage_is_bound_once_and_only_returns_a_blocked_pending_result():
    with _candidate_scope() as (
        v16,
        front,
        candidate,
        bundle,
        bridge,
        certification_module,
        root_custody,
    ):
        with v16.c01_root_invocation_scope(
            front, bundle, bridge, certification_module, root_custody
        ) as scope:
            stage = _stage(v16, candidate)
            nonce = v16.current_c01_root_invocation_nonce()
            pending = v16.pending_root_admission_result(nonce, _issuer_result(bundle.issuer))
            assert stage.request_count == 8
            assert stage.auth_login_callback_count == 2
            assert stage.query_callback_count == 6
            assert stage.snapshot_count == 2
            assert stage.write_invocation_count == 0
            assert stage.biz_type_state == "unclassified"
            assert pending.to_dict() == {
                "case_id": "C01",
                "profile": "C01_NATIVE_TD_READ_V18",
                "status": "BLOCKED",
                "reason": "candidate_complete_pending_root_admission",
                "writes": 0,
                "case_receipt_authority": "none",
            }
            assert "nonce" in repr(pending)
            assert nonce.__repr__() not in repr(pending)
            assert v16.verify_current_c01_request_ledger(scope, pending) is None
            with pytest.raises(v16.C01RootV16Error, match="root_postverify_unconfigured"):
                v16.record_root_native_ledger_receipt(
                    scope,
                    pending,
                    root_custody_module=root_custody,
                    receipt=object(),
                )
            with pytest.raises(v16.C01RootV16Error, match="candidate_stage_reused"):
                _stage(v16, candidate)
            with pytest.raises(v16.C01RootV16Error, match="root_postverify_unconfigured"):
                v16._mint_root_postverify_proof(
                    scope=scope,
                    pending=pending,
                    source_postverify_receipt=object(),
                    runtime_postverify_receipt=object(),
                    artifact_postverify_receipt=object(),
                    account_binding_receipt=object(),
                    native_ledger_receipt=scope.verification,
                )

        assert bundle._active is True
        assert pending.to_dict()["status"] == "BLOCKED"
        wrong_custody_module = ModuleType(
            "backtrader_runtime.certification_simnow_c01_root_custody_v16"
        )
        wrong_custody_module.__c01_source_sha256__ = "c" * 64
        with pytest.raises(v16.C01RootV16Error, match="root_postverify_unconfigured"):
            v16.finalize_c01_root_case_result(
                pending,
                root_custody_module=wrong_custody_module,
                postverify_proof=True,
            )
        with pytest.raises(v16.C01RootV16Error, match="root_postverify_unconfigured"):
            v16.finalize_c01_root_case_result(
                pending,
                root_custody_module=root_custody,
                postverify_proof=True,
            )


def test_v18_scope_validation_accepts_stage_zero_and_rejects_foreign_scope():
    with _candidate_scope() as (
        v16,
        front,
        candidate,
        _fake_bundle,
        projection,
        certification_module,
        root_custody,
    ):
        assert hashlib.sha256(V18_PATH.read_bytes()).hexdigest() == front._V18_SHA256
        issuer = _load_module(front._V18_MODULE_NAME, V18_PATH)
        issuer.__c01_source_sha256__ = front._V18_SHA256
        owner = candidate["owner"]
        actual_bundle = front.VerifiedC01V18SourceBundle(
            ROOT,
            issuer,
            owner,
            _fake_bundle.helpers,
            _factory=front._BUNDLE_FACTORY,
        )
        with v16.c01_root_invocation_scope(
            front, actual_bundle, projection, certification_module, root_custody
        ) as scope:
            assert scope.stage_count == 0
            assert v16.current_c01_root_invocation_nonce() is scope.nonce
            resolved_root, resolved_owner, resolved_helpers = issuer._validate_root_scope(
                scope, issuer
            )
            assert resolved_root.resolve(strict=True) == ROOT.resolve(strict=True)
            assert resolved_owner is owner
            assert resolved_helpers is actual_bundle.helpers

            foreign_scope = v16._C01RootInvocationScope(
                front,
                actual_bundle,
                projection,
                certification_module,
                root_custody,
                _factory=v16._SCOPE_FACTORY,
            )
            with pytest.raises(issuer._IssuerError, match="root_invocation_scope_invalid"):
                issuer._validate_root_scope(foreign_scope, issuer)
            foreign_scope.active = False
        actual_bundle._active = False


def _issuer_result(issuer):
    return issuer.C01NativeTdReadV18Result()


@pytest.mark.parametrize(
    "mutation, expected_code",
    [
        ("account", "candidate_evidence_invalid"),
        ("session", "candidate_evidence_invalid"),
        ("cleanup", "candidate_evidence_invalid"),
        ("order_write", "candidate_evidence_invalid"),
    ],
)
def test_stage_rejects_misbinding_write_or_incomplete_cleanup(mutation, expected_code):
    with _candidate_scope() as (
        v16,
        _front,
        candidate,
        bundle,
        bridge,
        certification_module,
        root_custody,
    ):
        if mutation == "account":
            candidate["admission"].bindings = {
                **candidate["admission"].bindings,
                "account_scope_sha256": "f" * 64,
            }
        elif mutation == "session":
            worker_payload = candidate["process"].worker_receipt.to_dict()
            for callback in worker_payload["callbacks"]:
                if callback["kind"] == "login":
                    callback["session_id"] = "different-session"
            worker = candidate["protocol"].parse_worker_frame(
                candidate["protocol"].encode_worker_frame(worker_payload)
            )
            candidate["process"] = dataclasses.replace(
                candidate["process"], worker_receipt=worker
            )
        elif mutation == "cleanup":
            lifecycle = dataclasses.replace(
                candidate["process"].process_lifecycle, job_active_count=1
            )
            candidate["process"] = dataclasses.replace(
                candidate["process"], process_lifecycle=lifecycle
            )
        else:
            worker_payload = candidate["process"].worker_receipt.to_dict()
            worker_payload["write_counters"]["ReqOrderInsert"] = 1
            worker = candidate["protocol"].parse_worker_frame(
                candidate["protocol"].encode_worker_frame(worker_payload)
            )
            candidate["process"] = dataclasses.replace(
                candidate["process"], worker_receipt=worker
            )

        with v16.c01_root_invocation_scope(
            _front, bundle, bridge, certification_module, root_custody
        ):
            with pytest.raises(v16.C01RootV16Error) as exc:
                _stage(v16, candidate)
        assert str(exc.value) == expected_code


def test_nonce_and_manual_result_payload_cannot_finalize_a_case():
    with _candidate_scope() as (
        v16,
        _front,
        candidate,
        bundle,
        bridge,
        certification_module,
        root_custody,
    ):
        with v16.c01_root_invocation_scope(
            _front, bundle, bridge, certification_module, root_custody
        ):
            _stage(v16, candidate)
            good_nonce = v16.current_c01_root_invocation_nonce()
            bad_nonce = object()
            with pytest.raises(v16.C01RootV16Error, match="candidate_pending_binding_invalid"):
                v16.pending_root_admission_result(bad_nonce, _issuer_result(bundle.issuer))
            pending = v16.pending_root_admission_result(
                good_nonce, _issuer_result(bundle.issuer)
            )

        with pytest.raises(v16.C01RootV16Error, match="root_postverify_unconfigured"):
            v16.finalize_c01_root_case_result(
                pending,
                root_custody_module=root_custody,
                postverify_proof={"status": "PASS"},
            )
        with pytest.raises(v16.C01RootV16Error, match="case_result_factory_required"):
            v16.C01RootCaseResultReceipt({"case_id": "C01", "status": "PASS"})


def test_unscoped_hook_and_unpinned_bridge_fail_closed():
    with _candidate_scope() as (
        v16,
        _front,
        candidate,
        bundle,
        bridge,
        certification_module,
        root_custody,
    ):
        with pytest.raises(v16.C01RootV16Error, match="root_invocation_not_active"):
            _stage(v16, candidate)
        certification_module.__c01_source_sha256__ = "0" * 64
        with pytest.raises(v16.C01RootV16Error, match="certification_source_invalid"):
            with v16.c01_root_invocation_scope(
                _front, bundle, bridge, certification_module, root_custody
            ):
                pass
        certification_module.__c01_source_sha256__ = hashlib.sha256(
            ROOT.joinpath(
                "examples",
                "000_live_certification",
                "simnow_penetration",
                "common",
                "certification.py",
            ).read_bytes()
        ).hexdigest()
        bridge.__c01_source_sha256__ = "0" * 64
        with pytest.raises(v16.C01RootV16Error, match="projection_source_invalid"):
            with v16.c01_root_invocation_scope(
                _front, bundle, bridge, certification_module, root_custody
            ):
                pass
