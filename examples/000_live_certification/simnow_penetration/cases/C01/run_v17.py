"""Fixed, default-closed dispatcher for the unregistered C01 V17 candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType

PROFILE_ID = "C01_NATIVE_TD_READ_V17"
ISSUER_RELATIVE = "backtrader_runtime/certification_simnow_c01_native_td_read_v17.py"
ISSUER_SHA256 = "fa202e00da45fced059b6409e17c2ea9d41b0f8e0f1666f56491735a7f39b795"
MAX_ISSUER_BYTES = 2 * 1024 * 1024
ADMISSION_FAILURE_STAGES = frozenset(
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
ADMISSION_FAILURE_CLASSES = frozenset(
    {"none", "permission", "os", "type_value", "runtime", "other"}
)


def _blocked(reason: str) -> int:
    print(json.dumps({
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
    }, separators=(",", ":"), sort_keys=True))
    return 2


def _run_fixed_profile() -> int:
    case_path = Path(__file__).resolve()
    root = case_path.parents[5]
    entry = root / Path(ISSUER_RELATIVE)
    module_name = "_c01_native_td_read_v17_fixed_entry"
    try:
        info = entry.lstat()
        if (
            entry.is_symlink()
            or getattr(info, "st_file_attributes", 0) & 0x400
            or not entry.is_file()
            or info.st_size > MAX_ISSUER_BYTES
            or module_name in sys.modules
        ):
            raise ValueError
        with entry.open("rb") as stream:
            raw = stream.read(MAX_ISSUER_BYTES + 1)
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) > MAX_ISSUER_BYTES or digest != ISSUER_SHA256:
            raise ValueError
        module = ModuleType(module_name)
        module.__file__ = str(entry)
        module.__package__ = None
        module.__c01_source_sha256__ = digest
        sys.modules[module_name] = module
        try:
            exec(compile(raw, str(entry), "exec", dont_inherit=True), module.__dict__)
            result = module.run_c01_native_td_read_v17()
            if type(result) is not module.C01NativeTdReadV17Result:
                raise ValueError
            payload = result.to_dict()
            if (
                type(payload) is not dict
                or set(payload) != {
                    "case_id", "certification", "mode", "profile", "reason",
                    "write_policy", "writes", "admission_failure_stage",
                    "admission_failure_class", "worker_observation",
                    "post_worker_failure_stage", "post_worker_failure_code",
                }
                or payload["case_id"] != "C01"
                or payload["certification"] not in {"PASS", "BLOCKED"}
                or payload["mode"] != PROFILE_ID
                or payload["profile"] != PROFILE_ID
                or payload["write_policy"] != "NO_WRITE"
                or payload["writes"] != 0
                or (
                    payload["worker_observation"] is not None
                    and type(payload["worker_observation"]) is not dict
                )
                or type(payload["reason"]) is not str
                    or type(payload["post_worker_failure_stage"]) is not str
                    or payload["post_worker_failure_stage"] not in {
                        "none", "verify_tree", "read_snapshot_artifacts"
                    }
                    or type(payload["post_worker_failure_code"]) is not str
                    or payload["post_worker_failure_code"] not in {
                        "none",
                        "unclassified_owner_error",
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
                        "private_snapshot_size_invalid",
                        "private_snapshot_read_failed",
                    }
                    or (
                        (payload["post_worker_failure_stage"] == "none")
                        != (payload["post_worker_failure_code"] == "none")
                    )
                    or (
                        payload["post_worker_failure_stage"] == "verify_tree"
                        and payload["post_worker_failure_code"]
                        not in {
                            "unclassified_owner_error",
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
                    or (
                        payload["post_worker_failure_stage"] == "read_snapshot_artifacts"
                        and payload["post_worker_failure_code"]
                        not in {
                            "unclassified_owner_error",
                            "private_snapshot_size_invalid",
                            "private_snapshot_read_failed",
                            "private_snapshot_shape_invalid",
                        }
                    )
                    or (
                        payload["post_worker_failure_stage"] != "none"
                        and (
                            payload["certification"] != "BLOCKED"
                            or payload["reason"] != "candidate_owner_validation_failed"
                        )
                    )
                    or (
                        payload["reason"] == "candidate_owner_validation_failed"
                        and payload["post_worker_failure_stage"] == "none"
                    )
                or type(payload["admission_failure_stage"]) is not str
                or payload["admission_failure_stage"] not in ADMISSION_FAILURE_STAGES
                or type(payload["admission_failure_class"]) is not str
                or payload["admission_failure_class"] not in ADMISSION_FAILURE_CLASSES
                or (
                    (payload["admission_failure_stage"] == "none")
                    != (payload["admission_failure_class"] == "none")
                )
                or (
                    payload["certification"] == "PASS"
                    and payload["admission_failure_stage"] != "none"
                )
                or (
                    payload["admission_failure_stage"] != "none"
                    and (
                        payload["certification"] != "BLOCKED"
                        or payload["reason"]
                        not in {
                            "admission_lease_failed",
                            "admission_source_handle_close_failed",
                        }
                    )
                )
                or (
                    payload["reason"]
                    in {"admission_lease_failed", "admission_source_handle_close_failed"}
                    and payload["admission_failure_stage"] == "none"
                )
            ):
                raise ValueError
        finally:
            if sys.modules.get(module_name) is module:
                sys.modules.pop(module_name, None)
    except Exception:
        return _blocked("fixed_issuer_unavailable")
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0 if payload["certification"] == "PASS" else 2


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    approved = (["--live", "--profile", PROFILE_ID], ["--profile", PROFILE_ID, "--live"])
    if args in approved:
        return _run_fixed_profile()
    return _blocked("managed_ctp_v17_candidate_not_registered")


if __name__ == "__main__":
    raise SystemExit(main())
