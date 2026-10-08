"""Source-fake integration for the additive current C01 front-selection closure."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import time
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
ISSUER_PATH = ROOT / "backtrader_runtime" / "certification_simnow_c01_native_td_read_v3.py"
OWNER_MODULE_NAME = "backtrader_runtime._c01_native_td_read_v3_owner"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if path == ISSUER_PATH:
        module.__c01_source_sha256__ = _sha256(path)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_contract_fixtures():
    path = ROOT / "tests" / "unit" / "runtime" / "test_certification_simnow_c01_v2_contract.py"
    return _load_module("_c01_v2_contract_test_fixtures_for_v3", path)


class _FakeConnector:
    def __init__(self, outcomes):
        self.outcomes = {host: list(samples) for host, samples in outcomes.items()}
        self.elapsed = 0.0

    def clock(self):
        return self.elapsed

    def connect(self, host, port, timeout):
        outcome = self.outcomes[host].pop(0)
        if outcome is None:
            self.elapsed += timeout
            raise TimeoutError("source-fake transport failure")
        self.elapsed += outcome / 1000.0

        class _Socket:
            def close(self):
                return None

        return _Socket()


@contextlib.contextmanager
def _verified_v3_helpers():
    issuer = _load_module("_c01_native_td_read_v3_sourcefake_issuer", ISSUER_PATH)
    owner = None
    try:
        issuer._verify_public_profile_sources(ROOT)
        owner = issuer._load_frozen_owner(ROOT)
        issuer._verify_source_manifest(ROOT, owner)
        with owner._verified_helper_bundle() as bundle:
            helpers = dict(bundle)
            helpers["owner_now_utc"] = owner._now_utc
            yield issuer, owner, helpers
    finally:
        if owner is not None and sys.modules.get(OWNER_MODULE_NAME) is owner:
            sys.modules.pop(OWNER_MODULE_NAME, None)
        sys.modules.pop("_c01_native_td_read_v3_sourcefake_issuer", None)


def _front_pairs():
    return [
        {"md_front": "tcp://192.0.2.1:10001", "td_front": "tcp://192.0.2.2:10002"},
        {"md_front": "tcp://192.0.2.3:10003", "td_front": "tcp://192.0.2.4:10004"},
    ]


def _latency_first_degraded_fixture():
    return _FakeConnector(
        {
            "192.0.2.1": [None, 4.0, None],
            "192.0.2.2": [None, 5.0, None],
            "192.0.2.3": [9.0, 10.0, 11.0],
            "192.0.2.4": [9.0, 10.0, 11.0],
        }
    )


def _assert_original_validator_accepts_only_blocked_synthetic_candidate(
    helpers, owner, fixtures, binding
):
    payload = fixtures._payload()
    payload["pair_binding"] = binding.to_dict()
    worker_sha = owner._SOURCE_PINS[
        "backtrader_runtime/certification_simnow_c01_native_v2.py"
    ]
    payload["worker_source_sha256"] = worker_sha
    artifacts, _docs = fixtures._artifact_bundle(payload)
    worker = helpers["protocol"].parse_worker_frame(
        helpers["protocol"].encode_worker_frame(payload)
    )
    process = helpers["protocol"].C01ProcessLifecycleReceipt(
        run_nonce=payload["run_nonce"],
        parent_pid=payload["parent_pid"],
        worker_pid=payload["worker_pid"],
        worker_source_sha256=worker_sha,
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
    validation = helpers["contract"].validate_c01_candidate(
        worker,
        process,
        expected_pair_binding=binding,
        expected_worker_source_sha256=worker_sha,
        expected_account_scope_sha256=fixtures._ACCOUNT_SCOPE_SHA256,
        expected_credential_binding_sha256=fixtures._CREDENTIAL_BINDING_SHA256,
        private_snapshot_artifacts=artifacts,
        expected_broker_id=fixtures._BROKER_ID,
        expected_user_id=fixtures._USER_ID,
    )
    assert type(validation) is helpers["protocol"].C01CandidateValidation
    assert validation.eligible_for_protected_admission is True
    assert validation.status == "BLOCKED"
    assert validation.reasons == (helpers["contract"]._PROTECTED_ADMISSION_REQUIRED,)
    assert validation.checked_request_count == 8
    assert validation.checked_snapshot_count == 2
    return validation


def test_v3_manifest_and_root_admission_bind_the_current_selector_closure():
    with _verified_v3_helpers() as (issuer, _owner, _helpers):
        manifest_raw = (ROOT / issuer._SOURCE_MANIFEST_PATH).read_bytes()
        manifest = json.loads(manifest_raw)
        assert manifest["profile_id"] == "C01_NATIVE_TD_READ_V3"
        assert manifest["admission_bound_files"] == [
            "backtrader_runtime/certification_simnow_c01_native_td_read_v3.py",
            "examples/000_live_certification/simnow_penetration/cases/C01/run_v3.py",
        ]
        assert manifest["source_files"]["scripts/ctp_000_paired_front_selector.py"] == _sha256(
            ROOT / "scripts" / "ctp_000_paired_front_selector.py"
        )
        assert manifest["source_files"]["scripts/ctp_000_front_handoff.py"] == _sha256(
            ROOT / "scripts" / "ctp_000_front_handoff.py"
        )
        assert manifest["source_files"]["backtrader_runtime/ctp_front_pair_probe.py"] == _sha256(
            ROOT / "backtrader_runtime" / "ctp_front_pair_probe.py"
        )

        root_wrapper = _load_module(
            "_c01_native_td_read_v3_root_sourcefake",
            ROOT / "scripts" / "run_simnow_c01_native_td_read_v3_root_activation_r1.py",
        )
        assert root_wrapper._validate_manifest(manifest_raw) == manifest["source_files"]
        assert set(root_wrapper._ADMISSION_BOUND_PINS) == set(manifest["admission_bound_files"])
        assert root_wrapper._profile_contract_sha256(ISSUER_PATH.read_bytes()) == (
            issuer.PROFILE_CONTRACT_SHA256
        )
        with pytest.raises(ValueError, match="root_source_pin_required"):
            root_wrapper._parse_root_arguments(
                [],
                (ROOT / "scripts" / "run_simnow_c01_native_td_read_v3_root_activation_r1.py").read_bytes(),
            )


def test_multi_pair_latency_first_handoff_reaches_original_native_pre_admission_validator():
    fixtures = _load_contract_fixtures()
    front_pairs = _front_pairs()
    connector = _latency_first_degraded_fixture()

    with _verified_v3_helpers() as (issuer, owner, helpers):
        audit = {}
        binding = issuer._select_current_pair(
            helpers,
            front_pairs,
            deadline=time.monotonic() + 30.0,
            audit_sink=audit,
            connector=connector.connect,
            probe_clock=connector.clock,
        )

        assert type(binding) is helpers["protocol"].C01PairBinding
        assert binding.selected_index == 0
        assert binding.td_front == front_pairs[0]["td_front"]
        assert audit["fresh_pair_selection"]["degraded_candidate"] is True
        assert audit["fresh_pair_selection"]["observation_binding_sha256"] == (
            binding.selection_sha256
        )

        _assert_original_validator_accepts_only_blocked_synthetic_candidate(
            helpers, owner, fixtures, binding
        )


def test_one_pair_one_of_three_handoff_reaches_original_native_pre_admission_validator():
    fixtures = _load_contract_fixtures()
    front_pairs = _front_pairs()[:1]
    connector = _FakeConnector(
        {
            "192.0.2.1": [None, 6.0, None],
            "192.0.2.2": [None, 7.0, None],
        }
    )

    with _verified_v3_helpers() as (issuer, owner, helpers):
        audit = {}
        binding = issuer._select_current_pair(
            helpers,
            front_pairs,
            deadline=time.monotonic() + 30.0,
            audit_sink=audit,
            connector=connector.connect,
            probe_clock=connector.clock,
        )
        assert binding.selected_index == 0
        assert audit["fresh_pair_selection"]["degraded_candidate"] is True
        _assert_original_validator_accepts_only_blocked_synthetic_candidate(
            helpers, owner, fixtures, binding
        )


def test_one_sided_current_observation_does_not_issue_a_pair_binding():
    front_pairs = [
        {"md_front": "tcp://192.0.2.1:10001", "td_front": "tcp://192.0.2.2:10002"}
    ]
    connector = _FakeConnector(
        {
            "192.0.2.1": [1.0, 2.0, 3.0],
            "192.0.2.2": [None, None, None],
        }
    )

    with _verified_v3_helpers() as (issuer, _owner, helpers):
        with pytest.raises(issuer._IssuerError, match="fresh_pair_no_transport_candidate"):
            issuer._select_current_pair(
                helpers,
                front_pairs,
                deadline=time.monotonic() + 30.0,
                connector=connector.connect,
                probe_clock=connector.clock,
            )


def test_v3_fixed_case_runner_is_default_closed():
    runner = _load_module(
        "_c01_native_td_read_v3_fixed_runner_sourcefake",
        ROOT / "examples" / "000_live_certification" / "simnow_penetration" / "cases" / "C01" / "run_v3.py",
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert runner.main([]) == 2
    result = json.loads(output.getvalue())
    assert result["certification"] == "BLOCKED"
    assert result["reason"] == "managed_ctp_v3_candidate_not_registered"
    assert result["writes"] == 0
    assert result["write_policy"] == "NO_WRITE"
    assert runner.ISSUER_SHA256 == _sha256(ISSUER_PATH)
