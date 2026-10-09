"""Unexecuted R17 Root source-fake diagnostic QA harness for Binance R2.

It materializes the exact 19-input selected-source closure and runs the nine
named fake tests only. Its selected runner and models overlays derive from
clean HEAD blobs. It narrowly validates the canonical built-in winreg module
needed by Windows stdlib bootstrap while denying imports and registry audit
operations. Root reviews and executes this draft once if approved.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from uuid import uuid4


ROOT = Path("D:/source_code/backtrader").resolve()
EXPECTED_HEAD = "__R6_EXPECTED_HEAD__"
EXPECTED_INTERPRETER_PREFIX_ROOT_KEYS = {
    str(value).replace(chr(92), "/").casefold().rstrip("/")
    for value in (sys.base_prefix, sys.prefix)
}
PYTHON = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe")
SITE = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages")
RESULT = ROOT / ".codex-tmp/binance_account_full_r2_root_source_qa_r17_20261009.json"
QA = Path("D:/bafsr2r17_" + uuid4().hex[:8])
SELECTED_ROOT = QA / "selected-source"
STD_TEMP = QA / "stdlib-temp"
PYTEST_BASE_TEMP = QA / "pytest-basetemp"
PYTEST_CONFIG_CONTENT = b"[pytest]\n"

RUNNER_RELATIVE = (
    "examples/000_live_certification/binance_penetration/_certification/runner.py"
)
RUNNER_SIGNATURE_OLD = b"    currency: str,\n) -> ActionPlan:"
RUNNER_SIGNATURE_NEW = b"    currency: str,\n    venue: str | None = None,\n) -> ActionPlan:"
MODEL_PLANNED_OLD = (
    b"    instrument_spec_id: str | None\n"
    b"\n"
    b"\n"
    b"@dataclass(frozen=True)\n"
    b"class ActionPlan:"
)
MODEL_PLANNED_NEW = (
    b"    instrument_spec_id: str | None\n"
    b"    position_side: str | None = None\n"
    b"    time_in_force: str | None = None\n"
    b"    request_digest: str | None = None\n"
    b"\n"
    b"\n"
    b"@dataclass(frozen=True)\n"
    b"class ActionPlan:"
)
MODEL_ORDER_STATE_OLD = (
    b"    remaining: Decimal\n"
    b"\n"
    b"\n"
    b"@dataclass(frozen=True)\n"
    b"class PositionState:"
)
MODEL_ORDER_STATE_NEW = (
    b"    remaining: Decimal\n"
    b"    position_side: str | None = None\n"
    b"    time_in_force: str | None = None\n"
    b"\n"
    b"\n"
    b"@dataclass(frozen=True)\n"
    b"class PositionState:"
)

PINS = {
    "tests/unit/live_certification/test_binance_th01_account_full_snapshot_r2.py": {
        "bytes": 34381,
        "sha256": "839d0a25d8efbffe0417503f9474ede3a963777deb019ee7306539e28416692a",
        "origin": "checkout",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_account_full_snapshot_r2.py": {
        "bytes": 83891,
        "sha256": "8524d5fa9934e1c119a5bd7c57f34480311eb9e1d18efb1edc8c8a4792d7d141",
        "origin": "checkout",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/__init__.py": {
        "bytes": 65,
        "sha256": "dc6242322955db538276366944d6359193d4f23fbdf7d085ea5db97b7b26f12c",
        "origin": "head",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/models.py": {
        "bytes": 6414,
        "sha256": "bb3ec5d580822500b6dc222df3377a5401441c8855e0923bec7108b4b2807f4e",
        "origin": "head_with_selected_model_hunk",
        "head_bytes": 6228,
        "head_sha256": "4f791454c7ced5111178a4ee1edfcd8926409ec20854690ef45af5c2e2d61fa3",
        "head_blob": "8a058db531726420b761ced7ee6fd37fb084a72d",
        "selected_blob": "010f78626b760a306550028695708d17f95b7f53",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/cases.py": {
        "bytes": 5569,
        "sha256": "0e0d7618846975db37551222f3c902ceee2b975f4be0b8236dcf021508492762",
        "origin": "head",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/config.py": {
        "bytes": 17469,
        "sha256": "778cb7ea430b79d7d9a27a2fd2c31a3e6e7ea6ed63d735f3f936abcc93dfd101",
        "origin": "head",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/evidence.py": {
        "bytes": 5491,
        "sha256": "05916efcd52a49fbd6303d315e17b8f57a3f411b3557872250e899636ffb9217",
        "origin": "head",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/backends.py": {
        "bytes": 24420,
        "sha256": "e896424a73678b0126038373f013253d752a2318e7b2099b05fba390bd0e8f3c",
        "origin": "head",
        "materialize": True,
    },
    RUNNER_RELATIVE: {
        "bytes": 83391,
        "sha256": "f139752d19ca42c68d79c50293338abee22a74abab2757091d29efbd5f950932",
        "origin": "head_with_selected_venue_hunk",
        "head_bytes": 83361,
        "head_sha256": "2204b85350706fd308d57a88f51d9af318123cf13323fffbcd5b206f0310bc58",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_account_full_snapshot_r1.py": {
        "bytes": 60349,
        "sha256": "049ef44814d2131b53a5b32dfdd5519b5c4607cb3db9922d330c1282c01d93c5",
        "origin": "checkout",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r9.py": {
        "bytes": 73002,
        "sha256": "c937a07671a6df7991fb29e131d895c0eca21644d28140542fab7c8b0db1b944",
        "origin": "head",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py": {
        "bytes": 92566,
        "sha256": "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f",
        "origin": "head",
        "materialize": True,
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_root_readonly.py": {
        "bytes": 51587,
        "sha256": "2b5e055aff27a07c3d28b6499a45ebf1c7546e7a8f0710ea60feb68d2561ca0f",
        "origin": "checkout_pin_only",
        "materialize": False,
    },
    "examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py": {
        "bytes": 62664,
        "sha256": "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63",
        "origin": "head",
        "materialize": True,
    },
    "scripts/iteration41_binance_th01_account_window_candidate_r2.py": {
        "bytes": 11391,
        "sha256": "698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6",
        "origin": "head",
        "materialize": True,
    },
    "scripts/iteration41_binance_th01_root_account_window_call_r1.py": {
        "bytes": 132886,
        "sha256": "ba0360ecc5ed99b37196e3d077e25a78cd771facec8e224ab1371635cf9be021",
        "origin": "head",
        "materialize": True,
    },
    "backtrader_runtime/certification_roundtrip_private.py": {
        "bytes": 17537,
        "sha256": "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
        "origin": "head_pin_only",
        "materialize": False,
    },
    "backtrader_runtime/certification_roundtrip_r3_bootstrap.py": {
        "bytes": 24354,
        "sha256": "6ecf2060558753d3a9f5b4fe9d2e4329659e9b9c00879d539ff4408c9778b4da",
        "origin": "checkout_pin_only",
        "materialize": False,
    },
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py": {
        "bytes": 33887,
        "sha256": "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
        "origin": "head_pin_only",
        "materialize": False,
    },
}

TEST_RELATIVE = "tests/unit/live_certification/test_binance_th01_account_full_snapshot_r2.py"
CHECKOUT_INPUT_RELATIVES = tuple(
    relative for relative, record in PINS.items()
    if record["origin"] in {"checkout", "checkout_pin_only"}
)
MATERIALIZED_RELATIVES = tuple(
    relative for relative, record in PINS.items() if record["materialize"]
)
PIN_ONLY_PATHS = tuple(
    relative for relative, record in PINS.items() if not record["materialize"]
)
EXPECTED_TEST_NAMES = (
    "test_catalog_capture_and_baseline_produce_scoped_candidate",
    "test_unknown_catalog_contract_blocks_producer_before_account_snapshot",
    "test_cross_family_catalog_symbol_collision_blocks_producer",
    "test_internal_module_global_drift_invalidates_held_producer",
    "test_coin_m_family_conflict_in_current_state_never_issues_snapshot",
    "test_root_callback_chain_issues_three_reconciled_snapshots_with_r9_tickets",
    "test_stable_nonempty_window_history_reconciles_between_later_phases",
    "test_truncated_current_page_cannot_enter_a_baseline_snapshot",
    "test_after_cleanup_balance_delta_fails_closed_as_not_account_full",
)
EXPECTED_GUARD_SELFCHECKS = (
    "windows_chr92_normalization",
    "private_env_open_denied",
    "private_config_open_denied",
    "pytest_config_open_write_denied",
    "pytest_config_replace_denied",
    "pytest_config_unlink_denied",
    "private_secrets_open_denied",
    "private_capture_open_denied",
    "opaque_dll_open_denied",
    "external_software_exe_open_denied",
    "native_pyd_open_denied",
    "SDK_import_denied",
    "native_import_denied",
    "network_audit_denied",
    "DNS_audit_denied",
    "socket_constructor_denied",
    "DNS_function_denied",
    "ctypes_loader_denied",
    "ctypes_proxy_denied",
    "subprocess_start_denied",
    "os_process_start_denied",
    "multiprocessing_start_denied",
    "multiprocessing_pipe_denied",
    "connection_wait_denied",
    "WinAPI_process_audit_denied",
    "WinAPI_pipe_audit_denied",
    "WinAPI_process_function_denied",
    "WinAPI_pipe_function_denied",
    "winreg_registry_operation_audit_denied",
)
EXPECTED_EARLY_GUARD_CHECKS = (
    "private_input_open_denied_before_qa_packages",
    "pytest_config_mutation_denied_before_qa_packages",
    "sdk_import_denied_before_qa_packages",
    "network_denied_before_qa_packages",
    "native_load_denied_before_qa_packages",
    "subprocess_denied_before_qa_packages",
    "winapi_process_denied_before_qa_packages",
    "multiprocessing_pipe_denied_before_qa_packages",
    "ctypes_c_loader_denied_before_qa_packages",
    "windll_load_replaced_by_inert_facade_before_qa_packages",
    "winreg_canonical_binding_verified_before_qa_packages",
    "winreg_forged_module_denied_before_qa_packages",
    "winreg_nonbuiltin_origin_denied_before_qa_packages",
    "winreg_function_rebinding_denied_before_qa_packages",
    "winreg_import_denied_before_qa_packages",
    "winreg_operation_audit_denied_before_qa_packages",
    "pyexpat_canonical_parent_and_children_verified_before_qa_packages",
    "pyexpat_forged_sys_modules_child_denied_before_qa_packages",
    "pyexpat_parent_attribute_identity_denied_before_qa_packages",
    "pyexpat_parent_sys_modules_identity_denied_before_qa_packages",
    "pyexpat_parent_origin_mutation_denied_before_qa_packages",
    "pyexpat_parent_loader_mutation_denied_before_qa_packages",
    "pyexpat_child_spec_mutation_denied_before_qa_packages",
    "pyexpat_child_file_mutation_denied_before_qa_packages",
    "pyexpat_trusted_origin_forgery_rejected_by_all_post_stdlib_children",
    "pyexpat_trusted_origin_forgery_rejected_by_all_post_qa_children",
    "pyexpat_parent_binding_rechecked_for_all_post_stdlib_children",
    "pyexpat_parent_binding_rechecked_for_all_post_qa_children",
)
CHILD_TRACE_PREFIX = "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17_TRACE:"
CHILD_ORIGIN_SCAN_REJECTION_PREFIX = "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17_SCAN_REJECTED:"
CHILD_ORIGIN_SCAN_REJECTION_CATEGORIES = {
    "winreg_builtin_binding_mismatch",
    "pyexpat_synthetic_child_binding_mismatch",
    "child_source_origin_wrong_module", "main_alias_identity_mismatch",
    "missing_or_nonstring_origin", "outside_trusted_stdlib_roots",
    "typing_deprecated_alias_identity_mismatch",
}
EXPECTED_PRELOADED_MODULE_ORIGIN_ALLOWANCES = (
    ("__main__", "main_module_at_pinned_child_origin"),
    ("__mp_main__", "same_object_main_alias_at_pinned_child_origin"),
    ("pyexpat.errors", "synthetic_child_of_canonical_pyexpat_extension"),
    ("pyexpat.model", "synthetic_child_of_canonical_pyexpat_extension"),
    ("typing.io", "typing_deprecated_type_alias_at_trusted_typing_origin"),
    ("typing.re", "typing_deprecated_type_alias_at_trusted_typing_origin"),
    ("winreg", "canonical_winreg_builtin_binding"),
)
EXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS = {
    "initial": 7,
    "post_stdlib": 7,
    "post_qa": 7,
}
CHILD_TRACE_PHASES = {
    "child_startup", "interpreter_flags", "trusted_stdlib_path_setup",
    "trusted_stdlib_prefix_root_filter", "importlib_machinery_origin_check",
    "trusted_stdlib_origin_preload", "trusted_preloaded_module_origin_scan",
    "qa_preload_validation", "trusted_stdlib_origin_recheck",
    "trusted_module_origin_recheck", "early_hard_guard_install",
    "third_party_module_origin_audit", "qa_preload", "qa_main",
    "full_qa_guard_install", "selected_source_loader_install",
    "focused_pytest_execution", "child_summary", "focused_qa_gate",
}
CHILD_TRACE_DEPENDENCIES = {
    "colorama", "colorama.ansi", "colorama.ansitowin32",
    "colorama.initialise", "colorama.win32", "colorama.winterm",
    "yaml", "pytest",
}
CHILD_TRACE_STATUSES = {"start", "complete", "hold", "exception"}
CHILD_EXCEPTION_TYPES = {
    "AssertionError", "AttributeError", "FileNotFoundError", "GuardViolation",
    "ImportError", "ModuleNotFoundError", "NameError", "OSError",
    "OtherException", "PermissionError", "RuntimeError", "SystemExit",
    "TypeError", "ValueError",
}
CHILD_EXCEPTION_CATEGORIES = {
    "dependency_or_source_import_failure", "filesystem_or_os_failure",
    "focused_gate_exit", "guard_denial", "other_child_exception",
    "preload_or_harness_validation_failure",
}
MAX_CHILD_LOG_BYTES = 4 * 1024 * 1024


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_blob_id(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def _git(*arguments: str) -> bytes:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SystemRoot", "WINDIR")
        if key in os.environ
    }
    environment.update(
        {
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *arguments],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=20,
    ).stdout


def _checkout_bytes(relative: str) -> bytes:
    path = ROOT / relative
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("source_shape_invalid")
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("source_reparse_point_denied")
    return path.read_bytes()


def _source_bytes(relative: str) -> bytes:
    expected = PINS[relative]
    origin = expected["origin"]
    if origin in {"checkout", "checkout_pin_only"}:
        raw = _checkout_bytes(relative)
    elif origin in {"head", "head_pin_only"}:
        raw = _git("show", f"HEAD:{relative}")
    elif origin == "head_with_selected_venue_hunk":
        base = _git("show", f"HEAD:{relative}")
        if (
            len(base) != expected["head_bytes"]
            or _sha(base) != expected["head_sha256"]
            or base.count(RUNNER_SIGNATURE_OLD) != 1
        ):
            raise RuntimeError("runner_clean_head_or_hunk_mismatch")
        raw = base.replace(RUNNER_SIGNATURE_OLD, RUNNER_SIGNATURE_NEW, 1)
    elif origin == "head_with_selected_model_hunk":
        base = _git("show", f"HEAD:{relative}")
        if (
            len(base) != expected["head_bytes"]
            or _sha(base) != expected["head_sha256"]
            or _git("rev-parse", f"HEAD:{relative}").decode("ascii").strip()
            != expected["head_blob"]
            or _git_blob_id(base) != expected["head_blob"]
            or base.count(MODEL_PLANNED_OLD) != 1
            or base.count(MODEL_ORDER_STATE_OLD) != 1
        ):
            raise RuntimeError("models_clean_head_or_hunk_mismatch")
        raw = base.replace(MODEL_PLANNED_OLD, MODEL_PLANNED_NEW, 1)
        raw = raw.replace(MODEL_ORDER_STATE_OLD, MODEL_ORDER_STATE_NEW, 1)
        if _git_blob_id(raw) != expected["selected_blob"]:
            raise RuntimeError("models_selected_blob_mismatch")
    else:
        raise RuntimeError("unknown_source_origin")
    actual = {"bytes": len(raw), "sha256": _sha(raw)}
    if actual != {"bytes": expected["bytes"], "sha256": expected["sha256"]}:
        raise RuntimeError("source_pin_mismatch")
    return raw


def _pin(relative: str) -> dict[str, object]:
    raw = _source_bytes(relative)
    return {
        "path": relative,
        "origin": PINS[relative]["origin"],
        "bytes": len(raw),
        "sha256": _sha(raw),
    }


def _pin_all() -> dict[str, dict[str, object]]:
    return {relative: _pin(relative) for relative in PINS}


def _raw_index_sha256() -> str:
    value = _git("rev-parse", "--git-path", "index").decode("utf-8", "strict").strip()
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("git_index_shape_invalid")
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("git_index_reparse_point_denied")
    return _sha(path.read_bytes())


def _materialize_selected_namespace() -> dict[str, dict[str, object]]:
    materialized = {}
    for relative in MATERIALIZED_RELATIVES:
        raw = _source_bytes(relative)
        path = SELECTED_ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        materialized[relative] = {
            "bytes": len(raw),
            "sha256": _sha(raw),
            "origin": PINS[relative]["origin"],
        }
    return materialized


def _selected_tree_pins() -> dict[str, dict[str, object]]:
    actual_paths = set()
    for path in SELECTED_ROOT.rglob("*"):
        if path.is_symlink():
            raise RuntimeError("selected_namespace_symlink_denied")
        if path.is_file():
            actual_paths.add(path.relative_to(SELECTED_ROOT).as_posix())
    if actual_paths != set(MATERIALIZED_RELATIVES):
        raise RuntimeError("selected_namespace_file_set_mismatch")
    return {
        relative: {
            "bytes": len((SELECTED_ROOT / relative).read_bytes()),
            "sha256": _sha((SELECTED_ROOT / relative).read_bytes()),
        }
        for relative in MATERIALIZED_RELATIVES
    }


def _git_snapshot() -> dict[str, object]:
    branch = _git("branch", "--show-current").decode("ascii").strip()
    head = _git("rev-parse", "HEAD").decode("ascii").strip()
    staged = _git("diff", "--cached", "--name-only", "-z")
    status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    scoped_status = _git(
        "status", "--porcelain=v1", "-z", "--untracked-files=all", "--",
        *CHECKOUT_INPUT_RELATIVES,
    )
    index_sha256 = _raw_index_sha256()
    if branch != "dev" or head != EXPECTED_HEAD or staged:
        raise RuntimeError("git_preflight_mismatch")
    return {
        "branch": branch,
        "head": head,
        "staged_index_empty": not staged,
        "raw_index_sha256": index_sha256,
        "global_worktree_status_sha256": _sha(status),
        "checkout_input_status_sha256": _sha(scoped_status),
    }


def _same_required_git_state(before: dict[str, object], after: dict[str, object]) -> bool:
    required = (
        "branch", "head", "staged_index_empty", "raw_index_sha256",
        "checkout_input_status_sha256",
    )
    return all(before.get(key) == after.get(key) for key in required)


def _external_file_pin(path: Path) -> dict[str, object]:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("external_config_shape_invalid")
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("external_config_reparse_point_denied")
    raw = path.read_bytes()
    return {
        "bytes": len(raw),
        "sha256": _sha(raw),
        "matches_expected": raw == PYTEST_CONFIG_CONTENT,
    }


def _parse_child_trace(stdout: str) -> tuple[list[dict[str, str]], list[str]]:
    events = []
    problems = []
    for line in stdout.splitlines():
        if not line.startswith(CHILD_TRACE_PREFIX):
            continue
        parts = line[len(CHILD_TRACE_PREFIX):].split("|")
        if len(parts) != 4:
            problems.append("trace_field_count_invalid")
            continue
        phase, status, exception_type, category = parts
        if phase.startswith("qa_dependency_import:"):
            if phase.partition(":")[2] not in CHILD_TRACE_DEPENDENCIES:
                problems.append("trace_dependency_phase_invalid")
                continue
        elif phase not in CHILD_TRACE_PHASES:
            problems.append("trace_phase_invalid")
            continue
        if status not in CHILD_TRACE_STATUSES:
            problems.append("trace_status_invalid")
            continue
        if status in {"exception", "hold"}:
            if exception_type not in CHILD_EXCEPTION_TYPES:
                problems.append("trace_exception_type_invalid")
                continue
            if category not in CHILD_EXCEPTION_CATEGORIES:
                problems.append("trace_exception_category_invalid")
                continue
        elif exception_type != "-" or category != "-":
            problems.append("trace_nonexception_fields_invalid")
            continue
        events.append(
            {
                "phase": phase,
                "status": status,
                "exception_type": exception_type,
                "category": category,
            }
        )
    return events, problems


def _parse_preloaded_origin_rejection(stdout: str) -> tuple[dict | None, list[str]]:
    records = [
        line[len(CHILD_ORIGIN_SCAN_REJECTION_PREFIX):]
        for line in stdout.splitlines()
        if line.startswith(CHILD_ORIGIN_SCAN_REJECTION_PREFIX)
    ]
    if not records:
        return None, []
    if len(records) != 1:
        return None, ["origin_scan_rejection_count_invalid"]
    fields = records[0].split("|")
    if len(fields) != 2:
        return None, ["origin_scan_rejection_field_count_invalid"]
    module_name, origin_category = fields
    if (
        not module_name
        or len(module_name) > 128
        or not module_name.isascii()
        or any(not (character.isalnum() or character in "._") for character in module_name)
    ):
        return None, ["origin_scan_rejection_module_name_invalid"]
    if origin_category not in CHILD_ORIGIN_SCAN_REJECTION_CATEGORIES:
        return None, ["origin_scan_rejection_category_invalid"]
    return {"module_name": module_name, "origin_category": origin_category}, []


def _child_diagnostic(stdout: str, child_summary: dict | None, return_code: int) -> dict:
    events, trace_problems = _parse_child_trace(stdout)
    positions = {
        (event["phase"], event["status"]): index
        for index, event in enumerate(events)
    }
    early_complete = positions.get(("early_hard_guard_install", "complete"))
    first_third_party = next(
        (
            index for index, event in enumerate(events)
            if event["phase"].startswith("qa_dependency_import:")
            and event["status"] == "start"
        ),
        None,
    )
    full_guard_complete = positions.get(("full_qa_guard_install", "complete"))
    loader_start = positions.get(("selected_source_loader_install", "start"))
    loader_complete = positions.get(("selected_source_loader_install", "complete"))
    pytest_start = positions.get(("focused_pytest_execution", "start"))
    preload_order = bool(
        early_complete is not None
        and first_third_party is not None
        and early_complete < first_third_party
        and ("trusted_stdlib_origin_preload", "complete") in positions
        and ("trusted_preloaded_module_origin_scan", "complete") in positions
        and ("trusted_stdlib_origin_recheck", "complete") in positions
        and ("trusted_module_origin_recheck", "complete") in positions
    )
    guard_order = bool(
        full_guard_complete is not None
        and loader_start is not None
        and full_guard_complete < loader_start
        and loader_complete is not None
        and pytest_start is not None
        and loader_complete < pytest_start
    )
    exception_event = next(
        (event for event in reversed(events) if event["status"] in {"exception", "hold"}),
        None,
    )
    if exception_event is None and return_code != 0:
        exception = {
            "observed": False,
            "type": None,
            "category": "child_failure_unclassified",
        }
    elif exception_event is None:
        exception = {"observed": False, "type": None, "category": None}
    else:
        exception = {
            "observed": True,
            "type": exception_event["exception_type"],
            "category": exception_event["category"],
            "phase": exception_event["phase"],
        }
    return {
        "scope": "public_source_fake_child_only",
        "last_phase": events[-1]["phase"] if events else None,
        "phase_trace": events,
        "trace_parse_problems": trace_problems,
        "trusted_preload": {
            "stdlib_origins_verified": (
                ("trusted_stdlib_origin_preload", "complete") in positions
                and ("trusted_stdlib_origin_recheck", "complete") in positions
                and ("trusted_module_origin_recheck", "complete") in positions
            ),
            "early_guards_installed_before_first_qa_dependency": preload_order,
            "qa_preload_completed": ("qa_preload", "complete") in positions,
        },
        "installed_guards": {
            "full_guards_completed_before_selected_loader": guard_order,
            "early_selfchecks": (
                child_summary.get("early_guard_selfchecks") if child_summary else None
            ),
            "full_selfchecks": (
                child_summary.get("guard_selfchecks", {}).get("checks")
                if child_summary else None
            ),
            "candidate_denials": (
                child_summary.get("candidate_denied_attempts") if child_summary else None
            ),
        },
        "child_exception": exception,
        "pytest_failure_diagnostic": (
            child_summary.get("pytest_failure_diagnostic") if child_summary else None
        ),
    }


def _persist_child_log(path: Path, payload: bytes) -> dict[str, object]:
    saved = payload[:MAX_CHILD_LOG_BYTES]
    with path.open("xb") as stream:
        stream.write(saved)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("child_log_artifact_shape_invalid")
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("child_log_artifact_reparse_point_denied")
    persisted = path.read_bytes()
    return {
        "path": str(path),
        "bytes_observed": len(payload),
        "bytes_persisted": len(persisted),
        "sha256_observed": _sha(payload),
        "sha256_persisted": _sha(persisted),
        "truncated_at_limit": len(payload) > MAX_CHILD_LOG_BYTES,
        "persisted_exactly": persisted == payload,
    }


CHILD = r'''import sys

ACTIVE_PHASE = "child_startup"
TRACE_EXCEPTION_EMITTED = False
TRACE_PREFIX = "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17_TRACE:"
SAFE_EXCEPTION_TYPES = {
    "AssertionError", "AttributeError", "FileNotFoundError", "GuardViolation",
    "ImportError", "ModuleNotFoundError", "NameError", "OSError",
    "PermissionError", "RuntimeError", "SystemExit", "TypeError", "ValueError",
}

def _trace(phase, status, exception_type="-", category="-"):
    global ACTIVE_PHASE
    ACTIVE_PHASE = phase
    fields = (phase, status, exception_type, category)
    sys.stdout.write(TRACE_PREFIX + "|".join(fields) + "\n")
    sys.stdout.flush()

def _failure_category(exception_type):
    if exception_type == "GuardViolation":
        return "guard_denial"
    if exception_type in {"ImportError", "ModuleNotFoundError"}:
        return "dependency_or_source_import_failure"
    if exception_type in {"OSError", "PermissionError", "FileNotFoundError"}:
        return "filesystem_or_os_failure"
    if exception_type == "SystemExit":
        return "focused_gate_exit"
    if exception_type == "RuntimeError":
        return "preload_or_harness_validation_failure"
    return "other_child_exception"

def _record_uncaught(exc_type, _exc, _traceback):
    global TRACE_EXCEPTION_EMITTED
    if TRACE_EXCEPTION_EMITTED:
        sys.__excepthook__(exc_type, _exc, _traceback)
        return
    name = getattr(exc_type, "__name__", "Exception")
    if name not in SAFE_EXCEPTION_TYPES:
        name = "OtherException"
    _trace(ACTIVE_PHASE, "exception", name, _failure_category(name))
    TRACE_EXCEPTION_EMITTED = True
    sys.__excepthook__(exc_type, _exc, _traceback)

sys.excepthook = _record_uncaught
_trace("interpreter_flags", "start")

if sys.flags.isolated != 1 or sys.flags.no_site != 1:
    raise RuntimeError("isolated_no_site_interpreter_required")
_trace("interpreter_flags", "complete")

def _boot_norm(value):
    return str(value).replace(chr(92), "/").casefold().rstrip("/")

def _boot_under(value, parent):
    value_key = _boot_norm(value)
    parent_key = _boot_norm(parent)
    return value_key == parent_key or value_key.startswith(parent_key + "/")

_trace("trusted_stdlib_path_setup", "start")
_boot_prefixes = tuple(dict.fromkeys((sys.base_prefix, sys.prefix)))
_boot_roots = tuple(
    prefix.rstrip("/\\") + suffix
    for prefix in _boot_prefixes
    for suffix in ("/Lib", "/DLLs")
)
_boot_zip_paths = tuple(
    prefix.rstrip("/\\")
    + "/python"
    + str(sys.version_info.major)
    + str(sys.version_info.minor)
    + ".zip"
    for prefix in _boot_prefixes
)
_boot_stdlib_allowed_entries = {_boot_norm(path) for path in (*_boot_roots, *_boot_zip_paths)}
_boot_prefix_roots = {_boot_norm(prefix) for prefix in _boot_prefixes}
_boot_allowed_entries = _boot_stdlib_allowed_entries | _boot_prefix_roots
_boot_initial_path = tuple(sys.path)
_trace("trusted_stdlib_prefix_root_filter", "start")
if (
    not _boot_initial_path
    or any(not isinstance(path, str) or not path for path in _boot_initial_path)
    or any(_boot_norm(path) not in _boot_allowed_entries for path in _boot_initial_path)
):
    raise RuntimeError("initial_import_path_not_trusted_stdlib")
_boot_initial_prefix_root_entries_removed = tuple(
    str(path) for path in _boot_initial_path if _boot_norm(path) in _boot_prefix_roots
)
_boot_prefix_root_keys_authorized = tuple(sorted(_boot_prefix_roots))
_boot_path_after_prefix_drop = tuple(
    path for path in _boot_initial_path if _boot_norm(path) not in _boot_prefix_roots
)
if (
    not _boot_path_after_prefix_drop
    or any(_boot_norm(path) not in _boot_stdlib_allowed_entries for path in _boot_path_after_prefix_drop)
):
    raise RuntimeError("post_prefix_drop_import_path_not_trusted_stdlib")
sys.path[:] = list(dict.fromkeys(_boot_path_after_prefix_drop))
if any(_boot_norm(path) in _boot_prefix_roots for path in sys.path):
    raise RuntimeError("interpreter_prefix_root_remained_on_import_path")
_boot_initial_path_after_prefix_drop = tuple(sys.path)
_trace("trusted_stdlib_prefix_root_filter", "complete")

# The isolated child starts with only its interpreter-provided standard-library
# entries. Keep QA site-packages out until every stdlib preload origin is checked.
import importlib
import importlib.machinery
_trace("trusted_stdlib_path_setup", "complete")

_trace("importlib_machinery_origin_check", "start")
_machinery_origin = getattr(importlib.machinery, "__file__", None)
if not isinstance(_machinery_origin, str) or not any(
    _boot_under(_machinery_origin, root) for root in _boot_roots
):
    raise RuntimeError("importlib_machinery_origin_not_trusted")
_trace("importlib_machinery_origin_check", "complete")

_stdlib_preload_names = (
    "asyncio", "unittest.mock", "ssl", "http.client", "socket",
    "multiprocessing", "multiprocessing.connection", "multiprocessing.process",
    "subprocess", "threading", "ctypes", "ctypes.util", "ctypes.wintypes",
    "sqlite3", "hashlib", "hmac", "base64", "contextlib", "importlib.util",
    "inspect", "tempfile", "dataclasses", "decimal", "datetime", "json",
    "pickle", "re", "struct", "types", "typing", "unicodedata", "urllib.parse", "uuid", "weakref",
    "zipfile", "collections", "copy", "builtins", "io", "os", "pathlib",
    "stat", "sysconfig", "time", "warnings", "bisect", "faulthandler",
    "pyexpat",
    "xml.etree.ElementTree",
)

def _boot_origin(module):
    origin = getattr(module, "__file__", None)
    if origin is None:
        origin = getattr(getattr(module, "__spec__", None), "origin", None)
    return origin

def _boot_origin_is_trusted(origin):
    if origin in {"built-in", "frozen", "namespace"}:
        return True
    if not isinstance(origin, str):
        return False
    if any(_boot_under(origin, root) for root in _boot_roots):
        return True
    return any(_boot_under(origin, archive) for archive in _boot_zip_paths)

_stdlib_origins = {}
_PYEXPAT_IMPORTED_PARENT = None
_trace("trusted_stdlib_origin_preload", "start")
for _name in _stdlib_preload_names:
    _module = importlib.import_module(_name)
    _origin = _boot_origin(_module)
    if not _boot_origin_is_trusted(_origin):
        raise RuntimeError("stdlib_preload_origin_not_trusted")
    _stdlib_origins[_name] = str(_origin or "built-in-or-frozen")
    if _name == "pyexpat":
        if _PYEXPAT_IMPORTED_PARENT is not None:
            raise RuntimeError("pyexpat_import_binding_duplicate")
        _PYEXPAT_IMPORTED_PARENT = _module
_trace("trusted_stdlib_origin_preload", "complete")

_child_origin = _boot_norm(__file__)
_trace("trusted_preloaded_module_origin_scan", "start")
_preloaded_module_origin_scan_allowances = []
_preloaded_module_origin_scan_rejection = None
_preloaded_module_origin_scan_counts = {
    "initial": 0,
    "post_stdlib": 0,
    "post_qa": 0,
}
_origin_scan_rejection_prefix = "ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17_SCAN_REJECTED:"

def _origin_scan_safe_name(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.isascii()
        or any(not (character.isalnum() or character in "._") for character in value)
    ):
        return "noncanonical"
    return value

_PYEXPAT_CHILD_BINDINGS = (
    ("pyexpat.errors", "errors"),
    ("pyexpat.model", "model"),
)
_PYEXPAT_CHILD_MODULE_NAMES = frozenset(name for name, _attribute in _PYEXPAT_CHILD_BINDINGS)
_PYEXPAT_EXPECTED_ORIGIN = _boot_norm(
    sys.base_prefix.rstrip("/\\") + "/DLLs/pyexpat.pyd"
)


def _pyexpat_snapshot_candidate():
    parent = _PYEXPAT_IMPORTED_PARENT
    types_module = sys.modules.get("types")
    machinery_module = importlib.machinery
    module_spec_type = getattr(machinery_module, "ModuleSpec", None)
    extension_loader_type = getattr(machinery_module, "ExtensionFileLoader", None)
    if (
        parent is None
        or types_module is None
        or type(types_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(types_module))
        or _boot_norm(_stdlib_origins.get("types", ""))
        != _boot_norm(_boot_origin(types_module))
        or sys.modules.get("importlib.machinery") is not machinery_module
        or type(machinery_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(machinery_module))
        or module_spec_type is not importlib.machinery.ModuleSpec
        or extension_loader_type is not importlib.machinery.ExtensionFileLoader
        or type(parent) is not types_module.ModuleType
        or sys.modules.get("pyexpat") is not parent
        or getattr(parent, "__name__", None) != "pyexpat"
    ):
        return None
    expected_origin = _PYEXPAT_EXPECTED_ORIGIN
    if (
        not isinstance(expected_origin, str)
        or expected_origin != PYEXPAT_ORIGIN_TEXT.casefold()
        or not any(
            _boot_under(expected_origin, root)
            and _boot_norm(root).endswith("/dlls")
            for root in _boot_roots
        )
        or not _boot_origin_is_trusted(expected_origin)
    ):
        return None
    parent_file = getattr(parent, "__file__", None)
    spec = getattr(parent, "__spec__", None)
    loader = getattr(parent, "__loader__", None)
    if (
        not isinstance(parent_file, str)
        or _boot_norm(parent_file) != expected_origin
        or type(spec) is not module_spec_type
        or getattr(spec, "name", None) != "pyexpat"
        or not isinstance(getattr(spec, "origin", None), str)
        or _boot_norm(spec.origin) != expected_origin
        or type(loader) is not extension_loader_type
        or getattr(spec, "loader", None) is not loader
        or getattr(loader, "name", None) != "pyexpat"
        or not isinstance(getattr(loader, "path", None), str)
        or _boot_norm(loader.path) != expected_origin
        or _boot_norm(_stdlib_origins.get("pyexpat", "")) != expected_origin
    ):
        return None
    children = []
    parent_namespace = vars(parent)
    for module_name, attribute in _PYEXPAT_CHILD_BINDINGS:
        child = sys.modules.get(module_name)
        if (
            child is None
            or type(child) is not types_module.ModuleType
            or parent_namespace.get(attribute) is not child
        ):
            return None
        child_namespace = vars(child)
        if (
            child_namespace.get("__name__") != module_name
            or "__file__" in child_namespace
            or "__spec__" not in child_namespace
            or child_namespace["__spec__"] is not None
        ):
            return None
        children.append((module_name, attribute, child, module_name, False, True, None, None))
    return (
        parent,
        spec,
        loader,
        expected_origin,
        tuple(children),
        types_module,
        machinery_module,
        module_spec_type,
        extension_loader_type,
    )


def _pyexpat_snapshot_matches(snapshot):
    if not isinstance(snapshot, tuple) or len(snapshot) != 9:
        return False
    (
        parent, expected_spec, expected_loader, expected_origin, children,
        expected_types_module, expected_machinery_module,
        expected_module_spec_type, expected_extension_loader_type,
    ) = snapshot
    types_module = sys.modules.get("types")
    if (
        types_module is None
        or types_module is not expected_types_module
        or type(types_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(types_module))
        or _boot_norm(_stdlib_origins.get("types", ""))
        != _boot_norm(_boot_origin(types_module))
        or sys.modules.get("importlib.machinery") is not expected_machinery_module
        or importlib.machinery is not expected_machinery_module
        or type(expected_machinery_module) is not type(sys)
        or not _boot_origin_is_trusted(_boot_origin(expected_machinery_module))
        or getattr(expected_machinery_module, "ModuleSpec", None)
        is not expected_module_spec_type
        or getattr(expected_machinery_module, "ExtensionFileLoader", None)
        is not expected_extension_loader_type
        or type(parent) is not types_module.ModuleType
        or parent is not _PYEXPAT_IMPORTED_PARENT
        or sys.modules.get("pyexpat") is not parent
        or getattr(parent, "__name__", None) != "pyexpat"
        or getattr(parent, "__file__", None) is None
        or _boot_norm(parent.__file__) != expected_origin
        or expected_origin != _PYEXPAT_EXPECTED_ORIGIN
        or expected_origin != PYEXPAT_ORIGIN_TEXT.casefold()
        or not _boot_origin_is_trusted(expected_origin)
        or not any(
            _boot_under(expected_origin, root)
            and _boot_norm(root).endswith("/dlls")
            for root in _boot_roots
        )
        or _boot_norm(_stdlib_origins.get("pyexpat", "")) != expected_origin
        or getattr(parent, "__spec__", None) is not expected_spec
        or type(expected_spec) is not expected_module_spec_type
        or getattr(expected_spec, "name", None) != "pyexpat"
        or getattr(expected_spec, "origin", None) is None
        or _boot_norm(expected_spec.origin) != expected_origin
        or getattr(parent, "__loader__", None) is not expected_loader
        or getattr(expected_spec, "loader", None) is not expected_loader
        or type(expected_loader) is not expected_extension_loader_type
        or getattr(expected_loader, "name", None) != "pyexpat"
        or getattr(expected_loader, "path", None) is None
        or _boot_norm(expected_loader.path) != expected_origin
        or not isinstance(children, tuple)
        or len(children) != len(_PYEXPAT_CHILD_BINDINGS)
    ):
        return False
    parent_namespace = vars(parent)
    for expected, (module_name, attribute) in zip(children, _PYEXPAT_CHILD_BINDINGS):
        if not isinstance(expected, tuple) or len(expected) != 8:
            return False
        (
            expected_name, expected_attribute, child, child_name,
            child_file_present, child_spec_present, child_file, child_spec,
        ) = expected
        current = sys.modules.get(module_name)
        if (
            expected_name != module_name
            or expected_attribute != attribute
            or child_name != module_name
            or child_file_present is not False
            or child_spec_present is not True
            or child_file is not None
            or child_spec is not None
            or current is not child
            or parent_namespace.get(attribute) is not child
            or type(child) is not types_module.ModuleType
        ):
            return False
        child_namespace = vars(child)
        if (
            child_namespace.get("__name__") != child_name
            or ("__file__" in child_namespace) is not child_file_present
            or ("__spec__" in child_namespace) is not child_spec_present
            or child_namespace.get("__file__") is not child_file
            or child_namespace.get("__spec__") is not child_spec
        ):
            return False
    return True


_PYEXPAT_EXPECTED_BINDING = _pyexpat_snapshot_candidate()


def _pyexpat_binding_is_live(_snapshot=_PYEXPAT_EXPECTED_BINDING):
    return (
        _snapshot is not None
        and _pyexpat_snapshot_matches(_snapshot)
    )


def _pyexpat_child_binding_is_live(
    name, module, _snapshot=_PYEXPAT_EXPECTED_BINDING,
    _binding_check=_pyexpat_binding_is_live,
):
    if name not in _PYEXPAT_CHILD_MODULE_NAMES or not _binding_check():
        return False
    for expected in _snapshot[4]:
        if expected[0] == name:
            return module is expected[2]
    return False


_PYEXPAT_BOOTSTRAP_RECEIPT = {
    "status": "verified",
    "module_name": "pyexpat",
    "module_type": "types.ModuleType",
    "spec_origin": _PYEXPAT_EXPECTED_ORIGIN,
    "loader": "ExtensionFileLoader",
    "child_module_names": ["pyexpat.errors", "pyexpat.model"],
    "child_module_type": "types.ModuleType",
    "child_file": "absent",
    "child_spec": "present_none",
    "parent_attribute_and_sys_modules_identity_checked": True,
    "extension_api_calls_performed": False,
}


def _origin_scan_rejection_category(name, origin):
    if name in _PYEXPAT_CHILD_MODULE_NAMES:
        return "pyexpat_synthetic_child_binding_mismatch"
    if name == "winreg":
        return "winreg_builtin_binding_mismatch"
    if name == "__mp_main__":
        return "main_alias_identity_mismatch"
    if name in {"typing.io", "typing.re"}:
        return "typing_deprecated_alias_identity_mismatch"
    if not isinstance(origin, str):
        return "missing_or_nonstring_origin"
    if _boot_norm(origin) == _child_origin:
        return "child_source_origin_wrong_module"
    return "outside_trusted_stdlib_roots"

_main_module = sys.modules.get("__main__")
_typing_module = sys.modules.get("typing")
_typing_origin = _boot_origin(_typing_module) if _typing_module is not None else None
_typing_deprecated_type = getattr(_typing_module, "_DeprecatedType", None)

_WINREG_FUNCTION_NAMES = (
    "CloseKey", "ConnectRegistry", "CreateKey", "CreateKeyEx", "DeleteKey",
    "DeleteKeyEx", "DeleteValue", "DisableReflectionKey", "EnableReflectionKey",
    "EnumKey", "EnumValue", "ExpandEnvironmentStrings", "FlushKey", "LoadKey",
    "OpenKey", "OpenKeyEx", "QueryInfoKey", "QueryReflectionKey", "QueryValue",
    "QueryValueEx", "SaveKey", "SetValue", "SetValueEx",
)
_WINREG_CLASS_NAMES = ("HKEYType", "error")
_WINREG_PUBLIC_NAMES = frozenset(_WINREG_FUNCTION_NAMES + _WINREG_CLASS_NAMES)


def _winreg_binding_shape(module):
    types_module = sys.modules.get("types")
    if (
        module is None
        or types_module is None
        or type(module) is not types_module.ModuleType
        or sys.modules.get("winreg") is not module
        or getattr(module, "__name__", None) != "winreg"
        or getattr(module, "__file__", None) is not None
    ):
        return None
    spec = getattr(module, "__spec__", None)
    builtin_importer = importlib.machinery.BuiltinImporter
    if (
        type(spec) is not importlib.machinery.ModuleSpec
        or getattr(spec, "name", None) != "winreg"
        or getattr(spec, "origin", None) != "built-in"
        or getattr(spec, "loader", None) is not builtin_importer
        or getattr(module, "__loader__", None) is not builtin_importer
    ):
        return None
    canonical_spec = builtin_importer.find_spec("winreg")
    if (
        type(canonical_spec) is not importlib.machinery.ModuleSpec
        or getattr(canonical_spec, "name", None) != "winreg"
        or getattr(canonical_spec, "origin", None) != "built-in"
        or getattr(canonical_spec, "loader", None) is not builtin_importer
    ):
        return None
    namespace = vars(module)
    public_bindings = {
        name: value
        for name, value in namespace.items()
        if not name.startswith("_")
        and (
            type(value) is types_module.BuiltinFunctionType
            or type(value) is type
        )
    }
    if set(public_bindings) != _WINREG_PUBLIC_NAMES:
        return None
    function_bindings = []
    for name in _WINREG_FUNCTION_NAMES:
        value = public_bindings.get(name)
        if (
            type(value) is not types_module.BuiltinFunctionType
            or getattr(value, "__module__", None) != "winreg"
            or getattr(value, "__name__", None) != name
            or getattr(value, "__qualname__", None) != name
            or getattr(value, "__self__", None) is not module
        ):
            return None
        function_bindings.append((name, value))
    hkey_type = public_bindings.get("HKEYType")
    winreg_error = public_bindings.get("error")
    if (
        type(hkey_type) is not type
        or getattr(hkey_type, "__module__", None) != "builtins"
        or getattr(hkey_type, "__name__", None) != "PyHKEY"
        or getattr(hkey_type, "__qualname__", None) != "PyHKEY"
        or getattr(hkey_type, "__bases__", None) != (object,)
        or winreg_error is not OSError
        or type(winreg_error) is not type
        or getattr(winreg_error, "__module__", None) != "builtins"
        or getattr(winreg_error, "__name__", None) != "OSError"
        or getattr(winreg_error, "__qualname__", None) != "OSError"
    ):
        return None
    return (
        module,
        spec,
        builtin_importer,
        tuple(function_bindings),
        (("HKEYType", hkey_type), ("error", winreg_error)),
    )


_WINREG_BOOTSTRAP_BINDING = _winreg_binding_shape(sys.modules.get("winreg"))


def _winreg_binding_is_live(name, module):
    if name != "winreg" or module is None or sys.modules.get("winreg") is not module:
        return False
    held = _WINREG_BOOTSTRAP_BINDING
    current = _winreg_binding_shape(module)
    if held is None or current is None:
        return False
    if current[0] is not held[0] or current[1] is not held[1] or current[2] is not held[2]:
        return False
    return (
        len(current[3]) == len(held[3])
        and all(
            current_name == held_name and current_value is held_value
            for (current_name, current_value), (held_name, held_value)
            in zip(current[3], held[3])
        )
        and len(current[4]) == len(held[4])
        and all(
            current_name == held_name and current_value is held_value
            for (current_name, current_value), (held_name, held_value)
            in zip(current[4], held[4])
        )
    )


_WINREG_BOOTSTRAP_RECEIPT = {
    "status": "verified",
    "module_name": "winreg",
    "module_type": "types.ModuleType",
    "spec_origin": "built-in",
    "loader": "BuiltinImporter",
    "function_names": list(_WINREG_FUNCTION_NAMES),
    "class_bindings": {
        "HKEYType": "builtins.type:PyHKEY",
        "error": "builtins.type:OSError",
    },
    "registry_operation_audit_denied": True,
    "registry_api_calls_performed": False,
}


def _origin_scan_typing_alias_is_live(name, module):
    if name not in {"typing.io", "typing.re"}:
        return False
    alias_name = name.rsplit(".", 1)[1]
    current_typing = sys.modules.get("typing")
    if current_typing is None or current_typing is not _typing_module:
        return False
    if type(current_typing) is not type(sys):
        return False
    current_origin = _boot_origin(current_typing)
    if (
        not isinstance(_typing_origin, str)
        or not isinstance(current_origin, str)
        or _boot_norm(current_origin) != _boot_norm(_typing_origin)
        or not _boot_origin_is_trusted(current_origin)
    ):
        return False
    recorded_origin = _stdlib_origins.get("typing")
    if (
        not isinstance(recorded_origin, str)
        or _boot_norm(recorded_origin) != _boot_norm(_typing_origin)
    ):
        return False
    current_deprecated_type = getattr(current_typing, "_DeprecatedType", None)
    if (
        current_deprecated_type is None
        or current_deprecated_type is not _typing_deprecated_type
        or type(current_deprecated_type) is not type
        or getattr(current_deprecated_type, "__module__", None) != "typing"
        or getattr(current_deprecated_type, "__qualname__", None) != "_DeprecatedType"
    ):
        return False
    return (
        type(module) is current_deprecated_type
        and module is getattr(current_typing, alias_name, None)
        and getattr(module, "__module__", None) == "typing"
        and getattr(module, "__qualname__", None) == alias_name
    )

def _origin_scan_rescan_category(name, module, origin, scan_name):
    if scan_name not in {"post_stdlib", "post_qa"}:
        raise RuntimeError("origin_rescan_name_invalid")
    origin_key = _boot_norm(origin) if isinstance(origin, str) else ""
    if name == "__main__" and module is _main_module and origin_key == _child_origin:
        return "main_module_at_pinned_child_origin"
    if name == "__mp_main__" and module is _main_module and origin_key == _child_origin:
        return "same_object_main_alias_at_pinned_child_origin"
    if name in _PYEXPAT_CHILD_MODULE_NAMES:
        if _pyexpat_child_binding_is_live(name, module):
            return "synthetic_child_of_canonical_pyexpat_extension"
        return "pyexpat_synthetic_child_binding_mismatch"
    if _winreg_binding_is_live(name, module):
        return "canonical_winreg_builtin_binding"
    if _origin_scan_typing_alias_is_live(name, module):
        return "typing_deprecated_type_alias_at_trusted_typing_origin"
    return None

def _record_preloaded_origin_rejection(name, origin):
    global _preloaded_module_origin_scan_rejection
    safe_name = _origin_scan_safe_name(name)
    category = _origin_scan_rejection_category(name, origin)
    _preloaded_module_origin_scan_rejection = {
        "module_name": safe_name,
        "origin_category": category,
    }
    sys.stdout.write(_origin_scan_rejection_prefix + safe_name + "|" + category + "\n")
    sys.stdout.flush()
    raise RuntimeError("preloaded_module_origin_not_trusted")

if not _pyexpat_binding_is_live():
    _record_preloaded_origin_rejection("pyexpat.errors", None)

for _name, _module in tuple(sys.modules.items()):
    _origin = _boot_origin(_module)
    _origin_key = _boot_norm(_origin or "") if isinstance(_origin, str) else ""
    if (
        _name == "__main__"
        and _module is _main_module
        and _origin_key == _child_origin
    ):
        _preloaded_module_origin_scan_allowances.append(
            {"module_name": "__main__", "origin_category": "main_module_at_pinned_child_origin"}
        )
        _preloaded_module_origin_scan_counts["initial"] += 1
        continue
    if (
        _name == "__mp_main__"
        and _module is _main_module
        and _origin_key == _child_origin
    ):
        _preloaded_module_origin_scan_allowances.append(
            {
                "module_name": "__mp_main__",
                "origin_category": "same_object_main_alias_at_pinned_child_origin",
            }
        )
        _preloaded_module_origin_scan_counts["initial"] += 1
        continue
    if _name in _PYEXPAT_CHILD_MODULE_NAMES:
        if _pyexpat_child_binding_is_live(_name, _module):
            _preloaded_module_origin_scan_allowances.append(
                {
                    "module_name": _name,
                    "origin_category": "synthetic_child_of_canonical_pyexpat_extension",
                }
            )
            _preloaded_module_origin_scan_counts["initial"] += 1
            continue
        _record_preloaded_origin_rejection(_name, _origin)
    if _name in {"typing.io", "typing.re"}:
        _alias_name = _name.rsplit(".", 1)[1]
        if _origin_scan_typing_alias_is_live(_name, _module):
            _preloaded_module_origin_scan_allowances.append(
                {
                    "module_name": _name,
                    "origin_category": "typing_deprecated_type_alias_at_trusted_typing_origin",
                }
            )
            _preloaded_module_origin_scan_counts["initial"] += 1
            continue
    if _name == "winreg":
        if _winreg_binding_is_live(_name, _module):
            _preloaded_module_origin_scan_allowances.append(
                {
                    "module_name": "winreg",
                    "origin_category": "canonical_winreg_builtin_binding",
                }
            )
            _preloaded_module_origin_scan_counts["initial"] += 1
            continue
        _record_preloaded_origin_rejection(_name, _origin)
    if _boot_origin_is_trusted(_origin):
        continue
    _record_preloaded_origin_rejection(_name, _origin)

_preloaded_module_origin_scan_allowances.sort(key=lambda item: item["module_name"])
_preloaded_module_origin_scan_receipt = {
    "status": "complete",
    "allowed_entry_count": len(_preloaded_module_origin_scan_allowances),
    "allowed_entries": list(_preloaded_module_origin_scan_allowances),
    "scan_allowance_counts": _preloaded_module_origin_scan_counts,
}
_trace("trusted_preloaded_module_origin_scan", "complete")

import builtins, ctypes, ctypes.util, dataclasses, decimal, hashlib, hmac
import http.client, importlib, importlib.machinery, importlib.util, inspect, io, json
import multiprocessing, multiprocessing.connection, multiprocessing.process
import os, pathlib, pickle, re, socket, sqlite3, ssl, stat, subprocess, sys, sysconfig
import tempfile, threading, time, types, urllib.parse, uuid, warnings, weakref, zipfile
from collections import defaultdict
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import ModuleType

REPO_ROOT = pathlib.Path(REPO_ROOT_TEXT).resolve()
ROOT = pathlib.Path(ROOT_TEXT).resolve()
SITE = pathlib.Path(SITE_TEXT).resolve()
QA = pathlib.Path(QA_TEXT).resolve()
STD_TEMP = pathlib.Path(STD_TEMP_TEXT).resolve()
PYTEST_BASE_TEMP = QA / "pytest-basetemp"
PYTEST_CONFIG_PATH = pathlib.Path(PYTEST_CONFIG_TEXT_PATH).resolve()
PYTEST_CONFIG_EXPECTED = PYTEST_CONFIG_CONTENT_TEXT.encode("ascii")
PYTEST_CONFIG_EXPECTED_SHA256 = PYTEST_CONFIG_SHA256_TEXT
TEST_PATH = (ROOT / TEST_RELATIVE).resolve()
SUITE_PATH = TEST_PATH.parents[3] / "examples" / "000_live_certification" / "binance_penetration"
PIN_MAP = PIN_MAP_VALUE
EXPECTED_NAMES = EXPECTED_TEST_NAMES_VALUE
EXPECTED_SELF_CHECKS = EXPECTED_GUARD_SELFCHECKS_VALUE
EXPECTED_EARLY_GUARD_CHECKS = EXPECTED_EARLY_GUARD_CHECKS_VALUE
EXPECTED_PRIVATE_MODULE_ROOTS = {
    "bt_api", "bt_api_py", "binance", "binance_sdk", "binance_common",
    "python_binance", "ccxt", "xtquant", "backtrader_runtime",
    "win32api", "win32con", "win32file", "win32event", "win32process", "winreg",
}
NATIVE_SUFFIXES = {".dll", ".exe", ".bin", ".pyd", ".so", ".dylib"}
BLOCKED = []
SELF_CHECK = True
FAKE_CONSOLE_CALLS = {"library_requests": 0, "api_calls": 0, "configurations": 0}
REPO_SOURCE_LOADS = {}
REPO_SOURCE_READS = set()
IMPORT_SNAPSHOT = {}
SELF_CHECKS_DONE = []
PIN_ONLY_PATHS = {
    "examples/000_live_certification/binance_penetration/_certification/th01_root_readonly.py",
    "backtrader_runtime/certification_roundtrip_private.py",
    "backtrader_runtime/certification_roundtrip_r3_bootstrap.py",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py",
}
RUNTIME_NATIVE_ORIGINS = set()
CONSOLE_FACADE = None
EARLY_GUARD_CHECKS = []


class GuardViolation(PermissionError):
    pass


def norm_path(value):
    if isinstance(value, (bytes, bytearray)):
        value = os.fsdecode(value)
    elif isinstance(value, os.PathLike):
        value = os.fspath(value)
    return str(value).replace(chr(92), "/").casefold()


def under(path, parent):
    try:
        return norm_path(os.path.commonpath([path, parent])) == norm_path(parent)
    except ValueError:
        return False


ROOT_KEY = norm_path(ROOT).rstrip("/")
REPO_KEY = norm_path(REPO_ROOT).rstrip("/")
SITE_KEY = norm_path(SITE).rstrip("/")
QA_KEY = norm_path(QA).rstrip("/")
PYTEST_CONFIG_KEY = norm_path(PYTEST_CONFIG_PATH)
BASE_KEY = norm_path(sys.base_prefix).rstrip("/")
PIN_PATHS = {norm_path(ROOT / relative) for relative in PIN_MAP}
PIN_ONLY_KEYS = {norm_path(ROOT / relative) for relative in PIN_ONLY_PATHS}
STD_ROOTS = {
    norm_path(value)
    for key in ("stdlib", "platstdlib")
    if (value := sysconfig.get_paths().get(key))
}
STD_ROOTS.update(_boot_norm(root) for root in _boot_roots)
STD_ZIP_ROOTS = {_boot_norm(path) for path in _boot_zip_paths}
STD_DLL_ROOTS = {
    _boot_norm(root) for root in _boot_roots if _boot_norm(root).endswith("/dlls")
}


def denied_path(value):
    value = norm_path(value)
    leaf = value.rsplit("/", 1)[-1]
    suffix = pathlib.Path(value).suffix.casefold()
    private_markers = (
        "private-capture", "private_capture", "private-captures", "private_captures",
        "/captures/", "/capture/",
    )
    opaque_markers = ("/opaque/", "/external-software/", "/external_software/")
    return (
        leaf in {".env", "config.yaml", "secrets.yaml"}
        or any(marker in value for marker in private_markers)
        or any(marker in ("/" + value.strip("/") + "/") for marker in opaque_markers)
        or suffix in {".dll", ".exe", ".bin"}
        or (
            suffix in {".pyd", ".so", ".dylib"}
            and not any(under(value, root) for root in STD_DLL_ROOTS)
        )
    )


class SafeConsoleApi:
    """Inert facade used only while Colorama is imported on Windows."""
    def __getattr__(self, _name):
        return self
    def __setattr__(self, _name, _value):
        FAKE_CONSOLE_CALLS["configurations"] += 1
    def __call__(self, *_args, **_kwargs):
        FAKE_CONSOLE_CALLS["api_calls"] += 1
        return 0
    def __bool__(self):
        return False


def _pytest_config_pin() -> dict:
    info = PYTEST_CONFIG_PATH.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("pytest_config_shape_invalid")
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("pytest_config_reparse_point_denied")
    raw = PYTEST_CONFIG_PATH.read_bytes()
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "matches_expected": raw == PYTEST_CONFIG_EXPECTED,
    }


def _preload() -> dict:
    global CONSOLE_FACADE
    _trace("qa_preload_validation", "start")
    if os.name != "nt":
        raise RuntimeError("root_qa_requires_windows")
    if not STD_TEMP.is_dir() or not under(norm_path(STD_TEMP), norm_path(QA)):
        raise RuntimeError("stdlib_temp_root_invalid")
    if any(under(norm_path(entry), SITE_KEY) for entry in sys.path):
        raise RuntimeError("qa_site_present_before_stdlib_verification")
    if (
        PYTEST_CONFIG_PATH != (QA / "pytest.ini").resolve()
        or PYTEST_CONFIG_EXPECTED != b"[pytest]\n"
        or hashlib.sha256(PYTEST_CONFIG_EXPECTED).hexdigest()
        != PYTEST_CONFIG_EXPECTED_SHA256
        or not _pytest_config_pin()["matches_expected"]
    ):
        raise RuntimeError("pytest_config_preload_pin_mismatch")
    if (
        norm_path(os.environ.get("TEMP", "")) != norm_path(STD_TEMP)
        or norm_path(os.environ.get("TMP", "")) != norm_path(STD_TEMP)
    ):
        raise RuntimeError("stdlib_temp_environment_mismatch")
    tempfile.tempdir = str(STD_TEMP)
    if any(name == "_certification" or name.startswith("_certification.")
           or name.startswith("test_binance_th01_account_full_snapshot_r2")
           for name in sys.modules):
        raise RuntimeError("candidate_preloaded_before_guards")
    _trace("qa_preload_validation", "complete")

    facade = SafeConsoleApi()
    CONSOLE_FACADE = facade
    ctypes.windll = facade
    ctypes.oledll = facade
    def safe_library(*_args, **_kwargs):
        FAKE_CONSOLE_CALLS["library_requests"] += 1
        return facade
    for name in ("WinDLL", "OleDLL"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, safe_library)

    # TLS/HTTP, asyncio and process-support imports have already been loaded
    # with SITE absent from sys.path. Recheck their trusted origins before the
    # QA package path is made visible.
    preload_names = tuple(_stdlib_preload_names)
    preload_origins = {}
    _trace("trusted_stdlib_origin_recheck", "start")
    for name in preload_names:
        module = importlib.import_module(name)
        origin = _boot_origin(module)
        if not _boot_origin_is_trusted(origin):
            raise RuntimeError("stdlib_preload_origin_mismatch")
        preload_origins[name] = str(origin or "built-in-or-frozen")
    _trace("trusted_stdlib_origin_recheck", "complete")

    _trace("trusted_module_origin_recheck", "start")
    for name, module in tuple(sys.modules.items()):
        origin = _boot_origin(module)
        alias_category = _origin_scan_rescan_category(name, module, origin, "post_stdlib")
        if alias_category == "pyexpat_synthetic_child_binding_mismatch":
            _record_preloaded_origin_rejection(name, origin)
        if alias_category is not None:
            _preloaded_module_origin_scan_counts["post_stdlib"] += 1
            continue
        if not _boot_origin_is_trusted(origin):
            _record_preloaded_origin_rejection(name, origin)
    _trace("trusted_module_origin_recheck", "complete")
    forbidden_before_qa = sorted(
        name for name in sys.modules
        if name.partition(".")[0].casefold() in EXPECTED_PRIVATE_MODULE_ROOTS
        and name.partition(".")[0].casefold() != "_winapi"
        and not (name == "winreg" and _winreg_binding_is_live(name, sys.modules.get(name)))
    )
    if forbidden_before_qa:
        raise RuntimeError("forbidden_module_preloaded_before_early_guards")

    _trace("early_hard_guard_install", "start")
    early_guard_installation = install_early_guards()
    if (
        early_guard_installation.get("installed_before_first_qa_package") is not True
        or tuple(early_guard_installation.get("checks", ()))
        != tuple(EXPECTED_EARLY_GUARD_CHECKS)
        or EARLY_GUARD_CHECKS != list(EXPECTED_EARLY_GUARD_CHECKS)
    ):
        raise RuntimeError("early_guard_installation_not_verified")
    _trace("early_hard_guard_install", "complete")

    sys.path.append(str(SITE))
    if not sys.path or norm_path(sys.path[-1]) != SITE_KEY:
        raise RuntimeError("qa_site_not_appended_after_stdlib")

    # Colorama sees only the inert facade above. The pure-Python YAML loader is
    # also required; no QA/native extension may enter from site-packages.
    qa_preload_names = (
        "colorama", "colorama.ansi", "colorama.ansitowin32", "colorama.initialise",
        "colorama.win32", "colorama.winterm",
    )
    for name in qa_preload_names:
        _trace("qa_dependency_import:" + name, "start")
        module = importlib.import_module(name)
        origin = _boot_origin(module)
        if not isinstance(origin, str) or not under(norm_path(origin), SITE_KEY):
            raise RuntimeError("colorama_origin_mismatch")
        preload_origins[name] = origin
        _trace("qa_dependency_import:" + name, "complete")

    # The certification package imports config.py, which imports PyYAML. Force
    # its supported pure-Python fallback if the optional C accelerator exists.
    class RejectYamlAccelerator:
        def find_spec(self, fullname, path=None, target=None):
            if fullname in {"yaml._yaml", "_yaml"}:
                raise ImportError("source_qa_yaml_native_accelerator_disabled")
            return None
    sys.meta_path.insert(0, RejectYamlAccelerator())
    for name in ("yaml", "pytest"):
        _trace("qa_dependency_import:" + name, "start")
        module = importlib.import_module(name)
        origin = getattr(module, "__file__", None)
        if not isinstance(origin, str) or not under(norm_path(origin), SITE_KEY):
            raise RuntimeError("qa_dependency_origin_mismatch")
        preload_origins[name] = origin
        _trace("qa_dependency_import:" + name, "complete")

    _trace("third_party_module_origin_audit", "start")
    for name, module in tuple(sys.modules.items()):
        origin = _boot_origin(module)
        alias_category = _origin_scan_rescan_category(name, module, origin, "post_qa")
        if alias_category == "pyexpat_synthetic_child_binding_mismatch":
            _record_preloaded_origin_rejection(name, origin)
        if alias_category is not None:
            _preloaded_module_origin_scan_counts["post_qa"] += 1
            continue
        if origin in {"built-in", "frozen", "namespace"}:
            continue
        origin_key = norm_path(origin)
        if not (
            any(under(origin_key, root) for root in STD_ROOTS)
            or any(_boot_under(origin_key, root) for root in STD_ZIP_ROOTS)
            or under(origin_key, SITE_KEY)
        ):
            _record_preloaded_origin_rejection(name, origin)
    _trace("third_party_module_origin_audit", "complete")

    forbidden_preload = sorted(
        name for name in sys.modules
        if name.partition(".")[0].casefold() in EXPECTED_PRIVATE_MODULE_ROOTS
        or name.partition(".")[0].casefold() in {"_winapi"}
    )
    # _winapi is loaded by Windows multiprocessing before the guard. Its
    # callable surface is patched below; other forbidden roots must be absent.
    forbidden_preload = [
        name for name in forbidden_preload
        if name != "_winapi"
        and not (name == "winreg" and _winreg_binding_is_live(name, sys.modules.get(name)))
    ]
    if forbidden_preload:
        raise RuntimeError("forbidden_module_preloaded")

    extension_origins = {}
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if isinstance(origin, str) and pathlib.Path(origin).suffix.casefold() in NATIVE_SUFFIXES:
            origin_key = norm_path(origin)
            if not any(under(origin_key, root) for root in STD_DLL_ROOTS):
                raise RuntimeError("external_native_module_preloaded")
            extension_origins[name] = origin
    RUNTIME_NATIVE_ORIGINS.update(norm_path(value) for value in extension_origins.values())
    _trace("qa_preload", "complete")
    return {
        "status": "complete",
        "phase": "trusted_stdlib_verified_then_hard_guards_before_qa_site_and_third_party_imports",
        "stdlib_verified_before_site": True,
        "initial_import_prefix_root_entries_removed": list(_boot_initial_prefix_root_entries_removed),
        "initial_import_prefix_root_keys_authorized": list(_boot_prefix_root_keys_authorized),
        "initial_import_path_after_prefix_drop": list(_boot_initial_path_after_prefix_drop),
        "preloaded_module_origin_scan": _preloaded_module_origin_scan_receipt,
        "early_guard_installation": early_guard_installation,
        "hard_guards_before_first_third_party_import": True,
        "forbidden_modules_absent_before_guard_install": not forbidden_before_qa,
        "winreg_bootstrap_binding": dict(_WINREG_BOOTSTRAP_RECEIPT),
        "pyexpat_bootstrap_binding": dict(_PYEXPAT_BOOTSTRAP_RECEIPT),
        "site_path_position": "appended_after_trusted_stdlib_paths",
        "modules": list(preload_names) + list(qa_preload_names) + ["yaml", "pytest"],
        "bootstrap_stdlib_origins": dict(_stdlib_origins),
        "module_origins": preload_origins,
        "windows_console_api": "inert_facade",
        "python_runtime_extension_origins": extension_origins,
        "candidate_imported": False,
    }


def deny(label):
    if not SELF_CHECK:
        BLOCKED.append(label)
    raise GuardViolation("source_qa_denied:" + label)


def audit(event, args):
    if isinstance(event, str) and event.startswith("winreg."):
        deny("blocked_winreg_operation")
    if event == "import" and args:
        name = args[0] if isinstance(args[0], str) else ""
        root = name.partition(".")[0].casefold()
        if root in EXPECTED_PRIVATE_MODULE_ROOTS or root == "_winapi":
            deny("blocked_import")
        origin = args[1] if len(args) > 1 else None
        if isinstance(origin, (str, bytes, os.PathLike)):
            origin_key = norm_path(origin)
            suffix = pathlib.Path(origin_key).suffix.casefold()
            if denied_path(origin):
                deny("native_or_opaque_import")
            if suffix in NATIVE_SUFFIXES and origin_key not in RUNTIME_NATIVE_ORIGINS:
                deny("unpreloaded_native_import")
    if event in {"open", "os.open"} and args:
        path = args[0]
        if isinstance(path, (str, bytes, os.PathLike)):
            path_key = norm_path(path)
            if denied_path(path):
                deny("private_or_native_read")
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            writing = (isinstance(mode, str) and any(char in mode for char in "wax+")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            if writing:
                if path_key == PYTEST_CONFIG_KEY:
                    deny("pytest_config_write_denied")
                if under(path_key, ROOT_KEY):
                    deny("write_to_selected_source_denied")
                if not under(path_key, QA_KEY):
                    deny("write_outside_external_qa")
            elif under(path_key, ROOT_KEY):
                if path_key not in PIN_PATHS or path_key in PIN_ONLY_KEYS:
                    deny("unpinned_or_pin_only_repo_read")
                REPO_SOURCE_READS.add(path_key)
            elif under(path_key, REPO_KEY):
                deny("checkout_read_outside_selected_namespace")
            elif not (
                under(path_key, QA_KEY)
                or under(path_key, SITE_KEY)
                or any(under(path_key, root) for root in STD_ROOTS)
                or any(_boot_under(path_key, root) for root in STD_ZIP_ROOTS)
            ):
                deny("filesystem_read_outside_qa_closure")
    if event in {"os.remove", "os.rename"}:
        candidates = args[:2] if event == "os.rename" else args[:1]
        if any(
            isinstance(value, (str, bytes, os.PathLike))
            and norm_path(value) == PYTEST_CONFIG_KEY
            for value in candidates
        ):
            deny("pytest_config_mutation_denied")
    if event in {
        "socket.__new__", "socket.connect", "socket.connect_ex", "socket.getaddrinfo",
        "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo",
        "subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.exec",
        "os.fork", "os.forkpty", "ctypes.dlopen", "ctypes.dlsym", "_ctypes.dlopen",
        "_winapi.CreateProcess", "_winapi.CreatePipe",
        "_winapi.CreateNamedPipe", "_winapi.ConnectNamedPipe",
    }:
        deny("blocked_audit_event")


class BlockImports:
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition(".")[0].casefold()
        if root in EXPECTED_PRIVATE_MODULE_ROOTS or root == "_winapi":
            deny("blocked_import")
        return None


def install_early_guards() -> dict:
    """Block private, native, network and process operations before QA imports."""
    global EARLY_GUARD_CHECKS
    if any(
        name.partition(".")[0].casefold() in {"colorama", "yaml", "pytest"}
        for name in sys.modules
    ):
        raise RuntimeError("third_party_module_loaded_before_early_guards")

    for operation in ("remove", "unlink", "rename", "replace", "truncate"):
        original = getattr(os, operation, None)
        if original is None:
            continue
        def guarded_config_mutation(*args, _operation=operation, _original=original, **kwargs):
            candidates = args[:2] if _operation in {"rename", "replace"} else args[:1]
            if any(
                isinstance(value, (str, bytes, os.PathLike))
                and norm_path(value) == PYTEST_CONFIG_KEY
                for value in candidates
            ):
                deny("pytest_config_mutation_denied")
            return _original(*args, **kwargs)
        setattr(os, operation, guarded_config_mutation)

    original_socket = socket.socket
    class DeniedSocket(original_socket):
        def __new__(cls, *_args, **_kwargs):
            return deny("socket_constructor")
    for name in ("connect", "connect_ex", "sendto", "bind", "listen", "accept"):
        if hasattr(original_socket, name):
            setattr(DeniedSocket, name, lambda *_a, _n=name, **_k: deny("socket_" + _n))
    socket.socket = DeniedSocket
    for name in (
        "socketpair", "create_connection", "create_server", "getaddrinfo",
        "gethostbyname", "gethostbyaddr", "getnameinfo", "fromfd",
    ):
        if hasattr(socket, name):
            setattr(socket, name, lambda *_a, _n=name, **_k: deny("socket_" + _n))
    for cls_name in ("HTTPConnection", "HTTPSConnection"):
        cls = getattr(http.client, cls_name, None)
        if cls is not None and hasattr(cls, "connect"):
            cls.connect = lambda *_a, _n=cls_name, **_k: deny("http_" + _n)

    def safe_library(*_args, **_kwargs):
        FAKE_CONSOLE_CALLS["library_requests"] += 1
        return CONSOLE_FACADE

    for name in ("WinDLL", "OleDLL"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, safe_library)
    for name in ("CDLL", "PyDLL"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, lambda *_a, _n=name, **_k: deny("ctypes_" + _n))
    ctypes.util.find_library = lambda *_a, **_k: deny("ctypes_find_library")
    class DenyNativeProxy:
        def __getattr__(self, _name):
            return deny("ctypes_native_proxy")
        def __call__(self, *_a, **_k):
            return deny("ctypes_native_proxy")
    ctypes.cdll = DenyNativeProxy()
    ctypes.pydll = DenyNativeProxy()
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory = lambda *_a, **_k: deny("os_add_dll_directory")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        setattr(subprocess, name, lambda *_a, _n=name, **_k: deny("subprocess_" + _n))
    for name in ("system", "popen", "startfile"):
        if hasattr(os, name):
            setattr(os, name, lambda *_a, _n=name, **_k: deny("os_" + _n))
    for name in dir(os):
        if name.startswith(("spawn", "exec")):
            try:
                setattr(os, name, lambda *_a, _n=name, **_k: deny("os_" + _n))
            except (AttributeError, TypeError):
                pass
    multiprocessing.Process.start = lambda *_a, **_k: deny("multiprocessing_start")
    multiprocessing.process.BaseProcess.start = lambda *_a, **_k: deny("base_process_start")
    multiprocessing.Pipe = lambda *_a, **_k: deny("multiprocessing_pipe")
    multiprocessing.connection.Pipe = lambda *_a, **_k: deny("connection_pipe")
    multiprocessing.connection.wait = lambda *_a, **_k: deny("connection_wait")

    winapi = sys.modules.get("_winapi")
    if winapi is not None:
        for name in dir(winapi):
            if not name.startswith("__") and callable(getattr(winapi, name, None)):
                try:
                    setattr(winapi, name, lambda *_a, _n=name, **_k: deny("_winapi_" + _n))
                except (AttributeError, TypeError):
                    pass
    sys.meta_path.insert(0, BlockImports())
    sys.addaudithook(audit)

    checks = []
    def expect(label, action):
        before = len(BLOCKED)
        try:
            action()
        except GuardViolation:
            if len(BLOCKED) != before:
                raise RuntimeError("early_guard_selfcheck_counted")
            checks.append(label)
            return
        raise RuntimeError("early_guard_selfcheck_failed")

    expect(
        "private_input_open_denied_before_qa_packages",
        lambda: sys.audit("open", str(REPO_ROOT / ".env"), "r", 0),
    )
    expect(
        "pytest_config_mutation_denied_before_qa_packages",
        lambda: sys.audit("os.remove", str(PYTEST_CONFIG_PATH)),
    )
    expect("sdk_import_denied_before_qa_packages", lambda: sys.audit("import", "bt_api.source_qa_probe", None))
    expect("network_denied_before_qa_packages", lambda: sys.audit("socket.connect", None, None))
    expect("native_load_denied_before_qa_packages", lambda: sys.audit("ctypes.dlopen", None, None))
    expect("subprocess_denied_before_qa_packages", lambda: sys.audit("subprocess.Popen", None))
    expect("winapi_process_denied_before_qa_packages", lambda: sys.audit("_winapi.CreateProcess", None))
    expect("multiprocessing_pipe_denied_before_qa_packages", lambda: multiprocessing.Pipe())
    expect("ctypes_c_loader_denied_before_qa_packages", lambda: ctypes.CDLL("C:/opaque/blocked.dll"))
    library_before = FAKE_CONSOLE_CALLS["library_requests"]
    if ctypes.WinDLL("C:/opaque/fake-only.dll") is not CONSOLE_FACADE:
        raise RuntimeError("preload_windows_dll_facade_not_inert")
    if FAKE_CONSOLE_CALLS["library_requests"] != library_before + 1:
        raise RuntimeError("preload_windows_dll_facade_not_observed")
    checks.append("windll_load_replaced_by_inert_facade_before_qa_packages")
    _winreg_module = sys.modules.get("winreg")
    if not _winreg_binding_is_live("winreg", _winreg_module):
        raise RuntimeError("winreg_bootstrap_binding_not_live")
    checks.append("winreg_canonical_binding_verified_before_qa_packages")
    _winreg_fake = types.ModuleType("winreg")
    try:
        sys.modules["winreg"] = _winreg_fake
        _winreg_forged_module_rejected = not _winreg_binding_is_live("winreg", _winreg_fake)
    finally:
        sys.modules["winreg"] = _winreg_module
    if not _winreg_forged_module_rejected:
        raise RuntimeError("winreg_forged_module_accepted")
    checks.append("winreg_forged_module_denied_before_qa_packages")
    _winreg_spec = _winreg_module.__spec__
    _winreg_origin = _winreg_spec.origin
    try:
        _winreg_spec.origin = "C:/opaque/forged_winreg.py"
        _winreg_wrong_origin_rejected = not _winreg_binding_is_live("winreg", _winreg_module)
    finally:
        _winreg_spec.origin = _winreg_origin
    if not _winreg_wrong_origin_rejected:
        raise RuntimeError("winreg_nonbuiltin_origin_accepted")
    checks.append("winreg_nonbuiltin_origin_denied_before_qa_packages")
    _winreg_open_key = _winreg_module.OpenKey
    try:
        _winreg_module.OpenKey = _winreg_module.CloseKey
        _winreg_rebound_function_rejected = not _winreg_binding_is_live("winreg", _winreg_module)
    finally:
        _winreg_module.OpenKey = _winreg_open_key
    if not _winreg_rebound_function_rejected:
        raise RuntimeError("winreg_function_rebinding_accepted")
    checks.append("winreg_function_rebinding_denied_before_qa_packages")
    expect(
        "winreg_import_denied_before_qa_packages",
        lambda: sys.audit("import", "winreg.source_qa_probe", None),
    )
    expect(
        "winreg_operation_audit_denied_before_qa_packages",
        lambda: sys.audit("winreg.OpenKey", None),
    )
    if not _pyexpat_binding_is_live():
        raise RuntimeError("pyexpat_bootstrap_binding_not_live")
    checks.append("pyexpat_canonical_parent_and_children_verified_before_qa_packages")
    _pyexpat_fake_child = types.ModuleType("pyexpat.errors")
    _pyexpat_original_child = sys.modules["pyexpat.errors"]
    try:
        sys.modules["pyexpat.errors"] = _pyexpat_fake_child
        _pyexpat_forged_child_rejected = not _pyexpat_binding_is_live()
    finally:
        sys.modules["pyexpat.errors"] = _pyexpat_original_child
    if not _pyexpat_forged_child_rejected:
        raise RuntimeError("pyexpat_forged_child_accepted")
    checks.append("pyexpat_forged_sys_modules_child_denied_before_qa_packages")
    _pyexpat_parent = _PYEXPAT_EXPECTED_BINDING[0]
    try:
        _pyexpat_parent.errors = _pyexpat_fake_child
        _pyexpat_parent_attribute_rejected = not _pyexpat_binding_is_live()
    finally:
        _pyexpat_parent.errors = _pyexpat_original_child
    if not _pyexpat_parent_attribute_rejected:
        raise RuntimeError("pyexpat_parent_attribute_rebinding_accepted")
    checks.append("pyexpat_parent_attribute_identity_denied_before_qa_packages")
    try:
        sys.modules["pyexpat"] = _pyexpat_fake_child
        _pyexpat_forged_parent_rejected = not _pyexpat_binding_is_live()
    finally:
        sys.modules["pyexpat"] = _pyexpat_parent
    if not _pyexpat_forged_parent_rejected:
        raise RuntimeError("pyexpat_forged_parent_accepted")
    checks.append("pyexpat_parent_sys_modules_identity_denied_before_qa_packages")
    _pyexpat_parent_spec = _PYEXPAT_EXPECTED_BINDING[1]
    _pyexpat_parent_origin = _pyexpat_parent_spec.origin
    try:
        _pyexpat_parent_spec.origin = "C:/opaque/pyexpat.pyd"
        _pyexpat_wrong_origin_rejected = not _pyexpat_binding_is_live()
    finally:
        _pyexpat_parent_spec.origin = _pyexpat_parent_origin
    if not _pyexpat_wrong_origin_rejected:
        raise RuntimeError("pyexpat_noncanonical_origin_accepted")
    checks.append("pyexpat_parent_origin_mutation_denied_before_qa_packages")
    _pyexpat_parent_loader = _PYEXPAT_EXPECTED_BINDING[2]
    try:
        _pyexpat_parent_spec.loader = _pyexpat_fake_child
        _pyexpat_wrong_loader_rejected = not _pyexpat_binding_is_live()
    finally:
        _pyexpat_parent_spec.loader = _pyexpat_parent_loader
    if not _pyexpat_wrong_loader_rejected:
        raise RuntimeError("pyexpat_noncanonical_loader_accepted")
    checks.append("pyexpat_parent_loader_mutation_denied_before_qa_packages")
    _pyexpat_original_child_spec = _pyexpat_original_child.__spec__
    try:
        _pyexpat_original_child.__spec__ = importlib.machinery.ModuleSpec("pyexpat.errors", None)
        _pyexpat_child_metadata_rejected = not _pyexpat_binding_is_live()
    finally:
        _pyexpat_original_child.__spec__ = _pyexpat_original_child_spec
    if not _pyexpat_child_metadata_rejected:
        raise RuntimeError("pyexpat_child_metadata_mutation_accepted")
    checks.append("pyexpat_child_spec_mutation_denied_before_qa_packages")
    try:
        _pyexpat_original_child.__file__ = "C:/opaque/pyexpat_errors.py"
        _pyexpat_child_file_rejected = not _pyexpat_binding_is_live()
    finally:
        delattr(_pyexpat_original_child, "__file__")
    if not _pyexpat_child_file_rejected:
        raise RuntimeError("pyexpat_child_file_mutation_accepted")
    checks.append("pyexpat_child_file_mutation_denied_before_qa_packages")
    _pyexpat_trusted_origin = _boot_origin(sys.modules["types"])
    if not _boot_origin_is_trusted(_pyexpat_trusted_origin):
        raise RuntimeError("pyexpat_trusted_fake_origin_unavailable")
    for _scan_name, _check_name in (
        ("post_stdlib", "pyexpat_trusted_origin_forgery_rejected_by_all_post_stdlib_children"),
        ("post_qa", "pyexpat_trusted_origin_forgery_rejected_by_all_post_qa_children"),
    ):
        for _child_name, _child_attribute, _held_child, *_child_state in _PYEXPAT_EXPECTED_BINDING[4]:
            _pyexpat_fake_child_for_rescan = types.ModuleType(_child_name)
            _pyexpat_fake_child_for_rescan.__file__ = _pyexpat_trusted_origin
            _pyexpat_fake_child_for_rescan.__spec__ = importlib.machinery.ModuleSpec(
                _child_name, None, origin=_pyexpat_trusted_origin
            )
            _forged_category = _origin_scan_rescan_category(
                _child_name, _pyexpat_fake_child_for_rescan, _pyexpat_trusted_origin, _scan_name
            )
            if (
                not _boot_origin_is_trusted(_pyexpat_trusted_origin)
                or _forged_category != "pyexpat_synthetic_child_binding_mismatch"
            ):
                raise RuntimeError("pyexpat_trusted_origin_forgery_not_rejected")
        checks.append(_check_name)
    for _scan_name, _check_name in (
        ("post_stdlib", "pyexpat_parent_binding_rechecked_for_all_post_stdlib_children"),
        ("post_qa", "pyexpat_parent_binding_rechecked_for_all_post_qa_children"),
    ):
        for _child_name, _child_attribute, _held_child, *_child_state in _PYEXPAT_EXPECTED_BINDING[4]:
            _pyexpat_fake_child_for_parent = types.ModuleType(_child_name)
            _pyexpat_fake_child_for_parent.__file__ = _pyexpat_trusted_origin
            _pyexpat_fake_child_for_parent.__spec__ = importlib.machinery.ModuleSpec(
                _child_name, None, origin=_pyexpat_trusted_origin
            )
            _original_parent_child = getattr(_pyexpat_parent, _child_attribute)
            try:
                setattr(_pyexpat_parent, _child_attribute, _pyexpat_fake_child_for_parent)
                _parent_category = _origin_scan_rescan_category(
                    _child_name, _held_child, _pyexpat_trusted_origin, _scan_name
                )
            finally:
                setattr(_pyexpat_parent, _child_attribute, _original_parent_child)
            if getattr(_pyexpat_parent, _child_attribute, None) is not _original_parent_child:
                raise RuntimeError("pyexpat_parent_binding_not_restored")
            if _parent_category != "pyexpat_synthetic_child_binding_mismatch":
                raise RuntimeError("pyexpat_parent_binding_not_rechecked")
        checks.append(_check_name)
    expected = (
        "private_input_open_denied_before_qa_packages",
        "pytest_config_mutation_denied_before_qa_packages",
        "sdk_import_denied_before_qa_packages",
        "network_denied_before_qa_packages",
        "native_load_denied_before_qa_packages",
        "subprocess_denied_before_qa_packages",
        "winapi_process_denied_before_qa_packages",
        "multiprocessing_pipe_denied_before_qa_packages",
        "ctypes_c_loader_denied_before_qa_packages",
        "windll_load_replaced_by_inert_facade_before_qa_packages",
        "winreg_canonical_binding_verified_before_qa_packages",
        "winreg_forged_module_denied_before_qa_packages",
        "winreg_nonbuiltin_origin_denied_before_qa_packages",
        "winreg_function_rebinding_denied_before_qa_packages",
        "winreg_import_denied_before_qa_packages",
        "winreg_operation_audit_denied_before_qa_packages",
        "pyexpat_canonical_parent_and_children_verified_before_qa_packages",
        "pyexpat_forged_sys_modules_child_denied_before_qa_packages",
        "pyexpat_parent_attribute_identity_denied_before_qa_packages",
        "pyexpat_parent_sys_modules_identity_denied_before_qa_packages",
        "pyexpat_parent_origin_mutation_denied_before_qa_packages",
        "pyexpat_parent_loader_mutation_denied_before_qa_packages",
        "pyexpat_child_spec_mutation_denied_before_qa_packages",
        "pyexpat_child_file_mutation_denied_before_qa_packages",
        "pyexpat_trusted_origin_forgery_rejected_by_all_post_stdlib_children",
        "pyexpat_trusted_origin_forgery_rejected_by_all_post_qa_children",
        "pyexpat_parent_binding_rechecked_for_all_post_stdlib_children",
        "pyexpat_parent_binding_rechecked_for_all_post_qa_children",
    )
    if tuple(checks) != expected:
        raise RuntimeError("early_guard_selfcheck_inventory_mismatch")
    EARLY_GUARD_CHECKS = checks
    return {
        "installed_before_first_qa_package": True,
        "first_qa_package_not_imported": True,
        "checks": list(checks),
        "candidate_imported": False,
        "candidate_denials_before_test_import": 0,
        "console_api": "inert_facade_until_colorama_and_pytest_loaded",
    }


def install_guards():
    global SELF_CHECK
    for operation in ("remove", "unlink", "rename", "replace", "truncate"):
        original = getattr(os, operation, None)
        if original is None:
            continue
        def guarded_config_mutation(*args, _operation=operation, _original=original, **kwargs):
            candidates = args[:2] if _operation in {"rename", "replace"} else args[:1]
            if any(
                isinstance(value, (str, bytes, os.PathLike))
                and norm_path(value) == PYTEST_CONFIG_KEY
                for value in candidates
            ):
                deny("pytest_config_mutation_denied")
            return _original(*args, **kwargs)
        setattr(os, operation, guarded_config_mutation)

    original_socket = socket.socket
    class DeniedSocket(original_socket):
        def __new__(cls, *_args, **_kwargs):
            return deny("socket_constructor")

    for name in ("connect", "connect_ex", "sendto", "bind", "listen", "accept"):
        if hasattr(original_socket, name):
            setattr(DeniedSocket, name, lambda *_a, _n=name, **_k: deny("socket_" + _n))
    socket.socket = DeniedSocket
    for name in (
        "socketpair", "create_connection", "create_server", "getaddrinfo",
        "gethostbyname", "gethostbyaddr", "getnameinfo", "fromfd",
    ):
        if hasattr(socket, name):
            setattr(socket, name, lambda *_a, _n=name, **_k: deny("socket_" + _n))
    for cls_name in ("HTTPConnection", "HTTPSConnection"):
        cls = getattr(http.client, cls_name, None)
        if cls is not None and hasattr(cls, "connect"):
            cls.connect = lambda *_a, _n=cls_name, **_k: deny("http_" + _n)

    for name in ("WinDLL", "OleDLL", "CDLL", "PyDLL"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, lambda *_a, _n=name, **_k: deny("ctypes_" + _n))
    ctypes.util.find_library = lambda *_a, **_k: deny("ctypes_find_library")
    class DenyNativeProxy:
        def __getattr__(self, _name):
            return deny("ctypes_native_proxy")
        def __call__(self, *_a, **_k):
            return deny("ctypes_native_proxy")
    for name in ("windll", "oledll", "cdll", "pydll"):
        setattr(ctypes, name, DenyNativeProxy())
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory = lambda *_a, **_k: deny("os_add_dll_directory")

    for name in ("Popen", "run", "call", "check_call", "check_output"):
        setattr(subprocess, name, lambda *_a, _n=name, **_k: deny("subprocess_" + _n))
    for name in ("system", "popen", "startfile"):
        if hasattr(os, name):
            setattr(os, name, lambda *_a, _n=name, **_k: deny("os_" + _n))
    for name in dir(os):
        if name.startswith(("spawn", "exec")):
            try:
                setattr(os, name, lambda *_a, _n=name, **_k: deny("os_" + _n))
            except (AttributeError, TypeError):
                pass
    multiprocessing.Process.start = lambda *_a, **_k: deny("multiprocessing_start")
    multiprocessing.process.BaseProcess.start = lambda *_a, **_k: deny("base_process_start")
    multiprocessing.Pipe = lambda *_a, **_k: deny("multiprocessing_pipe")
    multiprocessing.connection.Pipe = lambda *_a, **_k: deny("connection_pipe")
    multiprocessing.connection.wait = lambda *_a, **_k: deny("connection_wait")

    winapi = sys.modules.get("_winapi")
    if winapi is not None:
        for name in dir(winapi):
            if not name.startswith("__") and callable(getattr(winapi, name, None)):
                try:
                    setattr(winapi, name, lambda *_a, _n=name, **_k: deny("_winapi_" + _n))
                except (AttributeError, TypeError):
                    pass
    sys.meta_path.insert(0, BlockImports())
    sys.addaudithook(audit)

    # Guard self-checks run before test collection; their denials are separated
    # from the candidate-attempt count, which is reset before pytest starts.
    baseline = {"blocked_attempts": len(BLOCKED), "private_native_network_process": 0}
    def expect(label, action):
        before = len(BLOCKED)
        try:
            action()
        except GuardViolation:
            if len(BLOCKED) != before:
                raise RuntimeError("selfcheck_counted_as_candidate_attempt")
            SELF_CHECKS_DONE.append(label)
            return
        raise RuntimeError("guard_selfcheck_failed")

    winpath = "D:" + chr(92) + "private" + chr(92) + ".env"
    if norm_path(winpath) != "d:/private/.env":
        raise RuntimeError("windows_path_normalization_failed")
    SELF_CHECKS_DONE.append("windows_chr92_normalization")
    expect("private_env_open_denied", lambda: sys.audit("open", winpath, "r", 0))
    expect("private_config_open_denied", lambda: sys.audit("open", "D:/private/config.yaml", "r", 0))
    expect(
        "pytest_config_open_write_denied",
        lambda: sys.audit("open", str(PYTEST_CONFIG_PATH), "w", 0),
    )
    expect(
        "pytest_config_replace_denied",
        lambda: os.replace(PYTEST_CONFIG_PATH, PYTEST_CONFIG_PATH),
    )
    expect("pytest_config_unlink_denied", lambda: os.unlink(PYTEST_CONFIG_PATH))
    expect("private_secrets_open_denied", lambda: sys.audit("open", "D:/private/secrets.yaml", "r", 0))
    expect(
        "private_capture_open_denied",
        lambda: sys.audit("open", "D:" + chr(92) + "captures" + chr(92) + "private_capture.json", "r", 0),
    )
    expect("opaque_dll_open_denied", lambda: sys.audit("open", "C:/opaque/provider.dll", "r", 0))
    expect(
        "external_software_exe_open_denied",
        lambda: sys.audit("open", "C:/external-software/vendor.exe", "r", 0),
    )
    expect("native_pyd_open_denied", lambda: sys.audit("open", "C:/opaque/provider.pyd", "r", 0))
    expect("SDK_import_denied", lambda: sys.audit("import", "bt_api.source_qa_probe", None))
    expect(
        "native_import_denied",
        lambda: sys.audit("import", "opaque.source_qa_probe", "C:/opaque/provider.pyd"),
    )
    expect("network_audit_denied", lambda: sys.audit("socket.connect", None, None))
    expect(
        "DNS_audit_denied",
        lambda: sys.audit("socket.getaddrinfo", "source-qa.invalid", None, None, None, None),
    )
    expect("socket_constructor_denied", lambda: socket.socket())
    expect(
        "DNS_function_denied",
        lambda: socket.getaddrinfo("source-qa.invalid", 443, type=socket.SOCK_STREAM),
    )
    expect("ctypes_loader_denied", lambda: ctypes.WinDLL("C:/opaque/provider.dll"))
    expect("ctypes_proxy_denied", lambda: ctypes.windll.LoadLibrary("C:/opaque/provider.dll"))
    expect("subprocess_start_denied", lambda: subprocess.Popen(["blocked.exe"]))
    expect("os_process_start_denied", lambda: os.system("blocked.exe"))
    expect("multiprocessing_start_denied", lambda: multiprocessing.Process.start(object()))
    expect("multiprocessing_pipe_denied", lambda: multiprocessing.Pipe())
    expect("connection_wait_denied", lambda: multiprocessing.connection.wait([]))
    expect("WinAPI_process_audit_denied", lambda: sys.audit("_winapi.CreateProcess", None))
    expect("WinAPI_pipe_audit_denied", lambda: sys.audit("_winapi.CreatePipe", None))
    if winapi is None or not hasattr(winapi, "CreateProcess") or not hasattr(winapi, "CreatePipe"):
        raise RuntimeError("winapi_selfcheck_surface_missing")
    expect("WinAPI_process_function_denied", lambda: winapi.CreateProcess())
    expect("WinAPI_pipe_function_denied", lambda: winapi.CreatePipe())
    expect("winreg_registry_operation_audit_denied", lambda: sys.audit("winreg.OpenKey", None))
    if tuple(SELF_CHECKS_DONE) != tuple(EXPECTED_SELF_CHECKS):
        raise RuntimeError("guard_selfcheck_inventory_mismatch")
    SELF_CHECK = False
    BLOCKED.clear()
    return {
        "baseline": baseline,
        "checks": list(SELF_CHECKS_DONE),
        "path_normalization": norm_path(winpath),
        "candidate_delta_after_selfchecks": len(BLOCKED),
    }


class PinnedRepoSourceLoader:
    """Patch SourceFileLoader to compile only pinned repository Python files."""
    def __init__(self):
        self.loader = importlib.machinery.SourceFileLoader
        self.original = self.loader.get_code
    def install(self):
        checker = self
        def get_code(loader, fullname):
            path = pathlib.Path(loader.path).resolve()
            try:
                relative = path.relative_to(ROOT).as_posix()
            except ValueError:
                if under(norm_path(path), REPO_KEY):
                    raise ImportError("checkout_source_outside_selected_namespace")
                return checker.original(loader, fullname)
            expected = PIN_MAP.get(relative)
            if expected is None:
                raise ImportError("unpinned_repository_source_denied")
            raw = path.read_bytes()
            if len(raw) != expected["bytes"] or hashlib.sha256(raw).hexdigest() != expected["sha256"]:
                raise ImportError("repository_source_pin_mismatch")
            REPO_SOURCE_LOADS[fullname] = {"path": relative, "sha256": expected["sha256"]}
            return compile(raw, str(path), "exec", dont_inherit=True)
        self.loader.get_code = get_code


def _canonical(path):
    return str(pathlib.Path(path).resolve()).replace(chr(92), "/").casefold()


def _module_path(module):
    value = getattr(module, "__file__", None)
    return _canonical(value) if isinstance(value, (str, os.PathLike)) else None


def _module_origin_matches(module, path):
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    return _module_path(module) == _canonical(path) and isinstance(origin, str) and _canonical(origin) == _canonical(path)


def _code_path(value):
    code = getattr(value, "__code__", None)
    return _canonical(code.co_filename) if code is not None else None


class Gate:
    def __init__(self):
        self.items = []
        self.reports = defaultdict(list)
        self.warnings = []
        self.fixtures = []
        self.owner_binding_snapshots = []
        self.test_module = None
        self.origins = {}
        self.problems = []
        self.pytest_config_binding = None
        self.failure_diagnostics = []

    def _record_failure_diagnostic(self, phase, fallback_category):
        if len(self.failure_diagnostics) >= 4:
            return
        label = BLOCKED[-1] if BLOCKED else None
        categories = {
            "write_outside_external_qa": "external_qa_write_denied",
            "pytest_config_write_denied": "pytest_config_write_denied",
            "write_to_selected_source_denied": "selected_source_write_denied",
            "private_or_native_read": "protected_input_read_denied",
            "blocked_import": "protected_import_denied",
            "native_or_opaque_import": "native_or_opaque_import_denied",
        }
        self.failure_diagnostics.append(
            {"phase": phase, "category": categories.get(label, fallback_category)}
        )

    def pytest_configure(self, config):
        actual_ini = getattr(config, "inipath", None)
        actual_root = getattr(config, "rootpath", None)
        derived = dict(getattr(config, "inicfg", {}))
        config_pin = _pytest_config_pin()
        binding = {
            "inipath": _canonical(actual_ini) if actual_ini is not None else None,
            "rootpath": _canonical(actual_root) if actual_root is not None else None,
            "derived_config": derived,
            "file_bytes": config_pin["bytes"],
            "file_sha256": config_pin["sha256"],
            "file_matches_expected": config_pin["matches_expected"],
        }
        self.pytest_config_binding = binding
        if (
            binding["inipath"] != _canonical(PYTEST_CONFIG_PATH)
            or binding["rootpath"] != _canonical(QA)
            or binding["derived_config"] != {}
            or not binding["file_matches_expected"]
            or binding["file_bytes"] != len(PYTEST_CONFIG_EXPECTED)
            or binding["file_sha256"] != PYTEST_CONFIG_EXPECTED_SHA256
        ):
            self.problems.append("pytest_config_binding_mismatch")

    def _capture_owner_method_bindings(self, owner):
        expected_owner = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"
        try:
            if type(owner) is not ModuleType:
                return (
                    owner, None, None, (False, False, False),
                    (False, False, False, False), (), "other_or_missing",
                )
            owner_namespace = owner.__dict__
            module_checks = (
                type(owner) is ModuleType,
                getattr(owner, "__name__", None) == "__main__",
                sys.modules.get("__main__") is owner,
            )
            owner_class = owner_namespace.get("FixedAccountWindowGetV1")
            if type(owner_class) is not type:
                return (
                    owner, owner_namespace, owner_class, module_checks,
                    (False, False, False, False), (), "other_or_missing",
                )
            class_namespace = owner_class.__dict__
            class_checks = (
                owner_namespace.get("FixedAccountWindowGetV1") is owner_class,
                getattr(owner_class, "__module__", None) == getattr(owner, "__name__", None),
                getattr(owner_class, "__qualname__", None) == "FixedAccountWindowGetV1",
                getattr(owner_class, "__bases__", None) == (object,),
            )
            expectations = (
                ("_require", 1596, "FixedAccountWindowGetV1._require"),
                ("_get", 1610, "FixedAccountWindowGetV1._get"),
            )
            method_records = []
            for method_name, expected_line, expected_qualname in expectations:
                method = class_namespace.get(method_name)
                if type(method) is type(_code_path):
                    code = method.__code__
                    method_globals = method.__globals__
                    filename = getattr(code, "co_filename", None)
                else:
                    code = None
                    method_globals = None
                    filename = None
                if filename == "<string>":
                    origin_category = "dataclass_generated"
                elif isinstance(filename, str) and _canonical(filename) == _canonical(expected_owner):
                    origin_category = "pinned_owner_source"
                else:
                    origin_category = "other_or_missing"
                method_ok = (
                    type(method) is type(_code_path)
                    and code is not None
                    and class_namespace.get(method_name) is method
                    and method_globals is owner_namespace
                    and getattr(method, "__module__", None) == getattr(owner, "__name__", None)
                    and getattr(method, "__name__", None) == method_name
                    and getattr(method, "__qualname__", None) == expected_qualname
                    and getattr(code, "co_name", None) == method_name
                    and getattr(code, "co_qualname", None) == expected_qualname
                    and getattr(code, "co_firstlineno", None) == expected_line
                    and origin_category == "pinned_owner_source"
                )
                method_records.append(
                    (method_name, method, code, method_globals, origin_category, bool(method_ok))
                )
            init_method = class_namespace.get("__init__")
            init_code = init_method.__code__ if type(init_method) is type(_code_path) else None
            init_filename = getattr(init_code, "co_filename", None)
            if init_filename == "<string>":
                init_origin = "dataclass_generated"
            elif isinstance(init_filename, str) and _canonical(init_filename) == _canonical(expected_owner):
                init_origin = "pinned_owner_source"
            else:
                init_origin = "other_or_missing"
            return (
                owner, owner_namespace, owner_class, module_checks,
                class_checks, tuple(method_records), init_origin,
            )
        except Exception:
            return (
                owner, None, None, (False, False, False),
                (False, False, False, False), (), "other_or_missing",
            )

    def _owner_method_bindings_still_match(self, fixture, snapshot):
        expected_owner = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"
        try:
            if type(snapshot) is not tuple or len(snapshot) != 7:
                return False
            (
                captured_owner, owner_namespace, owner_class, module_checks,
                class_checks, method_records, init_origin,
            ) = snapshot
            owner = getattr(fixture, "owner", None)
            if (
                owner is not captured_owner
                or type(owner) is not ModuleType
                or owner.__dict__ is not owner_namespace
                or not all(module_checks)
                or not all(class_checks)
                or type(owner_class) is not type
                or getattr(owner, "__name__", None) != "__main__"
                or owner_namespace.get("FixedAccountWindowGetV1") is not owner_class
                or getattr(owner_class, "__module__", None) != getattr(owner, "__name__", None)
                or getattr(owner_class, "__qualname__", None) != "FixedAccountWindowGetV1"
                or getattr(owner_class, "__bases__", None) != (object,)
                or type(method_records) is not tuple
                or len(method_records) != 2
            ):
                return False
            class_namespace = owner_class.__dict__
            expected = {
                "_require": (1596, "FixedAccountWindowGetV1._require"),
                "_get": (1610, "FixedAccountWindowGetV1._get"),
            }
            seen = set()
            for record in method_records:
                if type(record) is not tuple or len(record) != 6:
                    return False
                method_name, captured_method, captured_code, captured_globals, captured_origin, captured_ok = record
                if method_name not in expected or method_name in seen:
                    return False
                seen.add(method_name)
                expected_line, expected_qualname = expected[method_name]
                method = class_namespace.get(method_name)
                code = getattr(method, "__code__", None) if type(method) is type(_code_path) else None
                filename = getattr(code, "co_filename", None)
                origin_category = (
                    "dataclass_generated" if filename == "<string>"
                    else "pinned_owner_source"
                    if isinstance(filename, str) and _canonical(filename) == _canonical(expected_owner)
                    else "other_or_missing"
                )
                if not (
                    captured_ok is True
                    and captured_origin == "pinned_owner_source"
                    and origin_category == captured_origin
                    and method is captured_method
                    and type(method) is type(_code_path)
                    and code is captured_code
                    and method.__globals__ is captured_globals is owner_namespace
                    and getattr(method, "__module__", None) == getattr(owner, "__name__", None)
                    and getattr(method, "__name__", None) == method_name
                    and getattr(method, "__qualname__", None) == expected_qualname
                    and getattr(code, "co_name", None) == method_name
                    and getattr(code, "co_qualname", None) == expected_qualname
                    and getattr(code, "co_firstlineno", None) == expected_line
                ):
                    return False
            return seen == set(expected)
        except Exception:
            return False

    def _owner_method_binding_observation(self, snapshot):
        if type(snapshot) is not tuple or len(snapshot) != 7:
            return {
                "owner_main_module": False,
                "owner_sys_modules_identity_during_fixture": False,
                "class_global_identity": False,
                "class_module_identity": False,
                "class_qualname_identity": False,
                "class_bases_identity": False,
                "require_globals_identity": False,
                "get_globals_identity": False,
                "require_code_origin": "other_or_missing",
                "get_code_origin": "other_or_missing",
                "dataclass_init_origin": "other_or_missing",
            }
        owner, owner_namespace, owner_class, module_checks, class_checks, records, init_origin = snapshot
        by_name = {
            record[0]: record
            for record in records
            if type(record) is tuple and len(record) == 6 and isinstance(record[0], str)
        }
        require = by_name.get("_require")
        get_method = by_name.get("_get")
        return {
            "owner_main_module": bool(len(module_checks) > 1 and module_checks[0] and module_checks[1]),
            "owner_sys_modules_identity_during_fixture": bool(len(module_checks) > 2 and module_checks[2]),
            "class_global_identity": bool(len(class_checks) > 0 and class_checks[0]),
            "class_module_identity": bool(len(class_checks) > 1 and class_checks[1]),
            "class_qualname_identity": bool(len(class_checks) > 2 and class_checks[2]),
            "class_bases_identity": bool(len(class_checks) > 3 and class_checks[3]),
            "require_globals_identity": bool(require is not None and require[3] is owner_namespace),
            "get_globals_identity": bool(get_method is not None and get_method[3] is owner_namespace),
            "require_code_origin": require[4] if require is not None else "other_or_missing",
            "get_code_origin": get_method[4] if get_method is not None else "other_or_missing",
            "dataclass_init_origin": init_origin if init_origin in {"dataclass_generated", "pinned_owner_source", "other_or_missing"} else "other_or_missing",
        }
    def pytest_collection_finish(self, session):
        self.items = list(session.items)
        names = tuple(sorted(item.name for item in self.items))
        if names != tuple(sorted(EXPECTED_NAMES)):
            self.problems.append("test_collection_mismatch")
        matches = [
            module for module in tuple(sys.modules.values())
            if isinstance(module, ModuleType) and _module_path(module) == _canonical(TEST_PATH)
        ]
        if len(matches) != 1:
            self.problems.append("test_module_origin_count")
            return
        self.test_module = matches[0]
        original = getattr(self.test_module, "_fixture", None)
        if not callable(original):
            self.problems.append("sourcefake_fixture_missing")
            return
        gate = self
        def capture_fixture(*args, **kwargs):
            fixture = original(*args, **kwargs)
            try:
                owner = getattr(fixture, "owner", None)
            except Exception:
                owner = None
            snapshot = gate._capture_owner_method_bindings(owner)
            gate.fixtures.append(fixture)
            gate.owner_binding_snapshots.append(snapshot)
            return fixture
        self.test_module._fixture = capture_fixture

    def pytest_runtest_logreport(self, report):
        if report.when in {"setup", "call", "teardown"}:
            self.reports[report.nodeid].append((report.when, report.outcome, bool(getattr(report, "wasxfail", False))))

    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        self.warnings.append({"when": str(when), "nodeid_present": bool(nodeid)})

    def pytest_internalerror(self, excrepr, excinfo):
        self._record_failure_diagnostic("pytest_internalerror", "pytest_internal_error")

    def pytest_collectreport(self, report):
        if getattr(report, "failed", False):
            self._record_failure_diagnostic("pytest_collection", "collection_failure")

    def pytest_sessionfinish(self, session, exitstatus):
        if self.test_module is None:
            self.problems.append("test_module_not_observed")
            return
        module = self.test_module
        if not _module_origin_matches(module, TEST_PATH):
            self.problems.append("test_module_origin_mismatch")
        r1_path = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_account_full_snapshot_r1.py"
        r2_path = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_account_full_snapshot_r2.py"
        if not _module_origin_matches(module.r1, r1_path):
            self.problems.append("r1_origin_mismatch")
        if not _module_origin_matches(module.r2, r2_path):
            self.problems.append("r2_origin_mismatch")
        if sys.modules.get(module.r2.__name__) is not module.r2 or module.r2._r1 is not module.r1:
            self.problems.append("package_binding_mismatch")
        code_origins = {
            "r1.collect_account_snapshot": _code_path(module.r1.collect_account_snapshot),
            "r2.classifier": _code_path(module.r2._classify_pages_and_snapshot),
        }
        if (
            code_origins["r1.collect_account_snapshot"]
            != _canonical(r1_path)
            or code_origins["r2.classifier"] != _canonical(r2_path)
        ):
            self.problems.append("adapter_code_origin_mismatch")
        self.origins["test"] = _module_path(module)
        self.origins["r1"] = _module_path(module.r1)
        self.origins["r2"] = _module_path(module.r2)
        self.origins["adapter_code_objects"] = code_origins

        package_modules = {
            "_certification": ROOT / "examples/000_live_certification/binance_penetration/_certification/__init__.py",
            "_certification.models": ROOT / "examples/000_live_certification/binance_penetration/_certification/models.py",
            "_certification.cases": ROOT / "examples/000_live_certification/binance_penetration/_certification/cases.py",
            "_certification.config": ROOT / "examples/000_live_certification/binance_penetration/_certification/config.py",
            "_certification.evidence": ROOT / "examples/000_live_certification/binance_penetration/_certification/evidence.py",
            "_certification.backends": ROOT / "examples/000_live_certification/binance_penetration/_certification/backends.py",
            "_certification.runner": ROOT / "examples/000_live_certification/binance_penetration/_certification/runner.py",
        }
        for name, expected in package_modules.items():
            actual = sys.modules.get(name)
            if actual is None or not _module_origin_matches(actual, expected):
                self.problems.append("package_module_origin_mismatch")
            else:
                self.origins[name] = _module_path(actual)

        runner = sys.modules.get("_certification.runner")
        parameters = tuple(inspect.signature(runner._plan).parameters.values()) if runner else ()
        if (
            not parameters
            or parameters[-1].name != "venue"
            or parameters[-1].default is not None
            or parameters[-1].kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD
            or tuple(item.name for item in parameters)
            != ("case_id", "params", "spec", "ref", "currency", "venue")
        ):
            self.problems.append("selected_runner_plan_signature_mismatch")
        if "_certification.fixed_owner_routes" in sys.modules:
            self.problems.append("untracked_fixed_owner_route_loaded")
        self.origins["selected_runner_plan_code"] = (
            _code_path(runner._plan) if runner is not None else None
        )

        if _module_path(sys.modules.get("pytest")) is None or not under(
            norm_path(_module_path(sys.modules["pytest"])), SITE_KEY
        ):
            self.problems.append("pytest_origin_mismatch")
        if _module_path(sys.modules.get("yaml")) is None or not under(
            norm_path(_module_path(sys.modules["yaml"])), SITE_KEY
        ):
            self.problems.append("yaml_origin_mismatch")
        self.origins["pytest"] = _module_path(sys.modules.get("pytest"))
        self.origins["yaml"] = _module_path(sys.modules.get("yaml"))

        expected_owner = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"
        expected_candidate = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py"
        expected_r9 = ROOT / "examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r9.py"
        expected_wrapper = ROOT / "scripts/iteration41_binance_th01_root_account_window_call_r1.py"
        if len(self.fixtures) != len(EXPECTED_NAMES):
            self.problems.append("fixture_count_mismatch")
        if len(self.owner_binding_snapshots) != len(self.fixtures):
            self.problems.append("owner_binding_snapshot_count_mismatch")
        for fixture, owner_binding_snapshot in zip(self.fixtures, self.owner_binding_snapshots):
            owner = fixture.owner
            candidate = getattr(owner, "_CANDIDATE_MODULE", None)
            force_module = fixture.force_module
            wrapper = fixture.wrapper
            if (
                not isinstance(owner, ModuleType)
                or _canonical(owner.OWNER_PATH) != _canonical(expected_owner)
                or _canonical(owner.__th01_verified_owner_source_path__) != _canonical(expected_owner)
                or owner.__th01_verified_owner_source_sha256__ != PIN_MAP[
                    "examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py"
                ]["sha256"]
                or _module_path(owner) != _canonical(ROOT / "scripts/iteration41_binance_th01_account_window_candidate_r2.py")
            ):
                self.problems.append("owner_source_binding_mismatch")
            owner_binding_ok = self._owner_method_bindings_still_match(
                fixture, owner_binding_snapshot
            )
            owner_observation = self._owner_method_binding_observation(owner_binding_snapshot)
            owner_observation["owner_bindings_valid_after_fixture"] = bool(owner_binding_ok)
            self.origins.setdefault("owner_code_binding_observations", []).append(owner_observation)
            if not owner_binding_ok:
                self.problems.append("owner_code_origin_mismatch")
            if (
                not isinstance(candidate, ModuleType)
                or _module_path(candidate) != _canonical(expected_candidate)
                or getattr(candidate, "__th01_verified_candidate_source_sha256__", None)
                != PIN_MAP["examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py"]["sha256"]
            ):
                self.problems.append("candidate_source_binding_mismatch")
            if _code_path(candidate._verify_candidate_source_binding) != _canonical(expected_candidate):
                self.problems.append("candidate_code_origin_mismatch")
            if (
                not isinstance(force_module, ModuleType)
                or _module_path(force_module) != _canonical(expected_r9)
                or getattr(force_module, "__name__", None) != module.r2.R9_MODULE_NAME
                or getattr(force_module, "_EXTENSION_SELF_PIN", None)
                != "baa9a92fe71258528291a4748af0b811cdc0cece40f3ac80859c6a54d1801f63"
            ):
                self.problems.append("r9_source_binding_mismatch")
            if _code_path(force_module.install_force_orders_extension) != _canonical(expected_r9):
                self.problems.append("r9_code_origin_mismatch")
            spec = getattr(wrapper, "__spec__", None)
            if (
                not isinstance(wrapper, ModuleType)
                or _module_path(wrapper) != _canonical(expected_wrapper)
                or spec is None
                or _canonical(spec.origin) != _canonical(expected_wrapper)
                or getattr(wrapper, "__th01_held_source_sha256__", None)
                != PIN_MAP["scripts/iteration41_binance_th01_root_account_window_call_r1.py"]["sha256"]
            ):
                self.problems.append("wrapper_source_binding_mismatch")
            if _code_path(wrapper.RootSnapshotBackendHookV1.__init__) != _canonical(expected_wrapper):
                self.problems.append("wrapper_code_origin_mismatch")

        forbidden_loaded = sorted(
            name for name in sys.modules
            if name.partition(".")[0].casefold() in EXPECTED_PRIVATE_MODULE_ROOTS
            or name.partition(".")[0].casefold() == "_winapi"
        )
        # Windows multiprocessing may preload _winapi; it has already been
        # patched to deny all callable process/Pipe entries.
        forbidden_loaded = [
            name for name in forbidden_loaded
            if name != "_winapi"
            and not (name == "winreg" and _winreg_binding_is_live(name, sys.modules.get(name)))
        ]
        if forbidden_loaded:
            self.problems.append("forbidden_module_loaded")
        if "yaml._yaml" in sys.modules or "_yaml" in sys.modules:
            self.problems.append("yaml_native_accelerator_loaded")

        repo_modules = {}
        for name, candidate_module in tuple(sys.modules.items()):
            if not isinstance(candidate_module, ModuleType):
                continue
            file_path = _module_path(candidate_module)
            if file_path and under(norm_path(file_path), ROOT_KEY):
                relative = pathlib.Path(file_path).relative_to(pathlib.Path(_canonical(ROOT))).as_posix()
                if relative not in PIN_MAP:
                    self.problems.append("unpinned_repository_module_loaded")
                else:
                    repo_modules[name] = relative
        self.origins["source_fake_repo_modules"] = repo_modules
        self.origins["sourcefileloader_reads"] = dict(REPO_SOURCE_LOADS)
        self.origins["source_read_paths"] = sorted(
            pathlib.Path(path).relative_to(pathlib.Path(ROOT_KEY)).as_posix()
            for path in REPO_SOURCE_READS
        )
        self.origins["root_readonly_loaded"] = any(
            name.endswith("th01_root_readonly") for name in sys.modules
        )
        self.origins["private_helper_loaded"] = any(
            name.endswith("certification_roundtrip_private") for name in sys.modules
        )
        if self.origins["root_readonly_loaded"] or self.origins["private_helper_loaded"]:
            self.problems.append("provider_authority_source_loaded_in_fake_fixture")


def main():
    _trace("qa_main", "start")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        preload = _preload()
        _trace("full_qa_guard_install", "start")
        guard_selfchecks = install_guards()
        _trace("full_qa_guard_install", "complete")
        loader = PinnedRepoSourceLoader()
        _trace("selected_source_loader_install", "start")
        loader.install()
        if any(name == "_certification" or name.startswith("_certification.")
               or name.startswith("test_binance_th01_account_full_snapshot_r2")
               for name in sys.modules):
            raise RuntimeError("candidate_imported_before_guards")
        _trace("selected_source_loader_install", "complete")

        pytest_log_path = QA / "pytest.log"
        if not under(norm_path(pytest_log_path), QA_KEY):
            raise RuntimeError("pytest_log_path_outside_qa")
        arguments = [
            str(TEST_PATH), "-q", "--tb=short", "--noconftest", "--collect-in-virtualenv",
            "--capture=sys", "--assert=plain", "--import-mode=importlib",
            "-c", str(QA / "pytest.ini"), "-p", "no:asyncio", "-p", "no:cacheprovider",
            "--basetemp", str(PYTEST_BASE_TEMP),
            "--log-file", str(pytest_log_path), "--log-file-level", "CRITICAL",
        ]
        gate = Gate()
        import pytest
        output = io.StringIO()
        error_output = io.StringIO()
        _trace("focused_pytest_execution", "start")
        with redirect_stdout(output), redirect_stderr(error_output):
            exit_code = int(pytest.main(arguments, plugins=[gate]))
        _trace("focused_pytest_execution", "complete")
        python_warnings = [type(item.message).__name__ for item in caught]

    expected_calls = len(EXPECTED_NAMES)
    call_reports = {
        nodeid: [outcome for when, outcome, wasxfail in reports if when == "call"]
        for nodeid, reports in gate.reports.items()
    }
    pass_calls = sum(1 for outcomes in call_reports.values() if outcomes == ["passed"])
    skipped = sum(
        1 for reports in gate.reports.values()
        for _when, outcome, wasxfail in reports if outcome == "skipped" or wasxfail
    )
    failed = sum(
        1 for reports in gate.reports.values()
        for _when, outcome, _wasxfail in reports if outcome == "failed"
    )
    other = sum(
        1 for reports in gate.reports.values()
        for _when, outcome, _wasxfail in reports if outcome not in {"passed", "skipped", "failed"}
    )
    total_expected_reports = expected_calls * 3
    if gate.failure_diagnostics:
        pytest_failure_diagnostic = gate.failure_diagnostics[0]
    elif exit_code != 0 and not gate.items:
        pytest_failure_diagnostic = {
            "phase": "focused_pytest_execution",
            "category": "pytest_nonzero_before_collection",
        }
    elif exit_code != 0 and failed:
        pytest_failure_diagnostic = {"phase": "pytest_test_reports", "category": "test_failure"}
    elif exit_code != 0:
        pytest_failure_diagnostic = {
            "phase": "focused_pytest_execution",
            "category": "pytest_nonzero_unclassified",
        }
    elif gate.problems:
        pytest_failure_diagnostic = {
            "phase": "pytest_result_gate",
            "category": "source_origin_or_collection_gate_problem",
        }
    else:
        pytest_failure_diagnostic = {"phase": None, "category": None}
    all_reports_passed = (
        len(gate.reports) == expected_calls
        and sum(len(items) for items in gate.reports.values()) == total_expected_reports
        and all(len(items) == 3 and all(outcome == "passed" for _when, outcome, _xf in items)
                for items in gate.reports.values())
    )
    summary = {
        "pytest_exit_code": exit_code,
        "pytest_failure_diagnostic": pytest_failure_diagnostic,
        "pytest_failure_diagnostics": list(gate.failure_diagnostics),
        "collected": len(gate.items),
        "expected": expected_calls,
        "passed_call_reports": pass_calls,
        "call_reports": call_reports,
        "skipped_or_xfailed_reports": skipped,
        "failed_reports": failed,
        "other_reports": other,
        "pytest_warnings": len(gate.warnings),
        "python_warnings": len(python_warnings),
        "origin_problems": gate.problems,
        "module_origins": gate.origins,
        "pytest_config_binding": gate.pytest_config_binding,
        "pytest_config_pin_after_tests": _pytest_config_pin(),
        "guard_selfchecks": guard_selfchecks,
        "early_guard_selfchecks": list(EARLY_GUARD_CHECKS),
        "candidate_denied_attempts": list(BLOCKED),
        "preloader": preload,
        "winreg_bootstrap_binding": preload.get("winreg_bootstrap_binding"),
        "pyexpat_bootstrap_binding": preload.get("pyexpat_bootstrap_binding"),
        "guards_before_test_import": True,
        "sourcefake_only": True,
        "actual_provider_or_account": False,
        "actual_process_or_pipe": False,
        "formal_th01_pass": False,
    }
    _trace("child_summary", "complete")
    print("ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17:" + json.dumps(summary, sort_keys=True))
    if (
        exit_code != 0 or len(gate.items) != expected_calls or pass_calls != expected_calls
        or not all_reports_passed or skipped or failed or other or gate.warnings
        or python_warnings or gate.problems or BLOCKED
        or guard_selfchecks["candidate_delta_after_selfchecks"] != 0
        or tuple(guard_selfchecks["checks"]) != tuple(EXPECTED_SELF_CHECKS)
    ):
        _trace("focused_qa_gate", "hold", "SystemExit", "focused_gate_exit")
        raise SystemExit(2)
    _trace("focused_qa_gate", "complete")


try:
    main()
except BaseException as exc:
    if not TRACE_EXCEPTION_EMITTED:
        exception_name = type(exc).__name__
        if exception_name not in SAFE_EXCEPTION_TYPES:
            exception_name = "OtherException"
        _trace(ACTIVE_PHASE, "exception", exception_name, _failure_category(exception_name))
        TRACE_EXCEPTION_EMITTED = True
    raise
'''


def _child_source() -> str:
    header = "\n".join(
        (
            "REPO_ROOT_TEXT = " + repr(str(ROOT)),
            "ROOT_TEXT = " + repr(str(SELECTED_ROOT)),
            "SITE_TEXT = " + repr(str(SITE)),
            "QA_TEXT = " + repr(str(QA)),
            "STD_TEMP_TEXT = " + repr(str(STD_TEMP)),
            "PYTEST_CONFIG_TEXT_PATH = " + repr(str(QA / "pytest.ini")),
            "PYTEST_CONFIG_CONTENT_TEXT = " + repr(PYTEST_CONFIG_CONTENT.decode("ascii")),
            "PYTEST_CONFIG_SHA256_TEXT = " + repr(_sha(PYTEST_CONFIG_CONTENT)),
            "TEST_RELATIVE = " + repr(TEST_RELATIVE),
            "PIN_MAP_VALUE = " + repr(PINS),
            "EXPECTED_TEST_NAMES_VALUE = " + repr(EXPECTED_TEST_NAMES),
            "EXPECTED_GUARD_SELFCHECKS_VALUE = " + repr(EXPECTED_GUARD_SELFCHECKS),
            "EXPECTED_EARLY_GUARD_CHECKS_VALUE = " + repr(EXPECTED_EARLY_GUARD_CHECKS),
            "PYEXPAT_ORIGIN_TEXT = " + repr(EXPECTED_PYEXPAT_ORIGIN),
        )
    )
    return header + "\n" + CHILD


def main() -> int:
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("unexpected_repository_root")
    if not PYTHON.is_file() or not SITE.is_dir():
        raise RuntimeError("designated_qa_venv_unavailable")
    if RESULT.exists():
        raise RuntimeError("result_path_already_exists")

    pre_git = _git_snapshot()
    pre_pins = _pin_all()

    QA.mkdir(parents=False, exist_ok=False)
    STD_TEMP.mkdir(parents=False, exist_ok=False)
    if PYTEST_BASE_TEMP.exists():
        raise RuntimeError("pytest_basetemp_not_initially_absent")
    config = QA / "pytest.ini"
    child = QA / "source_qa_child.py"
    config.write_bytes(PYTEST_CONFIG_CONTENT)
    config_pin_pre = _external_file_pin(config)
    if not config_pin_pre["matches_expected"]:
        raise RuntimeError("pytest_config_parent_pre_pin_mismatch")
    selected_pre = _materialize_selected_namespace()
    selected_files_pre = _selected_tree_pins()
    if selected_files_pre != {
        relative: {"bytes": item["bytes"], "sha256": item["sha256"]}
        for relative, item in selected_pre.items()
    }:
        raise RuntimeError("selected_namespace_materialization_mismatch")
    child.write_text(_child_source(), encoding="utf-8", newline="\n")

    # Only Windows runtime variables and the explicit QA temp paths are passed.
    # No ambient provider credentials, .env values, PYTHONPATH, or SDK settings.
    environment = {
        key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ
    }
    environment.update(
        {
            "PATH": str(PYTHON.parent),
            "TEMP": str(STD_TEMP),
            "TMP": str(STD_TEMP),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "NO_COLOR": "1",
            "PY_COLORS": "0",
        }
    )
    command = [str(PYTHON), "-I", "-S", "-B", "-X", "utf8", str(child)]
    completed = subprocess.run(
        command,
        cwd=QA,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=240,
        check=False,
    )
    child_stdout_artifact = _persist_child_log(QA / "child.stdout.bin", completed.stdout)
    child_stderr_artifact = _persist_child_log(QA / "child.stderr.bin", completed.stderr)
    stdout = completed.stdout.decode("utf-8", errors="replace")
    _, child_trace_problems = _parse_child_trace(stdout)
    summary_line = next(
        (line.removeprefix("ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17:")
         for line in reversed(stdout.splitlines())
         if line.startswith("ROOT_ACCOUNT_FULL_R2_SOURCE_QA_R17:")),
        None,
    )
    child_summary = json.loads(summary_line) if summary_line else None
    child_diagnostic = _child_diagnostic(stdout, child_summary, int(completed.returncode))
    rejection, rejection_parse_problems = _parse_preloaded_origin_rejection(stdout)
    child_diagnostic["preloaded_module_origin_scan"] = {
        "rejected_count": 1 if rejection is not None else 0,
        "first_rejection": rejection,
        "parse_problems": rejection_parse_problems,
    }

    config_pin_post = _external_file_pin(config)
    post_pins = _pin_all()
    selected_files_post = _selected_tree_pins()
    post_git = _git_snapshot()
    if (
        not _same_required_git_state(pre_git, post_git)
        or pre_pins != post_pins
        or selected_files_pre != selected_files_post
        or config_pin_pre != config_pin_post
        or not config_pin_post["matches_expected"]
    ):
        raise RuntimeError("postflight_source_or_git_mismatch")

    exact_nine = bool(
        child_summary
        and child_summary.get("pytest_exit_code") == 0
        and child_summary.get("collected") == 9
        and child_summary.get("expected") == 9
        and child_summary.get("passed_call_reports") == 9
        and child_summary.get("skipped_or_xfailed_reports") == 0
        and child_summary.get("failed_reports") == 0
        and child_summary.get("other_reports") == 0
        and child_summary.get("pytest_warnings") == 0
        and child_summary.get("python_warnings") == 0
        and not completed.stderr
        and child_summary.get("guards_before_test_import") is True
        and not child_trace_problems
        and child_stdout_artifact["persisted_exactly"] is True
        and child_stderr_artifact["persisted_exactly"] is True
        and not child_stdout_artifact["truncated_at_limit"]
        and not child_stderr_artifact["truncated_at_limit"]
        and child_diagnostic["child_exception"]["observed"] is False
        and child_diagnostic["preloaded_module_origin_scan"].get("rejected_count") == 0
        and not child_diagnostic["preloaded_module_origin_scan"].get("parse_problems")
        and child_diagnostic["trusted_preload"]["early_guards_installed_before_first_qa_dependency"] is True
        and child_diagnostic["installed_guards"]["full_guards_completed_before_selected_loader"] is True
        and child_summary.get("preloader", {}).get("hard_guards_before_first_third_party_import") is True
        and child_summary.get("preloader", {}).get("forbidden_modules_absent_before_guard_install") is True
        and bool(child_summary.get("preloader", {}).get("initial_import_prefix_root_entries_removed"))
        and all(
            isinstance(value, str)
            and value.replace(chr(92), "/").casefold().rstrip("/")
            in EXPECTED_INTERPRETER_PREFIX_ROOT_KEYS
            for value in child_summary.get("preloader", {}).get(
                "initial_import_prefix_root_entries_removed", ()
            )
        )
        and child_summary.get("preloader", {}).get("preloaded_module_origin_scan", {}).get("status") == "complete"
        and child_summary.get("preloader", {}).get("preloaded_module_origin_scan", {}).get("allowed_entry_count") == len(EXPECTED_PRELOADED_MODULE_ORIGIN_ALLOWANCES)
        and tuple(
            (entry.get("module_name"), entry.get("origin_category"))
            for entry in child_summary.get("preloader", {}).get("preloaded_module_origin_scan", {}).get("allowed_entries", ())
        ) == EXPECTED_PRELOADED_MODULE_ORIGIN_ALLOWANCES
        and child_summary.get("preloader", {}).get("preloaded_module_origin_scan", {}).get("scan_allowance_counts")
        == EXPECTED_PRELOADED_MODULE_ORIGIN_SCAN_COUNTS
        and child_summary.get("preloader", {}).get("winreg_bootstrap_binding")
        == EXPECTED_WINREG_BOOTSTRAP_BINDING_RECEIPT
        and child_summary.get("preloader", {}).get("pyexpat_bootstrap_binding")
        == EXPECTED_PYEXPAT_BOOTSTRAP_BINDING_RECEIPT
        and tuple(child_summary.get("early_guard_selfchecks", ()))
        == tuple(EXPECTED_EARLY_GUARD_CHECKS)
        and tuple(
            child_summary.get("preloader", {}).get("early_guard_installation", {}).get("checks", ())
        ) == tuple(EXPECTED_EARLY_GUARD_CHECKS)
        and child_summary.get("sourcefake_only") is True
        and child_summary.get("pytest_config_pin_after_tests", {}).get("matches_expected") is True
        and child_summary.get("pytest_config_binding", {}).get("inipath")
        == str((QA / "pytest.ini").resolve()).replace(chr(92), "/").casefold()
        and child_summary.get("pytest_config_binding", {}).get("rootpath")
        == str(QA.resolve()).replace(chr(92), "/").casefold()
        and child_summary.get("pytest_config_binding", {}).get("derived_config") == {}
        and not child_summary.get("origin_problems")
        and not child_summary.get("candidate_denied_attempts")
        and child_summary.get("guard_selfchecks", {}).get("candidate_delta_after_selfchecks") == 0
    )
    result = {
        "schema": "iteration41.binance.th01.account_full_snapshot_r2.root_source_qa.r17",
        "status": "SOURCE_FAKE_PRODUCER_COMPONENT_ONLY" if exact_nine else "HOLD_SOURCE_FAKE_QA",
        "evidence_level": "SOURCE_FAKE_ACCOUNT_FULL_SNAPSHOT_PRODUCER_ONLY",
        "branch": post_git["branch"],
        "head": post_git["head"],
        "staging_index_empty_before_and_after": post_git["staged_index_empty"],
        "global_worktree_status_changed_during_child": (
            post_git["global_worktree_status_sha256"]
            != pre_git["global_worktree_status_sha256"]
        ),
        "global_worktree_status_sha256_pre_post": {
            "pre": pre_git["global_worktree_status_sha256"],
            "post": post_git["global_worktree_status_sha256"],
        },
        "checkout_input_status_unchanged": (
            post_git["checkout_input_status_sha256"]
            == pre_git["checkout_input_status_sha256"]
        ),
        "checkout_input_status_sha256_pre_post": {
            "pre": pre_git["checkout_input_status_sha256"],
            "post": post_git["checkout_input_status_sha256"],
        },
        "raw_git_index_unchanged": (
            post_git["raw_index_sha256"] == pre_git["raw_index_sha256"]
        ),
        "raw_git_index_sha256_pre_post": {
            "pre": pre_git["raw_index_sha256"],
            "post": post_git["raw_index_sha256"],
        },
        "pytest_config_pre_post_pin": {
            "pre": config_pin_pre,
            "post": config_pin_post,
            "content": "[pytest]\\n",
        },
        "focused_test": TEST_RELATIVE,
        "expected_case_count": 9,
        "focused_test_entries": {
            "expected": len(EXPECTED_TEST_NAMES),
            "collected": child_summary.get("collected") if child_summary else None,
            "passed_call_reports": child_summary.get("passed_call_reports") if child_summary else None,
        },
        "exact_nine_passed": exact_nine,
        "child_return_code": int(completed.returncode),
        "child_summary": child_summary,
        "pyexpat_bootstrap_binding": (
            child_summary.get("preloader", {}).get("pyexpat_bootstrap_binding")
            if child_summary else None
        ),
        "child_diagnostic": child_diagnostic,
        "child_output_artifacts": {
            "stdout": child_stdout_artifact,
            "stderr": child_stderr_artifact,
            "storage_root": str(QA),
        },
        "source_pre_post_pins": {
            path: {"pre": pre_pins[path], "post": post_pins[path]} for path in PINS
        },
        "selected_namespace_pre_post_pins": {
            path: {"pre": selected_files_pre[path], "post": selected_files_post[path]}
            for path in selected_files_pre
        },
        "selected_namespace_provenance": {
            "root": str(SELECTED_ROOT),
            "clean_dependency_basis": "exact_git_show_HEAD_blobs",
            "runner_change": {
                "relative_path": RUNNER_RELATIVE,
                "change": "one optional trailing venue parameter on _plan",
                "base_head_bytes": PINS[RUNNER_RELATIVE]["head_bytes"],
                "base_head_sha256": PINS[RUNNER_RELATIVE]["head_sha256"],
                "selected_bytes": PINS[RUNNER_RELATIVE]["bytes"],
                "selected_sha256": PINS[RUNNER_RELATIVE]["sha256"],
            },
            "model_change": {
                "relative_path": "examples/000_live_certification/binance_penetration/_certification/models.py",
                "change": "five defaulted read-action fields from the frozen clean HEAD blob",
                "base_head_bytes": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["head_bytes"],
                "base_head_sha256": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["head_sha256"],
                "base_head_blob": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["head_blob"],
                "selected_bytes": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["bytes"],
                "selected_sha256": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["sha256"],
                "selected_blob": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["selected_blob"],
            },
            "selected_source_origins": {
                RUNNER_RELATIVE: PINS[RUNNER_RELATIVE]["origin"],
                "examples/000_live_certification/binance_penetration/_certification/models.py": PINS["examples/000_live_certification/binance_penetration/_certification/models.py"]["origin"],
            },
            "expected_test_entry_count": len(EXPECTED_TEST_NAMES),
            "expected_test_names": list(EXPECTED_TEST_NAMES),
            "dirty_models_config_backends_runner_excluded": True,
            "untracked_fixed_owner_routes_excluded": True,
        },
        "root_qa_via_fresh_isolated_child": True,
        "r6_overlay_source": {
            "bytes": R6_OVERLAY_BYTES,
            "sha256": R6_OVERLAY_SHA256,
            "base_r5_bytes": R5_BYTES,
            "base_r5_sha256": R5_SHA256,
        },
        "r17_overlay_source": {
            "bytes": R17_OVERLAY_BYTES,
            "sha256": R17_OVERLAY_SHA256,
            "base_r8_generated_bytes": R8_GENERATED_BYTES,
            "base_r8_generated_sha256": R8_GENERATED_SHA256,
        },
        "private_inputs_read": False,
        "external_opaque_software_read": False,
        "provider_network_account_or_actual_worker": False,
        "formal_th01_pass": False,
        "accepted_r1_r9_wrapper_suites_repeated": False,
        "stderr_emitted": bool(completed.stderr),
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    with RESULT.open("x", encoding="ascii") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(
        json.dumps(
            {
                "result_path": str(RESULT),
                "status": result["status"],
                "child_return_code": int(completed.returncode),
                "exact_nine_passed": exact_nine,
                "child_diagnostic": child_diagnostic,
                "child_output_artifacts": {
                    "stdout": child_stdout_artifact,
                    "stderr": child_stderr_artifact,
                    "storage_root": str(QA),
                },
                "root_runtime_public_qa": True,
            },
            sort_keys=True,
        )
    )
    return 0 if exact_nine else 2


if __name__ == "__main__":
    raise SystemExit(main())
