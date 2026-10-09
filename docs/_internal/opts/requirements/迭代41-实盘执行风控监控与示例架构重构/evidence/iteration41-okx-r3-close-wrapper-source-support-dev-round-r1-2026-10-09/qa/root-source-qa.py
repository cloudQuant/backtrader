"""Root-only guarded source-fake QA for the additive OKX R3 close wrapper.

The parent binds the current dev checkout and launches one isolated child.
The child directly calls exactly three pinned fake-test functions. This file
does not invoke the retained host or any account/provider/native operation.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import sysconfig
import tempfile
import types


ROOT = Path("D:/source_code/backtrader")
CONFIG_REL = ".codex-tmp/okx_r3_close_wrapper_support_root_qa_r1_20261009.json"
CONFIG_PIN = (3264, "cb7b7ca2c359a0c02a01eebc5af4b469ee090fc6fe24cbddddf173cc100d4f73")
MANIFEST_REL = ".codex-tmp/okx_full_close_r2_public_dependency_manifest_r1_20261009.json"
MANIFEST_PIN = (11176, "38afededf245978ae0617298c79d98eaf1434c3a6e2cb2acd23b4140f6d9146c")
CLASSIFICATION_REL = ".codex-tmp/okx_full_close_r2_public_dependency_head_classification_r1_20261009.json"
CLASSIFICATION_PIN = (19324, "85d89673562f08150a987f0f15bf3437a3940746ff353d41325a686a0e4d1bd0")
TEST_REL = "tests/unit/scripts/test_iteration41_okx_m01_r3_normal_cu_close_root_actual_r2_source_fake.py"
CALLER_REL = ".codex-tmp/okx_m01_protected_rebind_r3_root_actual_candidate_20261009.py"
HELPER_REL = ".codex-tmp/okx_m01_r3_normal_cu_close_helper_r2_20261009.py"
WRAPPER_REL = ".codex-tmp/okx_m01_r3_normal_cu_close_root_actual_r2_20261009.py"
TEST_PIN = (13856, "386bff884a77a425b90f6cd7c040e565e69392e4c46db57865a0ac76070d2931")
CALLER_PIN = (55093, "f80890de30021dc9751a439a247c0549afca7303fb13f8f8bb27019e6c193fd6")
HELPER_PIN = (19399, "01a51406d2b54abb116b70e93111e741beaa8f3ada54f15e3b5c67c684c59072")
WRAPPER_PIN = (36419, "e314606fce79a5c536749c16d8cc2b446a5fc01db72cea9a154b4a08d8058d3e")
EXPECTED_INPUT_COUNT = 36
EXPECTED_ORIGINAL_PUBLIC_COUNT = 33
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_INDEX_BYTES = 64 * 1024 * 1024
OUTPUT_ROOT = Path("D:/temp/okx_r3_close_wrapper_support_root_qa_r1_20261009")
RESULT_PATH = OUTPUT_ROOT / "result.json"
BASETEMP_PATH = OUTPUT_ROOT / "basetemp"
CHILD_FLAG = "--internal-source-fake-child"

CASE_SPECS = (
    (
        "test_root_wrapper_closes_only_the_original_scope_once_and_preserves_result",
        None,
    ),
    (
        "test_root_wrapper_blocks_tampered_original_caller_before_close",
        "filename",
    ),
    (
        "test_root_wrapper_blocks_tampered_original_caller_before_close",
        "nested_constant",
    ),
)


def _norm(path: object) -> str:
    return os.path.normcase(os.path.abspath(os.fsdecode(os.fspath(path))))


def _within(path: str, parent: str) -> bool:
    try:
        return os.path.commonpath((path, parent)) == parent
    except (OSError, ValueError):
        return False


def _bounded_read(path: Path, size: int, digest: str, limit: int = MAX_INPUT_BYTES) -> bytes:
    if type(size) is not int or size < 0 or size > limit:
        raise RuntimeError("public_size_limit")
    before = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & reparse:
        raise RuntimeError("public_file_type")
    if before.st_size != size:
        raise RuntimeError("public_size_mismatch")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(path), flags)
    try:
        after = os.fstat(descriptor)
        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_size != size
            or (getattr(before, "st_ino", 0) and after.st_ino != before.st_ino)
            or (getattr(before, "st_dev", 0) and after.st_dev != before.st_dev)
        ):
            raise RuntimeError("public_file_changed")
        chunks: list[bytes] = []
        remaining = size + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise RuntimeError("public_pin_mismatch")
    return raw


def _manifest_rows(raw: bytes) -> dict[str, tuple[int, str, str]]:
    document = json.loads(raw.decode("utf-8", errors="strict"))
    if document.get("schema") != "iteration41.okx.r3_normal_close_r2.public_dependency_manifest.v1":
        raise RuntimeError("manifest_schema")
    rows = document.get("source_artifact_pins")
    if type(rows) is not list or len(rows) != EXPECTED_INPUT_COUNT:
        raise RuntimeError("manifest_count")
    result: dict[str, tuple[int, str, str]] = {}
    for row in rows:
        if type(row) is not dict:
            raise RuntimeError("manifest_row")
        relative, size, digest, kind = row.get("path"), row.get("size"), row.get("sha256"), row.get("kind")
        candidate = Path(relative) if type(relative) is str else Path(".")
        if (
            type(relative) is not str
            or candidate.is_absolute()
            or ".." in candidate.parts
            or type(size) is not int
            or size < 0
            or size > MAX_INPUT_BYTES
            or type(digest) is not str
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or type(kind) is not str
            or relative in result
        ):
            raise RuntimeError("manifest_row_shape")
        result[relative] = (size, digest, kind)
    special = {
        HELPER_REL: (*HELPER_PIN, "accepted-r2-helper"),
        WRAPPER_REL: (*WRAPPER_PIN, "new-root-wrapper"),
        TEST_REL: (*TEST_PIN, "new-focused-test"),
        CALLER_REL: (*CALLER_PIN, "original-public-input"),
    }
    if any(result.get(name) != pin for name, pin in special.items()):
        raise RuntimeError("fixed_dependency_pin")
    if sum(kind == "original-public-input" for _, _, kind in result.values()) != EXPECTED_ORIGINAL_PUBLIC_COUNT:
        raise RuntimeError("original_input_count")
    return result


def _preload_child_runtime() -> tuple[object, list[str]]:
    modules = (
        "ast",
        "asyncio",
        "contextlib",
        "ctypes",
        "hashlib",
        "http.client",
        "importlib",
        "inspect",
        "io",
        "json",
        "logging",
        "multiprocessing",
        "multiprocessing.connection",
        "multiprocessing.popen_spawn_win32",
        "os",
        "pathlib",
        "pytest",
        "selectors",
        "shutil",
        "socket",
        "ssl",
        "stat",
        "subprocess",
        "sys",
        "tempfile",
        "threading",
        "types",
        "unittest.mock",
        "urllib.request",
        "warnings",
        "_winapi",
        "colorama",
        "colorama.ansitowin32",
        "colorama.win32",
    )
    missing_optional: list[str] = []
    for name in modules:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            if name.startswith("colorama"):
                missing_optional.append(name)
            else:
                raise
    return sys.modules["pytest"], missing_optional


def _fixed_case_calls(test_module: types.ModuleType, public_paths: dict[str, Path]) -> dict[str, object]:
    import builtins
    import contextlib
    import io
    import warnings

    pytest = sys.modules["pytest"]
    expected_test_path = _norm(public_paths[TEST_REL])
    module_origin = _norm(test_module.__file__)
    spec_origin = _norm(test_module.__spec__.origin)
    function_origins_ok = all(
        _norm(getattr(test_module, name).__code__.co_filename) == expected_test_path
        for name in {function for function, _ in CASE_SPECS}
    )
    observed_files: set[str] = set()
    original_profile = sys.getprofile()

    def observe(frame, event, arg):
        if event == "call":
            filename = frame.f_code.co_filename
            try:
                observed_files.add(_norm(filename))
            except (TypeError, ValueError, OSError):
                pass
        if original_profile is not None:
            original_profile(frame, event, arg)

    cases: list[dict[str, object]] = []
    warning_count = 0
    error_count = 0
    output_bytes = 0
    sys.setprofile(observe)
    try:
        for index, (function_name, tamper) in enumerate(CASE_SPECS, start=1):
            test_function = getattr(test_module, function_name)
            patcher = pytest.MonkeyPatch()
            case_dir = Path(tempfile.mkdtemp(prefix=f"case-{index}-", dir=str(BASETEMP_PATH)))
            captured_out = io.StringIO()
            captured_err = io.StringIO()
            case_warnings: list[object] = []
            case_error: str | None = None
            try:
                with warnings.catch_warnings(record=True) as recorded:
                    warnings.simplefilter("error")
                    with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(captured_err):
                        if tamper is None:
                            test_function(case_dir, patcher)
                        else:
                            test_function(case_dir, patcher, tamper)
                    case_warnings = list(recorded)
            except BaseException as exc:
                case_error = type(exc).__name__
            finally:
                warning_count += len(case_warnings)
                error_count += int(case_error is not None)
                output_bytes += len(captured_out.getvalue().encode("utf-8", errors="replace"))
                output_bytes += len(captured_err.getvalue().encode("utf-8", errors="replace"))
                try:
                    patcher.undo()
                except BaseException as exc:
                    if case_error is None:
                        case_error = type(exc).__name__
                        error_count += 1
                import shutil

                shutil.rmtree(case_dir, ignore_errors=True)
            cases.append(
                {
                    "case_index": index,
                    "function": function_name,
                    "tamper": tamper,
                    "status": "passed" if case_error is None and not case_warnings else "failed",
                    "error_type": case_error,
                    "warning_count": len(case_warnings),
                }
            )
    finally:
        sys.setprofile(original_profile)

    expected_origins = {
        _norm(public_paths[TEST_REL]),
        _norm(public_paths[WRAPPER_REL]),
        _norm(public_paths[CALLER_REL]),
        _norm(public_paths[HELPER_REL]),
    }
    origins_verified = (
        module_origin == expected_test_path
        and spec_origin == expected_test_path
        and function_origins_ok
        and expected_origins.issubset(observed_files)
    )
    return {
        "cases": cases,
        "executed_cases": len(cases),
        "passed_cases": sum(case["status"] == "passed" for case in cases),
        "warning_count": warning_count,
        "error_count": error_count,
        "captured_output_bytes": output_bytes,
        "origin_verified": origins_verified,
        "observed_origin_count": len(observed_files),
    }


def _child_guard(public_paths: dict[str, Path]) -> tuple[list[dict[str, str]], list[str]]:
    import ctypes
    import multiprocessing
    import multiprocessing.connection
    import os
    import socket
    import ssl
    import subprocess
    import sys

    runtime_denials: list[dict[str, str]] = []
    selfcheck_denials: list[dict[str, str]] = []
    selfcheck_mode = False
    allowed_public = {_norm(path) for path in public_paths.values()}
    allowed_public.update(
        {
            _norm(ROOT / CONFIG_REL),
            _norm(ROOT / MANIFEST_REL),
            _norm(ROOT / CLASSIFICATION_REL),
            _norm(Path(__file__).resolve()),
        }
    )
    temp_root = _norm(BASETEMP_PATH)
    repo_root = _norm(ROOT)
    python_roots: set[str] = set()
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        candidate = sysconfig.get_path(key)
        if candidate:
            normalized = _norm(candidate)
            if not _within(normalized, repo_root):
                python_roots.add(normalized)
    for candidate in sys.path:
        if candidate:
            normalized = _norm(candidate)
            if not _within(normalized, repo_root) and os.path.isdir(normalized):
                python_roots.add(normalized)

    def deny(category: str) -> None:
        target = selfcheck_denials if selfcheck_mode else runtime_denials
        target.append({"category": category})
        raise PermissionError("source_fake_guard:" + category)

    def path_category(path: str) -> str:
        lower = path.lower()
        suffix = Path(lower).suffix
        if suffix in {".dll", ".exe", ".pyd", ".so", ".dylib"}:
            return "software_payload_read"
        if Path(lower).name in {".env", "config.yaml", "secrets.yaml"}:
            return "private_or_config_read"
        if not _within(path, repo_root):
            return "external_custody_source_read"
        return "unlisted_file_access"

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.spawn",
            "os.fork",
            "os.posix_spawn",
            "os.startfile",
            "os.kill",
            "os.add_dll_directory",
        }:
            deny("process_operation")
        if event.startswith("socket."):
            deny("network_operation")
        if event.startswith("ctypes."):
            deny("native_operation")
        if event == "import" and args:
            top = str(args[0]).split(".", 1)[0].lower()
            if top in {
                "_winapi",
                "winreg",
                "win32api",
                "win32con",
                "pywintypes",
                "multiprocessing",
                "socket",
                "ssl",
                "ctypes",
                "subprocess",
            }:
                deny("blocked_import")
            module_path = args[1] if len(args) > 1 else None
            if isinstance(module_path, (str, bytes, os.PathLike)):
                if Path(os.fsdecode(module_path)).suffix.lower() in {".pyd", ".dll", ".so", ".dylib"}:
                    deny("native_module_load")
        if event == "open" and args:
            raw_path = args[0]
            if not isinstance(raw_path, (str, bytes, os.PathLike)):
                deny("unbound_file_descriptor")
            normalized = _norm(raw_path)
            mode = args[1] if len(args) > 1 else None
            writing = False
            if isinstance(mode, str):
                writing = any(char in mode for char in "wax+")
            if len(args) > 2 and type(args[2]) is int:
                flags = args[2]
                writing = writing or bool(
                    flags
                    & (
                        os.O_WRONLY
                        | os.O_RDWR
                        | os.O_CREAT
                        | os.O_TRUNC
                        | os.O_APPEND
                    )
                )
            if writing and _within(normalized, temp_root):
                return
            if not writing and normalized in allowed_public:
                return
            if not writing and _within(normalized, temp_root):
                return
            if not writing and any(_within(normalized, base) for base in python_roots):
                if Path(normalized).suffix.lower() in {".py", ".pyc", ".pyw", ".zip"}:
                    return
            deny(path_category(normalized))
        if event in {"os.mkdir", "os.rmdir", "os.remove", "os.rename", "os.replace"} and args:
            targets = [args[0]]
            if event in {"os.rename", "os.replace"} and len(args) > 1:
                targets.append(args[1])
            for target in targets:
                if not isinstance(target, (str, bytes, os.PathLike)) or not _within(_norm(target), temp_root):
                    deny("repository_write")

    def blocked(category: str):
        def call(*args, **kwargs):
            deny(category)

        return call

    api_blocks: list[tuple[object, str, str]] = []
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        if hasattr(subprocess, name):
            api_blocks.append((subprocess, name, "process_operation"))
    for name in ("system", "popen", "startfile", "kill", "add_dll_directory"):
        if hasattr(os, name):
            api_blocks.append((os, name, "process_operation"))
    for name in tuple(dir(os)):
        if name.startswith(("spawn", "exec")) and callable(getattr(os, name, None)):
            api_blocks.append((os, name, "process_operation"))
    for name in ("create_connection", "socketpair", "getaddrinfo", "gethostbyname"):
        if hasattr(socket, name):
            api_blocks.append((socket, name, "network_operation"))
    api_blocks.append((socket, "socket", "network_operation"))
    for name in ("wrap_socket",):
        if hasattr(ssl, name):
            api_blocks.append((ssl, name, "network_operation"))
    for name in ("CDLL", "PyDLL", "WinDLL", "OleDLL"):
        if hasattr(ctypes, name):
            api_blocks.append((ctypes, name, "native_operation"))
    for name in ("Process",):
        if hasattr(multiprocessing, name):
            api_blocks.append((multiprocessing, name, "process_operation"))
    for name in ("Pipe", "Client", "Listener"):
        if hasattr(multiprocessing.connection, name):
            api_blocks.append((multiprocessing.connection, name, "process_operation"))
    originals: list[tuple[object, str, object]] = []
    for module, name, category in api_blocks:
        originals.append((module, name, getattr(module, name)))
        setattr(module, name, blocked(category))
    if hasattr(multiprocessing, "Process") and hasattr(multiprocessing.Process, "start"):
        originals.append((multiprocessing.Process, "start", multiprocessing.Process.start))
        multiprocessing.Process.start = blocked("process_operation")
    sys.addaudithook(audit)

    selfchecks: list[str] = []
    selfcheck_mode = True
    for label, operation in (
        ("process_api", lambda: subprocess.Popen(["guard-selfcheck-no-exec"])),
        ("network_api", lambda: socket.create_connection(("127.0.0.1", 1))),
        ("native_api", lambda: ctypes.CDLL("guard-selfcheck-no-load.dll")),
    ):
        try:
            operation()
        except PermissionError:
            selfchecks.append(label)
        except BaseException:
            pass
    for label, event, args in (
        ("process_audit", "subprocess.Popen", ("blocked",)),
        ("network_audit", "socket.connect", (None, ("127.0.0.1", 1))),
        ("native_audit", "ctypes.dlopen", ("blocked.dll",)),
        ("private_path", "open", (str(ROOT / ".env"), "r", None)),
        ("software_path", "open", ("D:/Program Files/Vendor/fixed.dll", "rb", None)),
        ("external_custody_path", "open", ("D:/temp/iteration41-root-public-custody-v2.py", "rb", None)),
    ):
        before = len(selfcheck_denials)
        try:
            sys.audit(event, *args)
        except PermissionError:
            if len(selfcheck_denials) == before + 1:
                selfchecks.append(label)
    selfcheck_mode = False
    if len(selfchecks) != 9:
        raise RuntimeError("guard_selfcheck_incomplete")
    return runtime_denials, selfchecks


def _child_main(expected_head: str, expected_parent: str) -> int:
    import contextlib
    import io
    import warnings

    prelude_out = io.StringIO()
    prelude_err = io.StringIO()
    with warnings.catch_warnings(record=True) as prelude_warnings:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(prelude_out), contextlib.redirect_stderr(prelude_err):
            _pytest, missing_optional = _preload_child_runtime()
    forbidden_modules = {
        "_okx_r3_close_wrapper_support_source_fake_test",
        "_okx_m01_r3_normal_cu_close_root_actual_r2_20261009",
        "_okx_m01_r3_normal_cu_close_helper_r2_root_20261009",
        "_okx_m01_r3_root_caller_prefix_fake",
        "_root_public_custody_v2",
        "_root_public_custody_private",
        "_root_public_custody_cli",
    }
    preguard_clear = not any(name in sys.modules for name in forbidden_modules)
    provider_roots = {"ccxt", "okx", "binance", "simnow", "vnpy", "pybit", "ib_insync"}
    provider_import_absent_pre = not any(
        name.split(".", 1)[0].lower() in provider_roots for name in sys.modules
    )
    config_raw = _bounded_read(ROOT / CONFIG_REL, *CONFIG_PIN)
    manifest_raw = _bounded_read(ROOT / MANIFEST_REL, *MANIFEST_PIN)
    classification_raw = _bounded_read(ROOT / CLASSIFICATION_REL, *CLASSIFICATION_PIN)
    config = json.loads(config_raw.decode("utf-8", errors="strict"))
    classification = json.loads(classification_raw.decode("utf-8", errors="strict"))
    rows = _manifest_rows(manifest_raw)
    public_paths = {relative: ROOT / Path(relative) for relative in rows}
    runtime_denials, selfchecks = _child_guard(public_paths)
    pre_pins_match = True
    for relative, (size, digest, _kind) in rows.items():
        try:
            _bounded_read(public_paths[relative], size, digest)
        except BaseException:
            pre_pins_match = False
            break
    test_raw = _bounded_read(public_paths[TEST_REL], *TEST_PIN)
    module_name = "_okx_r3_close_wrapper_support_source_fake_test"
    module = types.ModuleType(module_name)
    module.__file__ = str(public_paths[TEST_REL])
    module.__package__ = ""
    module.__cached__ = None
    module.__spec__ = importlib.machinery.ModuleSpec(module_name, loader=None, origin=module.__file__)
    sys.modules[module_name] = module
    exec(compile(test_raw, module.__file__, "exec", dont_inherit=True), module.__dict__)
    case_result = _fixed_case_calls(module, public_paths)
    post_pins_match = True
    for relative, (size, digest, _kind) in rows.items():
        try:
            _bounded_read(public_paths[relative], size, digest)
        except BaseException:
            post_pins_match = False
            break
    classification_rows = classification.get("classifications")
    configured_cases = config.get("fixed_cases")
    configured_case_pairs = (
        [(row.get("function"), row.get("tamper")) for row in configured_cases]
        if type(configured_cases) is list and all(type(row) is dict for row in configured_cases)
        else []
    )
    expected_case_pairs = [(function, tamper) for function, tamper in CASE_SPECS]
    classification_shape_ok = (
        classification.get("schema") == "iteration41.okx.r3_normal_close_r2.public_dependency_head_classification.v1"
        and classification.get("input_count") == EXPECTED_INPUT_COUNT
        and classification.get("all_worktree_pins_match") is True
        and classification.get("all_head_pins_match") is False
        and classification.get("all_stage0_index_pins_match") is True
        and classification.get("head") == config["public_dependency_head_classification"]["classification_head"]
        and type(classification_rows) is list
        and len(classification_rows) == EXPECTED_INPUT_COUNT
        and all(type(row) is dict for row in classification_rows)
        and sum(row.get("head_matches_expected_pin") is True for row in classification_rows) == 34
        and sum(row.get("head_state") == "absent" for row in classification_rows) == 2
        and sum(row.get("index_state") == "untracked-or-ignored" for row in classification_rows) == 2
        and configured_case_pairs == expected_case_pairs
    )
    provider_import_absent_post = not any(
        name.split(".", 1)[0].lower() in provider_roots for name in sys.modules
    )
    passed = (
        config.get("schema") == "iteration41.okx.r3_close_wrapper_support.root_qa_config.v1"
        and config.get("evidence_level") == "SOURCE_FAKE_ROOT_CLOSE_WRAPPER_ONLY"
        and expected_head != expected_parent
        and preguard_clear
        and pre_pins_match
        and post_pins_match
        and classification_shape_ok
        and case_result["executed_cases"] == 3
        and case_result["passed_cases"] == 3
        and case_result["warning_count"] == 0
        and case_result["error_count"] == 0
        and case_result["captured_output_bytes"] == 0
        and case_result["origin_verified"]
        and provider_import_absent_pre
        and provider_import_absent_post
        and not runtime_denials
        and len(selfchecks) >= 4
        and not missing_optional
        and not prelude_warnings
        and not prelude_out.getvalue()
        and not prelude_err.getvalue()
    )
    result = {
        "schema": "iteration41.okx.r3_close_wrapper_support.root_qa_child.v1",
        "status": "PASS_SOURCE_FAKE_ROOT_CLOSE_WRAPPER_ONLY" if passed else "HOLD",
        "evidence_level": "SOURCE_FAKE_ROOT_CLOSE_WRAPPER_ONLY",
        "executed_cases": case_result["executed_cases"],
        "passed_cases": case_result["passed_cases"],
        "test_exit_code": 0 if case_result["passed_cases"] == 3 else 1,
        "cases": case_result["cases"],
        "warnings": case_result["warning_count"] + len(prelude_warnings),
        "prelude_output_bytes": len(prelude_out.getvalue().encode("utf-8", errors="replace"))
        + len(prelude_err.getvalue().encode("utf-8", errors="replace")),
        "errors": case_result["error_count"],
        "denials": {
            category: sum(row["category"] == category for row in runtime_denials)
            for category in {row["category"] for row in runtime_denials}
        },
        "denial_count": len(runtime_denials),
        "guard_selfchecks": selfchecks,
        "guard_selfcheck_count": len(selfchecks),
        "origin_verified": case_result["origin_verified"],
        "provider_import_absent": provider_import_absent_pre and provider_import_absent_post,
        "observed_origin_count": case_result["observed_origin_count"],
        "candidate_modules_absent_before_guard": preguard_clear,
        "public_input_count": len(rows),
        "pre_pins_match": pre_pins_match,
        "post_pins_match": post_pins_match,
        "classification_shape_ok": classification_shape_ok,
        "pytest_main_called": False,
        "pytest_collection_claimed": False,
        "host_47595_status": "NOT_CHECKED_BY_SOURCE_QA",
        "actual_host_close_performed": False,
        "metadata_or_admission_call": False,
        "provider_call": False,
        "account_call": False,
        "candidate_process_operation": False,
        "network_operation": False,
        "native_operation": False,
    }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if passed else 2


def _git_bytes(*args: str, env: dict[str, str]) -> bytes:
    completed = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("git_read_failed")
    return completed.stdout


def _git_state(env: dict[str, str], rows: dict[str, tuple[int, str, str]]) -> dict[str, object]:
    head = _git_bytes("rev-parse", "HEAD", env=env).decode("ascii").strip()
    parent = _git_bytes("rev-parse", "HEAD^", env=env).decode("ascii").strip()
    branch = _git_bytes("branch", "--show-current", env=env).decode("utf-8", errors="strict").strip()
    status = _git_bytes("status", "--porcelain=v1", "-z", "--untracked-files=all", env=env)
    staged = _git_bytes("diff", "--cached", "--raw", "--no-renames", "-z", env=env)
    tracked_diff = _git_bytes(
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--binary",
        "--no-renames",
        "--no-color",
        env=env,
    )
    git_path = _git_bytes("rev-parse", "--git-path", "index", env=env).decode("utf-8", errors="strict").strip()
    index_path = Path(git_path)
    if not index_path.is_absolute():
        index_path = ROOT / index_path
    index_stat = index_path.stat()
    if not stat.S_ISREG(index_stat.st_mode) or index_stat.st_size > MAX_INDEX_BYTES:
        raise RuntimeError("git_index_shape")
    index_raw = _bounded_read(index_path, index_stat.st_size, _hash_file_bounded(index_path, index_stat.st_size), MAX_INDEX_BYTES)
    pins: dict[str, dict[str, object]] = {}
    for relative, (size, digest, kind) in rows.items():
        _bounded_read(ROOT / Path(relative), size, digest)
        pins[relative] = {"size": size, "sha256": digest, "kind": kind}
    return {
        "head": head,
        "parent": parent,
        "branch": branch,
        "status_size": len(status),
        "status_sha256": hashlib.sha256(status).hexdigest(),
        "staged_diff_size": len(staged),
        "staged_diff_sha256": hashlib.sha256(staged).hexdigest(),
        "tracked_diff_size": len(tracked_diff),
        "tracked_diff_sha256": hashlib.sha256(tracked_diff).hexdigest(),
        "index_size": len(index_raw),
        "index_sha256": hashlib.sha256(index_raw).hexdigest(),
        "inputs": pins,
        "input_count": len(pins),
    }


def _hash_file_bounded(path: Path, size: int) -> str:
    if size < 0 or size > MAX_INDEX_BYTES:
        raise RuntimeError("git_index_size")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size != size:
        raise RuntimeError("git_index_type")
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        after = os.fstat(descriptor)
        if not stat.S_ISREG(after.st_mode) or after.st_size != size:
            raise RuntimeError("git_index_changed")
        digest = hashlib.sha256()
        read_size = 0
        while read_size <= size:
            chunk = os.read(descriptor, min(1024 * 1024, size + 1 - read_size))
            if not chunk:
                break
            digest.update(chunk)
            read_size += len(chunk)
    finally:
        os.close(descriptor)
    if read_size != size:
        raise RuntimeError("git_index_read_size")
    return digest.hexdigest()


def _write_external_result(result: dict[str, object]) -> None:
    if not OUTPUT_ROOT.is_dir() or not BASETEMP_PATH.is_dir() or RESULT_PATH.exists():
        raise RuntimeError("external_output_state")
    raw = (json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with RESULT_PATH.open("xb") as stream:
        stream.write(raw)


def _parent_main(args: argparse.Namespace) -> int:
    if ROOT.resolve() != Path.cwd().resolve():
        raise RuntimeError("wrong_repository_root")
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_head) is None:
        raise RuntimeError("invalid_expected_head")
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_parent) is None:
        raise RuntimeError("invalid_expected_parent")
    if OUTPUT_ROOT.exists() or RESULT_PATH.exists() or BASETEMP_PATH.exists():
        raise RuntimeError("external_output_already_exists")
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    config_raw = _bounded_read(ROOT / CONFIG_REL, *CONFIG_PIN)
    config = json.loads(config_raw.decode("utf-8", errors="strict"))
    manifest_raw = _bounded_read(ROOT / MANIFEST_REL, *MANIFEST_PIN)
    rows = _manifest_rows(manifest_raw)
    classification_raw = _bounded_read(ROOT / CLASSIFICATION_REL, *CLASSIFICATION_PIN)
    if config.get("expected_branch") != "dev" or config.get("runner", {}).get("child_count") != 1:
        raise RuntimeError("qa_config_scope")
    before = _git_state(env, rows)
    if (
        before["head"] != args.expected_head
        or before["parent"] != args.expected_parent
        or before["branch"] != "dev"
    ):
        raise RuntimeError("git_precondition_mismatch")
    OUTPUT_ROOT.mkdir(parents=False, exist_ok=False)
    BASETEMP_PATH.mkdir(parents=False, exist_ok=False)
    child_command = [
        sys.executable,
        "-I",
        "-B",
        str(Path(__file__).resolve()),
        CHILD_FLAG,
        "--expected-head",
        args.expected_head,
        "--expected-parent",
        args.expected_parent,
    ]
    child_env = dict(env)
    child_env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    completed = subprocess.run(
        child_command,
        cwd=ROOT,
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
        shell=False,
    )
    child_stdout_sha = hashlib.sha256(completed.stdout).hexdigest()
    child_stderr_sha = hashlib.sha256(completed.stderr).hexdigest()
    child_result: dict[str, object] = {}
    try:
        child_result = json.loads(completed.stdout.decode("utf-8", errors="strict").splitlines()[-1])
    except BaseException:
        child_result = {"status": "HOLD", "parse_error": True}
    after = _git_state(env, rows)
    input_status_index_unchanged = before == after
    passed = (
        completed.returncode == 0
        and child_result.get("status") == "PASS_SOURCE_FAKE_ROOT_CLOSE_WRAPPER_ONLY"
        and child_result.get("executed_cases") == 3
        and child_result.get("passed_cases") == 3
        and child_result.get("warnings") == 0
        and child_result.get("errors") == 0
        and child_result.get("denials") == {}
        and child_result.get("denial_count") == 0
        and child_result.get("guard_selfcheck_count", 0) >= 4
        and child_result.get("origin_verified") is True
        and child_result.get("pre_pins_match") is True
        and child_result.get("post_pins_match") is True
        and child_result.get("provider_import_absent") is True
        and child_result.get("prelude_output_bytes") == 0
        and len(completed.stderr) == 0
        and input_status_index_unchanged
    )
    inputs_unchanged = before["inputs"] == after["inputs"] and child_result.get("pre_pins_match") is True and child_result.get("post_pins_match") is True
    result = {
        "schema": "iteration41.okx.r3_close_wrapper_support.root_qa_result.v1",
        "status": "PASS_SOURCE_FAKE_ROOT_CLOSE_WRAPPER_ONLY" if passed else "HOLD",
        "evidence_level": "SOURCE_FAKE_ROOT_CLOSE_WRAPPER_ONLY",
        "repository": str(ROOT),
        "branch": after["branch"],
        "parent": after["parent"],
        "current_head": after["head"],
        "expected_parent": args.expected_parent,
        "expected_head": args.expected_head,
        "python_exit": completed.returncode,
        "test_exit": child_result.get("test_exit_code"),
        "executed_cases": child_result.get("executed_cases", 0),
        "passed_cases": child_result.get("passed_cases", 0),
        "warnings": child_result.get("warnings", 0),
        "errors": child_result.get("errors", 0),
        "denials": child_result.get("denials", {}),
        "denial_count": child_result.get("denial_count", 0),
        "guard_selfchecks": child_result.get("guard_selfchecks", []),
        "guard_selfcheck_count": child_result.get("guard_selfcheck_count", 0),
        "origin_verified": child_result.get("origin_verified", False),
        "provider_import_absent": child_result.get("provider_import_absent", False),
        "input_pins": after["inputs"],
        "input_count": after["input_count"],
        "inputs_unchanged": inputs_unchanged,
        "input_status_and_index_unchanged": input_status_index_unchanged,
        "git_before": {key: value for key, value in before.items() if key != "inputs"},
        "git_after": {key: value for key, value in after.items() if key != "inputs"},
        "child_stdout_sha256": child_stdout_sha,
        "child_stdout_size": len(completed.stdout),
        "child_stderr_sha256": child_stderr_sha,
        "child_stderr_size": len(completed.stderr),
        "pytest_main_called": False,
        "pytest_collection_claimed": False,
        "actual_host_close_performed": False,
        "host_47595_status": "NOT_CHECKED_BY_SOURCE_QA",
        "metadata_or_admission_call": False,
        "provider_call": False,
        "account_call": False,
        "candidate_process_operation": False,
        "network_operation": False,
        "native_operation": False,
        "runner_error": None,
        "result_location": str(RESULT_PATH),
        "harness_sha256": _hash_file_bounded(Path(__file__), Path(__file__).stat().st_size),
        "harness_size": Path(__file__).stat().st_size,
        "config_sha256": hashlib.sha256(config_raw).hexdigest(),
        "config_size": len(config_raw),
        "classification_sha256": hashlib.sha256(classification_raw).hexdigest(),
        "classification_size": len(classification_raw),
    }
    _write_external_result(result)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if passed else 2


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument(CHILD_FLAG, action="store_true", dest="child")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-parent", required=True)
    args = parser.parse_args()
    if args.child:
        return _child_main(args.expected_head, args.expected_parent)
    return _parent_main(args)


if __name__ == "__main__":
    raise SystemExit(_main())
