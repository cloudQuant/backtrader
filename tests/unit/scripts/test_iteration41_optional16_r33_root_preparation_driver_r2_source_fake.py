"""Sourcefake contracts for the additive R2 Root preparation driver."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(r"D:\source_code\backtrader")
DRIVER_PATH = ROOT / "scripts/iteration41_optional16_r33_root_preparation_driver_r2.py"
SPEC = importlib.util.spec_from_file_location("optional16_root_preparation_driver_r2_test", DRIVER_PATH)
assert SPEC is not None and SPEC.loader is not None
DRIVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DRIVER)


class _ScopeState:
    def __init__(self, state):
        self.state = state


def _successful_receipt(scope_state="CLOSED"):
    return {
        "schema": DRIVER.CALL_SCHEMA,
        "status": "PREPARATION_VERIFIED_NO_AUTHORITY",
        "reason_code": "held_source_preparation_complete",
        "evidence_level": "ROOT_HELD_PREPARATION_ONLY",
        "public_rows": 582,
        "full_union_rows": 620,
        "software_rows": 5,
        "held_rows": 625,
        "profiler_modules": 3,
        "boundary": "before_r5_worker_installer",
        "scope_state": scope_state,
        "authority": "NONE",
        "activation": "NOT_ENTERED",
        "control": "NOT_ENTERED",
        "child": "NOT_ENTERED",
        "diagnostic_phase": "result_check",
        "diagnostic_category": "none",
        "diagnostic_code": "preparation_complete",
    }


def test_request_defaults_closed_without_public_reads(monkeypatch):
    monkeypatch.setattr(
        DRIVER,
        "_read_public_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected read")),
    )
    result = DRIVER.prepare_root_held_source_gate()
    assert result["status"] == "BLOCKED"
    assert result["reason_code"] == "preparation_request_required"
    assert result["scope_state"] == "NOT_OPENED"
    assert result["diagnostic_phase"] == "root_preflight"
    assert result["diagnostic_code"] == "root_setup_failed"
    assert DRIVER._ATTEMPT_STARTED is False
    assert DRIVER._RETAINED_ATTEMPTS == []


def test_one_shot_rejection_preserves_retained_state(monkeypatch):
    monkeypatch.setattr(DRIVER, "_ATTEMPT_STARTED", True)
    scope = _ScopeState("RETAINED")
    monkeypatch.setattr(DRIVER, "_RETAINED_ATTEMPTS", [(None, None, None, None, scope)])

    result = DRIVER.prepare_root_held_source_gate(requested=True)

    assert result["status"] == "BLOCKED_RETAINED"
    assert result["reason_code"] == "one_shot_attempt_already_used"
    assert result["scope_state"] == "RETAINED"
    assert result["retry"] == "DO_NOT_RETRY_IN_THIS_PROCESS"


def test_fixed_payload_is_built_from_pinned_public_sources_only():
    payload_raw, loaded = DRIVER._build_payload()
    assert type(payload_raw) is bytes
    assert 0 < len(payload_raw) <= DRIVER.MAX_PAYLOAD_BYTES
    assert len(loaded) == 3
    r5, invoke, whole = loaded
    assert r5.__verified_source_sha256__ == DRIVER.R5_SHA256
    assert invoke.__verified_source_sha256__ == DRIVER.R27_INVOKE_SHA256
    assert whole.__verified_source_sha256__ == DRIVER.R27_WHOLE_SHA256
    assert r5.ROOT_ACTUAL_ENABLED is False
    assert invoke.ROOT_ACTUAL_ENABLED is False
    assert whole.ROOT_ACTUAL_ENABLED is False
    assert whole.ROOT_NATIVE_ENABLED is False
    assert b"parent_deadline_monotonic" in payload_raw


def test_success_receipt_requires_exact_rows_and_diagnostic_fields():
    receipt = _successful_receipt()
    assert DRIVER._verified_receipt(receipt, _ScopeState("CLOSED")) is True
    assert DRIVER._verified_receipt(receipt, _ScopeState("OPEN")) is False

    for field, value in (
        ("public_rows", 581),
        ("software_rows", 4),
        ("profiler_modules", 2),
        ("boundary", "worker_installer_entered"),
        ("authority", "ROOT"),
        ("child", "ENTERED"),
        ("diagnostic_phase", "raw/path"),
        ("diagnostic_category", "credential"),
        ("diagnostic_code", "private text"),
    ):
        changed = dict(receipt)
        changed[field] = value
        assert DRIVER._verified_receipt(changed, _ScopeState("CLOSED")) is False

    extra = dict(receipt, raw_payload="forbidden")
    assert DRIVER._verified_receipt(extra, _ScopeState("CLOSED")) is False


def test_finite_call_diagnostics_are_projected_and_unknowns_are_rejected():
    projected = DRIVER._diagnostic_from_receipt(
        {
            "diagnostic_phase": "module_binding",
            "diagnostic_category": "source_contract",
            "diagnostic_code": "module_binding_rejected",
            "detail": "private input must not be copied",
        }
    )
    assert projected == {
        "diagnostic_phase": "module_binding",
        "diagnostic_category": "source_contract",
        "diagnostic_code": "module_binding_rejected",
    }
    assert DRIVER._diagnostic_from_receipt({"diagnostic_phase": "raw path"}) == {
        "diagnostic_phase": "root_call_adapter",
        "diagnostic_category": "unexpected",
        "diagnostic_code": "unexpected_exception",
    }
