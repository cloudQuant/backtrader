"""Source-fake validation of the V20 candidate/outer-close boundary."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
ADJUDICATOR_PATH = ROOT / "backtrader_runtime/certification_simnow_c01_root_formal_adjudicator_v1.py"
MODULE_NAME = "backtrader_runtime.certification_simnow_c01_root_formal_adjudicator_v1"


def _load_adjudicator():
    raw = ADJUDICATOR_PATH.read_bytes()
    module = ModuleType(MODULE_NAME)
    module.__file__ = str(ADJUDICATOR_PATH)
    module.__package__ = "backtrader_runtime"
    import hashlib

    module.__c01_source_sha256__ = hashlib.sha256(raw).hexdigest()
    exec(compile(raw, str(ADJUDICATOR_PATH), "exec", dont_inherit=True), module.__dict__)
    return module


def _candidate_projection():
    return {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": "C01_NATIVE_TD_READ_V20",
        "profile": "C01_NATIVE_TD_READ_V20",
        "reason": "candidate_root_handoff_written",
        "write_policy": "NO_WRITE",
        "writes": 0,
        "receipt_type": "C01RootContentCustodyReceipt",
        "receipt_verified": True,
        "source_closure_verified": True,
        "root_postverify_verified": True,
        "request_count": 8,
        "query_callback_count": 6,
        "snapshot_count": 2,
        "write_invocation_count": 0,
        "outer_job_empty": None,
        "stdout_eof": None,
        "stderr_eof": None,
        "stderr_empty": None,
        "job_handles_closed": None,
        "reader_threads_joined": None,
        "cleanup_verified": None,
    }


def _wrapper_receipt(projection=None, *, frame=None, process_frame=None):
    driver = ModuleType("_c01_v20_root_actual_driver")
    process_type = type("C01V20ParentProcessReceipt", (), {})
    driver.C01V20ParentProcessReceipt = process_type
    bound_frame = object() if frame is None else frame
    process = process_type()
    process.frame = bound_frame if process_frame is None else process_frame
    process.call_nonce = object()
    process.exit_code = 0
    receipt = SimpleNamespace(
        projection_raw=json.dumps(
            _candidate_projection() if projection is None else projection,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        frame=bound_frame,
        parent_process_receipt=process,
        call_nonce=process.call_nonce,
        parent_driver_module=driver,
    )
    return receipt


def test_adjudicator_accepts_only_the_child_blocked_candidate_shape():
    adjudicator = _load_adjudicator()
    adjudicator._validate_wrapper_projection(_wrapper_receipt())


def test_source_function_lookup_supports_root_v17_marker_free_object_maps():
    adjudicator = _load_adjudicator()
    root_module = ModuleType(adjudicator._ROLE_NAMES["root"])
    root_path = adjudicator._ROLE_PATHS["root"]
    rows = MappingProxyType({"validate_c01_root_invocation_receipt": object()})
    assert adjudicator._module_path_for(root_module, {root_path: rows}) == root_path

    package_module = ModuleType(
        "examples.000_live_certification.simnow_penetration.common.c01_root_ledger_v1"
    )
    package_path = (
        "examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py"
    )
    assert adjudicator._module_path_for(package_module, {package_path: rows}) == package_path


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(certification="PASS"),
        lambda value: value.update(reason="root_case_receipt_verified"),
        lambda value: value.update(receipt_type="C01RootCaseResultReceipt"),
        lambda value: value.update(outer_job_empty=True),
        lambda value: value.update(request_count=True),
        lambda value: value.update(query_callback_count=9),
        lambda value: value.update(write_invocation_count=1),
    ],
)
def test_candidate_projection_rejects_promoted_or_inconsistent_claims(mutate):
    adjudicator = _load_adjudicator()
    projection = _candidate_projection()
    mutate(projection)
    with pytest.raises(adjudicator.C01RootFormalAdjudicationError):
        adjudicator._validate_wrapper_projection(_wrapper_receipt(projection))


def test_candidate_projection_rejects_frame_rebinding():
    adjudicator = _load_adjudicator()
    with pytest.raises(
        adjudicator.C01RootFormalAdjudicationError,
        match="wrapper_projection_invalid",
    ):
        adjudicator._validate_wrapper_projection(
            _wrapper_receipt(frame=object(), process_frame=object())
        )


def test_outer_close_must_bind_same_process_frame_and_nonce_chain():
    adjudicator = _load_adjudicator()
    wrapper = _wrapper_receipt()
    process = wrapper.parent_process_receipt
    process.call_nonce = object()
    outer = SimpleNamespace(
        outer_postverify_verified=True,
        normal_close_verified=True,
        source_postclose_pins_verified=True,
        retained_reference_count=0,
        outer_exit_code=0,
        outer_job_empty=True,
        stdout_eof=True,
        stderr_eof=True,
        stderr_empty=True,
        frame_eof=True,
        job_handles_closed=True,
        reader_threads_joined=True,
        cleanup_verified=True,
        public_source_pins=MappingProxyType({"a.py": "a" * 64}),
        software_source_pins=MappingProxyType({"python.exe": "b" * 64}),
        observed_held_public_count=1,
        observed_held_software_count=1,
        observed_held_count=2,
        call_nonce=process.call_nonce,
        parent_process_receipt=process,
    )
    adjudicator._validate_outer_close_receipt(outer, wrapper)
    outer.parent_process_receipt = SimpleNamespace(frame=wrapper.frame, call_nonce=object())
    with pytest.raises(
        adjudicator.C01RootFormalAdjudicationError,
        match="outer_close_call_binding_invalid",
    ):
        adjudicator._validate_outer_close_receipt(outer, wrapper)


def test_candidate_projection_rejects_noncanonical_bytes():
    adjudicator = _load_adjudicator()
    receipt = _wrapper_receipt()
    receipt.projection_raw += b"\n"
    with pytest.raises(adjudicator.C01RootFormalAdjudicationError):
        adjudicator._validate_wrapper_projection(receipt)
