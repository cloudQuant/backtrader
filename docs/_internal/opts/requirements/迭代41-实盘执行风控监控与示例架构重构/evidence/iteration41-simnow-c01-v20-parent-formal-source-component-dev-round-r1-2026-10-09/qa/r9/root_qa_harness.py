"""Guarded Root source-fake QA runner for the frozen SimNow C01 V20 packet.

The parent checks public pins and the live Git branch/index, then starts one
fresh fixed Python child with output redirected to files. The child installs
all file, network, native, process, and Pipe guards before pytest collection.
This harness never invokes the Root activation route.
"""

from __future__ import annotations

import builtins
import atexit
import ctypes
import hashlib
import http.client
import importlib
import io
import json
import multiprocessing
import multiprocessing.connection
import os
import pathlib
import re
import socket
import ssl
import subprocess
import sys
import sysconfig
import tempfile
import time
import types
import urllib.request


EXPECTED_PYTHON = (
    "D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe"
)
EXPECTED_INVENTORY_BYTES = 24731
EXPECTED_INVENTORY_SHA256 = (
    "7e816abf38830289ce6820bbce581c143ea02d1fed7d97a16c1a116f9491c6b1"
)
PACKET_REL = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-parent-formal-composition-r7-2026-10-09"
)
OUTPUT_REL = ".codex-tmp/iteration41-simnow-c01-v20-parent-formal-root-qa-r9"
EXPECTED_CANDIDATE_PINS = (
    11822,
    "dfc523215960b8d279b3ad68fc81a91b0fc196941fdbcf573b3a5f06009798af"
)
EXPECTED_ARTIFACT_PINS = (
    1014,
    "8cae29ebc204fecf43650844c67a78bb5ba5153f57c7cbe160d5218b05290b02"
)
EXPECTED_REVIEW = (
    "docs/_internal/opts/requirements/"
    "迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-parent-formal-composition-independent-review-r1-"
    "2026-10-09/README.md",
    4296,
    "97c770970de8102e5cc7a2b4e0799387913771afd3dd2e3fd5528309b48f78d8",
)
EXPECTED_TESTS = (
    "tests/unit/runtime/test_certification_simnow_c01_root_v17_ownership_source_fake.py",
    "tests/unit/runtime/test_certification_simnow_c01_native_td_read_v20_source_fake.py",
    "tests/unit/runtime/test_iteration41_simnow_c01_v20_root_actual_driver_r1_source_fake.py",
    "tests/unit/runtime/test_certification_simnow_c01_root_formal_adjudicator_v1_source_fake.py",
    "tests/unit/runtime/test_c01_root_completion_v1_source_fake.py",
    "tests/unit/runtime/test_certification_simnow_c01_rootseal_custody_v1_source_fake.py",
    "tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py",
    "tests/unit/runtime/test_certification_simnow_c01_interpreter_binding_v1.py",
)
METADATA_ONLY_EXCLUDED_RUNTIME_PATHS = (
    "backtrader_runtime/__init__.py",
    "backtrader_runtime/config.py",
    "backtrader_runtime/errors.py",
    "backtrader_runtime/policy.py",
    "backtrader_runtime/managed_execution.py",
    "backtrader_runtime/inventory.py",
    "backtrader_runtime/registry.py",
    "backtrader_runtime/provider_preflight.py",
    "backtrader_runtime/test_execution_profile.py",
    "backtrader_runtime/review_evidence.py",
    "backtrader_runtime/framework_projection.py",
    "backtrader_runtime/provider_deployment.py",
    "backtrader_runtime/ctp_simnow_operator.py",
)
SELECTED_RUNTIME_MODULE_ALIASES = (
    "backtrader_runtime._c01_native_td_read_v7_owner",
)
TEST_FIXTURE_RUNTIME_SOURCE_PATHS = (
    "backtrader_runtime/unpinned_extra_source_fake.py",
)
EXPECTED_TEST_COUNT = 118
SOURCE_QA_TIMEOUT_SECONDS = 360
MAX_CHILD_LOG_BYTES = 1_048_576
EXPECTED_PYTEST_CONFIG_BYTES = b"[pytest]\n"
EXPECTED_PYTEST_CONFIG_SHA256 = hashlib.sha256(
    EXPECTED_PYTEST_CONFIG_BYTES
).hexdigest()
PERSISTENT_CANONICAL_RUNTIME_MODULES = {
    "backtrader_runtime.certification_simnow_c01_interpreter_binding_v1": (
        "backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py"
    ),
    "backtrader_runtime.certification_simnow_c01_native_v4": (
        "backtrader_runtime/certification_simnow_c01_native_v4.py"
    ),
    "backtrader_runtime.certification_simnow_c01_v3_protocol": (
        "backtrader_runtime/certification_simnow_c01_v3_protocol.py"
    ),
}
EPHEMERAL_RUNTIME_MODULE_NAMES = (
    "backtrader_runtime.unpinned_extra_source_fake",
)
CHILD_ENV_KEYS = (
    "SYSTEMROOT",
    "WINDIR",
    "PATH",
    "TEMP",
    "TMP",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONNOUSERSITE",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
)
CHILD_ENV_EXCLUDED_KEYS = (
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTHONPATH",
    "PYTHONHOME",
    "all_other_inherited_variables_including_credentials",
)
EXPECTED_METADATA_PROBE_SCOPE_LIMIT = (
    "Fixed-suite source-fake guard only. Metadata-only stat, lstat, access, and "
    "readlink operations are outside this guard boundary; this is not a "
    "generalized filesystem security boundary."
)
EXPECTED_PYTEST_ARGUMENT_POLICY = (
    "--noconftest",
    "--collect-in-virtualenv",
    "-c <fresh external QA artifact directory>/pytest.ini",
    "--assert=plain",
    "-p no:asyncio",
    "-p no:cacheprovider",
    "-o addopts=",
    "-o log_file=<fresh external QA artifact directory>/pytest.log",
    "-o log_file_level=CRITICAL",
    "-s",
    "--tb=short",
    "explicitly pinned eight test paths only",
)
EXPECTED_EXTERNAL_PYTEST_ARTIFACT_LAYOUT = {
    "artifact_root": "fresh_external_temp_parent",
    "pytest_config": "pytest.ini",
    "pytest_log": "pytest.log",
    "child_stdout_log": "pytest-child-stdout.txt",
    "child_stderr_log": "pytest-child-stderr.txt",
    "stdlib_temp_directory": "stdlib-temp",
    "stdlib_temp_directory_created_before_child": True,
    "temp_environment_directory": "stdlib-temp",
    "tempfile_default_directory": "stdlib-temp",
    "pytest_basetemp": "pytest-basetemp",
    "pytest_basetemp_initially_absent": True,
    "pytest_clears_only_nested_basetemp": True,
    "child_guard_read_write_scope": (
        "fresh_external_artifact_parent_and_its_two_temp_directories"
    ),
}
EXPECTED_CHILD_OUTPUT_WRITER_LIFECYCLE = {
    "close_is_idempotent": True,
    "flush_after_close": "no_op",
    "atexit_closes_both_writers": True,
}
EXPECTED_PARENT_CONSOLE_SUMMARY_POLICY = {
    "mode": "compact_status_counts_paths_only",
    "full_finite_result_file": "root-qa-result.json",
    "full_result_written_before_console_summary": True,
}
EXPECTED_DERIVED_PYTEST_CONFIG = {
    "inipath": "<fresh external QA artifact directory>/pytest.ini",
    "inicfg": {},
    "addopts": [],
    "python_files": ["test_*.py", "*_test.py"],
    "python_functions": ["test"],
    "python_classes": ["Test"],
    "usefixtures": [],
    "xfail_strict": False,
    "testpaths": [],
}
EXPECTED_REPORT_OUTCOME_CONTRACT = {
    "collected_items": 118,
    "passed_call_reports": 118,
    "passed_setup_reports": 118,
    "passed_teardown_reports": 118,
    "zero_failures_skips_xfails_xpasses_unexpected_reports_collection_errors": True,
    "zero_unexpected_collection_outcomes": True,
    "zero_warnings": True,
    "wasxfail_classification": (
        "skipped reports are xfail; passed or failed reports are xpass; all are rejected"
    ),
}
PRELOAD_MODULE_NAMES = (
    "traceback",
    "warnings",
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
    "pytest",
)
FAKED_CTYPES_ENTRIES = (
    "CDLL",
    "WinDLL",
    "OleDLL",
    "PyDLL",
    "cdll",
    "windll",
    "oledll",
)
EXPECTED_WINDOWS_PRELOAD_POLICY = {
    "phase": "before_colorama_pytest_candidate_imports_and_before_hard_denials",
    "modules": list(PRELOAD_MODULE_NAMES),
    "inert_facade": "false_result_facade_for_ctypes_console_library_access",
    "faked_ctypes_entries": list(FAKED_CTYPES_ENTRIES),
    "candidate_runtime_or_test_modules_absent_before_and_after": True,
    "preloaded_module_origins": "standard_library_or_source_qa_venv_site_packages_only",
    "hard_denials_installed_after_preload": True,
    "preload_warnings_must_be_zero": True,
}
PERMITTED_GUARD_COUNTER_DELTAS = ("test_fixture_source_compile",)
EXPECTED_GUARD_COUNTER_DELTA_POLICY = {
    "baseline_phase": "after_guard_selfchecks_before_pytest_main",
    "forbidden_operation_deltas_must_be_zero": True,
    "permitted_delta_counters": list(PERMITTED_GUARD_COUNTER_DELTAS),
    "all_other_guard_counters_remain_at_baseline": True,
}
EXPECTED_EPHEMERAL_ALIAS_DERIVATION = (
    "All selected backtrader_runtime source module names and declared import aliases "
    "except the three persistent canonical aliases and package namespace must be "
    "absent at collection capture and after the test suite."
)


class _InertWindowsConsoleApi:
    """False-result facade for pytest/Colorama startup; never calls native code."""

    def __init__(self, counters: dict[str, int]) -> None:
        object.__setattr__(self, "_counters", counters)

    def __getattr__(self, _name: str):
        return self

    def __setattr__(self, name: str, _value: object) -> None:
        if name == "_counters":
            object.__setattr__(self, name, _value)
        else:
            self._counters["fake_api_configurations"] += 1

    def __call__(self, *_args: object, **_kwargs: object) -> int:
        self._counters["fake_api_calls"] += 1
        return 0

    def __bool__(self) -> bool:
        return False


def _preload_guard_runtime() -> tuple[dict[str, object], dict[str, int]]:
    sensitive_preloaded = [
        name
        for name in tuple(sys.modules)
        if name in {"asyncio", "unittest.mock", "pytest"}
        or name.startswith(("asyncio.", "unittest.mock.", "pytest", "_pytest", "colorama"))
    ]
    if sensitive_preloaded:
        raise RuntimeError("windows_guard_runtime_preloaded_before_facade")
    candidates_preloaded = [
        name
        for name in tuple(sys.modules)
        if name == "tests"
        or name.startswith("tests.")
        or name == "backtrader_runtime"
        or name.startswith("backtrader_runtime.")
    ]
    if candidates_preloaded:
        raise RuntimeError("candidate_module_preloaded_before_windows_facade")

    counters = {
        "fake_api_calls": 0,
        "fake_library_requests": 0,
        "fake_api_configurations": 0,
    }
    facade = _InertWindowsConsoleApi(counters)

    def fake_windows_library(*_args: object, **_kwargs: object):
        counters["fake_library_requests"] += 1
        return facade

    # pytest calls Colorama's Windows console workaround even when capture is
    # disabled. Keep every ctypes loader inert until the hard deny is installed.
    for name in ("CDLL", "WinDLL", "OleDLL", "PyDLL"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, fake_windows_library)
    for name in ("cdll", "windll", "oledll"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, facade)

    class _CandidateImportBlocker(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if (
                fullname == "tests"
                or fullname.startswith("tests.")
                or fullname == "backtrader_runtime"
                or fullname.startswith("backtrader_runtime.")
            ):
                raise RuntimeError("candidate_import_denied_during_guard_preload")
            return None

    warnings_module = importlib.import_module("warnings")
    blocker = _CandidateImportBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        with warnings_module.catch_warnings(record=True) as preload_warnings:
            warnings_module.simplefilter("always")
            for name in PRELOAD_MODULE_NAMES:
                importlib.import_module(name)
    except BaseException as exc:
        raise RuntimeError("guard_runtime_preload_failed") from exc
    finally:
        sys.meta_path.remove(blocker)

    standard_roots = {
        _canonical(value)
        for key in ("stdlib", "platstdlib")
        if (value := sysconfig.get_paths().get(key))
    }
    standard_roots.add(_canonical(pathlib.Path(sys.base_prefix) / "DLLs"))
    qa_roots = {
        _canonical(value)
        for key in ("purelib", "platlib")
        if (value := sysconfig.get_paths().get(key))
    }
    standard_roots.discard(None)
    qa_roots.discard(None)
    if not standard_roots or not qa_roots:
        raise RuntimeError("guard_runtime_origin_roots_unavailable")

    origin_rows: list[dict[str, str]] = []
    for name in PRELOAD_MODULE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, types.ModuleType):
            raise RuntimeError("guard_runtime_module_missing:" + name)
        origin = getattr(module, "__file__", None)
        if origin is None:
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if origin in {None, "built-in", "frozen"}:
            scope = "stdlib_builtin_or_frozen"
        else:
            canonical = _canonical(origin)
            if canonical is None:
                raise RuntimeError("guard_runtime_module_origin_invalid:" + name)
            if any(_under(canonical, root) for root in qa_roots):
                scope = "source_qa_venv_site_packages"
            elif any(_under(canonical, root) for root in standard_roots):
                scope = "stdlib"
            else:
                raise RuntimeError("guard_runtime_module_origin_outside_allowlist:" + name)
        expected_scope = (
            "source_qa_venv_site_packages"
            if name == "pytest" or name.startswith("colorama")
            else "stdlib"
        )
        if scope not in {expected_scope, "stdlib_builtin_or_frozen"}:
            raise RuntimeError("guard_runtime_module_origin_scope_mismatch:" + name)
        origin_rows.append({"name": name, "scope": scope})

    if not (
        ctypes.CDLL is fake_windows_library
        and ctypes.WinDLL is fake_windows_library
        and ctypes.OleDLL is fake_windows_library
        and ctypes.PyDLL is fake_windows_library
        and ctypes.cdll is facade
        and ctypes.windll is facade
        and ctypes.oledll is facade
    ):
        raise RuntimeError("inert_windows_console_facade_binding_changed")
    candidates_after_preload = [
        name
        for name in tuple(sys.modules)
        if name == "tests"
        or name.startswith("tests.")
        or name == "backtrader_runtime"
        or name.startswith("backtrader_runtime.")
    ]
    if candidates_after_preload:
        raise RuntimeError("candidate_module_imported_during_guard_preload")

    return (
        {
            "phase": "runtime_preload_before_hard_denials",
            "modules": origin_rows,
            "console_facade": "inert_false_result",
            "fake_ctypes_bindings_preserved": True,
            "candidate_modules_absent_before_and_after": True,
            "actual_winapi_calls": False,
            "warning_count": len(preload_warnings),
            "warning_categories": [
                type(item.message).__name__ for item in preload_warnings[:64]
            ],
        },
        counters,
    )


