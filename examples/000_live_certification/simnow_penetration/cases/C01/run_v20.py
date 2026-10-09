"""Root-only dispatcher for the unregistered SimNow C01 V20 candidate."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any


PROFILE_ID = "C01_NATIVE_TD_READ_V20"
ISSUER_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v20.py"
ISSUER_MODULE_NAME = "backtrader_runtime.certification_simnow_c01_native_td_read_v20"
ISSUER_SHA256 = "7118ed43cdc012181546f54f7b302ee51d3704860c5746807217c35087257f71"
_SAFE_REASON = re.compile(r"[a-z0-9_:-]{1,96}\Z")
_RESULT_KEYS = frozenset(
    {
        "case_id",
        "certification",
        "mode",
        "profile",
        "reason",
        "write_policy",
        "writes",
        "admission_failure_stage",
        "admission_failure_class",
        "worker_observation",
        "post_worker_failure_stage",
        "post_worker_failure_code",
    }
)
_POST_WORKER_FAILURE_STAGES = frozenset(
    {"none", "verify_tree", "read_snapshot_artifacts"}
)
_ADMISSION_FAILURE_STAGES = frozenset(
    {
        "none",
        "helper_load",
        "helper_registration",
        "known_folder",
        "issuer_source_lock",
        "runner_source_lock",
        "namespace_lock",
        "namespace_scan",
        "admission_read_parse",
        "profile_claim_create",
        "consumed_marker_create",
        "admitted_profile_body",
        "lease_revalidation",
        "source_handle_close",
    }
)
_ADMISSION_FAILURE_CLASSES = frozenset(
    {"none", "permission", "os", "type_value", "runtime", "other"}
)
_OWNER_VERIFY_TREE_FAILURE_CODES = frozenset(
    {
        "private_tree_depth_limit",
        "private_tree_entry_limit",
        "private_tree_acl_or_identity_invalid",
        "private_run_root_changed",
        "private_evidence_shape_invalid",
        "private_progress_sequence_invalid",
        "private_snapshot_directory_invalid",
        "private_snapshot_shape_invalid",
        "private_evidence_unexpected",
        "private_tree_verification_failed",
    }
)
_OWNER_SNAPSHOT_READ_FAILURE_CODES = frozenset(
    {
        "private_snapshot_size_invalid",
        "private_snapshot_read_failed",
        "private_snapshot_shape_invalid",
    }
)
_POST_WORKER_FAILURE_CODES = frozenset(
    {"none", "unclassified_owner_error"}
) | _OWNER_VERIFY_TREE_FAILURE_CODES | _OWNER_SNAPSHOT_READ_FAILURE_CODES
_ROOT_PATH = "backtrader_runtime/certification_simnow_c01_root_v17.py"
_OWNER_PATH = "backtrader_runtime/certification_simnow_c01_v7_owner.py"
_HELPER_PATHS = {
    "private": "backtrader_runtime/certification_roundtrip_private.py",
    "r3_cli": "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
    "selector": "scripts/ctp_000_paired_front_selector.py",
    "handoff": "scripts/ctp_000_front_handoff.py",
    "probe": "backtrader_runtime/ctp_front_pair_probe.py",
    "renderer": "scripts/ctp_000_render_config.py",
    "protocol": "backtrader_runtime/certification_simnow_c01_v3_protocol.py",
    "contract": "backtrader_runtime/certification_simnow_c01_v3_contract.py",
    "supervisor": "backtrader_runtime/certification_simnow_c01_v4_supervisor.py",
    "job_backend": "scripts/ctp_i13_i15_windows_job_backend.py",
    "watchdog": "scripts/ctp_i13_i15_outer_watchdog.py",
    "interpreter_binding": "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py",
}
_HELPER_MODULE_NAMES = {
    "private": "backtrader_runtime.certification_roundtrip_private",
    "r3_cli": "backtrader_runtime.certification_binance_roundtrip_r3_cli",
    "selector": "scripts.ctp_000_paired_front_selector",
    "handoff": "scripts.ctp_000_front_handoff",
    "probe": "backtrader_runtime.ctp_front_pair_probe",
    "renderer": "scripts.ctp_000_render_config",
    "protocol": "backtrader_runtime.certification_simnow_c01_v3_protocol",
    "contract": "backtrader_runtime.certification_simnow_c01_v3_contract",
    "supervisor": "backtrader_runtime.certification_simnow_c01_v4_supervisor",
    "job_backend": "scripts.ctp_i13_i15_windows_job_backend",
    "watchdog": "scripts.ctp_i13_i15_outer_watchdog",
    "interpreter_binding": "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1",
}


def invoke_v20_issuer(
    issuer_module: ModuleType,
    root_scope: Any,
    owner_module: ModuleType,
    helpers: Any,
) -> Any:
    """Call the exact active V20 bundle with the current Root-owned scope."""

    root_module = getattr(root_scope, "root_module", None)
    verified_modules = getattr(root_scope, "verified_source_modules", None)
    verified_objects = getattr(root_scope, "verified_source_objects", None)
    freshness_receipt = getattr(root_scope, "namespace_freshness_receipt", None)
    verify_freshness = (
        root_module.__dict__.get("verify_namespace_freshness_receipt")
        if type(root_module) is ModuleType
        else None
    )
    root_objects = (
        verified_objects.get(_ROOT_PATH) if type(verified_objects) is dict else None
    )
    if (
        type(issuer_module) is not ModuleType
        or issuer_module.__name__ != ISSUER_MODULE_NAME
        or getattr(issuer_module, "__c01_source_sha256__", None) != ISSUER_SHA256
        or type(getattr(issuer_module, "__file__", None)) is not str
        or type(root_module) is not ModuleType
        or type(root_scope) is not getattr(root_module, "C01RootInvocationScope", None)
        or getattr(root_scope, "active", None) is not True
        or getattr(root_scope, "consumed", None) is not False
        or type(verified_modules) is not dict
        or type(verified_objects) is not dict
        or type(freshness_receipt)
        is not getattr(root_module, "C01NamespaceFreshnessReceipt", None)
        or verified_modules.get(
            "backtrader_runtime/certification_simnow_c01_native_td_read_v20.py"
        )
        is not issuer_module
        or verified_modules.get(_OWNER_PATH) is not owner_module
        or type(owner_module) is not ModuleType
        or owner_module.__name__ != "backtrader_runtime._c01_native_td_read_v7_owner"
        or owner_module.__dict__.get("__c01_source_sha256__")
        != "ee492f115c60ca14f770a055061014f30b7b9cc1cecdfd09cae17f75aabf55e9"
        or type(helpers) not in (dict, MappingProxyType)
        or set(helpers) != set(_HELPER_PATHS) | {"owner_now_utc"}
        or any(
            verified_modules.get(relative) is not helpers.get(name)
            for name, relative in _HELPER_PATHS.items()
        )
        or any(
            type(helpers.get(name)) is not ModuleType
            or helpers[name].__name__ != _HELPER_MODULE_NAMES[name]
            for name in _HELPER_PATHS
        )
        or helpers.get("owner_now_utc") is not owner_module.__dict__.get("_now_utc")
        or type(verify_freshness) is not FunctionType
        or verify_freshness.__globals__ is not root_module.__dict__
        or type(root_objects) is not MappingProxyType
        or root_objects.get("verify_namespace_freshness_receipt") is not verify_freshness
        or root_objects.get("verify_namespace_freshness_receipt.__code__")
        is not verify_freshness.__code__
        or getattr(root_scope, "namespace_generation", None)
        is not getattr(freshness_receipt, "generation", None)
    ):
        raise ValueError("rooted_v20_invocation_binding_invalid")
    try:
        if verify_freshness(root_scope, freshness_receipt) is not True:
            raise ValueError("rooted_v20_namespace_stale")
    except Exception:
        raise ValueError("rooted_v20_namespace_stale") from None
    expected_path = Path(__file__).resolve(strict=True).parents[5] / Path(ISSUER_RELATIVE)
    try:
        actual_path = Path(issuer_module.__file__).resolve(strict=True)
    except Exception:
        raise ValueError("rooted_v20_issuer_path_invalid") from None
    if actual_path != expected_path.resolve(strict=True):
        raise ValueError("rooted_v20_issuer_path_invalid")
    function = issuer_module.__dict__.get("run_c01_native_td_read_v20")
    result_type = issuer_module.__dict__.get("C01NativeTdReadV20Result")
    if (
        type(function) is not FunctionType
        or function.__globals__ is not issuer_module.__dict__
        or function.__name__ != "run_c01_native_td_read_v20"
        or type(result_type) is not type
    ):
        raise ValueError("rooted_v20_issuer_api_invalid")
    result = function(
        _root_scope=root_scope,
        _owner_module=owner_module,
        _helpers=helpers,
    )
    if type(result) is not result_type:
        raise ValueError("rooted_v20_result_type_invalid")
    _validate_result_projection(result.to_dict())
    return result


def _validate_result_projection(value: object) -> None:
    if type(value) is not dict or set(value) != _RESULT_KEYS:
        raise ValueError("rooted_v20_result_projection_invalid")
    if (
        value.get("case_id") != "C01"
        or value.get("certification") not in {"PASS", "BLOCKED"}
        or value.get("mode") != PROFILE_ID
        or value.get("profile") != PROFILE_ID
        or value.get("write_policy") != "NO_WRITE"
        or type(value.get("writes")) is not int
        or value.get("writes") != 0
        or type(value.get("reason")) is not str
        or not _SAFE_REASON.fullmatch(value["reason"])
        or type(value.get("admission_failure_stage")) is not str
        or value["admission_failure_stage"] not in _ADMISSION_FAILURE_STAGES
        or type(value.get("admission_failure_class")) is not str
        or value["admission_failure_class"] not in _ADMISSION_FAILURE_CLASSES
        or (
            (value["admission_failure_stage"] == "none")
            != (value["admission_failure_class"] == "none")
        )
        or (
            value["certification"] == "PASS"
            and value["admission_failure_stage"] != "none"
        )
        or (
            value["admission_failure_stage"] != "none"
            and (
                value["certification"] != "BLOCKED"
                or value["reason"]
                not in {"admission_lease_failed", "admission_source_handle_close_failed"}
            )
        )
        or (
            value["reason"]
            in {"admission_lease_failed", "admission_source_handle_close_failed"}
            and value["admission_failure_stage"] == "none"
        )
        or type(value.get("worker_observation")) not in (dict, type(None))
        or type(value.get("post_worker_failure_stage")) is not str
        or value["post_worker_failure_stage"] not in _POST_WORKER_FAILURE_STAGES
        or type(value.get("post_worker_failure_code")) is not str
        or value["post_worker_failure_code"] not in _POST_WORKER_FAILURE_CODES
        or (
            (value["post_worker_failure_stage"] == "none")
            != (value["post_worker_failure_code"] == "none")
        )
        or (
            value["post_worker_failure_stage"] == "verify_tree"
            and value["post_worker_failure_code"]
            not in (_OWNER_VERIFY_TREE_FAILURE_CODES | {"unclassified_owner_error"})
        )
        or (
            value["post_worker_failure_stage"] == "read_snapshot_artifacts"
            and value["post_worker_failure_code"]
            not in (_OWNER_SNAPSHOT_READ_FAILURE_CODES | {"unclassified_owner_error"})
        )
        or (
            value["post_worker_failure_stage"] != "none"
            and (
                value["certification"] != "BLOCKED"
                or value["reason"] != "candidate_owner_validation_failed"
            )
        )
        or (
            value["reason"] == "candidate_owner_validation_failed"
            and value["post_worker_failure_stage"] == "none"
        )
    ):
        raise ValueError("rooted_v20_result_projection_invalid")


def _blocked(reason: str) -> int:
    payload = {
        "case_id": "C01",
        "certification": "BLOCKED",
        "mode": PROFILE_ID,
        "profile": PROFILE_ID,
        "reason": reason,
        "write_policy": "NO_WRITE",
        "writes": 0,
        "admission_failure_stage": "none",
        "admission_failure_class": "none",
        "worker_observation": None,
        "post_worker_failure_stage": "none",
        "post_worker_failure_code": "none",
    }
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 2


def main(argv: Any = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in (["--live", "--profile", PROFILE_ID], ["--profile", PROFILE_ID, "--live"]):
        return _blocked("root_owned_invocation_required")
    return _blocked("managed_ctp_v20_candidate_not_registered")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["invoke_v20_issuer", "main"]
