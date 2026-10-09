"""Guarded sourcefake QA launcher for Optional16 reconciliation R4.

The required mode is either a public-source preflight or the exact frozen fake
test. This runner never calls the retained Root host or a provider.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import sysconfig
import time
import uuid


ROOT = Path(r"D:\source_code\backtrader")
SCRIPT_REL = ".codex-tmp/optional16_r4_sourcefake_guarded_r2.py"
OUT_REL = ".codex-tmp/optional16_r4_sourcefake_guarded_r2"
QA_PYTHON = Path(r"D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe")
QA_SITE = Path(r"D:\temp\iteration41-main-source-qa-20260926\venv\Lib\site-packages")
EXPECTED_TESTS = 47
MAX_PUBLIC_FILE = 2_000_000
MAX_GIT_INDEX = 8_000_000
MAX_CAPTURE_CHARS = 256_000
GIT_EXECUTABLE: str | None = None
EXPECTED_SOURCE_IMPORTS = {
    "__future__", "argparse", "ast", "builtins", "contextlib", "copy", "ctypes",
    "dataclasses", "dis", "hashlib", "importlib", "inspect", "json", "math",
    "ntpath", "os", "pathlib", "pytest", "re", "shutil", "stat", "subprocess",
    "sys", "threading", "time", "types",
}

EVIDENCE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/"
    "evidence/"
)
SOURCE_INDEX_REL = (
    EVIDENCE
    + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/"
    + "source-index.json"
)
ROOT_RUNNER_REL = ".codex-tmp/optional16_root_preparation_actual_20261009.py"
CU_SNAPSHOT_REL = (
    EVIDENCE + "iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py"
)

# These are the exact production and historical source objects loaded or
# preserved by the reviewed fixture.  The 35 source-index rows plus SUPPORT
# and ROOT_RUNNER_REL form the frozen 42-row public outer map.
SUPPORT = {
    SOURCE_INDEX_REL: "5d9f43ff4c6e28d87f44e551e062b798c8e02c22cafca5f978d920d3938d9afb",
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/README.md":
        "ac6d32e0d5ea074b8a6d8f741e49e8312ff8adeda14aa6c21aa16d81adb273a8",
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-source-fake-r1-2026-10-09/checkpoint.json":
        "a62ab186aa6ca375d259ac7169ac89ba7f94288891721e8694a9ad39026011b7",
    EVIDENCE + "iteration41-optional16-r33-root-preparation-driver-independent-review-r1-2026-10-09/review.json":
        "b48e45c950d1bdd65197af01a37db4d5fb2896ef119a265376cda7675f3010c4",
    "backtrader_runtime/certification_roundtrip_private.py":
        "b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd",
    "backtrader_runtime/certification_binance_roundtrip_r3_cli.py":
        "62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76",
}

DIRECT_PINS = {
    "scripts/iteration41_optional16_preparation_source_reconciliation_r4.py":
        "bd5b8adf47edabbdcf5faf475ce11fa0dd6b936ad03c7e4be3cd991a26773760",
    "tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4_source_fake.py":
        "fd6bc283ec1a286d6ea2b315ff2dd904a239777468ed62b71cee532c429ffacd",
    "tests/__init__.py":
        "512e1e3b7f30908568916e60ff67f65142b85edf14a00d8b49a2a99d3e19a458",
    EVIDENCE + "iteration41-optional16-preparation-source-reconciliation-r4-independent-review-r1-2026-10-09.md":
        "96e483fe178ad68709f20cfce9eec8b5d0528242880d362c86d201f02ed6d234",
    "scripts/iteration41_optional16_preparation_source_reconciliation_r1.py":
        "5277b470a05cf956e29c826c4a8434e7bbd5697d90fb617df6756663cd09e4ba",
    "scripts/iteration41_optional16_preparation_source_reconciliation_r2.py":
        "b3323d01597f180905d9d33ffb86429b7d91104eb950af95544d2a3ac1567efd",
    "scripts/iteration41_optional16_preparation_source_reconciliation_r3.py":
        "769f6af037ee47ae8a0b165f49046cccd0b163f8f3992dd6490ec31ec90332ca",
    "scripts/iteration41_optional16_r33_root_preparation_driver_r1.py":
        "7930bb76a89b4a29721b30aac40163bebb2714667474961a4a058e066d62d71c",
    "scripts/iteration41_optional16_r33_root_preparation_call_r1.py":
        "762cf58ed2d9d4e2eed2c089a967946610ba660854327d7786c63f463ae4ef8e",
    "scripts/iteration41_optional16_r33_root_held_entry_r2.py":
        "80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead",
    "scripts/iteration41_optional16_r33_root_preparation_r1.py":
        "a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4",
    "scripts/iteration41_root_held_source_scope_v3.py":
        "f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677",
    "scripts/iteration41_root_held_source_scope_v4.py":
        "138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830",
    "scripts/iteration41_optional16_r33_root_held_invoke_r28_r5.py":
        "710452c8358887faa152cd2c6d11333ccf8ecb18fbe64d511ce86eb8f112c99c",
    "scripts/iteration41_optional16_r33_root_held_invoke_r27.py":
        "ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339",
    "scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py":
        "bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876",
    CU_SNAPSHOT_REL: "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246",
}

ARCHIVES = {
    EVIDENCE + "iteration41-optional16-r33-root-preparation-call-source-fake-r1-2026-10-09/source-packet.zip": {
        "bytes": 9112,
        "sha256": "2dfd4becf9a8b1d19c008b0db3efd943cb543c5fc88e178d56dc04f1b904aa51",
        "checkpoint": EVIDENCE + "iteration41-optional16-r33-root-preparation-call-source-fake-r1-2026-10-09/checkpoint.json",
        "checkpoint_sha256": "c575fae4136b42d98fa8a471c57e53bc405631da0bac2fc06f55d0bca735016b",
        "members": [
            "scripts/iteration41_optional16_r33_root_preparation_call_r1.py",
            "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r1_source_fake.py",
        ],
    },
    EVIDENCE + "iteration41-optional16-r33-root-preparation-source-fake-r1-2026-10-09/source-packet.zip": {
        "bytes": 7681,
        "sha256": "1201c232e264cdae67c94edb3fbe48ebb434365574ea84d7534e5eaf4b5e5f76",
        "checkpoint": EVIDENCE + "iteration41-optional16-r33-root-preparation-source-fake-r1-2026-10-09/checkpoint.json",
        "checkpoint_sha256": "3f66e6f3cbbbacaea84f1629b8ad26fad1365d34846f4dd9ae03bb67732b85b2",
        "members": [
            "scripts/iteration41_optional16_r33_root_preparation_r1.py",
            "tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_r1_source_fake.py",
        ],
    },
}


class GateFailure(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _key(value: object) -> str:
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    return os.path.normcase(os.path.normpath(str(value).replace("/", "\\")))


def _fail(code: str) -> None:
    raise GateFailure(code)


def _relative_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in ("", ".", "..") for part in pure.parts):
        _fail("unsafe_relative_path")
    if "\\" in value or ":" in value:
        _fail("unsafe_relative_path")
    return ROOT.joinpath(*pure.parts)


def _check_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        try:
            st = cursor.lstat()
        except OSError:
            _fail("path_component_missing")
        attrs = getattr(st, "st_file_attributes", 0)
        if stat.S_ISLNK(st.st_mode) or attrs & 0x400:
            _fail("reparse_or_symlink")


def _read_bounded(path: Path, limit: int = MAX_PUBLIC_FILE) -> bytes:
    _check_components(path)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size < 0 or before.st_size > limit:
            _fail("input_not_bounded_regular_file")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            raw = stream.read(limit + 1)
        after = path.lstat()
    except GateFailure:
        raise
    except OSError:
        _fail("input_read_failed")
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size,
        getattr(value, "st_mtime_ns", 0), getattr(value, "st_ctime_ns", 0),
    )
    if len(raw) > limit or identity(before) != identity(opened) or identity(opened) != identity(after):
        _fail("input_changed_or_over_limit")
    return raw


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git(args: list[str]) -> tuple[int, str]:
    if not GIT_EXECUTABLE:
        _fail("git_metadata_unavailable")
    try:
        result = subprocess.run(
            [GIT_EXECUTABLE, "-C", str(ROOT), *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            shell=False,
            timeout=10,
            env=dict(os.environ),
        )
    except (OSError, subprocess.SubprocessError):
        _fail("git_metadata_unavailable")
    return result.returncode, result.stdout.decode("ascii", "strict").strip()


def _git_snapshot() -> dict[str, object]:
    code, top = _git(["rev-parse", "--show-toplevel"])
    if code != 0 or _key(top) != _key(ROOT):
        _fail("git_root_mismatch")
    code, branch = _git(["branch", "--show-current"])
    if code != 0 or branch != "dev":
        _fail("git_branch_not_dev")
    code, head = _git(["rev-parse", "HEAD"])
    if code != 0 or len(head) != 40:
        _fail("git_head_unavailable")
    code, _ = _git(["diff", "--cached", "--quiet"])
    if code != 0:
        _fail("git_index_not_empty")
    index_path = ROOT / ".git" / "index"
    index_raw = _read_bounded(index_path, MAX_GIT_INDEX)
    head_file = _read_bounded(ROOT / ".git" / "HEAD", 1024).decode("ascii", "strict").strip()
    if head_file != "ref: refs/heads/dev":
        _fail("git_head_reference_not_dev")
    head_ref_path = None
    head_ref_sha256 = None
    if head_file.startswith("ref: "):
        ref_name = head_file[5:]
        ref_path = ROOT / ".git" / Path(*PurePosixPath(ref_name).parts)
        try:
            ref_raw = _read_bounded(ref_path, 1024)
            head_ref_path = str(ref_path)
            head_ref_sha256 = _sha(ref_raw)
        except GateFailure:
            packed = _read_bounded(ROOT / ".git" / "packed-refs", 1_000_000).decode("ascii", "strict")
            target = next((line.split(" ", 1)[0] for line in packed.splitlines()
                           if line and not line.startswith(("#", "^"))
                           and line.endswith(" " + ref_name)), None)
            if target is None:
                _fail("git_head_reference_unavailable")
            head_ref_path = str(ROOT / ".git" / "packed-refs")
            head_ref_sha256 = _sha(target.encode("ascii"))
    code, head_check = _git(["rev-parse", "HEAD"])
    if code != 0 or head_check != head:
        _fail("git_head_changed_during_preflight")
    code, _ = _git(["diff", "--cached", "--quiet"])
    if code != 0:
        _fail("git_index_changed_during_preflight")
    index_check = _read_bounded(index_path, MAX_GIT_INDEX)
    if _sha(index_check) != _sha(index_raw):
        _fail("git_index_changed_during_preflight")
    return {
        "branch": branch,
        "head": head,
        "head_ref_path": head_ref_path,
        "head_ref_sha256": head_ref_sha256,
        "staged_diff_empty": True,
        "index_bytes": len(index_raw),
        "index_sha256": _sha(index_raw),
    }


def _git_snapshot_after_guard(before: dict[str, object]) -> dict[str, object]:
    head_file = _read_bounded(ROOT / ".git" / "HEAD", 1024).decode("ascii", "strict").strip()
    if not head_file.startswith("ref: refs/heads/"):
        _fail("git_head_reference_changed")
    branch = head_file.removeprefix("ref: refs/heads/")
    if branch != "dev":
        _fail("git_branch_changed")
    ref_path = ROOT / ".git" / "refs" / "heads" / branch
    try:
        ref_raw = _read_bounded(ref_path, 1024)
        head = ref_raw.decode("ascii", "strict").strip()
        ref_identity = {"head_ref_path": str(ref_path), "head_ref_sha256": _sha(ref_raw)}
    except GateFailure:
        packed_raw = _read_bounded(ROOT / ".git" / "packed-refs", 1_000_000)
        packed = packed_raw.decode("ascii", "strict")
        head = next((line.split(" ", 1)[0] for line in packed.splitlines()
                     if line and not line.startswith(("#", "^"))
                     and line.endswith(" refs/heads/" + branch)), "")
        ref_identity = {"head_ref_path": str(ROOT / ".git" / "packed-refs"),
                        "head_ref_sha256": _sha(head.encode("ascii"))}
    index_raw = _read_bounded(ROOT / ".git" / "index", MAX_GIT_INDEX)
    snapshot = {
        "branch": branch,
        "head": head,
        **ref_identity,
        "staged_diff_empty": bool(before.get("staged_diff_empty")),
        "index_bytes": len(index_raw),
        "index_sha256": _sha(index_raw),
    }
    if snapshot["head"] != before.get("head") or snapshot["index_sha256"] != before.get("index_sha256"):
        snapshot["staged_diff_empty"] = False
    return snapshot


def _merge_pin(pins: dict[str, str], relative: str, digest: str) -> None:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
        _fail("invalid_expected_digest")
    prior = pins.get(relative)
    if prior is not None and prior != digest:
        _fail("pin_manifest_conflict")
    pins[relative] = digest.lower()


def _collect_pins() -> tuple[dict[str, str], dict[str, object], dict[str, object]]:
    index_raw = _read_bounded(_relative_path(SOURCE_INDEX_REL))
    if _sha(index_raw) != SUPPORT[SOURCE_INDEX_REL]:
        _fail("source_index_pin_mismatch")
    try:
        index = json.loads(index_raw.decode("utf-8", "strict"))
        rows = index["candidate_sources"] + index["fixed_dependencies"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        _fail("source_index_invalid")
    if type(rows) is not list or len(rows) != 35:
        _fail("source_index_count_mismatch")

    pins: dict[str, str] = {}
    for row in rows:
        if type(row) is not dict or type(row.get("path")) is not str:
            _fail("source_index_row_invalid")
        relative = row["path"]
        _relative_path(relative)
        row_bytes = row.get("bytes")
        if row_bytes is not None and (type(row_bytes) is not int or row_bytes < 0 or row_bytes > MAX_PUBLIC_FILE):
            _fail("source_index_size_invalid")
        _merge_pin(pins, relative, row.get("sha256", ""))
    for relative, digest in SUPPORT.items():
        _merge_pin(pins, relative, digest)
    _merge_pin(pins, ROOT_RUNNER_REL, "5fb9fb55fbfbfda43687b6020d40db9653269a422dae5478dc7ede3ee8f7dd35")
    if len(pins) != 42:
        _fail("public_outer_map_count_mismatch")

    for relative, digest in DIRECT_PINS.items():
        _merge_pin(pins, relative, digest)

    results: dict[str, object] = {}
    for relative, expected in sorted(pins.items()):
        path = _relative_path(relative)
        raw = _read_bounded(path)
        if _sha(raw) != expected:
            _fail("pinned_input_hash_mismatch")
        row = next((item for item in rows if item.get("path") == relative), None)
        if row is not None and row.get("bytes") is not None and row.get("bytes") != len(raw):
            _fail("source_index_size_mismatch")
        results[relative] = {"bytes": len(raw), "sha256": expected, "origin": str(path)}

    # Verify archive provenance from the pinned source index and checkpoints.
    # Archive bytes are read only for a bounded SHA-256 check; no member is
    # extracted or parsed here.  Root separately confirmed each central
    # directory contains only its two documented Python source members.
    fixed = {row["path"]: row for row in index["fixed_dependencies"]}
    archive_results = {}
    for relative, metadata in ARCHIVES.items():
        row = fixed.get(relative)
        if row is None or row.get("bytes") != metadata["bytes"] or row.get("sha256") != metadata["sha256"]:
            _fail("public_archive_index_metadata_mismatch")
        checkpoint_raw = _read_bounded(_relative_path(metadata["checkpoint"]))
        if _sha(checkpoint_raw) != metadata["checkpoint_sha256"]:
            _fail("public_archive_checkpoint_pin_mismatch")
        checkpoint = json.loads(checkpoint_raw.decode("utf-8", "strict"))
        packet_files = checkpoint.get("packet_files", [])
        if type(packet_files) is dict:
            packet_files = [dict(path=name, **details) for name, details in packet_files.items()]
        packet = next((item for item in packet_files if item.get("path") == "source-packet.zip"), None)
        if packet is None or packet.get("bytes") != metadata["bytes"] or packet.get("sha256") != metadata["sha256"]:
            _fail("public_archive_checkpoint_inventory_mismatch")
        members = checkpoint.get("source_packet_members")
        if members is not None and members != metadata["members"]:
            _fail("public_archive_member_manifest_mismatch")
        archive_results[relative] = {
            "index_role": "fixed_dependencies",
            "bytes": metadata["bytes"],
            "sha256": metadata["sha256"],
            "checkpoint": metadata["checkpoint"],
            "checkpoint_sha256": metadata["checkpoint_sha256"],
            "declared_members": metadata["members"],
            "body_handling": "bounded_hash_only_no_extraction",
            "central_directory_review": "Root public source-only check b1bf77; no separate artifact path or SHA supplied",
            "central_directory_read_by_this_harness": False,
        }

    test_rel = next(key for key in DIRECT_PINS if key.startswith("tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4"))
    test_tree = ast.parse(_read_bounded(_relative_path(test_rel)).decode("utf-8", "strict"))
    test_names = [node.name for node in test_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    regression = "test_z_original_root_audit_rejects_r3_transform_and_r4_exact_loader_closes_once"
    if regression not in test_names:
        _fail("original_root_audit_regression_missing")

    return pins, results, {
        "source_index_rows": 35,
        "outer_public_pin_rows": 42,
        "software_pin_rows": 3,
        "combined_outer_pin_rows": 45,
        "source_archives": archive_results,
        "test_function_names": test_names,
        "original_root_audit_regression": regression,
        "original_root_audit_regression_present": True,
        "historical_helper_sources": {
            name: DIRECT_PINS[name]
            for name in (
                "scripts/iteration41_optional16_preparation_source_reconciliation_r1.py",
                "scripts/iteration41_optional16_preparation_source_reconciliation_r2.py",
                "scripts/iteration41_optional16_preparation_source_reconciliation_r3.py",
            )
        },
        "historical_run_assignment_identity_proven": False,
        "retained_scope_fixture": "synthetic only",
    }


def _script_sha() -> str:
    path = ROOT / SCRIPT_REL
    raw = _read_bounded(path)
    return _sha(raw)


def _verify_self(expected: str) -> str:
    script = Path(__file__)
    if _key(script) != _key(ROOT / SCRIPT_REL):
        _fail("harness_origin_mismatch")
    actual = _script_sha()
    if actual != expected.lower():
        _fail("harness_self_pin_mismatch")
    return actual


def _check_runtime() -> None:
    if _key(Path.cwd()) != _key(ROOT):
        _fail("working_directory_mismatch")
    if _key(Path(sys.executable)) != _key(QA_PYTHON):
        _fail("qa_interpreter_mismatch")
    if sys.flags.isolated != 1 or sys.flags.no_site != 1 or not sys.dont_write_bytecode:
        _fail("isolated_runtime_flags_missing")
    if sys.flags.utf8_mode != 1:
        _fail("utf8_mode_missing")


def _install_allowlisted_environment(temp_dir: Path) -> dict[str, object]:
    global GIT_EXECUTABLE

    original = {key.upper(): value for key, value in os.environ.items()}
    system_root = original.get("SYSTEMROOT")
    windows_dir = original.get("WINDIR") or system_root
    if not system_root or not windows_dir:
        _fail("windows_environment_unavailable")
    git_path = shutil.which("git")
    if not git_path or not Path(git_path).is_absolute():
        _fail("git_metadata_unavailable")
    GIT_EXECUTABLE = str(Path(git_path))
    system32 = Path(system_root) / "System32"
    path_entries = (
        Path(git_path).parent,
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        QA_PYTHON.parent,
        system32,
    )
    controlled_path = os.pathsep.join(dict.fromkeys(str(path) for path in path_entries))

    allowed = {
        "SYSTEMROOT": system_root,
        "WINDIR": windows_dir,
        "PATH": controlled_path,
        "TEMP": str(temp_dir),
        "TMP": str(temp_dir),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "",
        "PYTEST_PLUGINS": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    os.environ.clear()
    os.environ.update(allowed)
    observed_names = {key.upper() for key in os.environ}
    expected_names = {key.upper() for key in allowed}
    if observed_names != expected_names or any(os.environ.get(key) != value for key, value in allowed.items()):
        _fail("process_environment_allowlist_mismatch")
    return {
        "installed": True,
        "allowed_names": sorted(expected_names),
        "observed_names": sorted(observed_names),
        "values_emitted": False,
        "git_executable_absolute": True,
    }


def _preload_source_stdlib(pins: dict[str, str]) -> list[dict[str, str]]:
    import_names: set[str] = set()
    source_paths = {
        relative for relative in pins
        if relative.endswith(".py")
        and (relative in DIRECT_PINS
             or relative in SUPPORT
             or relative == ROOT_RUNNER_REL)
    }
    for relative in source_paths:
        raw = _read_bounded(_relative_path(relative))
        if _sha(raw) != pins[relative]:
            _fail("preload_source_pin_mismatch")
        try:
            tree = ast.parse(raw.decode("utf-8", "strict"), filename=relative)
        except (UnicodeError, SyntaxError):
            _fail("preload_source_parse_failed")
        class _Imports(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                return None

            def visit_AsyncFunctionDef(self, node):
                return None

            def visit_Lambda(self, node):
                return None

            def visit_Import(self, node):
                import_names.update(alias.name.split(".", 1)[0] for alias in node.names)

            def visit_ImportFrom(self, node):
                if node.level == 0 and node.module:
                    import_names.add(node.module.split(".", 1)[0])

        _Imports().visit(tree)
    if import_names != EXPECTED_SOURCE_IMPORTS:
        _fail("source_import_closure_changed")

    standard_names = set(getattr(sys, "stdlib_module_names", ()))
    standard_names.update(sys.builtin_module_names)
    if import_names - standard_names != {"pytest"}:
        _fail("nonstandard_source_import")

    standard_roots = set()
    for key in ("stdlib", "platstdlib"):
        value = sysconfig.get_paths().get(key)
        if value:
            standard_roots.add(_key(value))
    standard_roots.add(_key(Path(sys.base_prefix) / "DLLs"))
    standard_zips = {_key(value) for value in sys.path if value and Path(value).suffix.lower() == ".zip"}

    imported = []
    for name in sorted(import_names - {"pytest"}):
        try:
            module = importlib.import_module(name)
        except Exception:
            _fail("stdlib_preload_failed")
        origin = getattr(module, "__file__", None)
        if origin is None:
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if isinstance(origin, str) and origin not in {"built-in", "frozen"}:
            origin_key = _key(origin)
            if not any(_under_path(origin_key, parent) for parent in standard_roots | standard_zips):
                _fail("stdlib_preload_origin_mismatch")
        imported.append({"name": name, "origin": str(origin or "built-in-or-frozen")})
    return imported


def _under_path(path_key: str, parent_key: str) -> bool:
    try:
        return os.path.commonpath([path_key, parent_key]) == parent_key
    except ValueError:
        return False


class _SafeWindowsConsoleApi:
    """Inert Colorama-facing WinAPI facade; never loads or calls native code."""

    def __init__(self, counter: dict[str, int]):
        object.__setattr__(self, "_counter", counter)

    def __getattr__(self, _name):
        return self

    def __setattr__(self, name, _value):
        if name == "_counter":
            object.__setattr__(self, name, _value)
        else:
            self._counter["fake_api_configurations"] += 1

    def __call__(self, *_args, **_kwargs):
        self._counter["fake_winapi_calls"] += 1
        return 0

    def __bool__(self):
        return False


def _preload_guard_runtime() -> tuple[dict[str, object], dict[str, int]]:
    import ctypes
    import ctypes.util
    import sysconfig

    candidate_modules = (
        "scripts.iteration41_optional16_preparation_source_reconciliation_r4",
        "tests.unit.scripts.test_iteration41_optional16_preparation_source_reconciliation_r4_source_fake",
    )
    sensitive_preloaded = [
        name for name in tuple(sys.modules)
        if name == "asyncio" or name.startswith("asyncio.")
        or name == "unittest.mock"
        or name == "colorama" or name.startswith("colorama.")
    ]
    if sensitive_preloaded:
        _fail("guard_runtime_preloaded_before_facade")
    forbidden_preloaded = [
        name for name in tuple(sys.modules)
        if name == "tests" or name.startswith("tests.")
        or name in candidate_modules
    ]
    if forbidden_preloaded:
        _fail("candidate_module_preloaded_before_guards")

    counter = {
        "fake_winapi_calls": 0,
        "fake_library_requests": 0,
        "fake_api_configurations": 0,
    }
    # Colorama may inspect kernel32 during pytest startup. Bind it to a false
    # console probe before importing Colorama, without touching WinAPI.
    facade = _SafeWindowsConsoleApi(counter)
    ctypes.windll = facade

    def fake_windows_library(*_args, **_kwargs):
        counter["fake_library_requests"] += 1
        return facade

    # Colorama's Windows module can construct a LibraryLoader from WinDLL
    # directly, so cover that entry point during preload too. The full hard
    # deny below replaces these functions before candidate test imports.
    for attribute in ("WinDLL", "OleDLL"):
        if hasattr(ctypes, attribute):
            setattr(ctypes, attribute, fake_windows_library)

    module_names = (
        "traceback",
        "asyncio",
        "unittest.mock",
        "builtins",
        "ctypes.util",
        "ctypes.wintypes",
        "contextlib",
        "importlib.machinery",
        "inspect",
        "math",
        "multiprocessing",
        "multiprocessing.connection",
        "ntpath",
        "re",
        "socket",
        "threading",
        "subprocess",
        "types",
        "zipfile",
        "colorama",
        "colorama.ansi",
        "colorama.ansitowin32",
        "colorama.initialise",
        "colorama.win32",
        "colorama.winterm",
    )
    standard_roots = {
        _key(value)
        for key in ("stdlib", "platstdlib")
        if (value := sysconfig.get_paths().get(key))
    }
    standard_roots.add(_key(Path(sys.base_prefix) / "DLLs"))
    qa_root = _key(QA_SITE)
    origin_rows = []
    for name in module_names:
        try:
            module = importlib.import_module(name)
        except BaseException:
            _fail("guard_runtime_preload_failed")
        origin = getattr(module, "__file__", None)
        if origin is None:
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if isinstance(origin, str) and origin not in {"built-in", "frozen"}:
            origin_key = _key(origin)
            scope = (
                "qa_runtime" if _under_path(origin_key, qa_root)
                else "stdlib" if any(_under_path(origin_key, root) for root in standard_roots)
                else "other"
            )
        else:
            scope = "stdlib"
        expected_scope = "qa_runtime" if name.startswith("colorama") else "stdlib"
        if scope != expected_scope:
            _fail("guard_runtime_preload_origin_mismatch")
        origin_rows.append({"module": name, "origin_scope": scope})

    candidate_loaded_after_preload = [
        name for name in tuple(sys.modules)
        if name == "tests" or name.startswith("tests.")
        or name in candidate_modules
    ]

    return ({
        "status": "complete",
        "phase": "runtime_preload_before_hard_denials",
        "modules": origin_rows,
        "windows_console_facade": "inert_false_result",
        "actual_winapi_calls": False,
        "candidate_source_imported": bool(candidate_loaded_after_preload),
        "candidate_modules_observed": candidate_loaded_after_preload,
    }, counter)


def _finite_runner_exception(exc: BaseException, pins: dict[str, str], output_root: Path) -> dict[str, object]:
    traceback_module = sys.modules.get("traceback")
    if traceback_module is None:
        return {"exception_type": "unavailable", "frames": [], "truncated": False}

    module_type = type(exc)
    module_name = getattr(module_type, "__module__", "")
    class_name = getattr(module_type, "__name__", "")
    if (module_name in {"builtins", "pytest", "_pytest", "colorama", "importlib", "ctypes"}
            and isinstance(class_name, str)
            and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", class_name)):
        exception_type = module_name + "." + class_name
    else:
        exception_type = "other_exception"

    stdlib_roots = {
        _key(value)
        for key in ("stdlib", "platstdlib")
        if (value := sysconfig.get_paths().get(key))
    }
    stdlib_roots.add(_key(Path(sys.base_prefix) / "DLLs"))
    root_key = _key(ROOT)
    output_key = _key(output_root)
    qa_key = _key(QA_SITE)
    rows = []
    total = 0
    traceback_obj = getattr(exc, "__traceback__", None)
    try:
        iterator = traceback_module.walk_tb(traceback_obj)
        for frame, line_number in iterator:
            total += 1
            if total > 64:
                break
            filename = frame.f_code.co_filename
            filename_key = _key(filename)
            if _under_path(filename_key, output_key):
                scope = "harness"
            elif _under_path(filename_key, root_key):
                try:
                    relative = os.path.relpath(filename, str(ROOT)).replace("\\", "/")
                except (OSError, ValueError):
                    relative = ""
                scope = "public_source" if relative in pins or relative == SCRIPT_REL else "other"
            elif any(_under_path(filename_key, base) for base in stdlib_roots):
                scope = "stdlib"
            elif _under_path(filename_key, qa_key):
                scope = "qa_runtime"
            else:
                scope = "other"
            function = frame.f_code.co_name
            if scope in {"harness", "public_source", "stdlib"}:
                if not isinstance(function, str) or not re.fullmatch(r"[A-Za-z0-9_<>.$-]{1,80}", function):
                    function = "public_function"
            else:
                function = "external_frame"
            rows.append({"scope": scope, "function": function, "line": int(line_number)})
    except BaseException:
        return {"exception_type": exception_type, "frames": [], "truncated": True}
    truncated = total > 12
    return {
        "exception_type": exception_type,
        "frames": rows[-12:],
        "truncated": truncated,
        "frame_count_capped": min(total, 64),
    }


def _check_loaded_repo_origins(pins: dict[str, str]) -> dict[str, object]:
    root_key = _key(ROOT)
    checked = 0
    mismatches = 0
    for module in tuple(sys.modules.values()):
        if module is None:
            continue
        spec_origin = getattr(getattr(module, "__spec__", None), "origin", None)
        for origin in (getattr(module, "__file__", None), spec_origin):
            if not isinstance(origin, str) or origin in {"built-in", "frozen", "namespace"}:
                continue
            origin_key = _key(origin)
            if not _under_path(origin_key, root_key):
                continue
            checked += 1
            try:
                relative = os.path.relpath(origin, str(ROOT)).replace("\\", "/")
            except (OSError, ValueError):
                mismatches += 1
                continue
            if relative == SCRIPT_REL:
                expected_path = ROOT / SCRIPT_REL
            else:
                expected_path = _relative_path(relative)
                if relative not in pins:
                    mismatches += 1
                    continue
            if _key(expected_path) != origin_key:
                mismatches += 1
    return {
        "status": "matched" if mismatches == 0 else "mismatch",
        "checked_origins": checked,
        "mismatch_count": mismatches,
    }


def _install_pinned_source_loader(pins: dict[str, str], guard_state: dict[str, object]) -> None:
    loader_type = importlib.machinery.SourceFileLoader
    original_get_code = loader_type.get_code

    def get_pinned_code(loader, fullname):
        origin = getattr(loader, "path", None)
        if isinstance(origin, str) and _under_path(_key(origin), _key(ROOT)):
            try:
                relative = os.path.relpath(origin, str(ROOT)).replace("\\", "/")
            except (OSError, ValueError):
                _fail("source_loader_origin_invalid")
            expected = pins.get(relative)
            if expected is None:
                _fail("unpinned_repo_source_load")
            path = _relative_path(relative)
            raw = _read_bounded(path)
            if _sha(raw) != expected:
                _fail("source_loader_pin_mismatch")
            guard_state["pinned_source_loader_reads"] = int(
                guard_state.get("pinned_source_loader_reads", 0)
            ) + 1
            return compile(raw, str(path), "exec", dont_inherit=True)
        return original_get_code(loader, fullname)

    loader_type.get_code = get_pinned_code
    guard_state["pinned_source_loader_installed"] = True


def _write_json(path: Path, value: object) -> None:
    output_root = _ensure_output_root()
    path_key = _key(path)
    root_key = _key(output_root)
    try:
        inside = os.path.commonpath([path_key, root_key]) == root_key
    except ValueError:
        inside = False
    if not inside:
        _fail("output_path_outside_namespace")
    if path.exists():
        _fail("output_receipt_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    _check_components(path.parent)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _ensure_output_root() -> Path:
    codex_tmp = ROOT / ".codex-tmp"
    _check_components(codex_tmp)
    output_root = ROOT / OUT_REL
    if output_root.exists():
        _check_components(output_root)
        if not output_root.is_dir():
            _fail("output_namespace_not_directory")
    else:
        output_root.mkdir(parents=False, exist_ok=False)
        _check_components(output_root)
    return output_root


class _BoundedText:
    def __init__(self, limit: int = MAX_CAPTURE_CHARS):
        self.limit = limit
        self.parts: list[str] = []
        self.size = 0
        self.truncated = False

    def write(self, value: str) -> int:
        text = str(value)
        remaining = self.limit - self.size
        if remaining > 0:
            self.parts.append(text[:remaining])
            self.size += min(len(text), remaining)
        if len(text) > remaining:
            self.truncated = True
        return len(text)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    @property
    def encoding(self) -> str:
        return "utf-8"

    def getvalue(self) -> str:
        value = "".join(self.parts)
        return value + ("\n[OUTPUT_TRUNCATED]" if self.truncated else "")


class _CollectionGate:
    def __init__(self, test_path: Path, pins: dict[str, str]):
        self.test_path = test_path
        self.pins = pins
        self.collected = 0
        self.names: list[str] = []
        self.pass_calls = 0
        self.failures = 0
        self.skips = 0
        self.other_reports = 0
        self.origin_mismatch = False
        self.support_origin_mismatch = False
        self.regression_missing = False
        self.count_mismatch = False

    def pytest_collection_finish(self, session):
        self.collected = len(session.items)
        self.names = sorted({item.originalname or item.name for item in session.items})
        if self.collected != EXPECTED_TESTS:
            self.count_mismatch = True
        if any(_key(item.path) != _key(self.test_path) for item in session.items):
            self.origin_mismatch = True
        for item in session.items:
            module = getattr(item, "module", None)
            module_file = getattr(module, "__file__", None)
            spec_origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if (not module_file or _key(module_file) != _key(self.test_path)
                    or (spec_origin and _key(spec_origin) != _key(self.test_path))):
                self.origin_mismatch = True

        tests_package = sys.modules.get("tests")
        if tests_package is not None:
            expected_init = _key(_relative_path("tests/__init__.py"))
            package_file = getattr(tests_package, "__file__", None)
            package_origin = getattr(getattr(tests_package, "__spec__", None), "origin", None)
            if (self.pins.get("tests/__init__.py") is None or not package_file
                    or _key(package_file) != expected_init
                    or not package_origin or _key(package_origin) != expected_init):
                self.support_origin_mismatch = True
        elif any(getattr(item.module, "__name__", "").startswith("tests.") for item in session.items):
            self.support_origin_mismatch = True

        for package_name, relative_dir in (
            ("tests.unit", "tests/unit"),
            ("tests.unit.scripts", "tests/unit/scripts"),
        ):
            package = sys.modules.get(package_name)
            if package is None:
                continue
            paths = getattr(package, "__path__", None)
            expected_dir = _key(ROOT / relative_dir)
            if not paths or {_key(path) for path in paths} != {expected_dir}:
                self.support_origin_mismatch = True
        if "test_z_original_root_audit_rejects_r3_transform_and_r4_exact_loader_closes_once" not in self.names:
            self.regression_missing = True
        if (self.count_mismatch or self.origin_mismatch or self.support_origin_mismatch
                or self.regression_missing):
            session.shouldfail = "sourcefake_collection_gate"

    def pytest_runtest_logreport(self, report):
        if report.when == "call" and report.outcome == "passed":
            self.pass_calls += 1
        elif report.outcome == "failed":
            self.failures += 1
        elif report.outcome == "skipped":
            self.skips += 1
        else:
            self.other_reports += 1


class _BlockImports:
    blocked = (
        "backtrader", "backtrader_runtime", "bt_api", "bt_api_py", "zmq",
        "win32api", "win32con", "win32file", "win32event", "win32process",
        "winreg", "_winapi",
    )

    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in self.blocked):
            raise ImportError("sourcefake import denied")
        return None


def _deny_guard(guard_state: dict[str, object], allowed_keys: set[str], output_root: Path) -> None:
    import builtins
    import ctypes
    import ctypes.util
    import ctypes.wintypes
    import contextlib
    import importlib.machinery
    import inspect
    import math
    import multiprocessing
    import multiprocessing.connection
    import ntpath
    import re
    import socket
    import threading
    import subprocess as subprocess_module
    import types
    import zipfile

    output_key = _key(output_root)
    qa_key = _key(QA_SITE)
    stdlib_paths = set()
    for key in ("stdlib", "platstdlib"):
        value = sysconfig.get_paths().get(key)
        if value:
            stdlib_paths.add(_key(value))
    denied_binary_paths = {
        _key(r"C:\anaconda3\python.exe"),
        _key(r"C:\anaconda3\python311.dll"),
        _key(r"D:\temp\iteration41-root-public-custody-v2.py"),
    }
    runtime_native_root = _key(Path(sys.base_prefix) / "DLLs")

    def under(path_key: str, parent_key: str) -> bool:
        try:
            return os.path.commonpath([path_key, parent_key]) == parent_key
        except ValueError:
            return False

    def deny(operation: str):
        def blocked(*_args, **_kwargs):
            guard_state[operation + "_attempts"] = int(guard_state.get(operation + "_attempts", 0)) + 1
            raise PermissionError("sourcefake operation denied")
        return blocked

    def audit(event, args):
        if event == "import" and args:
            name = args[0] if isinstance(args[0], str) else ""
            filename = args[1] if len(args) > 1 and isinstance(args[1], str) else ""
            filename_key = _key(filename) if filename else ""
            filename_suffix = Path(filename_key).suffix.lower() if filename_key else ""
            runtime_stdlib_extension = (
                filename_suffix == ".pyd" and bool(filename_key)
                and under(filename_key, runtime_native_root)
            )
            if any(name == prefix or name.startswith(prefix + ".") for prefix in (
                "backtrader", "backtrader_runtime", "bt_api", "bt_api_py", "zmq",
                "win32api", "win32con", "win32file", "win32event", "win32process",
                "winreg", "_winapi",
            )) or (filename_suffix in {".dll", ".exe"}
                   or (filename_suffix == ".pyd" and not runtime_stdlib_extension)):
                guard_state["audit_denials"] = int(guard_state.get("audit_denials", 0)) + 1
                raise ImportError("sourcefake import denied")
        if event == "open" and args:
            raw_path = args[0]
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            path_key = _key(raw_path) if isinstance(raw_path, (str, bytes, os.PathLike)) else ""
            suffix = Path(path_key).suffix.lower() if path_key else ""
            basename = Path(path_key).name.lower() if path_key else ""
            lowered = path_key.lower()
            private_name = basename in {".env", "config.yaml", "secrets.yaml"}
            private_name = private_name or any(part in lowered for part in (
                "\\private_capture\\", "\\private-capture\\", "\\private_captures\\",
                "\\private-captures\\", "\\captures\\",
            ))
            writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(
                flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            )
            if writing:
                if not path_key or not under(path_key, output_key):
                    guard_state["write_denials"] = int(guard_state.get("write_denials", 0)) + 1
                    raise PermissionError("sourcefake write denied")
            elif path_key:
                if private_name:
                    guard_state["private_read_attempts"] = int(guard_state.get("private_read_attempts", 0)) + 1
                    raise PermissionError("private input denied")
                runtime_stdlib_extension = suffix == ".pyd" and under(path_key, runtime_native_root)
                if path_key in denied_binary_paths or suffix in {".exe", ".dll"} or (suffix == ".pyd" and not runtime_stdlib_extension):
                    guard_state["opaque_or_native_reads"] = int(guard_state.get("opaque_or_native_reads", 0)) + 1
                    raise PermissionError("opaque or native input denied")
                allowed = path_key in allowed_keys or under(path_key, output_key) or under(path_key, qa_key)
                allowed = allowed or any(under(path_key, root) for root in stdlib_paths)
                allowed = allowed or (suffix == ".pyd" and under(path_key, runtime_native_root))
                if not allowed:
                    guard_state["read_denials"] = int(guard_state.get("read_denials", 0)) + 1
                    raise PermissionError("sourcefake read denied")
        if event.startswith(("socket.", "subprocess.", "os.system", "os.spawn", "os.exec", "os.fork")):
            guard_state["audit_denials"] = int(guard_state.get("audit_denials", 0)) + 1
            raise PermissionError("sourcefake operation denied")
        if event in {"ctypes.dlopen", "ctypes.dlsym", "_ctypes.dlopen", "winreg.OpenKey"}:
            guard_state["audit_denials"] = int(guard_state.get("audit_denials", 0)) + 1
            raise PermissionError("sourcefake operation denied")

    sys.addaudithook(audit)
    guard_state["open_policy_installed"] = True
    guard_state["audit_deny_installed"] = True

    sys.meta_path.insert(0, _BlockImports())
    guard_state["sdk_and_archive_import_block_installed"] = True
    guard_state["winapi_import_deny_installed"] = True
    zip_type = zipfile.ZipFile
    for attribute in ("__init__", "open", "extract", "extractall", "read", "write", "writestr"):
        if hasattr(zip_type, attribute):
            setattr(zip_type, attribute, deny("archive_read"))
    zipfile.ZipFile = deny("archive_read")
    guard_state["archive_extraction_deny_installed"] = True

    for attribute in ("WinDLL", "OleDLL", "CDLL", "PyDLL"):
        if hasattr(ctypes, attribute):
            setattr(ctypes, attribute, deny("native_load"))
    class _DenyNativeProxy:
        def __getattr__(self, _name):
            guard_state["native_load_attempts"] = int(guard_state.get("native_load_attempts", 0)) + 1
            raise PermissionError("native load denied")

        def __call__(self, *_args, **_kwargs):
            guard_state["native_load_attempts"] = int(guard_state.get("native_load_attempts", 0)) + 1
            raise PermissionError("native load denied")

    for attribute in ("windll", "oledll", "cdll", "pydll"):
        setattr(ctypes, attribute, _DenyNativeProxy())
    ctypes.util.find_library = deny("native_load")
    guard_state["ctypes_native_deny_installed"] = True

    for attribute in ("socket", "socketpair", "create_connection", "create_server", "getaddrinfo", "fromfd"):
        if hasattr(socket, attribute):
            setattr(socket, attribute, deny("network"))
    guard_state["network_deny_installed"] = True

    for attribute in ("Popen", "run", "call", "check_call", "check_output"):
        if hasattr(subprocess_module, attribute):
            setattr(subprocess_module, attribute, deny("subprocess"))
    for attribute in ("system", "popen", "startfile"):
        if hasattr(os, attribute):
            setattr(os, attribute, deny("os_process"))
    for attribute in dir(os):
        if attribute.startswith(("spawn", "exec")):
            try:
                setattr(os, attribute, deny("os_process"))
            except (AttributeError, TypeError):
                pass
    multiprocessing.Process.start = deny("multiprocessing")
    multiprocessing.Pipe = deny("multiprocessing")
    multiprocessing.connection.wait = deny("multiprocessing")
    winapi = sys.modules.get("_winapi")
    if winapi is not None:
        for attribute in dir(winapi):
            if not attribute.startswith("__") and callable(getattr(winapi, attribute, None)):
                try:
                    setattr(winapi, attribute, deny("winapi"))
                except (AttributeError, TypeError):
                    pass
        guard_state["winapi_callable_deny_installed"] = True
    else:
        guard_state["winapi_callable_deny_installed"] = False
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory = deny("native_load")
    guard_state["process_and_pipe_deny_installed"] = True
    guard_state["hard_denials_installed"] = True


def _run_sourcefake(pins: dict[str, str], pin_rows: dict[str, object], meta: dict[str, object], pre_git: dict[str, object]) -> dict[str, object]:
    if not QA_SITE.is_dir() or not QA_PYTHON.is_file():
        _fail("designated_qa_runtime_missing")
    _check_components(QA_SITE)
    preloaded_stdlib = _preload_source_stdlib(pins)

    output_root = _ensure_output_root()
    run_dir = output_root / ("run-" + uuid.uuid4().hex)
    run_dir.mkdir(parents=True, exist_ok=False)
    _check_components(run_dir)
    temp_dir = run_dir / "temp"
    temp_dir.mkdir(parents=False, exist_ok=False)
    _check_components(temp_dir)
    environment = _install_allowlisted_environment(temp_dir)
    config_path = run_dir / "pytest.ini"
    log_path = run_dir / "pytest.log"
    config_path.write_text("[pytest]\n", encoding="utf-8")

    # Pytest is imported before the sourcefake target, with plugin autoload
    # disabled.  The limited runtime preload comes first, while native loading
    # is still denied by an inert ctypes.windll facade.  Hard denials are then
    # installed before pytest collects the candidate file.
    sys.path.insert(0, str(QA_SITE))
    guard_runtime_preload, fake_api_counter = _preload_guard_runtime()
    try:
        pytest = importlib.import_module("pytest")
    except Exception:
        _fail("pytest_import_failed")
    pytest_origin = Path(pytest.__file__).resolve()
    if not _key(pytest_origin).startswith(_key(QA_SITE)):
        _fail("pytest_origin_mismatch")
    if any(name == "tests" or name.startswith("tests.") for name in sys.modules):
        _fail("test_package_preloaded_before_guard")

    test_rel = next(key for key in DIRECT_PINS if key.startswith("tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4"))
    test_path = _relative_path(test_rel)
    allowed_keys = {_key(_relative_path(relative)) for relative in pins}
    allowed_keys.add(_key(Path(__file__)))
    allowed_keys.update({
        _key(ROOT / ".git" / "HEAD"),
        _key(ROOT / ".git" / "index"),
        _key(ROOT / ".git" / "refs" / "heads" / "dev"),
        _key(ROOT / ".git" / "packed-refs"),
    })
    guard_state: dict[str, object] = {
        "open_policy_installed": False,
        "audit_deny_installed": False,
        "sdk_and_archive_import_block_installed": False,
        "archive_extraction_deny_installed": False,
        "ctypes_native_deny_installed": False,
        "network_deny_installed": False,
        "process_and_pipe_deny_installed": False,
        "winapi_import_deny_installed": False,
        "winapi_callable_deny_installed": False,
        "hard_denials_installed": False,
        "pinned_source_loader_installed": False,
        "pinned_source_loader_reads": 0,
        "private_read_attempts": 0,
        "opaque_or_native_reads": 0,
        "read_denials": 0,
        "write_denials": 0,
        "audit_denials": 0,
        "native_load_attempts": 0,
        "network_attempts": 0,
        "subprocess_attempts": 0,
        "os_process_attempts": 0,
        "multiprocessing_attempts": 0,
        "winapi_attempts": 0,
        "archive_read_attempts": 0,
    }
    _deny_guard(guard_state, allowed_keys, output_root)
    guard_state["guard_runtime_preload"] = guard_runtime_preload
    guard_state["candidate_import_boundary_ready"] = bool(
        guard_runtime_preload.get("status") == "complete"
        and guard_state.get("hard_denials_installed")
        and not guard_state.get("pinned_source_loader_installed")
    )
    _install_pinned_source_loader(pins, guard_state)
    guard_state["candidate_import_boundary_ready"] = bool(
        guard_state.get("candidate_import_boundary_ready")
        and guard_state.get("hard_denials_installed")
        and guard_state.get("pinned_source_loader_installed")
    )
    sys.path.insert(0, str(ROOT))
    guard_state["candidate_import_path_added_after_guards"] = bool(
        guard_state.get("candidate_import_boundary_ready")
    )

    gate = _CollectionGate(test_path, pins)
    stdout_capture = _BoundedText()
    stderr_capture = _BoundedText()
    original_stdout, original_stderr = sys.stdout, sys.stderr
    start = time.monotonic()
    sys.stdout, sys.stderr = stdout_capture, stderr_capture
    runner_exception = None
    result = 2
    try:
        result = pytest.main(
            [
                "--noconftest",
                "--collect-in-virtualenv",
                "-c", str(config_path),
                "--capture=sys",
                "--import-mode=importlib",
                "--assert=plain",
                "--basetemp", str(run_dir / "basetemp"),
                "-o", "log_file=" + str(log_path),
                "-p", "no:asyncio",
                "-p", "no:cacheprovider",
                "-q", "--tb=short", "-ra", "--maxfail=1",
                str(test_path),
            ],
            plugins=[gate],
        )
    except BaseException as exc:
        result = 2
        guard_state["runner_exception"] = "sourcefake_runner_exception"
        runner_exception = _finite_runner_exception(exc, pins, output_root)
    finally:
        sys.stdout, sys.stderr = original_stdout, original_stderr
    elapsed = round(time.monotonic() - start, 3)
    repo_origin_check = _check_loaded_repo_origins(pins)

    guard_scope = {
        "runtime_preload_completed_before_hard_denials": (
            guard_runtime_preload.get("status") == "complete"
        ),
        "runtime_preload_phase": guard_runtime_preload.get("phase"),
        "candidate_import_boundary_ready_before_collection": bool(
            guard_state.get("candidate_import_boundary_ready")
        ),
        "candidate_import_path_added_after_guards": bool(
            guard_state.get("candidate_import_path_added_after_guards")
        ),
        "hard_denials_installed": bool(guard_state.get("hard_denials_installed")),
        "pinned_source_loader_installed": bool(guard_state.get("pinned_source_loader_installed")),
        "collection_observed": gate.collected > 0,
        "candidate_source_loader_reads": int(guard_state.get("pinned_source_loader_reads", 0)),
        "protected_categories": [
            "private_inputs", "opaque_or_native_files", "network", "subprocess",
            "process_and_pipe", "WinAPI", "SDK_imports", "archive_reads", "writes_outside_output",
        ],
        "scope": "candidate collection starts only after the hard guard and pinned loader are installed",
    }

    diagnostic_path = run_dir / "runner-diagnostic.json"
    diagnostic = {
        "schema": "iteration41.optional16.r4.guarded-sourcefake-runner-diagnostic.r2",
        "pytest_result": int(result),
        "runner_exception": runner_exception,
        "collected_tests": int(gate.collected),
        "passed_call_reports": int(gate.pass_calls),
        "failure_reports": int(gate.failures),
        "skipped_reports": int(gate.skips),
        "pinned_source_loader_reads": int(guard_state.get("pinned_source_loader_reads", 0)),
        "preload_phase": guard_runtime_preload.get("phase"),
        "guard_scope": guard_scope,
        "stdout_chars_captured": len(stdout_capture.getvalue()),
        "stderr_chars_captured": len(stderr_capture.getvalue()),
        "stdout_truncated": stdout_capture.truncated,
        "stderr_truncated": stderr_capture.truncated,
        "exception_args_emitted": False,
        "traceback_text_emitted": False,
        "source_paths_emitted": False,
        "fake_preload_api_calls": dict(fake_api_counter),
    }
    _write_json(diagnostic_path, diagnostic)

    failure = bool(
        result != 0 or gate.count_mismatch or gate.origin_mismatch or gate.regression_missing
        or gate.collected != EXPECTED_TESTS or gate.pass_calls != EXPECTED_TESTS
        or gate.failures or gate.skips
        or gate.support_origin_mismatch
        or not guard_scope["runtime_preload_completed_before_hard_denials"]
        or not guard_scope["candidate_import_boundary_ready_before_collection"]
        or not guard_scope["candidate_import_path_added_after_guards"]
        or guard_runtime_preload.get("candidate_source_imported")
        or int(guard_state.get("pinned_source_loader_reads", 0)) < 1
        or not guard_state.get("pinned_source_loader_installed")
        or repo_origin_check["mismatch_count"]
        or any(int(guard_state.get(key, 0)) for key in (
            "private_read_attempts", "read_denials", "write_denials", "audit_denials", "opaque_or_native_reads",
            "native_load_attempts", "network_attempts", "subprocess_attempts",
            "os_process_attempts", "multiprocessing_attempts", "winapi_attempts", "archive_read_attempts",
        ))
    )

    try:
        post_pins = _collect_pins()
        if post_pins[0] != pins or post_pins[1] != pin_rows:
            failure = True
            guard_state["post_pin_check"] = "mismatch"
        else:
            guard_state["post_pin_check"] = "matched"
    except GateFailure as exc:
        failure = True
        guard_state["post_pin_check"] = exc.code
        post_pins = ({}, {})
    try:
        post_git = _git_snapshot_after_guard(pre_git)
        if post_git != pre_git:
            failure = True
            guard_state["post_git_check"] = "mismatch"
        else:
            guard_state["post_git_check"] = "matched"
    except GateFailure as exc:
        failure = True
        guard_state["post_git_check"] = exc.code
        post_git = {"branch": "UNOBSERVED", "head": "UNOBSERVED", "staged_diff_empty": False}

    guard_runtime_preload["fake_preload_api_calls_after_collection"] = dict(fake_api_counter)
    return {
        "status": "HOLD_SOURCEFAKE_QA" if failure else "SOURCEFAKE_QA_PASSED",
        "pytest_invoked": True,
        "pytest_exit_code": int(result),
        "expected_tests": EXPECTED_TESTS,
        "collected_tests": gate.collected,
        "passed_call_reports": gate.pass_calls,
        "failure_reports": gate.failures,
        "skipped_reports": gate.skips,
        "other_reports": gate.other_reports,
        "collection_origin_mismatch": gate.origin_mismatch,
        "support_package_origin_mismatch": gate.support_origin_mismatch,
        "collection_count_mismatch": gate.count_mismatch,
        "original_root_audit_regression_missing": gate.regression_missing,
        "test_names": gate.names,
        "test_origin": str(test_path),
        "pytest_origin": str(pytest_origin),
        "pytest_config": str(config_path),
        "pytest_log": str(log_path),
        "preloaded_stdlib": preloaded_stdlib,
        "guard_runtime_preload": guard_runtime_preload,
        "process_environment_allowlist": environment,
        "runner_diagnostic_path": str(diagnostic_path),
        "runner_diagnostic": diagnostic,
        "guard_scope": guard_scope,
        "loaded_repo_module_origin_check": repo_origin_check,
        "pinned_source_loader_read_count": int(guard_state.get("pinned_source_loader_reads", 0)),
        "elapsed_seconds": elapsed,
        "guard_observation": guard_state,
        "stdout": stdout_capture.getvalue(),
        "stderr": stderr_capture.getvalue(),
        "stdout_truncated": stdout_capture.truncated,
        "stderr_truncated": stderr_capture.truncated,
        "post_pins": post_pins[1],
        "post_git": post_git,
        "actual_root_call": False,
        "private_inputs_read": False,
        "historical_run_assignment_identity_proven": False,
        "external_software_payload_read": False,
        "provider_network_native_or_winapi_call": False,
        "forbidden_attempts_observed": {
            key: int(guard_state.get(key, 0)) for key in (
                "private_read_attempts", "opaque_or_native_reads", "read_denials",
                "write_denials", "audit_denials", "native_load_attempts",
                "network_attempts", "subprocess_attempts", "os_process_attempts",
                "multiprocessing_attempts", "winapi_attempts",
            )
        },
        "scope": "SOURCE_FAKE_ONLY; fixture uses synthetic retained Root scopes and fake file/API leaves",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight-only", action="store_true")
    mode.add_argument("--run-sourcefake", action="store_true")
    parser.add_argument("--self-sha256", required=True)
    args = parser.parse_args()

    run_id = uuid.uuid4().hex
    receipt_path = ROOT / OUT_REL / ("blocked-" + run_id + ".json")
    try:
        _ensure_output_root()
        self_sha = _verify_self(args.self_sha256)
        result_name = "preflight" if args.preflight_only else "sourcefake"
        receipt_path = ROOT / OUT_REL / (result_name + "-" + self_sha[:12] + "-" + run_id + ".json")
        _check_runtime()
        process_environment = _install_allowlisted_environment(ROOT / OUT_REL)
        pre_git = _git_snapshot()
        pins, pin_rows, meta = _collect_pins()
        receipt = {
            "schema": "iteration41.optional16.r4.guarded-sourcefake-qa.r2",
            "harness_sha256": self_sha,
            "harness_origin": str(ROOT / SCRIPT_REL),
            "mode": "PREFLIGHT_ONLY" if args.preflight_only else "SOURCEFAKE_QA",
            "status": "PREFLIGHT_ONLY" if args.preflight_only else "RUNNING_SOURCEFAKE",
            "pre_git": pre_git,
            "pins": pin_rows,
            "input_count": len(pins),
            "metadata": meta,
            "actual_root_call": False,
            "private_inputs_read": False,
            "external_software_payload_read": False,
            "provider_network_native_or_winapi_call": False,
            "sourcefake_not_actual_or_formal_acceptance": True,
            "process_environment_allowlist": process_environment,
        }
        if args.preflight_only:
            post_git = _git_snapshot()
            receipt["post_git"] = post_git
            receipt["post_pins"] = _collect_pins()[1]
            receipt["harness_post_sha256"] = _script_sha()
            receipt["pytest_invoked"] = False
            if post_git != pre_git or receipt["post_pins"] != pin_rows or receipt["harness_post_sha256"] != self_sha:
                _fail("preflight_postcheck_mismatch")
        else:
            qa = _run_sourcefake(pins, pin_rows, meta, pre_git)
            qa["harness_post_sha256"] = _script_sha()
            if qa["harness_post_sha256"] != self_sha:
                qa["status"] = "HOLD_SOURCEFAKE_QA"
                qa["guard_observation"]["harness_post_pin_check"] = "mismatch"
            receipt.update(qa)
            receipt["status"] = qa["status"]
        _write_json(receipt_path, receipt)
        print(json.dumps({"status": receipt["status"], "receipt": str(receipt_path), "harness_sha256": self_sha}, sort_keys=True))
        return 0 if receipt["status"] in {"PREFLIGHT_ONLY", "SOURCEFAKE_QA_PASSED"} else 2
    except GateFailure as exc:
        # Finite status only; never print arbitrary exception text.
        try:
            _write_json(receipt_path, {
                "schema": "iteration41.optional16.r4.guarded-sourcefake-qa.r2",
                "status": "BLOCKED",
                "reason_code": exc.code,
                "actual_root_call": False,
                "private_inputs_read": False,
                "external_software_payload_read": False,
                "provider_network_native_or_winapi_call": False,
            })
        except BaseException:
            pass
        print(json.dumps({"status": "BLOCKED", "reason_code": exc.code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