def _guard_counter_delta(
    baseline: dict[str, int], final: dict[str, int]
) -> dict[str, object]:
    keys = set(baseline) | set(final)
    deltas = {key: final.get(key, 0) - baseline.get(key, 0) for key in sorted(keys)}
    counter_regressions = {key: value for key, value in deltas.items() if value < 0}
    permitted = {
        key: value
        for key, value in deltas.items()
        if key in PERMITTED_GUARD_COUNTER_DELTAS and value >= 0
    }
    forbidden = {
        key: value
        for key, value in deltas.items()
        if key not in PERMITTED_GUARD_COUNTER_DELTAS and value != 0
    }
    return {
        "baseline": dict(sorted(baseline.items())),
        "after_tests": dict(sorted(final.items())),
        "delta": deltas,
        "permitted_delta_counters": permitted,
        "forbidden_operation_delta": forbidden,
        "counter_regressions": counter_regressions,
        "valid": not forbidden and not counter_regressions,
    }
BLOCKED_IMPORTS = (
    "ctp",
    "pyctp",
    "thostmduserapi",
    "thosttraderapi",
    "thostmduserapi_se",
    "thosttraderapi_se",
    "ctpwrapper",
    "vnpy_ctp",
    "bt_api",
    "bt_api_py",
    "requests",
    "httpx",
    "aiohttp",
    "websockets",
)
SENSITIVE_BASENAMES = {
    ".env",
    "config.yaml",
    "config.yml",
    "secrets.yaml",
    "secrets.yml",
}
SENSITIVE_DIRECTORY_NAMES = {
    "captures",
    "private-captures",
    "private_captures",
    "opaque",
}

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / OUTPUT_REL.replace("/", os.sep)
INVENTORY_PATH = OUTPUT_DIR / "input-inventory.json"
PACKET_ROOT = REPO_ROOT / PACKET_REL.replace("/", os.sep)
_RAW_OPEN = builtins.open
_RAW_IO_OPEN = io.open
_RAW_OS_OPEN = os.open
_RAW_EXEC = builtins.exec
_RAW_COMPILE = builtins.compile
_GUARD_COUNTS: dict[str, int] = {}
_SOURCE_COMPILES: dict[str, int] = {}
_SOURCE_EXECS: dict[str, int] = {}
_SOURCE_FUNCTION_ORIGINS: dict[str, set[str]] = {}
_SOURCE_MODULE_ORIGIN_EVENTS: dict[str, list[dict[str, object]]] = {}
_COMPILED_SOURCE_BINDINGS: dict[int, tuple[types.CodeType, str, str]] = {}
_TEST_FIXTURE_SOURCE_EVENTS: dict[str, list[str]] = {}
_ACTIVE_GUARD: dict[str, object] = {}
_CHILD_LOG_WRITERS: dict[str, object] = {}


class GuardViolation(RuntimeError):
    """Fixed public QA guard denial."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(path: object) -> str | None:
    try:
        value = os.fsdecode(os.fspath(path))
    except (TypeError, ValueError):
        return None
    if not value or value.startswith("<"):
        return None
    if not os.path.isabs(value):
        value = os.path.join(str(REPO_ROOT), value)
    return os.path.normcase(os.path.realpath(value)).casefold()


def _under(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except (OSError, ValueError):
        return False


def _relative_repo_path(path: object) -> str | None:
    value = _canonical(path)
    root = _canonical(REPO_ROOT)
    if value is None or root is None or not _under(value, root):
        return None
    return os.path.relpath(value, root).replace("\\", "/")


def _read_bytes(path: pathlib.Path) -> bytes:
    with builtins.open(path, "rb") as stream:
        return stream.read()


def _inventory() -> dict[str, object]:
    raw = _read_bytes(INVENTORY_PATH)
    if (
        len(raw) != EXPECTED_INVENTORY_BYTES
        or _sha256(raw) != EXPECTED_INVENTORY_SHA256
    ):
        raise RuntimeError("input_inventory_pin_mismatch")
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict:
        raise RuntimeError("input_inventory_shape_invalid")
    return value


def _input_rows() -> tuple[dict[str, object], dict[str, object]]:
    inventory = _inventory()
    packet_info = inventory.get("candidate_packet")
    if type(packet_info) is not dict:
        raise RuntimeError("candidate_packet_inventory_invalid")
    candidate_info = packet_info.get("candidate_pins")
    artifact_info = packet_info.get("artifact_pins")
    if type(candidate_info) is not dict or type(artifact_info) is not dict:
        raise RuntimeError("packet_pin_inventory_invalid")

    candidate_path = REPO_ROOT / str(candidate_info["path"]).replace("/", os.sep)
    artifact_path = REPO_ROOT / str(artifact_info["path"]).replace("/", os.sep)
    candidate_raw = _read_bytes(candidate_path)
    artifact_raw = _read_bytes(artifact_path)
    if (
        len(candidate_raw) != EXPECTED_CANDIDATE_PINS[0]
        or _sha256(candidate_raw) != EXPECTED_CANDIDATE_PINS[1]
        or len(artifact_raw) != EXPECTED_ARTIFACT_PINS[0]
        or _sha256(artifact_raw) != EXPECTED_ARTIFACT_PINS[1]
    ):
        raise RuntimeError("packet_pin_file_mismatch")

    candidate = json.loads(candidate_raw.decode("utf-8"))
    artifacts = json.loads(artifact_raw.decode("utf-8"))
    if (
        type(candidate) is not dict
        or type(artifacts) is not dict
        or candidate.get("candidate_status") != "SOURCE_FAKE_ONLY"
    ):
        raise RuntimeError("candidate_packet_status_invalid")
    sources = candidate.get("source_rows")
    tests = candidate.get("focused_test_rows")
    artifact_rows = artifacts.get("files")
    inventory_sources = inventory.get("source_rows")
    inventory_tests = inventory.get("focused_test_rows")
    inventory_artifacts = inventory.get("packet_artifacts")
    namespace_policy = inventory.get("selected_package_namespace")
    metadata_paths = inventory.get("metadata_only_excluded_runtime_source_paths")
    test_contract = inventory.get("test_contract")
    if not all(
        type(value) is list
        for value in (
            sources,
            tests,
            artifact_rows,
            inventory_sources,
            inventory_tests,
            inventory_artifacts,
            metadata_paths,
        )
    ) or type(namespace_policy) is not dict or type(test_contract) is not dict:
        raise RuntimeError("candidate_inventory_rows_invalid")
    if (
        len(sources) != 26
        or len(tests) != 8
        or len(artifact_rows) != 6
        or candidate.get("parent_module_source_count") != 26
        or candidate.get("child_frame_source_count") != 23
    ):
        raise RuntimeError("candidate_inventory_counts_invalid")
    if tuple(sorted(row.get("path") for row in tests if type(row) is dict)) != tuple(
        sorted(EXPECTED_TESTS)
    ):
        raise RuntimeError("focused_test_inventory_mismatch")
    if tuple(sorted(metadata_paths)) != tuple(
        sorted(METADATA_ONLY_EXCLUDED_RUNTIME_PATHS)
    ):
        raise RuntimeError("excluded_runtime_metadata_path_set_invalid")
    if (
        namespace_policy.get("mode")
        != "SOURCE_FAKE_SELECTED_MODULE_NAMESPACE_ONLY"
        or namespace_policy.get("package_name") != "backtrader_runtime"
        or namespace_policy.get("canonical_package_path")
        != str(REPO_ROOT / "backtrader_runtime")
        or namespace_policy.get("initializer_executed") is not False
        or namespace_policy.get("allowed_submodules")
        != "candidate_packet.source_rows_under_backtrader_runtime_only"
    ):
        raise RuntimeError("selected_package_namespace_policy_invalid")
    environment_policy = test_contract.get("environment")
    metadata_scope = test_contract.get("metadata_probe_scope_limit")
    pytest_policy = test_contract.get("pytest_arguments")
    pytest_config_policy = test_contract.get("external_pytest_config")
    artifact_layout_policy = test_contract.get("external_pytest_artifact_layout")
    outcome_policy = test_contract.get("report_outcome_gate")
    preload_policy = test_contract.get("windows_pytest_startup_preload")
    guard_delta_policy = test_contract.get("guard_counter_delta_gate")
    writer_lifecycle_policy = test_contract.get("child_output_writer_lifecycle")
    console_summary_policy = test_contract.get("parent_console_summary")
    if (
        type(environment_policy) is not dict
        or tuple(environment_policy.get("child_allowlist", ())) != CHILD_ENV_KEYS
        or tuple(environment_policy.get("excluded", ())) != CHILD_ENV_EXCLUDED_KEYS
        or environment_policy.get("plugin_autoload") != "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1"
        or tuple(pytest_policy or ()) != EXPECTED_PYTEST_ARGUMENT_POLICY
        or metadata_scope != EXPECTED_METADATA_PROBE_SCOPE_LIMIT
        or type(pytest_config_policy) is not dict
        or pytest_config_policy.get("content") != "[pytest]\n"
        or pytest_config_policy.get("bytes") != len(EXPECTED_PYTEST_CONFIG_BYTES)
        or pytest_config_policy.get("sha256") != EXPECTED_PYTEST_CONFIG_SHA256
        or pytest_config_policy.get("path")
        != "<fresh external QA artifact directory>/pytest.ini"
        or pytest_config_policy.get("capture_post_derived_config")
        != "pytest_configure and post-session module/config checks"
        or artifact_layout_policy != EXPECTED_EXTERNAL_PYTEST_ARTIFACT_LAYOUT
        or outcome_policy != EXPECTED_REPORT_OUTCOME_CONTRACT
        or preload_policy != EXPECTED_WINDOWS_PRELOAD_POLICY
        or guard_delta_policy != EXPECTED_GUARD_COUNTER_DELTA_POLICY
        or writer_lifecycle_policy != EXPECTED_CHILD_OUTPUT_WRITER_LIFECYCLE
        or console_summary_policy != EXPECTED_PARENT_CONSOLE_SUMMARY_POLICY
    ):
        raise RuntimeError("source_fake_guard_policy_inventory_invalid")

    persistent_module_policy = inventory.get(
        "persistent_canonical_runtime_modules"
    )
    ephemeral_module_policy = inventory.get("ephemeral_runtime_module_absence_contract")
    ephemeral_derivation = inventory.get("ephemeral_selected_source_alias_derivation")
    if (
        type(persistent_module_policy) is not list
        or type(ephemeral_module_policy) is not list
        or {
            str(row.get("module_name")): str(row.get("path"))
            for row in persistent_module_policy
            if type(row) is dict
        }
        != PERSISTENT_CANONICAL_RUNTIME_MODULES
        or tuple(ephemeral_module_policy)
        != tuple(EPHEMERAL_RUNTIME_MODULE_NAMES)
        or ephemeral_derivation != EXPECTED_EPHEMERAL_ALIAS_DERIVATION
    ):
        raise RuntimeError("runtime_module_identity_policy_invalid")
    pinned_source_paths = {
        str(row.get("path")) for row in sources if type(row) is dict
    }
    if not set(PERSISTENT_CANONICAL_RUNTIME_MODULES.values()).issubset(
        pinned_source_paths
    ):
        raise RuntimeError("persistent_runtime_source_not_in_candidate_closure")

    _compare_inventory_rows(sources, inventory_sources, "source_rows")
    _compare_inventory_rows(tests, inventory_tests, "focused_test_rows")
    _compare_artifact_rows(artifact_rows, inventory_artifacts)

    root_string = _canonical(REPO_ROOT)
    if root_string is None:
        raise RuntimeError("repository_origin_invalid")
    for row in inventory_sources + inventory_tests:
        if type(row) is not dict:
            raise RuntimeError("candidate_row_invalid")
        relative = row.get("path")
        origin = row.get("origin")
        if type(relative) is not str or type(origin) is not str:
            raise RuntimeError("candidate_origin_row_invalid")
        absolute = REPO_ROOT / relative.replace("/", os.sep)
        resolved = _canonical(absolute)
        if resolved is None or not _under(resolved, root_string):
            raise RuntimeError("candidate_origin_outside_repository")
        if resolved != _canonical(origin):
            raise RuntimeError("candidate_origin_map_mismatch")

    expected_rows: dict[str, dict[str, object]] = {}
    for row in inventory_sources:
        expected_rows[str(row["path"])] = dict(row)
    expected_tests: dict[str, dict[str, object]] = {}
    for row in inventory_tests:
        expected_tests[str(row["path"])] = dict(row)
    source_groups = [str(row["group"]) for row in sources]
    if (
        source_groups.count("child_frame") != 23
        or source_groups.count("parent_only") != 3
    ):
        raise RuntimeError("child_parent_source_partition_invalid")
    if set(expected_rows) != {str(row["path"]) for row in sources}:
        raise RuntimeError("source_origin_inventory_set_mismatch")
    return expected_rows, expected_tests


def _compare_inventory_rows(
    packet_rows: list[object],
    inventory_rows: list[object],
    field: str,
) -> None:
    def key(row: object) -> tuple[object, ...]:
        if type(row) is not dict:
            raise RuntimeError("candidate_row_invalid")
        return (
            row.get("group"),
            row.get("path"),
            row.get("bytes"),
            row.get("sha256"),
        )

    if sorted(key(row) for row in packet_rows) != sorted(
        key(row) for row in inventory_rows
    ):
        raise RuntimeError(field + "_inventory_mismatch")


def _compare_artifact_rows(
    packet_rows: list[object], inventory_rows: list[object]
) -> None:
    def key(row: object) -> tuple[object, ...]:
        if type(row) is not dict:
            raise RuntimeError("packet_artifact_row_invalid")
        return (row.get("path"), row.get("bytes"), row.get("sha256"))

    expected = []
    for row in packet_rows:
        if type(row) is not dict:
            raise RuntimeError("packet_artifact_row_invalid")
        expected.append(
            (
                PACKET_REL + "/" + str(row.get("path")),
                row.get("bytes"),
                row.get("sha256"),
            )
        )
    if sorted(expected) != sorted(key(row) for row in inventory_rows):
        raise RuntimeError("packet_artifact_inventory_mismatch")


def _verify_file(path: pathlib.Path, expected_size: int, expected_hash: str) -> None:
    raw = _read_bytes(path)
    if len(raw) != expected_size or _sha256(raw) != expected_hash:
        raise RuntimeError("input_pin_mismatch:" + str(path.relative_to(REPO_ROOT)))


def _verify_external_pytest_config(path: pathlib.Path) -> dict[str, object]:
    canonical = _canonical(path)
    repository = _canonical(REPO_ROOT)
    if canonical is None or repository is None or _under(canonical, repository):
        raise RuntimeError("external_pytest_config_origin_invalid")
    raw = _read_bytes(path)
    if (
        raw != EXPECTED_PYTEST_CONFIG_BYTES
        or len(raw) != len(EXPECTED_PYTEST_CONFIG_BYTES)
        or _sha256(raw) != EXPECTED_PYTEST_CONFIG_SHA256
    ):
        raise RuntimeError("external_pytest_config_pin_mismatch")
    return {
        "path": str(path.resolve()),
        "bytes": len(raw),
        "sha256": _sha256(raw),
        "content": raw.decode("ascii"),
        "origin_is_external": True,
    }


def _verify_inputs() -> dict[str, object]:
    sources, tests = _input_rows()
    inventory = _inventory()
    for row in tuple(sources.values()) + tuple(tests.values()):
        path = REPO_ROOT / str(row["path"]).replace("/", os.sep)
        _verify_file(path, int(row["bytes"]), str(row["sha256"]))

    packet_info = inventory["candidate_packet"]
    assert type(packet_info) is dict
    for key, expected in (
        ("candidate_pins", EXPECTED_CANDIDATE_PINS),
        ("artifact_pins", EXPECTED_ARTIFACT_PINS),
    ):
        item = packet_info[key]
        assert type(item) is dict
        path = REPO_ROOT / str(item["path"]).replace("/", os.sep)
        _verify_file(path, int(expected[0]), str(expected[1]))

    artifact_path = REPO_ROOT / PACKET_REL.replace("/", os.sep) / "artifact-pins.json"
    artifact_doc = json.loads(_read_bytes(artifact_path).decode("utf-8"))
    for row in artifact_doc["files"]:
        path = REPO_ROOT / PACKET_REL.replace("/", os.sep) / str(row["path"]).replace(
            "/", os.sep
        )
        _verify_file(path, int(row["bytes"]), str(row["sha256"]))

    review_path = REPO_ROOT / EXPECTED_REVIEW[0].replace("/", os.sep)
    _verify_file(review_path, EXPECTED_REVIEW[1], EXPECTED_REVIEW[2])
    return {
        "source_rows": sources,
        "focused_test_rows": tests,
        "inventory": inventory,
    }


def _git_check(label: str) -> dict[str, object]:
    branch_file = OUTPUT_DIR / (label + "-git-branch.txt")
    head_file = OUTPUT_DIR / (label + "-git-head.txt")
    index_file = OUTPUT_DIR / (label + "-git-index.txt")
    with _RAW_OPEN(branch_file, "wb") as stream:
        branch = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=20,
        )
    with _RAW_OPEN(head_file, "wb") as stream:
        head = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=20,
        )
    with _RAW_OPEN(index_file, "wb") as stream:
        index = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "diff", "--cached", "--quiet"],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=20,
        )
    branch_value = _read_bytes(branch_file).decode("ascii", "strict").strip()
    head_value = _read_bytes(head_file).decode("ascii", "strict").strip()
    return {
        "branch": branch_value,
        "head": head_value,
        "branch_exit": int(branch.returncode),
        "head_exit": int(head.returncode),
        "index_empty": index.returncode == 0,
        "index_exit": int(index.returncode),
    }


def _valid_git_check(value: dict[str, object]) -> bool:
    return (
        value.get("branch") == "dev"
        and value.get("branch_exit") == 0
        and value.get("head_exit") == 0
        and type(value.get("head")) is str
        and bool(re.fullmatch(r"[0-9a-f]{40}", str(value.get("head"))))
        and value.get("index_empty") is True
        and value.get("index_exit") == 0
    )


def _support_source_git_state(
    paths: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    state: dict[str, dict[str, object]] = {}
    for relative in sorted(paths):
        tracked = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--error-unmatch", "--", relative],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=20,
        )
        head = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "HEAD:" + relative],
            capture_output=True,
            text=True,
            encoding="ascii",
            check=False,
            timeout=20,
        )
        status = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--",
                relative,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=20,
        )
        is_tracked = tracked.returncode == 0 and tracked.stdout.strip() == relative
        head_blob = head.stdout.strip() if head.returncode == 0 else None
        status_text = status.stdout.strip()
        clean_equal = (
            is_tracked
            and head_blob is not None
            and status.returncode == 0
            and status_text == ""
        )
        if clean_equal:
            classification = "TRACKED_HEAD_CLEAN_EQUAL"
        elif status.returncode == 0 and status_text.startswith("??"):
            classification = "UNTRACKED_OR_NOT_TRACKED"
        elif any(result.returncode != 0 for result in (tracked, head, status)):
            classification = "GIT_METADATA_UNAVAILABLE"
        elif not is_tracked:
            classification = "UNTRACKED_OR_NOT_TRACKED"
        else:
            classification = "DIRTY_OR_HEAD_MISMATCH"
        state[relative] = {
            "classification": classification,
            "tracked": is_tracked,
            "head_blob_sha1": head_blob,
            "git_status_clean_against_head": clean_equal,
            "porcelain_status": status_text,
            "git_command_exit_codes": {
                "tracked": int(tracked.returncode),
                "head": int(head.returncode),
                "status": int(status.returncode),
            },
        }
    return state


def _excluded_runtime_git_state_is_clean(
    state: dict[str, dict[str, object]],
) -> bool:
    return set(state) == set(METADATA_ONLY_EXCLUDED_RUNTIME_PATHS) and all(
        row.get("classification") == "TRACKED_HEAD_CLEAN_EQUAL"
        for row in state.values()
    )


def _write_json(path: pathlib.Path, value: object) -> None:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )
    with builtins.open(path, "wb") as stream:
        stream.write(raw)
        stream.write(b"\n")


class _CappedTextWriter:
    def __init__(self, path: pathlib.Path, limit: int) -> None:
        self.path = path
        self.limit = limit
        self.stream = _RAW_OPEN(path, "wb")
        self.bytes_written = 0
        self.truncated = False
        self._close_requested = False

    @property
    def encoding(self) -> str:
        return "utf-8"

    @property
    def closed(self) -> bool:
        return self._close_requested or self.stream.closed

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False

    def write(self, value: str) -> int:
        if not isinstance(value, str):
            raise TypeError("text_log_requires_str")
        raw = value.encode("utf-8", "replace")
        remaining = max(0, self.limit - self.bytes_written)
        if remaining:
            chunk = raw[:remaining]
            self.stream.write(chunk)
            self.stream.flush()
            self.bytes_written += len(chunk)
        if len(raw) > remaining:
            self.truncated = True
        return len(value)

    def flush(self) -> None:
        if not self.closed:
            self.stream.flush()

    def close(self) -> None:
        if self.closed:
            return
        try:
            self.stream.flush()
        finally:
            self._close_requested = True
            self.stream.close()

    def diagnostics(self) -> dict[str, object]:
        self.flush()
        return {
            "path": str(self.path),
            "bytes_written": self.bytes_written,
            "limit_bytes": self.limit,
            "truncated": self.truncated,
            "sha256": _sha256(_read_bytes(self.path)),
        }


def _parent_main() -> int:
    if _canonical(sys.executable) != _canonical(EXPECTED_PYTHON):
        raise RuntimeError("source_qa_interpreter_mismatch")
    if pathlib.Path.cwd().resolve() != REPO_ROOT:
        raise RuntimeError("repository_working_directory_mismatch")

    pre_inputs = _verify_inputs()
    git_before = _git_check("before")
    support_git_before = _support_source_git_state(
        METADATA_ONLY_EXCLUDED_RUNTIME_PATHS
    )
    support_clean_before = _excluded_runtime_git_state_is_clean(support_git_before)
    if not _valid_git_check(git_before):
        _write_json(
            OUTPUT_DIR / "root-qa-result.json",
            {
                "status": "BLOCKED_PRECONDITION",
                "reason": "dev_branch_or_empty_index_required",
                "git_before": git_before,
                "support_source_git_state": support_git_before,
            },
        )
        return 2

    artifact_root = pathlib.Path(
        tempfile.mkdtemp(prefix="iteration41-c01-v20-parent-formal-root-qa-r9-")
    ).resolve()
    stdlib_tempdir = artifact_root / "stdlib-temp"
    basetemp = artifact_root / "pytest-basetemp"
    repo_canonical = _canonical(REPO_ROOT)
    artifact_canonical = _canonical(artifact_root)
    temp_root_canonical = _canonical(tempfile.gettempdir())
    base_canonical = _canonical(basetemp)
    if (
        repo_canonical is None
        or artifact_canonical is None
        or temp_root_canonical is None
        or base_canonical is None
        or _under(artifact_canonical, repo_canonical)
        or not _under(artifact_canonical, temp_root_canonical)
        or _under(base_canonical, repo_canonical)
        or _canonical(basetemp.parent) != artifact_canonical
        or basetemp.exists()
        or stdlib_tempdir.exists()
    ):
        raise RuntimeError("external_artifact_root_or_nested_basetemp_invalid")
    stdlib_tempdir.mkdir()
    if not stdlib_tempdir.is_dir():
        raise RuntimeError("external_stdlib_temp_directory_not_created")

    pytest_config_path = artifact_root / "pytest.ini"
    if pytest_config_path.exists():
        raise RuntimeError("fresh_external_pytest_config_already_exists")
    with _RAW_OPEN(pytest_config_path, "xb") as stream:
        stream.write(EXPECTED_PYTEST_CONFIG_BYTES)
    pytest_config_before = _verify_external_pytest_config(pytest_config_path)

    command = [
        sys.executable,
        str(pathlib.Path(__file__).resolve()),
        "--child",
        "--basetemp",
        str(basetemp),
        "--stdout-log",
        str(artifact_root / "pytest-child-stdout.txt"),
        "--stderr-log",
        str(artifact_root / "pytest-child-stderr.txt"),
        "--pytest-config",
        str(pytest_config_path),
    ]
    system_root = os.environ.get("SYSTEMROOT") or os.environ.get("WINDIR")
    if not system_root or not pathlib.Path(system_root).is_absolute():
        raise RuntimeError("windows_system_root_unavailable")
    venv_scripts = pathlib.Path(EXPECTED_PYTHON).parent
    base_prefix = pathlib.Path(sys.base_prefix).resolve()
    system32 = pathlib.Path(system_root) / "System32"
    child_path = os.pathsep.join(
        str(path)
        for path in (
            venv_scripts,
            base_prefix,
            base_prefix / "DLLs",
            system32,
            pathlib.Path(system_root),
        )
    )
    child_env = {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": child_path,
        "TEMP": str(stdlib_tempdir),
        "TMP": str(stdlib_tempdir),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    allowed_child_env_keys = set(CHILD_ENV_KEYS)
    if set(child_env) != allowed_child_env_keys:
        raise RuntimeError("child_environment_allowlist_invalid")

    stdout_path = artifact_root / "pytest-child-stdout.txt"
    stderr_path = artifact_root / "pytest-child-stderr.txt"
    _write_json(
        OUTPUT_DIR / "child-qa-result.json",
        {"status": "CHILD_RUNNING", "expected_test_count": EXPECTED_TEST_COUNT},
    )
    for log_path in (stdout_path, stderr_path):
        with _RAW_OPEN(log_path, "wb"):
            pass
    try:
        try:
            child = subprocess.run(
                command,
                cwd=str(REPO_ROOT),
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=SOURCE_QA_TIMEOUT_SECONDS,
            )
            child_returncode = int(child.returncode)
        except subprocess.TimeoutExpired:
            child_returncode = 124
        except OSError:
            child_returncode = 125
    finally:
        output_summary = _collect_child_output(stdout_path, stderr_path)
        _write_json(OUTPUT_DIR / "child-output-summary.json", output_summary)

    child_record = output_summary.get("child_result")
    expected_child_statuses = (
        {"PASS_SOURCE_FAKE_ONLY"}
        if child_returncode == 0
        else {
            "SOURCE_FAKE_FAILED_OR_BLOCKED",
            "CHILD_HARNESS_BLOCKED",
            "CHILD_RUNNING",
        }
    )
    output_gate_ok = (
        all(
            type(output_summary.get(name)) is dict
            and output_summary[name].get("within_limit") is True
            for name in ("stdout", "stderr")
        )
        and type(child_record) is dict
        and child_record.get("status") in expected_child_statuses
        and (
            child_record.get("status") != "PASS_SOURCE_FAKE_ONLY"
            or (
                type(output_summary.get("child_log_attestation")) is dict
                and output_summary["child_log_attestation"].get("valid") is True
            )
        )
    )
    git_after = _git_check("after")
    support_git_after = _support_source_git_state(
        METADATA_ONLY_EXCLUDED_RUNTIME_PATHS
    )
    support_clean_after = _excluded_runtime_git_state_is_clean(support_git_after)
    support_state_unchanged = support_git_after == support_git_before
    pytest_config_after: dict[str, object] | None = None
    pytest_config_post_error = None
    try:
        pytest_config_after = _verify_external_pytest_config(pytest_config_path)
    except Exception as exc:
        pytest_config_post_error = type(exc).__name__ + ":" + str(exc)
    post_error = None
    try:
        _verify_inputs()
    except Exception as exc:
        post_error = type(exc).__name__ + ":" + str(exc)
    if pytest_config_post_error is not None:
        post_error = pytest_config_post_error
    elif pytest_config_after != pytest_config_before:
        post_error = "external_pytest_config_changed_during_run"
    if (
        not _valid_git_check(git_after)
        or git_after.get("head") != git_before.get("head")
        or post_error is not None
        or not output_gate_ok
        or not support_state_unchanged
    ):
        status = "BLOCKED_POSTCONDITION"
    elif child_returncode == 0:
        status = "PASS_SOURCE_FAKE_ONLY"
    else:
        status = "SOURCE_FAKE_FAILED"

    result = {
        "schema": "iteration41-simnow-c01-v20-parent-formal-root-qa-result-r7",
        "status": status,
        "child_returncode": child_returncode,
        "expected_test_count": EXPECTED_TEST_COUNT,
        "git_before": git_before,
        "git_after": git_after,
        "support_source_git_state_before": support_git_before,
        "support_source_git_state_after": support_git_after,
        "support_source_head_clean_before": support_clean_before,
        "support_source_head_clean_after": support_clean_after,
        "support_source_state_unchanged": support_state_unchanged,
        "excluded_runtime_source_metadata": {
            "paths": list(METADATA_ONLY_EXCLUDED_RUNTIME_PATHS),
            "state_before": support_git_before,
            "state_after": support_git_after,
            "all_tracked_head_clean_before": support_clean_before,
            "all_tracked_head_clean_after": support_clean_after,
            "state_unchanged": support_state_unchanged,
            "scope": (
                "Read-only Git metadata only; these runtime initializer support "
                "sources are not pinned, compiled, imported, or part of the "
                "selected-source test closure."
            ),
        },
        "source_input_count": len(pre_inputs["source_rows"]),
        "focused_test_input_count": len(pre_inputs["focused_test_rows"]),
        "selected_package_namespace_mode": (
            "SOURCE_FAKE_SELECTED_MODULE_NAMESPACE_ONLY"
        ),
        "packet_artifact_count": 6,
        "external_pytest_artifact_root": str(artifact_root),
        "stdlib_temp_directory": str(stdlib_tempdir),
        "basetemp": str(basetemp),
        "pytest_log_path": str(artifact_root / "pytest.log"),
        "external_pytest_config_before": pytest_config_before,
        "external_pytest_config_after": pytest_config_after,
        "external_pytest_config_post_error": pytest_config_post_error,
        "derived_pytest_config": (
            child_record.get("derived_pytest_config")
            if type(child_record) is dict
            else None
        ),
        "command": command,
        "child_environment_keys": sorted(child_env),
        "child_environment_excluded_keys": list(CHILD_ENV_EXCLUDED_KEYS),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "child_output_summary_path": str(OUTPUT_DIR / "child-output-summary.json"),
        "child_output_gate_ok": output_gate_ok,
        "post_input_error": post_error,
        "evidence_limit": (
            "SOURCE_FAKE_ONLY; no Root activation, native or WinAPI call, "
            "SDK operation, real provider/account request, network access, "
            "or candidate process/Pipe operation."
        ),
        "metadata_probe_scope_limit": (
            "Fixed-suite source-fake guard only. Metadata-only stat, lstat, "
            "access, and readlink operations are outside this guard boundary; "
            "this result is not a generalized filesystem security boundary."
        ),
    }
    _write_json(OUTPUT_DIR / "root-qa-result.json", result)
    child_summary = (
        child_record.get("pytest_summary") if type(child_record) is dict else None
    )
    if type(child_summary) is not dict:
        child_summary = {}
    report_counts = child_summary.get("report_counts")
    if type(report_counts) is not dict:
        report_counts = {}
    compact_result = {
        "schema": result["schema"],
        "status": status,
        "child_returncode": child_returncode,
        "pytest_exit_code": (
            child_record.get("pytest_exit_code")
            if type(child_record) is dict
            else None
        ),
        "expected_test_count": EXPECTED_TEST_COUNT,
        "collected": child_summary.get("collected"),
        "passed_call_reports": child_summary.get("passed_call_reports"),
        "failed": child_summary.get("failed"),
        "skipped": report_counts.get("skipped"),
        "xfail": report_counts.get("xfail"),
        "xpass": report_counts.get("xpass"),
        "warnings": child_summary.get("warning_count"),
        "full_result_path": str(OUTPUT_DIR / "root-qa-result.json"),
        "child_result_path": str(OUTPUT_DIR / "child-qa-result.json"),
        "child_output_summary_path": str(OUTPUT_DIR / "child-output-summary.json"),
        "external_pytest_artifact_root": str(artifact_root),
        "pytest_config_path": str(pytest_config_path),
        "pytest_log_path": str(artifact_root / "pytest.log"),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "stdlib_temp_directory": str(stdlib_tempdir),
        "pytest_basetemp": str(basetemp),
    }
    print(json.dumps(compact_result, ensure_ascii=False, sort_keys=True))
    return 0 if status == "PASS_SOURCE_FAKE_ONLY" else 2


def _collect_child_output(
    stdout_path: pathlib.Path, stderr_path: pathlib.Path
) -> dict[str, object]:
    details: dict[str, object] = {}
    for name, path in (("stdout", stdout_path), ("stderr", stderr_path)):
        try:
            raw = _read_bytes(path)
            details[name] = {
                "path": str(path),
                "bytes": len(raw),
                "limit_bytes": MAX_CHILD_LOG_BYTES,
                "within_limit": len(raw) <= MAX_CHILD_LOG_BYTES,
                "sha256": _sha256(raw),
            }
        except Exception as exc:
            details[name] = {
                "path": str(path),
                "error": type(exc).__name__ + ":" + str(exc),
            }
    child_result_path = OUTPUT_DIR / "child-qa-result.json"
    if child_result_path.exists():
        try:
            child_raw = _read_bytes(child_result_path)
            if len(child_raw) > MAX_CHILD_LOG_BYTES:
                raise RuntimeError("child_result_size_limit_exceeded")
            child_result = json.loads(child_raw)
            details["child_result"] = child_result
            child_logs = (
                child_result.get("child_logs")
                if type(child_result) is dict
                else None
            )
            comparisons: dict[str, dict[str, object]] = {}
            for name in ("stdout", "stderr"):
                observed = details.get(name)
                child_claim = (
                    child_logs.get(name) if type(child_logs) is dict else None
                )
                comparisons[name] = {
                    "matches": bool(
                        type(observed) is dict
                        and type(child_claim) is dict
                        and child_claim.get("truncated") is False
                        and child_claim.get("bytes_written") == observed.get("bytes")
                        and child_claim.get("limit_bytes") == MAX_CHILD_LOG_BYTES
                        and child_claim.get("sha256") == observed.get("sha256")
                        and observed.get("within_limit") is True
                    ),
                    "child_truncated": (
                        child_claim.get("truncated")
                        if type(child_claim) is dict
                        else None
                    ),
                }
            details["child_log_attestation"] = {
                "valid": all(item.get("matches") is True for item in comparisons.values()),
                "files": comparisons,
            }
        except Exception as exc:
            details["child_result_error"] = type(exc).__name__ + ":" + str(exc)
    else:
        details["child_result"] = "missing"
    return details


def _is_write_access(mode: object = None, flags: object = None) -> bool:
    if isinstance(mode, str) and any(character in mode for character in "wax+"):
        return True
    if isinstance(flags, int):
        write_flags = (
            os.O_WRONLY
            | os.O_RDWR
            | os.O_CREAT
            | os.O_APPEND
            | os.O_TRUNC
        )
        if hasattr(os, "O_TMPFILE"):
            write_flags |= os.O_TMPFILE
        return bool(flags & write_flags)
    return False


def _check_path_access(
    path: object,
    allowed_roots: tuple[str, ...],
    *,
    write: bool = False,
) -> None:
    canonical = _canonical(path)
    if canonical is None:
        return
    base = os.path.basename(canonical).casefold()
    components = {part.casefold() for part in canonical.split(os.sep) if part}
    if (
        base in SENSITIVE_BASENAMES
        or base.startswith(".env.")
        or bool(components & SENSITIVE_DIRECTORY_NAMES)
    ):
        _GUARD_COUNTS["private_or_opaque_file_denied"] = (
            _GUARD_COUNTS.get("private_or_opaque_file_denied", 0) + 1
        )
        raise GuardViolation("private_or_opaque_file_denied")
    suffix = os.path.splitext(canonical)[1].casefold()
    if suffix in {".exe", ".dll", ".pyd", ".so", ".dylib"}:
        _GUARD_COUNTS["software_payload_denied"] = (
            _GUARD_COUNTS.get("software_payload_denied", 0) + 1
        )
        raise GuardViolation("software_payload_denied")
    if not any(_under(canonical, root) for root in allowed_roots):
        _GUARD_COUNTS["external_file_denied"] = (
            _GUARD_COUNTS.get("external_file_denied", 0) + 1
        )
        raise GuardViolation("external_file_denied")
    if write:
        write_roots = _ACTIVE_GUARD.get("write_roots", ())
        if not any(_under(canonical, root) for root in write_roots):
            _GUARD_COUNTS["repository_write_denied"] = (
                _GUARD_COUNTS.get("repository_write_denied", 0) + 1
            )
            raise GuardViolation("repository_write_denied")


def _blocked(action: str):
    def deny(*_args: object, **_kwargs: object) -> object:
        _GUARD_COUNTS[action] = _GUARD_COUNTS.get(action, 0) + 1
        raise GuardViolation(action)

    return deny


def _source_text_matches(source: object, expected_raw: bytes) -> bool:
    if type(source) is bytes:
        return _sha256(source) == _sha256(expected_raw)
    if type(source) is str:
        try:
            expected_text = expected_raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return False
        normalize_newlines = lambda value: value.replace("\r\n", "\n").replace(
            "\r", "\n"
        )
        return normalize_newlines(source) == normalize_newlines(expected_text)
    return False


def _nested_function_code_names(code: types.CodeType) -> set[str]:
    names: set[str] = set()
    pending = [code]
    while pending:
        current = pending.pop()
        for value in current.co_consts:
            if not isinstance(value, types.CodeType):
                continue
            if value.co_name != "<module>":
                names.add(str(getattr(value, "co_qualname", value.co_name)))
            pending.append(value)
    return names


def _install_child_guards(
    basetemp: pathlib.Path,
    external_artifact_root: pathlib.Path,
    source_rows: dict[str, dict[str, object]],
    test_rows: dict[str, dict[str, object]],
) -> tuple[str, ...]:
    allowed_values = {
        str(REPO_ROOT),
        str(pathlib.Path(sys.prefix).resolve()),
        str(pathlib.Path(sys.base_prefix).resolve()),
        str(pathlib.Path(sysconfig.get_paths()["stdlib"]).resolve()),
        str(pathlib.Path(sysconfig.get_paths()["purelib"]).resolve()),
        str(pathlib.Path(sysconfig.get_paths()["platlib"]).resolve()),
        str(basetemp),
        str(external_artifact_root.resolve()),
        str(OUTPUT_DIR.resolve()),
    }
    allowed_roots = tuple(
        sorted(
            {
                item
                for value in allowed_values
                if (item := _canonical(value)) is not None
            }
        )
    )
    source_by_origin: dict[str, tuple[str, bytes]] = {}
    test_fixture_runtime_origins = {
        canonical
        for relative in TEST_FIXTURE_RUNTIME_SOURCE_PATHS
        if (canonical := _canonical(REPO_ROOT / relative.replace("/", os.sep)))
        is not None
    }
    code_rows = dict(source_rows)
    code_rows.update(test_rows)
    selected_runtime_modules = {"backtrader_runtime"}
    for relative in source_rows:
        if relative.startswith("backtrader_runtime/") and relative.endswith(".py"):
            module_path = relative[len("backtrader_runtime/") : -len(".py")]
            if "/" not in module_path:
                selected_runtime_modules.add("backtrader_runtime." + module_path)
    selected_runtime_modules.update(SELECTED_RUNTIME_MODULE_ALIASES)
    for relative, row in code_rows.items():
        origin = REPO_ROOT / relative.replace("/", os.sep)
        raw = _read_bytes(origin)
        if len(raw) != int(row["bytes"]) or _sha256(raw) != row["sha256"]:
            raise RuntimeError("source_preimport_pin_mismatch")
        canonical = _canonical(origin)
        if canonical is None:
            raise RuntimeError("source_origin_invalid")
        source_by_origin[canonical] = (relative, raw)

    original_open = builtins.open
    original_io_open = io.open
    original_os_open = os.open
    original_import = builtins.__import__
    original_source_get_code = importlib.machinery.SourceFileLoader.get_code
    original_source_exec_module = importlib.machinery.SourceFileLoader.exec_module

    def guarded_open(file: object, *args: object, **kwargs: object):
        mode = args[0] if args else kwargs.get("mode", "r")
        if isinstance(file, int):
            if _is_write_access(mode=mode):
                raise GuardViolation("fd_write_denied")
        else:
            _check_path_access(
                file, allowed_roots, write=_is_write_access(mode=mode)
            )
        return original_open(file, *args, **kwargs)

    def guarded_io_open(file: object, *args: object, **kwargs: object):
        mode = args[0] if args else kwargs.get("mode", "r")
        if isinstance(file, int):
            if _is_write_access(mode=mode):
                raise GuardViolation("fd_write_denied")
        else:
            _check_path_access(
                file, allowed_roots, write=_is_write_access(mode=mode)
            )
        return original_io_open(file, *args, **kwargs)

    def guarded_os_open(
        path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        _check_path_access(path, allowed_roots, write=_is_write_access(flags=flags))
        if dir_fd is None:
            return original_os_open(path, flags, mode)
        return original_os_open(path, flags, mode, dir_fd=dir_fd)

    def _is_blocked_import(name: str) -> bool:
        value = name.casefold()
        return any(
            value == prefix
            or value.startswith(prefix + ".")
            or value.startswith(prefix + "_")
            for prefix in BLOCKED_IMPORTS
        )

    def _test_compile_caller() -> str | None:
        frame = sys._getframe(1)
        while frame is not None:
            relative = _relative_repo_path(frame.f_code.co_filename)
            if relative in test_rows:
                return relative
            frame = frame.f_back
        return None

    def guarded_compile(
        source,
        filename,
        mode,
        flags=0,
        dont_inherit=False,
        optimize=-1,
        *,
        _feature_version=-1,
    ):
        code = _RAW_COMPILE(
            source,
            filename,
            mode,
            flags,
            dont_inherit,
            optimize,
            _feature_version=_feature_version,
        )
        canonical = _canonical(filename)
        pinned = source_by_origin.get(canonical)
        if pinned is not None:
            relative, expected_raw = pinned
            if _source_text_matches(source, expected_raw):
                _COMPILED_SOURCE_BINDINGS[id(code)] = (
                    code,
                    relative,
                    "selected_source",
                )
            else:
                caller = _test_compile_caller()
                if caller is None:
                    raise GuardViolation("source_bytes_mismatch")
                _COMPILED_SOURCE_BINDINGS[id(code)] = (
                    code,
                    relative,
                    "test_fixture",
                )
                _TEST_FIXTURE_SOURCE_EVENTS.setdefault(relative, []).append(caller)
        return code

    def guarded_import(
        name: str,
        globals: object = None,
        locals: object = None,
        fromlist: object = (),
        level: int = 0,
    ):
        if type(name) is str and _is_blocked_import(name):
            _GUARD_COUNTS["sdk_import_denied"] = (
                _GUARD_COUNTS.get("sdk_import_denied", 0) + 1
            )
            raise GuardViolation("sdk_import_denied")
        if (
            type(name) is str
            and name.startswith("backtrader_runtime.")
            and name not in selected_runtime_modules
        ):
            _GUARD_COUNTS["unselected_runtime_module_denied"] = (
                _GUARD_COUNTS.get("unselected_runtime_module_denied", 0) + 1
            )
            raise GuardViolation("unselected_runtime_module_denied")
        return original_import(name, globals, locals, fromlist, level)

    def guarded_exec(source, globals=None, locals=None, *, closure=None):
        if closure is not None:
            result = _RAW_EXEC(source, globals, locals, closure=closure)
        elif globals is None and locals is None:
            result = _RAW_EXEC(source)
        elif locals is None:
            result = _RAW_EXEC(source, globals)
        else:
            result = _RAW_EXEC(source, globals, locals)
        if isinstance(source, types.CodeType):
            canonical = _canonical(source.co_filename)
            pinned = source_by_origin.get(canonical)
            binding = _COMPILED_SOURCE_BINDINGS.get(id(source))
            if (
                pinned is not None
                and binding is not None
                and binding[0] is source
                and binding[1] == pinned[0]
                and binding[2] == "selected_source"
            ):
                relative, _raw = pinned
                namespace = globals if type(globals) is dict else {}
                module_name = namespace.get("__name__")
                module_file = namespace.get("__file__")
                module_file_matches = _canonical(module_file) == canonical
                module_spec = namespace.get("__spec__")
                module_spec_origin = getattr(module_spec, "origin", None)
                module_spec_origin_matches = (
                    _canonical(module_spec_origin) == canonical
                    if module_spec_origin is not None
                    else None
                )
                loaded_module = (
                    sys.modules.get(module_name)
                    if type(module_name) is str
                    else None
                )
                module_registered_matches = (
                    loaded_module is not None
                    and getattr(loaded_module, "__dict__", None) is globals
                )
                _SOURCE_MODULE_ORIGIN_EVENTS.setdefault(relative, []).append(
                    {
                        "module_name": module_name,
                        "module_file": str(module_file) if module_file is not None else None,
                        "module_file_matches_source": module_file_matches,
                        "module_spec_origin": (
                            str(module_spec_origin)
                            if module_spec_origin is not None
                            else None
                        ),
                        "module_spec_origin_matches_source": module_spec_origin_matches,
                        "module_registered_identity_matches": module_registered_matches,
                        "compile_binding_kind": binding[2],
                        "selected_source_exec_observed": _SOURCE_EXECS.get(
                            relative, 0
                        ) > 0,
                    }
                )
        return result

    def guarded_source_get_code(loader, fullname: str):
        loader_path = getattr(loader, "path", None)
        canonical = _canonical(loader_path) if loader_path is not None else None
        pinned_source = source_by_origin.get(canonical)
        if pinned_source is None:
            return original_source_get_code(loader, fullname)
        relative, expected_raw = pinned_source
        with _RAW_OPEN(loader_path, "rb") as stream:
            current_raw = stream.read()
        if (
            len(current_raw) != len(expected_raw)
            or _sha256(current_raw) != _sha256(expected_raw)
        ):
            raise GuardViolation("source_bytes_changed_before_import:" + relative)
        source_text = importlib.util.decode_source(current_raw)
        return compile(source_text, str(loader_path), "exec", dont_inherit=True)

    def guarded_source_exec_module(loader, module):
        loader_path = getattr(loader, "path", None)
        canonical = _canonical(loader_path) if loader_path is not None else None
        pinned_source = source_by_origin.get(canonical)
        if pinned_source is None:
            return original_source_exec_module(loader, module)
        relative, _expected_raw = pinned_source
        exec_count_before = _SOURCE_EXECS.get(relative, 0)
        result = original_source_exec_module(loader, module)
        module_name = getattr(module, "__name__", None)
        module_file = getattr(module, "__file__", None)
        module_spec = getattr(module, "__spec__", None)
        module_spec_origin = getattr(module_spec, "origin", None)
        module_file_matches = _canonical(module_file) == canonical
        module_spec_origin_matches = (
            _canonical(module_spec_origin) == canonical
            if module_spec_origin is not None
            else None
        )
        module_registered_matches = (
            type(module_name) is str and sys.modules.get(module_name) is module
        )
        selected_exec_observed = _SOURCE_EXECS.get(relative, 0) > exec_count_before
        _SOURCE_MODULE_ORIGIN_EVENTS.setdefault(relative, []).append(
            {
                "module_name": module_name,
                "module_file": str(module_file) if module_file is not None else None,
                "module_file_matches_source": module_file_matches,
                "module_spec_origin": (
                    str(module_spec_origin) if module_spec_origin is not None else None
                ),
                "module_spec_origin_matches_source": module_spec_origin_matches,
                "module_registered_identity_matches": module_registered_matches,
                "compile_binding_kind": "selected_source_loader",
                "selected_source_exec_observed": selected_exec_observed,
            }
        )
        if not (
            module_file_matches
            and module_spec_origin_matches is True
            and selected_exec_observed
        ):
            raise GuardViolation("candidate_loader_module_origin_mismatch")
        return result

    builtins.open = guarded_open
    io.open = guarded_io_open
    os.open = guarded_os_open
    builtins.__import__ = guarded_import
    builtins.exec = guarded_exec
    builtins.compile = guarded_compile
    importlib.machinery.SourceFileLoader.get_code = guarded_source_get_code
    importlib.machinery.SourceFileLoader.exec_module = guarded_source_exec_module

    for name in (
        "socket",
        "create_connection",
        "create_server",
        "socketpair",
        "fromfd",
        "getaddrinfo",
        "gethostbyname",
        "gethostbyname_ex",
        "gethostbyaddr",
        "getnameinfo",
    ):
        if hasattr(socket, name):
            setattr(socket, name, _blocked("network_denied"))
    urllib.request.urlopen = _blocked("network_denied")
    http.client.HTTPConnection.connect = _blocked("network_denied")
    http.client.HTTPSConnection.connect = _blocked("network_denied")
    http.client.HTTPConnection.request = _blocked("network_denied")
    http.client.HTTPSConnection.request = _blocked("network_denied")

    for name in (
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
    ):
        if hasattr(subprocess, name):
            setattr(subprocess, name, _blocked("process_denied"))
    for name in (
        "pipe",
        "pipe2",
        "fork",
        "forkpty",
        "posix_spawn",
        "posix_spawnp",
        "system",
        "popen",
        "startfile",
        "_exit",
        "abort",
        "kill",
        "killpg",
    ):
        if hasattr(os, name):
            setattr(os, name, _blocked("process_or_pipe_denied"))
    for name in tuple(dir(os)):
        if name.startswith(("spawn", "exec")) and callable(getattr(os, name, None)):
            setattr(os, name, _blocked("process_denied"))
    multiprocessing.Pipe = _blocked("pipe_denied")
    multiprocessing.connection.Pipe = _blocked("pipe_denied")
    multiprocessing.connection.Client = _blocked("process_or_network_denied")
    multiprocessing.connection.Listener = _blocked("process_or_network_denied")
    for module_name in ("process",):
        module = getattr(multiprocessing, module_name, None)
        base_process = getattr(module, "BaseProcess", None)
        if base_process is not None:
            base_process.start = _blocked("process_denied")

    ctypes_module = ctypes
    for name in ("CDLL", "WinDLL", "OleDLL", "PyDLL"):
        if hasattr(ctypes_module, name):
            setattr(ctypes_module, name, _blocked("native_or_sdk_denied"))
    for name in ("cdll", "windll", "oledll"):
        if hasattr(ctypes_module, name):
            setattr(ctypes_module, name, _blocked("native_or_sdk_denied"))

    try:
        winapi = importlib.import_module("_winapi")
    except ImportError:
        winapi = None
    if winapi is not None:
        for name in tuple(dir(winapi)):
            if callable(getattr(winapi, name, None)):
                setattr(winapi, name, _blocked("winapi_denied"))

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event == "open" and args:
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else None
            _check_path_access(
                args[0],
                allowed_roots,
                write=_is_write_access(mode=mode, flags=flags),
            )
        elif event == "import" and args and isinstance(args[0], str):
            if _is_blocked_import(args[0]):
                _GUARD_COUNTS["audit_sdk_import_denied"] = (
                    _GUARD_COUNTS.get("audit_sdk_import_denied", 0) + 1
                )
                raise GuardViolation("audit_sdk_import_denied")
            if (
                args[0].startswith("backtrader_runtime.")
                and args[0] not in selected_runtime_modules
            ):
                _GUARD_COUNTS["audit_unselected_runtime_module_denied"] = (
                    _GUARD_COUNTS.get("audit_unselected_runtime_module_denied", 0) + 1
                )
                raise GuardViolation("audit_unselected_runtime_module_denied")
        elif event in {
            "os.mkdir",
            "os.remove",
            "os.rmdir",
            "os.chmod",
            "os.chown",
            "os.utime",
            "os.truncate",
            "os.symlink",
            "os.link",
            "os.chflags",
        } and args:
            _check_path_access(args[0], allowed_roots, write=True)
        elif event == "os.rename" and len(args) >= 2:
            _check_path_access(args[0], allowed_roots, write=True)
            _check_path_access(args[1], allowed_roots, write=True)
        elif event == "sqlite3.connect" and args:
            database = args[0]
            if not (
                isinstance(database, str)
                and (
                    database == ":memory:"
                    or "mode=memory" in database.casefold()
                )
            ):
                _check_path_access(database, allowed_roots, write=True)
        elif event == "compile" and len(args) >= 2:
            filename = args[1]
            canonical = _canonical(filename)
            runtime_root = _canonical(REPO_ROOT / "backtrader_runtime")
            if (
                canonical is not None
                and runtime_root is not None
                and _under(canonical, runtime_root)
                and canonical not in source_by_origin
                and canonical not in test_fixture_runtime_origins
            ):
                _GUARD_COUNTS["unselected_runtime_source_compile_denied"] = (
                    _GUARD_COUNTS.get("unselected_runtime_source_compile_denied", 0)
                    + 1
                )
                raise GuardViolation("unselected_runtime_source_compile_denied")
            if canonical in source_by_origin:
                relative, expected_raw = source_by_origin[canonical]
                if not _source_text_matches(args[0], expected_raw):
                    caller = _test_compile_caller()
                    if caller is None:
                        _GUARD_COUNTS["source_bytes_mismatch"] = (
                            _GUARD_COUNTS.get("source_bytes_mismatch", 0) + 1
                        )
                        raise GuardViolation("source_bytes_mismatch")
                    _GUARD_COUNTS["test_fixture_source_compile"] = (
                        _GUARD_COUNTS.get("test_fixture_source_compile", 0) + 1
                    )
                else:
                    _SOURCE_COMPILES[relative] = _SOURCE_COMPILES.get(relative, 0) + 1
        elif event == "exec" and args and isinstance(args[0], types.CodeType):
            canonical = _canonical(args[0].co_filename)
            runtime_root = _canonical(REPO_ROOT / "backtrader_runtime")
            if (
                canonical is not None
                and runtime_root is not None
                and _under(canonical, runtime_root)
                and canonical not in source_by_origin
                and canonical not in test_fixture_runtime_origins
            ):
                _GUARD_COUNTS["unselected_runtime_source_exec_denied"] = (
                    _GUARD_COUNTS.get("unselected_runtime_source_exec_denied", 0)
                    + 1
                )
                raise GuardViolation("unselected_runtime_source_exec_denied")
            if canonical in source_by_origin:
                relative, _raw = source_by_origin[canonical]
                binding = _COMPILED_SOURCE_BINDINGS.get(id(args[0]))
                if binding is None or binding[0] is not args[0]:
                    raise GuardViolation("candidate_exec_missing_compile_binding")
                if binding[1] != relative:
                    raise GuardViolation("candidate_exec_source_path_mismatch")
                if binding[2] == "test_fixture":
                    _TEST_FIXTURE_SOURCE_EVENTS.setdefault(relative, []).append(
                        "executed_fixture_code"
                    )
                elif binding[2] == "selected_source":
                    _SOURCE_EXECS[relative] = _SOURCE_EXECS.get(relative, 0) + 1
                    _SOURCE_FUNCTION_ORIGINS.setdefault(relative, set()).update(
                        _nested_function_code_names(args[0])
                    )
                else:
                    raise GuardViolation("candidate_exec_binding_kind_invalid")
        elif event in {
            "socket.connect",
            "socket.getaddrinfo",
            "subprocess.Popen",
            "os.system",
            "os.exec",
            "os.fork",
            "os.posix_spawn",
            "os.pipe",
            "ctypes.dlopen",
        }:
            _GUARD_COUNTS["audit_" + event.replace(".", "_")] = (
                _GUARD_COUNTS.get("audit_" + event.replace(".", "_"), 0) + 1
            )
            raise GuardViolation("audit_denied:" + event)

    sys.addaudithook(audit)
    _ACTIVE_GUARD.update(
        {
            "allowed_roots": allowed_roots,
            "write_roots": tuple(
                item
                for value in (
                    basetemp,
                    external_artifact_root.resolve(),
                    OUTPUT_DIR.resolve(),
                )
                if (item := _canonical(value)) is not None
            ),
            "source_origins": {
                relative: str(REPO_ROOT / relative.replace("/", os.sep))
                for relative in code_rows
            },
            "selected_runtime_modules": tuple(sorted(selected_runtime_modules)),
            "selected_runtime_namespace": None,
            "winapi_module": winapi,
        }
    )
    return allowed_roots


def _guard_selfcheck(basetemp: pathlib.Path, allowed_roots: tuple[str, ...]) -> list[str]:
    checked: list[str] = []

    def expect_block(name: str, action) -> None:
        try:
            action()
        except GuardViolation:
            checked.append(name)
            return
        raise RuntimeError("guard_selfcheck_failed:" + name)

    slash = "D:/source_code/backtrader/.env"
    backslash = "D:\\source_code\\backtrader\\.env"
    if _canonical(slash) != _canonical(backslash):
        raise RuntimeError("windows_path_normalization_selfcheck_failed")
    expect_block(
        "private_file_slash_path",
        lambda: builtins.open(slash, "rb"),
    )
    expect_block(
        "private_file_backslash_path",
        lambda: builtins.open(backslash, "rb"),
    )
    expect_block(
        "software_payload",
        lambda: builtins.open("D:/temp/opaque-sdk.dll", "rb"),
    )
    expect_block(
        "repository_write",
        lambda: builtins.open(
            str(
                REPO_ROOT
                / "backtrader_runtime"
                / "certification_simnow_c01_native_td_read_v19.py"
            ),
            "wb",
        ),
    )
    expect_block("socket", lambda: socket.socket())
    expect_block(
        "process",
        lambda: subprocess.Popen([sys.executable, "-V"]),
    )
    if hasattr(os, "_exit"):
        expect_block("os_process_exit", lambda: os._exit(0))
    expect_block("os_pipe", lambda: os.pipe())
    expect_block("multiprocessing_pipe", lambda: multiprocessing.Pipe())
    ctypes_module = importlib.import_module("ctypes")
    windll_available = hasattr(ctypes_module, "WinDLL")
    if windll_available:
        expect_block("windll", lambda: ctypes_module.WinDLL("kernel32.dll"))
    winapi = _ACTIVE_GUARD.get("winapi_module")
    winapi_available = False
    if winapi is not None:
        callable_names = [
            name for name in dir(winapi) if callable(getattr(winapi, name, None))
        ]
        if callable_names:
            winapi_available = True
            expect_block("winapi", lambda: getattr(winapi, callable_names[0])())
    expect_block(
        "sdk_import",
        lambda: builtins.__import__("thosttraderapi"),
    )
    expected_checks = (
        9
        + int(hasattr(os, "_exit"))
        + int(windll_available)
        + int(winapi_available)
    )
    if len(checked) != expected_checks:
        raise RuntimeError("guard_selfcheck_count_invalid")
    return checked


def _install_selected_runtime_namespace() -> dict[str, object]:
    package_name = "backtrader_runtime"
    if package_name in sys.modules:
        raise RuntimeError("runtime_package_preloaded_before_selected_namespace")
    package_path = str((REPO_ROOT / package_name).resolve())
    package_canonical = _canonical(package_path)
    if package_canonical is None:
        raise RuntimeError("runtime_package_path_invalid")
    namespace = types.ModuleType(package_name)
    namespace.__package__ = package_name
    namespace.__path__ = [package_path]
    spec = importlib.machinery.ModuleSpec(package_name, loader=None, is_package=True)
    spec.submodule_search_locations = [package_path]
    namespace.__spec__ = spec
    sys.modules[package_name] = namespace

    allowed_modules = set(_ACTIVE_GUARD.get("selected_runtime_modules", ()))

    class _SelectedRuntimeFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if (
                fullname.startswith(package_name + ".")
                and fullname not in allowed_modules
            ):
                _GUARD_COUNTS["unselected_runtime_module_denied"] = (
                    _GUARD_COUNTS.get("unselected_runtime_module_denied", 0) + 1
                )
                raise GuardViolation("unselected_runtime_module_denied")
            return None

    finder = _SelectedRuntimeFinder()
    sys.meta_path.insert(0, finder)
    _ACTIVE_GUARD.update(
        {
            "selected_runtime_namespace": namespace,
            "selected_runtime_namespace_spec": spec,
            "selected_runtime_namespace_path": package_path,
            "selected_runtime_namespace_canonical_path": package_canonical,
            "selected_runtime_finder": finder,
        }
    )
    snapshot = _selected_runtime_namespace_snapshot()
    if snapshot.get("valid") is not True:
        raise RuntimeError("selected_runtime_namespace_install_invalid")
    return snapshot


def _selected_runtime_namespace_snapshot() -> dict[str, object]:
    package_name = "backtrader_runtime"
    namespace = _ACTIVE_GUARD.get("selected_runtime_namespace")
    spec = _ACTIVE_GUARD.get("selected_runtime_namespace_spec")
    expected_path = _ACTIVE_GUARD.get("selected_runtime_namespace_path")
    expected_canonical = _ACTIVE_GUARD.get(
        "selected_runtime_namespace_canonical_path"
    )
    finder = _ACTIVE_GUARD.get("selected_runtime_finder")
    module_path = tuple(getattr(namespace, "__path__", ()))
    spec_path = tuple(getattr(spec, "submodule_search_locations", ()) or ())
    actual_canonical = tuple(
        _canonical(path) for path in module_path
    )
    spec_canonical = tuple(_canonical(path) for path in spec_path)
    same_identity = sys.modules.get(package_name) is namespace
    exact_path = (
        module_path == (expected_path,)
        and spec_path == (expected_path,)
        and actual_canonical == (expected_canonical,)
        and spec_canonical == (expected_canonical,)
    )
    valid_spec = (
        type(spec) is importlib.machinery.ModuleSpec
        and spec.name == package_name
        and spec.loader is None
        and spec.origin is None
        and spec.submodule_search_locations is not None
    )
    module_shape_valid = (
        isinstance(namespace, types.ModuleType)
        and getattr(namespace, "__name__", None) == package_name
        and getattr(namespace, "__package__", None) == package_name
    )
    spec_identity_matches = getattr(namespace, "__spec__", None) is spec
    initializer_absent = not hasattr(namespace, "__file__")
    finder_installed = finder in sys.meta_path
    return {
        "valid": bool(
            same_identity
            and exact_path
            and valid_spec
            and spec_identity_matches
            and module_shape_valid
            and initializer_absent
            and finder_installed
        ),
        "same_held_module_identity": same_identity,
        "selected_module_shape_valid": module_shape_valid,
        "module_id": id(namespace) if isinstance(namespace, types.ModuleType) else None,
        "canonical_package_path": expected_path,
        "canonical_package_path_matches": exact_path,
        "module_file_absent": initializer_absent,
        "spec_identity_matches": spec_identity_matches,
        "spec_is_selected_namespace": valid_spec,
        "selection_finder_installed": finder_installed,
        "initializer_source_compiles": _SOURCE_COMPILES.get(
            "backtrader_runtime/__init__.py", 0
        ),
        "initializer_source_execs": _SOURCE_EXECS.get(
            "backtrader_runtime/__init__.py", 0
        ),
    }


class _OriginAndCountPlugin:
    def __init__(
        self,
        expected_tests: dict[str, dict[str, object]],
        source_rows: dict[str, dict[str, object]],
        basetemp: pathlib.Path,
        allowed_roots: tuple[str, ...],
        pytest_config_path: pathlib.Path,
    ) -> None:
        self.expected_tests = expected_tests
        self.source_rows = source_rows
        self.basetemp = basetemp
        self.allowed_roots = allowed_roots
        self.pytest_config_path = pytest_config_path
        self.summary: dict[str, object] = {}
        self.test_origins: dict[str, str] = {}
        self.origin_error: str | None = None
        self.derived_pytest_config: dict[str, object] = {}
        self.derived_pytest_config_error: str | None = None
        self.collection_errors: list[dict[str, str]] = []
        self.collection_skips: list[dict[str, str]] = []
        self.collection_unexpected: list[dict[str, str]] = []
        self.warning_count = 0
        self.warning_rows: list[dict[str, str]] = []
        self.collected_nodeids: list[str] = []
        self.call_report_nodeids: list[str] = []
        self._call_reports: list[dict[str, object]] = []
        self.report_counts: dict[str, int] = {
            "reports": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "xfail": 0,
            "xpass": 0,
            "unknown_outcome": 0,
            "unexpected": 0,
        }
        self.phase_counts: dict[str, int] = {}
        self.seen_report_phases: set[tuple[str, str]] = set()
        self.unexpected_report_rows: list[dict[str, str]] = []
        self.persistent_runtime_module_refs: dict[str, types.ModuleType] = {}
        self.persistent_runtime_module_capture: dict[str, dict[str, object]] = {}
        self.persistent_runtime_module_post: dict[str, dict[str, object]] = {}
        self.runtime_aliases_at_capture: list[str] = []
        self.runtime_aliases_after_tests: list[str] = []
        self.ephemeral_aliases_absent_at_capture: list[str] = []
        self.ephemeral_aliases_absent_after_tests: list[str] = []
        self.module_binding_error: str | None = None

    def pytest_configure(self, config) -> None:
        inipath = getattr(config, "inipath", None)
        if inipath is None:
            inipath = getattr(config, "inifile", None)
        try:
            normalized_ini = dict(getattr(config, "inicfg", {}))
            self.derived_pytest_config = {
                "inipath": str(pathlib.Path(inipath).resolve()) if inipath else None,
                "inicfg": normalized_ini,
                "addopts": list(config.getini("addopts")),
                "python_files": list(config.getini("python_files")),
                "python_functions": list(config.getini("python_functions")),
                "python_classes": list(config.getini("python_classes")),
                "usefixtures": list(config.getini("usefixtures")),
                "xfail_strict": bool(config.getini("xfail_strict")),
                "testpaths": list(config.getini("testpaths")),
            }
            expected = dict(EXPECTED_DERIVED_PYTEST_CONFIG)
            expected["inipath"] = str(self.pytest_config_path.resolve())
            if self.derived_pytest_config != expected:
                self.derived_pytest_config_error = "derived_pytest_config_mismatch"
        except Exception as exc:
            self.derived_pytest_config_error = (
                type(exc).__name__ + ":" + str(exc)
            )

    def pytest_collectreport(self, report) -> None:
        if report.outcome == "failed":
            self.collection_errors.append(
                {"nodeid": str(report.nodeid), "outcome": str(report.outcome)}
            )
        elif report.outcome == "skipped":
            self.collection_skips.append(
                {"nodeid": str(report.nodeid), "outcome": str(report.outcome)}
            )
        elif report.outcome != "passed":
            self.collection_unexpected.append(
                {"nodeid": str(report.nodeid), "outcome": str(report.outcome)}
            )

    def pytest_warning_recorded(
        self, warning_message, when, nodeid, location
    ) -> None:
        self.warning_count += 1
        if len(self.warning_rows) < 64:
            message = getattr(warning_message, "message", None)
            self.warning_rows.append(
                {
                    "when": str(when),
                    "nodeid": str(nodeid),
                    "category": type(message).__name__,
                }
            )

    def pytest_runtest_logreport(self, report) -> None:
        self.report_counts["reports"] += 1
        phase = str(getattr(report, "when", ""))
        nodeid = str(getattr(report, "nodeid", ""))
        outcome = str(getattr(report, "outcome", ""))
        wasxfail = getattr(report, "wasxfail", None)
        self.phase_counts[phase] = self.phase_counts.get(phase, 0) + 1
        if outcome in {"passed", "failed", "skipped"}:
            self.report_counts[outcome] += 1
        else:
            self.report_counts["unknown_outcome"] += 1
        if wasxfail is not None:
            if outcome == "skipped":
                self.report_counts["xfail"] += 1
            elif outcome in {"passed", "failed"}:
                self.report_counts["xpass"] += 1
        if phase == "call":
            self.call_report_nodeids.append(nodeid)
            self._call_reports.append(
                {
                    "nodeid": nodeid,
                    "outcome": outcome,
                    "wasxfail": wasxfail is not None,
                }
            )

        problem = None
        if phase not in {"setup", "call", "teardown"}:
            problem = "unexpected_phase"
        elif nodeid not in set(self.collected_nodeids):
            problem = "nodeid_not_collected"
        elif (nodeid, phase) in self.seen_report_phases:
            problem = "duplicate_phase_report"
        elif outcome not in {"passed", "failed", "skipped"}:
            problem = "unexpected_outcome"
        self.seen_report_phases.add((nodeid, phase))
        if problem is not None:
            self.report_counts["unexpected"] += 1
            if len(self.unexpected_report_rows) < 64:
                self.unexpected_report_rows.append(
                    {
                        "nodeid": nodeid,
                        "phase": phase,
                        "outcome": outcome,
                        "reason": problem,
                    }
                )

    def _runtime_alias_names(self) -> list[str]:
        return sorted(
            name
            for name in sys.modules
            if name.startswith("backtrader_runtime.")
        )

    def _capture_persistent_runtime_modules(self) -> None:
        expected_names = set(PERSISTENT_CANONICAL_RUNTIME_MODULES)
        actual_names = self._runtime_alias_names()
        self.runtime_aliases_at_capture = actual_names
        if set(actual_names) != expected_names:
            self.module_binding_error = "canonical_runtime_alias_set_at_capture_mismatch"
        for name, relative in PERSISTENT_CANONICAL_RUNTIME_MODULES.items():
            module = sys.modules.get(name)
            if not isinstance(module, types.ModuleType):
                self.module_binding_error = "canonical_runtime_module_missing_at_capture"
                continue
            self.persistent_runtime_module_refs[name] = module
            expected_origin = _canonical(REPO_ROOT / relative.replace("/", os.sep))
            module_file = getattr(module, "__file__", None)
            spec = getattr(module, "__spec__", None)
            spec_origin = getattr(spec, "origin", None)
            row = {
                "module_id": id(module),
                "module_name": getattr(module, "__name__", None),
                "module_package": getattr(module, "__package__", None),
                "module_file": str(module_file) if module_file is not None else None,
                "module_file_matches_source": _canonical(module_file) == expected_origin,
                "spec_name": getattr(spec, "name", None),
                "spec_origin": str(spec_origin) if spec_origin is not None else None,
                "spec_origin_matches_source": _canonical(spec_origin) == expected_origin,
            }
            self.persistent_runtime_module_capture[name] = row
            if not (
                row["module_name"] == name
                and row["module_package"] == "backtrader_runtime"
                and row["module_file_matches_source"] is True
                and row["spec_name"] == name
                and row["spec_origin_matches_source"] is True
            ):
                self.module_binding_error = "canonical_runtime_module_origin_at_capture_mismatch"
        self.ephemeral_aliases_absent_at_capture = sorted(
            name
            for name in set(_ACTIVE_GUARD.get("selected_runtime_modules", ()))
            | set(EPHEMERAL_RUNTIME_MODULE_NAMES)
            if name != "backtrader_runtime"
            and name not in expected_names
            and name not in sys.modules
        )
        if any(
            name in sys.modules
            for name in set(_ACTIVE_GUARD.get("selected_runtime_modules", ()))
            | set(EPHEMERAL_RUNTIME_MODULE_NAMES)
            if name != "backtrader_runtime" and name not in expected_names
        ):
            self.module_binding_error = "ephemeral_runtime_alias_present_at_capture"

    def _verify_persistent_runtime_modules_after_tests(self) -> None:
        expected_names = set(PERSISTENT_CANONICAL_RUNTIME_MODULES)
        actual_names = self._runtime_alias_names()
        self.runtime_aliases_after_tests = actual_names
        if set(actual_names) != expected_names:
            self.module_binding_error = "canonical_runtime_alias_set_after_tests_mismatch"
        for name, relative in PERSISTENT_CANONICAL_RUNTIME_MODULES.items():
            module = sys.modules.get(name)
            captured = self.persistent_runtime_module_refs.get(name)
            expected_origin = _canonical(REPO_ROOT / relative.replace("/", os.sep))
            module_file = getattr(module, "__file__", None)
            spec = getattr(module, "__spec__", None)
            spec_origin = getattr(spec, "origin", None)
            row = {
                "module_id": id(module) if module is not None else None,
                "same_captured_object": module is captured,
                "module_name": getattr(module, "__name__", None),
                "module_package": getattr(module, "__package__", None),
                "module_file": str(module_file) if module_file is not None else None,
                "module_file_matches_source": _canonical(module_file) == expected_origin,
                "spec_name": getattr(spec, "name", None),
                "spec_origin": str(spec_origin) if spec_origin is not None else None,
                "spec_origin_matches_source": _canonical(spec_origin) == expected_origin,
            }
            self.persistent_runtime_module_post[name] = row
            if not (
                module is captured
                and isinstance(module, types.ModuleType)
                and row["module_name"] == name
                and row["module_package"] == "backtrader_runtime"
                and row["module_file_matches_source"] is True
                and row["spec_name"] == name
                and row["spec_origin_matches_source"] is True
            ):
                self.module_binding_error = "canonical_runtime_module_identity_after_tests_mismatch"
        ephemeral_names = (
            set(_ACTIVE_GUARD.get("selected_runtime_modules", ()))
            | set(EPHEMERAL_RUNTIME_MODULE_NAMES)
        ) - expected_names - {"backtrader_runtime"}
        self.ephemeral_aliases_absent_after_tests = sorted(
            name for name in ephemeral_names if name not in sys.modules
        )
        if any(name in sys.modules for name in ephemeral_names):
            self.module_binding_error = "ephemeral_runtime_alias_not_cleaned"

    def pytest_collection_finish(self, session) -> None:
        expected_paths = set(self.expected_tests)
        observed: set[str] = set()
        for item in session.items:
            self.collected_nodeids.append(str(item.nodeid))
            path = getattr(item, "path", None)
            relative = _relative_repo_path(path) if path is not None else None
            if relative in expected_paths:
                canonical = _canonical(path)
                expected_origin = _canonical(
                    REPO_ROOT / relative.replace("/", os.sep)
                )
                if canonical != expected_origin:
                    self.origin_error = "test_origin_mismatch:" + relative
                else:
                    observed.add(relative)
                    self.test_origins[relative] = str(pathlib.Path(path).resolve())
        if observed != expected_paths:
            missing = sorted(expected_paths - observed)
            extra = sorted(observed - expected_paths)
            self.origin_error = "test_collection_origin_set_mismatch"
            self.test_origins["missing"] = json.dumps(missing)
            self.test_origins["extra"] = json.dumps(extra)
        if (
            len(self.collected_nodeids) != EXPECTED_TEST_COUNT
            or len(set(self.collected_nodeids)) != EXPECTED_TEST_COUNT
        ):
            self.origin_error = "collected_nodeid_count_or_identity_invalid"
        self._capture_persistent_runtime_modules()

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        passed_call_reports = sum(
            1
            for report in self._call_reports
            if report["outcome"] == "passed" and report["wasxfail"] is False
        )
        call_report_set_matches = (
            len(self.call_report_nodeids) == EXPECTED_TEST_COUNT
            and len(set(self.call_report_nodeids)) == EXPECTED_TEST_COUNT
            and set(self.call_report_nodeids) == set(self.collected_nodeids)
        )
        expected_phase_counts = {
            "setup": EXPECTED_TEST_COUNT,
            "call": EXPECTED_TEST_COUNT,
            "teardown": EXPECTED_TEST_COUNT,
        }
        outcome_gate = bool(
            int(exitstatus) == 0
            and int(session.testscollected) == EXPECTED_TEST_COUNT
            and int(session.testsfailed) == 0
            and self.report_counts["reports"] == 3 * EXPECTED_TEST_COUNT
            and self.report_counts["passed"] == 3 * EXPECTED_TEST_COUNT
            and passed_call_reports == EXPECTED_TEST_COUNT
            and self.report_counts["failed"] == 0
            and self.report_counts["skipped"] == 0
            and self.report_counts["xfail"] == 0
            and self.report_counts["xpass"] == 0
            and self.report_counts["unknown_outcome"] == 0
            and self.report_counts["unexpected"] == 0
            and self.phase_counts == expected_phase_counts
            and self.collection_errors == []
            and self.collection_skips == []
            and self.collection_unexpected == []
            and self.warning_count == 0
            and call_report_set_matches
        )
        self.summary = {
            "collected": int(session.testscollected),
            "failed": int(session.testsfailed),
            "exit_status": int(exitstatus),
            "report_counts": dict(self.report_counts),
            "phase_counts": dict(self.phase_counts),
            "passed_call_reports": passed_call_reports,
            "call_reports": len(self.call_report_nodeids),
            "call_report_nodeids": list(self.call_report_nodeids),
            "call_report_set_matches_collected": call_report_set_matches,
            "unexpected_report_rows": list(self.unexpected_report_rows),
            "collection_errors": list(self.collection_errors),
            "collection_skips": list(self.collection_skips),
            "collection_unexpected": list(self.collection_unexpected),
            "warning_count": self.warning_count,
            "warning_rows": list(self.warning_rows),
            "exact_outcome_gate": outcome_gate,
            "derived_pytest_config": dict(self.derived_pytest_config),
            "derived_pytest_config_error": self.derived_pytest_config_error,
        }


def _child_main(
    basetemp_arg: str,
    stdout_log_arg: str,
    stderr_log_arg: str,
    pytest_config_arg: str,
) -> int:
    pytest_config_path = pathlib.Path(pytest_config_arg).resolve()
    external_artifact_root = pytest_config_path.parent
    stdlib_tempdir = external_artifact_root / "stdlib-temp"
    basetemp = pathlib.Path(basetemp_arg).resolve()
    repo_canonical = _canonical(REPO_ROOT)
    artifact_root_canonical = _canonical(external_artifact_root)
    stdlib_temp_canonical = _canonical(stdlib_tempdir)
    base_canonical = _canonical(basetemp)
    stdout_path = pathlib.Path(stdout_log_arg).resolve()
    stderr_path = pathlib.Path(stderr_log_arg).resolve()
    if (
        repo_canonical is None
        or artifact_root_canonical is None
        or stdlib_temp_canonical is None
        or base_canonical is None
        or _under(artifact_root_canonical, repo_canonical)
        or _under(base_canonical, repo_canonical)
        or not external_artifact_root.name.startswith(
            "iteration41-c01-v20-parent-formal-root-qa-r9-"
        )
        or not stdlib_tempdir.is_dir()
        or stdlib_tempdir.name != "stdlib-temp"
        or _canonical(stdlib_tempdir.parent) != artifact_root_canonical
        or not _under(stdlib_temp_canonical, artifact_root_canonical)
        or pytest_config_path != (external_artifact_root / "pytest.ini").resolve()
        or basetemp != (external_artifact_root / "pytest-basetemp").resolve()
        or _canonical(basetemp.parent) != artifact_root_canonical
        or basetemp.exists()
        or stdout_path
        != (external_artifact_root / "pytest-child-stdout.txt").resolve()
        or stderr_path
        != (external_artifact_root / "pytest-child-stderr.txt").resolve()
        or pathlib.Path(os.environ.get("TEMP", "")).resolve()
        != stdlib_tempdir.resolve()
        or pathlib.Path(os.environ.get("TMP", "")).resolve()
        != stdlib_tempdir.resolve()
    ):
        raise RuntimeError("child_external_artifact_layout_invalid")
    pytest_config_before = _verify_external_pytest_config(pytest_config_path)

    expected_child_env_keys = set(CHILD_ENV_KEYS)
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ.pop("PYTEST_PLUGINS", None)
    actual_child_env_keys = {str(key).upper() for key in os.environ}
    unexpected_child_env_keys = {
        key
        for key in actual_child_env_keys - expected_child_env_keys
        if re.fullmatch(r"=[A-Z]:", key) is None
    }
    if (
        not expected_child_env_keys.issubset(actual_child_env_keys)
        or unexpected_child_env_keys
        or os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") != "1"
    ):
        raise RuntimeError("child_environment_keys_invalid")

    stdout_writer = _CappedTextWriter(stdout_path, MAX_CHILD_LOG_BYTES)
    stderr_writer = _CappedTextWriter(stderr_path, MAX_CHILD_LOG_BYTES)
    _CHILD_LOG_WRITERS.update({"stdout": stdout_writer, "stderr": stderr_writer})
    atexit.register(stdout_writer.close)
    atexit.register(stderr_writer.close)
    sys.stdout = stdout_writer
    sys.stderr = stderr_writer

    os.environ["TEMP"] = str(stdlib_tempdir)
    os.environ["TMP"] = str(stdlib_tempdir)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    tempfile.tempdir = str(stdlib_tempdir)
    if pathlib.Path(tempfile.tempdir).resolve() != stdlib_tempdir.resolve():
        raise RuntimeError("stdlib_tempfile_directory_binding_invalid")
    temp_directory_binding_pre_valid = bool(
        stdlib_tempdir.is_dir()
        and pathlib.Path(os.environ["TEMP"]).resolve() == stdlib_tempdir.resolve()
        and pathlib.Path(os.environ["TMP"]).resolve() == stdlib_tempdir.resolve()
        and pathlib.Path(tempfile.tempdir).resolve() == stdlib_tempdir.resolve()
        and stdlib_tempdir.resolve() != basetemp.resolve()
    )
    if not temp_directory_binding_pre_valid:
        raise RuntimeError("stdlib_temp_directory_binding_invalid")
    os.chdir(REPO_ROOT)
    if pathlib.Path.cwd().resolve() != REPO_ROOT:
        raise RuntimeError("child_working_directory_mismatch")
    sys.path.insert(0, str(REPO_ROOT))

    # Load standard-library and test-runner support before guards are installed.
    # No candidate module or test module is imported in this preflight block.
    import ast  # noqa: F401
    import copy  # noqa: F401
    import contextlib  # noqa: F401
    import ctypes  # noqa: F401
    import dataclasses  # noqa: F401
    import datetime  # noqa: F401
    import importlib.abc  # noqa: F401
    import importlib.machinery  # noqa: F401
    import importlib.util  # noqa: F401
    import inspect  # noqa: F401
    import logging  # noqa: F401
    import math  # noqa: F401
    import ntpath  # noqa: F401
    import queue  # noqa: F401
    import selectors  # noqa: F401
    import struct  # noqa: F401
    import tokenize  # noqa: F401
    import threading  # noqa: F401
    import typing  # noqa: F401
    import uuid  # noqa: F401

    verified = _verify_inputs()
    source_rows = verified["source_rows"]
    test_rows = verified["focused_test_rows"]
    assert type(source_rows) is dict and type(test_rows) is dict
    preload_report, fake_windows_api_counters = _preload_guard_runtime()
    allowed_roots = _install_child_guards(
        basetemp, external_artifact_root, source_rows, test_rows
    )
    selfcheck = _guard_selfcheck(basetemp, allowed_roots)
    guard_counter_baseline = dict(_GUARD_COUNTS)
    namespace_before = _install_selected_runtime_namespace()
    pytest = importlib.import_module("pytest")
    plugin = _OriginAndCountPlugin(
        test_rows, source_rows, basetemp, allowed_roots, pytest_config_path
    )
    test_paths = [str(row["path"]) for row in test_rows.values()]
    pytest_args = [
        "--noconftest",
        "--collect-in-virtualenv",
        "-c",
        str(pytest_config_path),
        "-p",
        "no:asyncio",
        "-p",
        "no:cacheprovider",
        "-o",
        "log_file=" + str(external_artifact_root / "pytest.log"),
        "-o",
        "log_file_level=CRITICAL",
        "-o",
        "addopts=",
        "--assert=plain",
        *test_paths,
        "-q",
        "--tb=short",
        "--basetemp",
        str(basetemp),
        "-s",
    ]
    exit_code = pytest.main(pytest_args, plugins=[plugin])
    guard_counter_after_tests = dict(_GUARD_COUNTS)
    guard_counter_delta = _guard_counter_delta(
        guard_counter_baseline, guard_counter_after_tests
    )

    post_error: str | None = None
    pytest_config_after: dict[str, object] | None = None
    temp_directory_binding_after_tests = bool(
        stdlib_tempdir.is_dir()
        and type(tempfile.tempdir) is str
        and pathlib.Path(tempfile.tempdir).resolve() == stdlib_tempdir.resolve()
        and pathlib.Path(os.environ.get("TEMP", "")).resolve()
        == stdlib_tempdir.resolve()
        and pathlib.Path(os.environ.get("TMP", "")).resolve()
        == stdlib_tempdir.resolve()
        and stdlib_tempdir.resolve() != basetemp.resolve()
    )
    if not temp_directory_binding_after_tests:
        post_error = "stdlib_temp_directory_binding_changed"
    try:
        pytest_config_after = _verify_external_pytest_config(pytest_config_path)
    except Exception as exc:
        post_error = type(exc).__name__ + ":" + str(exc)
    if pytest_config_after != pytest_config_before:
        post_error = "external_pytest_config_changed_during_child_run"
    try:
        _verify_inputs()
    except Exception as exc:
        post_error = type(exc).__name__ + ":" + str(exc)
    plugin._verify_persistent_runtime_modules_after_tests()
    required_sources = set(source_rows)
    required_tests = set(test_rows)
    required_code = required_sources | required_tests
    source_compile_paths = set(_SOURCE_COMPILES)
    source_exec_paths = set(_SOURCE_EXECS)
    module_origins: dict[str, list[str]] = {}
    for module in tuple(sys.modules.values()):
        origin = getattr(module, "__file__", None)
        relative = _relative_repo_path(origin) if origin is not None else None
        if relative in required_sources:
            canonical = _canonical(origin)
            expected = _canonical(REPO_ROOT / relative.replace("/", os.sep))
            if canonical != expected:
                post_error = "loaded_module_origin_mismatch:" + relative
            module_origins.setdefault(relative, []).append(str(origin))

    missing_compile = sorted(required_code - source_compile_paths)
    missing_exec = sorted(required_code - source_exec_paths)
    candidate_module_origin_paths = {
        path
        for path, events in _SOURCE_MODULE_ORIGIN_EVENTS.items()
        if path in required_sources
        and any(
            event.get("module_file_matches_source") is True
            and type(event.get("module_name")) is str
            and event.get("compile_binding_kind")
            in {"selected_source", "selected_source_loader"}
            and event.get("selected_source_exec_observed") is True
            for event in events
        )
    }
    missing_candidate_module_origins = sorted(
        required_sources - candidate_module_origin_paths
    )
    missing_candidate_function_origins = sorted(
        path for path in required_sources if not _SOURCE_FUNCTION_ORIGINS.get(path)
    )
    namespace_after = _selected_runtime_namespace_snapshot()
    if namespace_after.get("valid") is not True:
        post_error = "selected_runtime_namespace_changed"
    unexpected_runtime_source_modules: list[str] = []
    selected_runtime_modules = set(_ACTIVE_GUARD.get("selected_runtime_modules", ()))
    selected_runtime_module_aliases: list[str] = []
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader_runtime" or not name.startswith("backtrader_runtime."):
            continue
        origin = getattr(module, "__file__", None)
        relative = _relative_repo_path(origin) if origin is not None else None
        if (
            relative is not None
            and relative.startswith("backtrader_runtime/")
            and relative not in required_sources
            and name != "backtrader_runtime.unpinned_extra_source_fake"
        ):
            unexpected_runtime_source_modules.append(name + "=" + relative)
        elif (
            relative in required_sources
            and name.startswith("backtrader_runtime.")
            and name not in selected_runtime_modules
        ):
            selected_runtime_module_aliases.append(name + "=" + relative)
    if plugin.origin_error is not None:
        post_error = plugin.origin_error
    if plugin.derived_pytest_config_error is not None:
        post_error = plugin.derived_pytest_config_error
    if plugin.module_binding_error is not None:
        post_error = plugin.module_binding_error
    if missing_compile or missing_exec:
        post_error = "source_origin_events_incomplete"
    if missing_candidate_module_origins:
        post_error = "candidate_module_origin_events_incomplete"
    if missing_candidate_function_origins:
        post_error = "candidate_function_code_origins_incomplete"
    if unexpected_runtime_source_modules:
        post_error = "unselected_runtime_source_module_loaded"

    report = {
        "schema": "iteration41-simnow-c01-v20-parent-formal-root-qa-child-r7",
        "status": "PASS_SOURCE_FAKE_ONLY"
        if (
            int(exit_code) == 0
            and plugin.summary.get("exact_outcome_gate") is True
            and preload_report.get("warning_count") == 0
            and preload_report.get("candidate_modules_absent_before_and_after") is True
            and preload_report.get("fake_ctypes_bindings_preserved") is True
            and preload_report.get("actual_winapi_calls") is False
            and guard_counter_delta.get("valid") is True
            and plugin.origin_error is None
            and plugin.derived_pytest_config_error is None
            and plugin.module_binding_error is None
            and pytest_config_after == pytest_config_before
            and temp_directory_binding_after_tests
            and post_error is None
            and not missing_compile
            and not missing_exec
            and not missing_candidate_module_origins
            and not missing_candidate_function_origins
        )
        else "SOURCE_FAKE_FAILED_OR_BLOCKED",
        "pytest_exit_code": int(exit_code),
        "external_pytest_artifact_root": str(external_artifact_root),
        "stdlib_temp_directory": str(stdlib_tempdir),
        "temp_directory_binding_pre_valid": temp_directory_binding_pre_valid,
        "temp_directory_binding_after_tests": temp_directory_binding_after_tests,
        "pytest_basetemp": str(basetemp),
        "pytest_log_path": str(external_artifact_root / "pytest.log"),
        "pytest_summary": plugin.summary,
        "pytest_config_file_before": pytest_config_before,
        "pytest_config_file_after": pytest_config_after,
        "derived_pytest_config": plugin.derived_pytest_config,
        "windows_pytest_startup_preload": preload_report,
        "fake_windows_console_api_counters": dict(fake_windows_api_counters),
        "guard_counter_delta_gate": guard_counter_delta,
        "derived_pytest_config_error": plugin.derived_pytest_config_error,
        "pytest_args": pytest_args,
        "source_count": len(source_rows),
        "test_input_count": len(test_rows),
        "source_compile_origins": {
            path: {
                "origin": str(REPO_ROOT / path.replace("/", os.sep)),
                "count": _SOURCE_COMPILES.get(path, 0),
                "sha256": str(source_rows[path]["sha256"]),
            }
            for path in sorted(source_rows)
        },
        "test_compile_origins": {
            path: {
                "origin": str(REPO_ROOT / path.replace("/", os.sep)),
                "count": _SOURCE_COMPILES.get(path, 0),
                "sha256": str(test_rows[path]["sha256"]),
            }
            for path in sorted(test_rows)
        },
        "source_exec_origins": {
            path: {
                "origin": str(REPO_ROOT / path.replace("/", os.sep)),
                "count": _SOURCE_EXECS.get(path, 0),
            }
            for path in sorted(source_rows)
        },
        "test_exec_origins": {
            path: {
                "origin": str(REPO_ROOT / path.replace("/", os.sep)),
                "count": _SOURCE_EXECS.get(path, 0),
            }
            for path in sorted(test_rows)
        },
        "candidate_function_code_origins": {
            path: {
                "origin": str(REPO_ROOT / path.replace("/", os.sep)),
                "function_code_names": sorted(_SOURCE_FUNCTION_ORIGINS.get(path, set())),
                "count": len(_SOURCE_FUNCTION_ORIGINS.get(path, set())),
            }
            for path in sorted(required_sources)
        },
        "candidate_module_origin_events": {
            path: _SOURCE_MODULE_ORIGIN_EVENTS.get(path, [])
            for path in sorted(required_sources)
        },
        "test_fixture_source_events": {
            path: list(events)
            for path, events in sorted(_TEST_FIXTURE_SOURCE_EVENTS.items())
        },
        "missing_candidate_module_origins": missing_candidate_module_origins,
        "missing_candidate_function_origins": missing_candidate_function_origins,
        "loaded_module_origins": module_origins,
        "unexpected_runtime_source_modules": sorted(
            unexpected_runtime_source_modules
        ),
        "selected_runtime_module_aliases": sorted(selected_runtime_module_aliases),
        "selected_runtime_module_allowlist": sorted(selected_runtime_modules),
        "selected_runtime_namespace_before": namespace_before,
        "selected_runtime_namespace_after": namespace_after,
        "persistent_canonical_runtime_modules": {
            "required": PERSISTENT_CANONICAL_RUNTIME_MODULES,
            "at_collection_capture": plugin.persistent_runtime_module_capture,
            "after_tests": plugin.persistent_runtime_module_post,
            "aliases_at_collection_capture": plugin.runtime_aliases_at_capture,
            "aliases_after_tests": plugin.runtime_aliases_after_tests,
            "ephemeral_aliases_absent_at_capture": (
                plugin.ephemeral_aliases_absent_at_capture
            ),
            "ephemeral_aliases_absent_after_tests": (
                plugin.ephemeral_aliases_absent_after_tests
            ),
            "ephemeral_alias_names": sorted(
                (
                    set(_ACTIVE_GUARD.get("selected_runtime_modules", ()))
                    | set(EPHEMERAL_RUNTIME_MODULE_NAMES)
                )
                - set(PERSISTENT_CANONICAL_RUNTIME_MODULES)
                - {"backtrader_runtime"}
            ),
            "error": plugin.module_binding_error,
        },
        "selected_package_namespace_mode": (
            "SOURCE_FAKE_SELECTED_MODULE_NAMESPACE_ONLY"
        ),
        "initializer_module_origin_executed": False,
        "initializer_compile_count": _SOURCE_COMPILES.get(
            "backtrader_runtime/__init__.py", 0
        ),
        "initializer_exec_count": _SOURCE_EXECS.get(
            "backtrader_runtime/__init__.py", 0
        ),
        "test_origins": plugin.test_origins,
        "missing_source_compile_origins": missing_compile,
        "missing_source_exec_origins": missing_exec,
        "guard_selfchecks": selfcheck,
        "guard_denial_counts_after_tests": dict(sorted(_GUARD_COUNTS.items())),
        "child_logs": {
            name: writer.diagnostics()
            for name, writer in _CHILD_LOG_WRITERS.items()
        },
        "post_input_error": post_error,
        "evidence_limit": (
            "SOURCE_FAKE_ONLY; this child did not invoke Root activation and "
            "did not access private inputs, external opaque/software payloads, "
            "native SDKs, WinAPI, network, real process, or real Pipe APIs."
        ),
        "metadata_probe_scope_limit": EXPECTED_METADATA_PROBE_SCOPE_LIMIT,
    }
    _write_json(OUTPUT_DIR / "child-qa-result.json", report)
    return 0 if report["status"] == "PASS_SOURCE_FAKE_ONLY" else 2


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        if (
            len(sys.argv) != 10
            or sys.argv[2] != "--basetemp"
            or sys.argv[4] != "--stdout-log"
            or sys.argv[6] != "--stderr-log"
            or sys.argv[8] != "--pytest-config"
        ):
            raise RuntimeError("child_command_shape_invalid")
        if _canonical(sys.executable) != _canonical(EXPECTED_PYTHON):
            raise RuntimeError("child_interpreter_mismatch")
        return _child_main(sys.argv[3], sys.argv[5], sys.argv[7], sys.argv[9])
    if len(sys.argv) != 1:
        raise RuntimeError("parent_command_shape_invalid")
    return _parent_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        child_mode = len(sys.argv) > 1 and sys.argv[1] == "--child"
        failure = {
            "schema": (
                "iteration41-simnow-c01-v20-parent-formal-root-qa-child-r7"
                if child_mode
                else "iteration41-simnow-c01-v20-parent-formal-root-qa-result-r7"
            ),
            "status": "CHILD_HARNESS_BLOCKED" if child_mode else "HARNESS_BLOCKED",
            "reason": type(exc).__name__ + ":" + str(exc),
        }
        try:
            result_name = "child-qa-result.json" if child_mode else "root-qa-result.json"
            _write_json(OUTPUT_DIR / result_name, failure)
        except Exception:
            pass
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        raise SystemExit(2)
