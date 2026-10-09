"""Root-run, guarded QA for the frozen V20 source-fake preparation packet.

This runner executes only the pinned 12-test source-fake file. It denies
private/config reads, software payload reads, native loading, provider imports,
network access, and child-process creation. It never invokes the credential-
free gate or C01 activation.
"""

from __future__ import annotations

import ctypes
import hashlib
import importlib.abc
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
import time
from types import ModuleType
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[7]
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
QA_PACKET = EVIDENCE / "iteration41-simnow-c01-v20-root-preparation-source-qa-r6-2026-10-09"
R1_PACKET = EVIDENCE / "iteration41-simnow-c01-v20-root-preparation-source-qa-r1-2026-10-09"
R5_PACKET = EVIDENCE / "iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09"
R1_REVIEW_PATH = EVIDENCE / (
    "iteration41-simnow-c01-v20-root-preparation-source-qa-r1-independent-static-review-2026-10-09/README.md"
)
REVIEW_PATH = EVIDENCE / (
    "iteration41-simnow-c01-v20-root-credential-free-caller-r5-independent-static-review-r1-2026-10-09/README.md"
)
R1_PIN_COPY = QA_PACKET / "inputs/r1-artifact-pins.json"
R1_REVIEW_COPY = QA_PACKET / "inputs/r1-independent-static-review.md"
R5_PIN_COPY = QA_PACKET / "inputs/r5-artifact-pins.json"
SOURCE_PIN_COPY = QA_PACKET / "inputs/r5-runtime-source-pins.json"
REVIEW_COPY = QA_PACKET / "inputs/r5-independent-static-review.md"
QA_ARTIFACT_PINS = QA_PACKET / "artifact-pins.json"
QA_CONFIG = QA_PACKET / "pytest.ini"
TEST_RELATIVE = (
    "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/"
    "iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09/"
    "test_root_gate_host_preparation_source_fake.py"
)

_SELECTED_TEST_NAMES = frozenset(
    {
        "test_unretained_host_cleanup_preserves_preexisting_cuv2_alias",
        "test_exact_source_components_are_pinned_and_precheck_is_bounded",
        "test_precheck_driver_snapshot_matches_outer_source_capture",
        "test_module_aliases_are_fixed_for_the_driver_and_v20_rows",
        "test_dependency_order_loads_exact_imports_before_consumers",
        "test_package_shell_does_not_execute_or_search_package_initializers",
        "test_exact_component_loader_compiles_only_the_supplied_bytes",
        "test_cuv2_pin_failure_precedes_precheck_and_any_lease_entry",
        "test_caller_rejects_old_or_unpinned_precheck_before_gate_call",
        "test_alias_preflight_rejects_preexisting_module_without_replacing_it",
        "test_source_root_comparison_uses_driver_normcase_and_normpath",
        "test_full_preparation_uses_real_driver_lease_binder_and_precheck_validator",
    }
)
_AUDIT_EVENT_NAMES = frozenset(
    {
        "open",
        "os.rename",
        "os.replace",
        "os.remove",
        "os.rmdir",
        "os.chmod",
        "os.mkdir",
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.exec",
        "socket.connect",
        "socket.connect_ex",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyaddr",
        "socket.bind",
        "ctypes.dlopen",
        "_winapi.CreateProcess",
    }
)
_DIAGNOSTIC_EXCEPTION_CLASSES = frozenset(
    {
        "AssertionError",
        "AttributeError",
        "FileNotFoundError",
        "GuardViolation",
        "ImportError",
        "ModuleNotFoundError",
        "OSError",
        "RuntimeError",
        "TypeError",
        "ValueError",
    }
)
_DIAGNOSTIC_PHASES = frozenset({"setup", "call", "teardown", "other_phase"})
_DIAGNOSTIC_FRAME_LABELS = frozenset(
    {"qa_runner", "test_source", "pinned_public_source", "qa_runtime"}
)

EXPECTED_R5_ARTIFACT_PINS = "62ddd86cc141a4b94dbe5eee6736c7b13099133f890e77a0f931f90d31bfef16"
EXPECTED_SOURCE_PINS = "e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387"
EXPECTED_REVIEW = "4dd6725c42dfc2b8f8ef6a2d8cb7952f4bde27a7995fb867fd6e916eab6fbfba"
EXPECTED_R1_ARTIFACT_PINS = "6e512153dfecc182a2fe772f4b4be445b7dc7702a329e321825167e88346fe2b"
EXPECTED_R1_REVIEW = "a0969324876b9bf3cbe9f005a70300dc568719517b5165e743d88d3f2d5b39aa"
EXPECTED_QA_TEST_COUNT = 12
EXPECTED_HEAD_OID = "902d55daa397d601a947141b6a87eb1ca1df4d0a"
EXPECTED_HEAD_REF = "refs/heads/dev"
EXPECTED_HEAD_FILE_SHA256 = "bda77d7d12a90332080071375095fb080d8cd2a6702e6ee44552863a0ca4317e"
EXPECTED_INDEX_BYTES = 2863553
EXPECTED_INDEX_ENTRY_COUNT = 13505
EXPECTED_INDEX_SHA256 = "b555903584c1b95e5f0da20fcef2fe87095bf608cd12a97e8b5e45b2af5a189b"
EXPECTED_QA_INTERPRETER = r"D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe"
QA_RUNTIME_ROOT = Path(r"D:\temp\iteration41-main-source-qa-20260926\venv")
EXPECTED_QA_PACKET_FILES = frozenset(
    {
        "README.md",
        "inputs/r1-artifact-pins.json",
        "inputs/r1-independent-static-review.md",
        "inputs/r5-artifact-pins.json",
        "inputs/r5-independent-static-review.md",
        "inputs/r5-runtime-source-pins.json",
        "pytest.ini",
        "qa/command.txt",
        "result-schema.json",
        "run_root_preparation_source_qa.py",
    }
)

_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "bt_api_base",
        "bt_api_ctp",
        "bt_api_execution",
        "bt_api_py",
        "ctpbeebt",
        "ctp_wrap",
        "thostmduserapi",
        "thosttraderapi",
    }
)
_SENSITIVE_NAMES = frozenset({".env", "config.yaml", "secrets.yaml"})
_PRIVATE_DIRECTORY_NAMES = frozenset({"capture", "captures", "private-capture", "private-captures"})
_BLOCKED_SOFTWARE_PATHS = frozenset(
    {
        "c:/anaconda3/python.exe",
        "c:/anaconda3/python311.dll",
        "d:/temp/iteration41-root-public-custody-v2.py",
    }
)


class GuardViolation(RuntimeError):
    """A forbidden operation was attempted; the category is safe to report."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class _Guard:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.attempts: list[str] = []
        self.denied_events: list[dict[str, Any]] = []
        self._active_event: str | None = None
        self.allowed_roots = tuple(
            path.resolve()
            for path in {
                ROOT.resolve(),
                Path(sys.prefix).resolve(),
                Path(sys.base_prefix).resolve(),
                QA_RUNTIME_ROOT.resolve(),
            }
        )

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _deny(
        self,
        category: str,
        *,
        event_name: str | None = None,
        extended_local_drive_prefix: bool = False,
        normalized_to_run_dir: bool = False,
    ) -> None:
        self.attempts.append(category)
        selected_event = event_name or self._active_event or "guarded_operation"
        if selected_event not in _AUDIT_EVENT_NAMES and selected_event not in {
            "module_import",
            "native_loader",
            "process_creation_api",
            "network_api",
            "guarded_operation",
        }:
            selected_event = "other_guarded_event"
        self.denied_events.append(
            {
                "category": category,
                "event": selected_event,
                "extended_local_drive_prefix": bool(extended_local_drive_prefix),
                "normalized_to_run_dir": bool(normalized_to_run_dir),
            }
        )
        raise GuardViolation(category)

    def _check_default_dir_fds(self, args: tuple[Any, ...], indexes: tuple[int, ...]) -> None:
        for index in indexes:
            if index < len(args):
                value = args[index]
                if value is not None and not (type(value) is int and value == -1):
                    self._deny("path_dir_fd_unverifiable")

    def _path(self, value: Any) -> Path | None:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return None
        try:
            return Path(os.fsdecode(value)).resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            self._deny("unresolvable_file_path")
        return None

    @staticmethod
    def _is_local_extended_drive_path(value: Any) -> bool:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        try:
            raw = os.fsdecode(value)
        except (TypeError, ValueError):
            return False
        return bool(re.match(r"^\\\\\?\\[A-Za-z]:\\", raw))

    def _path_resolves_inside_run_dir(self, value: Any, *, extended: bool) -> bool:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return False
        try:
            raw = os.fsdecode(value)
            if extended:
                raw = raw[4:]
            candidate = Path(raw).resolve(strict=False)
            return self._inside(candidate, self.run_dir)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def _check_file(self, value: Any, mode: Any = "r", flags: Any = None) -> None:
        extended_local_drive_prefix = self._is_local_extended_drive_path(value)
        normalized_to_run_dir = self._path_resolves_inside_run_dir(
            value, extended=extended_local_drive_prefix
        )

        def deny(category: str) -> None:
            self._deny(
                category,
                extended_local_drive_prefix=extended_local_drive_prefix,
                normalized_to_run_dir=normalized_to_run_dir,
            )

        path = self._path(value)
        if path is None:
            return
        normalized = os.path.normcase(str(path)).replace("\\", "/").casefold()
        in_qa_runtime = self._inside(path, QA_RUNTIME_ROOT.resolve())
        if normalized in _BLOCKED_SOFTWARE_PATHS or (
            normalized.startswith("d:/temp/") and not in_qa_runtime
        ):
            deny("software_payload_access")
        if path.name.casefold() in _SENSITIVE_NAMES:
            deny("private_config_access")
        if any(part.casefold() in _PRIVATE_DIRECTORY_NAMES for part in path.parts):
            deny("private_capture_access")
        if not any(self._inside(path, root) for root in self.allowed_roots) and not self._inside(
            path, self.run_dir
        ):
            deny("file_outside_public_qa_roots")
        writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
        if type(mode) is int:
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            writing = bool(mode & write_flags)
        if type(flags) is int:
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            writing = writing or bool(flags & write_flags)
        if writing:
            if not self._inside(path, self.run_dir):
                deny("write_outside_qa_output")

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        previous_event = self._active_event
        self._active_event = event if event in _AUDIT_EVENT_NAMES else "other_guarded_event"
        try:
            if event == "open" and args:
                mode = args[1] if len(args) > 1 else "r"
                flags = args[2] if len(args) > 2 else None
                self._check_file(args[0], mode, flags)
            elif event in {"subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "os.fork", "os.exec"}:
                self._deny("process_creation")
            elif event in {
                "socket.connect",
                "socket.connect_ex",
                "socket.sendto",
                "socket.sendmsg",
                "socket.getaddrinfo",
                "socket.gethostbyname",
                "socket.gethostbyaddr",
                "socket.bind",
            }:
                self._deny("network_access")
            elif event == "ctypes.dlopen":
                self._deny("native_library_load")
            elif event == "_winapi.CreateProcess":
                self._deny("win32_process_creation")
            elif event in {"os.rename", "os.replace"} and len(args) >= 2:
                self._check_default_dir_fds(args, (2, 3))
                self._check_file(args[0], "w")
                self._check_file(args[1], "w")
            elif event in {"os.remove", "os.rmdir"} and args:
                self._check_default_dir_fds(args, (1,))
                self._check_file(args[0], "w")
            elif event in {"os.chmod", "os.mkdir"} and args:
                self._check_default_dir_fds(args, (2,))
                self._check_file(args[0], "w")
        finally:
            self._active_event = previous_event


class _NoProviderImports(importlib.abc.MetaPathFinder):
    def __init__(self, guard: _Guard) -> None:
        self._guard = guard

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        root = fullname.split(".", 1)[0].casefold()
        if root in _FORBIDDEN_IMPORT_ROOTS or root.startswith("bt_api_"):
            self._guard._deny("provider_or_sdk_import", event_name="module_import")
        return None


def _install_inert_colorama_facade() -> None:
    if "colorama" in sys.modules:
        raise ValueError("colorama_preloaded_before_guard")

    def no_op(*args: Any, **kwargs: Any) -> None:
        del args, kwargs

    class InertAnsiToWin32:
        def __init__(self, wrapped: Any, **kwargs: Any) -> None:
            del kwargs
            self.wrapped = wrapped
            self.stream = wrapped
            self.strip = True
            self.convert = False
            self.should_wrap = False

        def write(self, value: str) -> Any:
            return self.wrapped.write(value)

        def flush(self) -> Any:
            return self.wrapped.flush()

    class EmptyAnsiCodes:
        def __getattr__(self, name: str) -> str:
            del name
            return ""

    module = ModuleType("colorama")
    module.__dict__.update(
        {
            "__path__": [],
            "__version__": "qa-inert-facade",
            "just_fix_windows_console": no_op,
            "init": no_op,
            "deinit": no_op,
            "reinit": no_op,
            "AnsiToWin32": InertAnsiToWin32,
            "Fore": EmptyAnsiCodes(),
            "Back": EmptyAnsiCodes(),
            "Style": EmptyAnsiCodes(),
        }
    )
    sys.modules["colorama"] = module


class _Counts:
    def __init__(
        self,
        guard: _Guard,
        *,
        public_source_paths: set[str],
        test_path: Path,
        runner_path: Path,
    ) -> None:
        self._guard = guard
        self._public_source_paths = public_source_paths
        self._test_path = os.path.normcase(os.path.normpath(str(test_path.resolve())))
        self._runner_path = os.path.normcase(os.path.normpath(str(runner_path.resolve())))
        self._event_offsets: dict[int, int] = {}
        self.failure_diagnostics: list[dict[str, Any]] = []
        self.collected = 0
        self.nodeids: list[str] = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.xfailed = 0
        self.xpassed = 0
        self.errors = 0
        self.deselected = 0
        self.warnings: dict[str, int] = {}

    def pytest_collection_finish(self, session: Any) -> None:
        self.collected = len(session.items)
        self.nodeids = [str(item.nodeid) for item in session.items]

    def pytest_deselected(self, items: list[Any]) -> None:
        self.deselected += len(items)

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when == "call":
            if getattr(report, "wasxfail", False):
                if report.outcome == "skipped":
                    self.xfailed += 1
                else:
                    self.xpassed += 1
            if report.outcome == "passed":
                self.passed += 1
            elif report.outcome == "failed":
                self.failed += 1
            elif report.outcome == "skipped":
                self.skipped += 1
        elif report.failed:
            self.errors += 1

    def pytest_runtest_setup(self, item: Any) -> None:
        self._event_offsets[id(item)] = len(self._guard.denied_events)

    def _frame_label(self, filename: Any) -> str | None:
        if type(filename) is not str:
            return None
        try:
            normalized = os.path.normcase(os.path.normpath(str(Path(filename).resolve(strict=False))))
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        if normalized == self._test_path:
            return "test_source"
        if normalized == self._runner_path:
            return "qa_runner"
        if normalized in self._public_source_paths:
            return "pinned_public_source"
        try:
            candidate = Path(normalized)
            if _Guard._inside(candidate, QA_RUNTIME_ROOT.resolve()):
                return "qa_runtime"
        except (OSError, RuntimeError, TypeError, ValueError):
            return None
        return None

    def _safe_frames(self, excinfo: Any) -> list[dict[str, Any]]:
        frames: list[dict[str, Any]] = []
        try:
            entries = list(excinfo.traceback)
        except (AttributeError, TypeError, ValueError):
            return frames
        for entry in entries[-16:]:
            try:
                code = entry.frame.code.raw
                label = self._frame_label(code.co_filename)
                name = code.co_name
                line = entry.lineno + 1
            except (AttributeError, TypeError, ValueError):
                continue
            if (
                label not in _DIAGNOSTIC_FRAME_LABELS
                or type(name) is not str
                or len(name) > 96
                or re.fullmatch(r"[A-Za-z0-9_<>.]+", name) is None
                or type(line) is not int
                or line < 1
            ):
                continue
            frames.append({"source": label, "function": name, "line": line})
        return frames

    def pytest_runtest_makereport(self, item: Any, call: Any):
        outcome = yield
        report = outcome.get_result()
        if not report.failed:
            return
        raw_nodeid = str(getattr(item, "nodeid", ""))
        test_name = raw_nodeid.rsplit("::", 1)[-1]
        nodeid = (
            f"test_root_gate_host_preparation_source_fake.py::{test_name}"
            if test_name in _SELECTED_TEST_NAMES
            else "unrecognized_selected_node"
        )
        phase = getattr(report, "when", None)
        if phase not in _DIAGNOSTIC_PHASES:
            phase = "other_phase"
        excinfo = getattr(call, "excinfo", None)
        raw_exception_class = type(getattr(excinfo, "value", None)).__name__ if excinfo else ""
        exception_class = (
            raw_exception_class
            if raw_exception_class in _DIAGNOSTIC_EXCEPTION_CLASSES
            else "other_exception"
        )
        offset = self._event_offsets.get(id(item), len(self._guard.denied_events))
        denied_events = [dict(row) for row in self._guard.denied_events[offset:]][:12]
        self._event_offsets[id(item)] = len(self._guard.denied_events)
        self.failure_diagnostics.append(
            {
                "nodeid": nodeid,
                "phase": phase,
                "exception_class": exception_class,
                "denied_events": denied_events,
                "frames": self._safe_frames(excinfo) if excinfo else [],
            }
        )

    def pytest_warning_recorded(self, warning_message: Any, when: str, nodeid: str, location: Any) -> None:
        category = type(warning_message.message).__name__
        self.warnings[category] = self.warnings.get(category, 0) + 1


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path_under(path: Path, allowed_root: Path) -> Path:
    resolved = path.resolve(strict=True)
    root = allowed_root.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("pinned_path_outside_expected_root") from exc
    if not resolved.is_file():
        raise ValueError("pinned_path_not_file")
    return resolved


def _read_pinned(
    path: Path, expected_bytes: int, expected_sha256: str, *, allowed_root: Path
) -> bytes:
    if type(expected_bytes) is not int or expected_bytes < 0:
        raise ValueError("invalid_expected_size")
    if type(expected_sha256) is not str or len(expected_sha256) != 64:
        raise ValueError("invalid_expected_sha256")
    if any(character not in "0123456789abcdef" for character in expected_sha256):
        raise ValueError("invalid_expected_sha256")
    checked_path = _path_under(path, allowed_root)
    if checked_path.stat().st_size != expected_bytes:
        raise ValueError("pinned_file_size_mismatch")
    with checked_path.open("rb") as stream:
        raw = stream.read(expected_bytes + 1)
    if len(raw) != expected_bytes or _sha(raw) != expected_sha256:
        raise ValueError("pinned_file_hash_mismatch")
    return raw


def _relative_path(value: str) -> PurePosixPath:
    if type(value) is not str or "\\" in value or ":" in value:
        raise ValueError("invalid_relative_path")
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.as_posix() != value
    ):
        raise ValueError("invalid_relative_path")
    return relative


def _read_metadata_inputs() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]
]:
    r1_artifact_bytes = _read_pinned(
        R1_PIN_COPY, 1394, EXPECTED_R1_ARTIFACT_PINS, allowed_root=QA_PACKET
    )
    _read_pinned(R1_REVIEW_COPY, 3542, EXPECTED_R1_REVIEW, allowed_root=QA_PACKET)
    _read_pinned(R1_REVIEW_PATH, 3542, EXPECTED_R1_REVIEW, allowed_root=EVIDENCE)
    r5_artifact_bytes = _read_pinned(
        R5_PIN_COPY, 1437, EXPECTED_R5_ARTIFACT_PINS, allowed_root=QA_PACKET
    )
    source_pin_bytes = _read_pinned(
        SOURCE_PIN_COPY, 9069, EXPECTED_SOURCE_PINS, allowed_root=QA_PACKET
    )
    _read_pinned(REVIEW_COPY, 2519, EXPECTED_REVIEW, allowed_root=QA_PACKET)
    _read_pinned(REVIEW_PATH, 2519, EXPECTED_REVIEW, allowed_root=EVIDENCE)
    r1_artifacts = json.loads(r1_artifact_bytes)
    artifacts = json.loads(r5_artifact_bytes)
    source_manifest = json.loads(source_pin_bytes)
    if (
        r1_artifacts.get("schema")
        != "iteration41.simnow.c01.v20.root-preparation-source-qa-artifact-pins.r1"
        or type(r1_artifacts.get("artifact_count")) is not int
        or r1_artifacts.get("artifact_count") != 8
        or type(r1_artifacts.get("artifacts")) is not list
        or len(r1_artifacts["artifacts"]) != 8
    ):
        raise ValueError("r1_packet_artifact_count_invalid")
    if (
        artifacts.get("schema")
        != "iteration41-simnow-c01-v20-root-preparation-composition-artifact-pins-r2"
        or type(artifacts.get("artifact_count")) is not int
        or artifacts.get("artifact_count") != 8
        or type(artifacts.get("artifacts")) is not list
        or len(artifacts["artifacts"]) != 8
    ):
        raise ValueError("r5_packet_artifact_count_invalid")
    rows = source_manifest.get("public_source_rows")
    if (
        source_manifest.get("schema") != "iteration41-simnow-c01-v20-credential-free-job-channel-source-pins-r3"
        or type(source_manifest.get("parent_module_source_count")) is not int
        or source_manifest.get("parent_module_source_count") != 26
        or type(source_manifest.get("child_frame_source_count")) is not int
        or source_manifest.get("child_frame_source_count") != 23
        or type(rows) is not list
        or len(rows) != 26
    ):
        raise ValueError("public_source_map_shape_invalid")
    paths = [row.get("path") for row in rows]
    if len(set(paths)) != 26:
        raise ValueError("public_source_paths_not_unique")
    expected_software = [
        {
            "body_included": False,
            "name": "fixed CPython executable",
            "path": "C:/anaconda3/python.exe",
            "sha256": "c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642",
        },
        {
            "body_included": False,
            "name": "fixed CPython runtime DLL",
            "path": "C:/anaconda3/python311.dll",
            "sha256": "162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00",
        },
        {
            "body_included": False,
            "bytes": 2344,
            "name": "fixed CUv2 held-source helper",
            "path": "D:/temp/iteration41-root-public-custody-v2.py",
            "sha256": "e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246",
        },
    ]
    if source_manifest.get("software_source_rows") != expected_software:
        raise ValueError("software_metadata_rows_invalid")
    if source_manifest.get("status") != "SOURCE_FAKE_ONLY":
        raise ValueError("source_manifest_status_invalid")
    return r1_artifacts, artifacts, source_manifest, rows


def _verify_qa_packet() -> tuple[dict[str, Any], dict[str, Any], str]:
    manifest_raw = _read_small(QA_ARTIFACT_PINS, 64 * 1024)
    manifest = json.loads(manifest_raw)
    artifacts = manifest.get("artifacts")
    if (
        manifest.get("schema")
        != "iteration41.simnow.c01.v20.root-preparation-source-qa-artifact-pins.r6"
        or type(manifest.get("artifact_count")) is not int
        or manifest.get("artifact_count") != 10
        or type(artifacts) is not list
        or len(artifacts) != 10
    ):
        raise ValueError("qa_packet_artifact_count_invalid")
    paths = [_relative_path(item.get("path")).as_posix() for item in artifacts]
    if len(set(paths)) != len(paths) or set(paths) != EXPECTED_QA_PACKET_FILES:
        raise ValueError("qa_packet_artifact_paths_invalid")
    schema_item = next(item for item in artifacts if item.get("path") == "result-schema.json")
    schema_raw: bytes | None = None
    for item in artifacts:
        relative = _relative_path(item.get("path"))
        candidate = QA_PACKET.joinpath(*relative.parts)
        raw = _read_pinned(
            candidate,
            item.get("bytes"),
            item.get("sha256"),
            allowed_root=QA_PACKET,
        )
        if item is schema_item:
            schema_raw = raw
    if schema_raw is None:
        raise ValueError("qa_result_schema_missing")
    schema = json.loads(schema_raw)
    if (
        schema.get("schema")
        != "iteration41.simnow.c01.v20.root-preparation-source-qa-result-schema.r3"
        or schema.get("result_schema")
        != "iteration41.simnow.c01.v20.root-preparation-source-qa.r3"
    ):
        raise ValueError("qa_result_schema_version_invalid")
    return manifest, schema, _sha(manifest_raw)


def _qa_interpreter_matches() -> bool:
    if (
        os.name != "nt"
        or not sys.flags.isolated
        or not sys.flags.dont_write_bytecode
        or not sys.dont_write_bytecode
        or sys.flags.utf8_mode != 1
        or sys.flags.no_site
        or sys.argv[1:]
    ):
        return False
    observed = os.path.normcase(os.path.normpath(sys.executable))
    expected = os.path.normcase(os.path.normpath(EXPECTED_QA_INTERPRETER))
    return observed == expected


def _repository_checkpoint_matches(value: dict[str, Any]) -> bool:
    return (
        type(value.get("head_ref")) is str
        and value.get("head_ref") == EXPECTED_HEAD_REF
        and type(value.get("head_oid")) is str
        and value.get("head_oid") == EXPECTED_HEAD_OID
        and type(value.get("head_file_sha256")) is str
        and value.get("head_file_sha256") == EXPECTED_HEAD_FILE_SHA256
        and type(value.get("index_bytes")) is int
        and value.get("index_bytes") == EXPECTED_INDEX_BYTES
        and type(value.get("index_entry_count")) is int
        and value.get("index_entry_count") == EXPECTED_INDEX_ENTRY_COUNT
        and type(value.get("index_sha256")) is str
        and value.get("index_sha256") == EXPECTED_INDEX_SHA256
    )


def _repository_checkpoint_contract_selfcheck() -> bool:
    baseline = {
        "head_ref": EXPECTED_HEAD_REF,
        "head_oid": EXPECTED_HEAD_OID,
        "head_file_sha256": EXPECTED_HEAD_FILE_SHA256,
        "index_bytes": EXPECTED_INDEX_BYTES,
        "index_entry_count": EXPECTED_INDEX_ENTRY_COUNT,
        "index_sha256": EXPECTED_INDEX_SHA256,
    }
    if not _repository_checkpoint_matches(baseline):
        return False
    rejected = []
    for field, invalid_value in (
        ("head_ref", "refs/heads/other"),
        ("head_oid", "0" * 40),
        ("index_bytes", 0),
        ("index_entry_count", 0),
        ("index_sha256", "0" * 64),
        ("index_bytes", True),
        ("index_entry_count", False),
    ):
        changed = dict(baseline)
        changed[field] = invalid_value
        rejected.append(not _repository_checkpoint_matches(changed))
    return all(rejected)


def _validate_result_schema(result: dict[str, Any], schema: dict[str, Any]) -> None:
    required = schema.get("required_keys")
    types = schema.get("types")
    if (
        type(required) is not list
        or any(type(key) is not str for key in required)
        or len(set(required)) != len(required)
        or type(types) is not dict
        or set(types) != set(required)
        or set(result) != set(required)
    ):
        raise ValueError("qa_result_schema_keys_invalid")

    def matches(value: Any, kind: str) -> bool:
        if kind == "str":
            return type(value) is str
        if kind == "bool":
            return type(value) is bool
        if kind == "int":
            return type(value) is int
        if kind == "number":
            return type(value) in {int, float}
        if kind == "dict":
            return type(value) is dict
        if kind == "list":
            return type(value) is list
        if kind == "nullable_int":
            return value is None or type(value) is int
        if kind == "nullable_str":
            return value is None or type(value) is str
        return False

    for key, kind in types.items():
        if not matches(result[key], kind):
            raise ValueError("qa_result_schema_type_invalid")
    constants = schema.get("constant_values")
    if type(constants) is not dict or any(
        key not in result
        or type(result[key]) is not type(value)
        or result[key] != value
        for key, value in constants.items()
    ):
        raise ValueError("qa_result_schema_constant_invalid")
    if result.get("status") not in schema.get("status_values", ()):
        raise ValueError("qa_result_schema_status_invalid")

    count_keys = schema.get("count_keys")
    counts = result.get("counts")
    if (
        type(count_keys) is not list
        or type(counts) is not dict
        or set(counts) != set(count_keys)
        or any(type(counts[key]) is not int or counts[key] < 0 for key in count_keys)
    ):
        raise ValueError("qa_result_schema_counts_invalid")
    for map_key in ("warnings_by_category", "guard_attempts_by_category"):
        values = result.get(map_key)
        if type(values) is not dict or any(
            type(key) is not str or type(count) is not int or count < 0
            for key, count in values.items()
        ):
            raise ValueError("qa_result_schema_category_map_invalid")
    if result.get("warning_count") != sum(result["warnings_by_category"].values()):
        raise ValueError("qa_result_schema_warning_count_invalid")

    diagnostics = result.get("failure_diagnostics")
    diagnostic_keys = schema.get("failure_diagnostic_keys")
    event_keys = schema.get("failure_event_keys")
    frame_keys = schema.get("failure_frame_keys")
    allowed_nodes = schema.get("selected_nodeids")
    allowed_categories = schema.get("diagnostic_guard_categories")
    allowed_events = schema.get("diagnostic_event_names")
    allowed_exceptions = schema.get("diagnostic_exception_classes")
    if (
        type(diagnostics) is not list
        or len(diagnostics) > EXPECTED_QA_TEST_COUNT * 3
        or type(diagnostic_keys) is not list
        or type(event_keys) is not list
        or type(frame_keys) is not list
        or type(allowed_nodes) is not list
        or type(allowed_categories) is not list
        or type(allowed_events) is not list
        or type(allowed_exceptions) is not list
    ):
        raise ValueError("qa_result_failure_diagnostics_invalid")
    for diagnostic in diagnostics:
        if (
            type(diagnostic) is not dict
            or set(diagnostic) != set(diagnostic_keys)
            or diagnostic.get("nodeid") not in allowed_nodes
            or diagnostic.get("phase") not in _DIAGNOSTIC_PHASES
            or diagnostic.get("exception_class") not in allowed_exceptions
            or type(diagnostic.get("denied_events")) is not list
            or len(diagnostic["denied_events"]) > 12
            or type(diagnostic.get("frames")) is not list
            or len(diagnostic["frames"]) > 16
        ):
            raise ValueError("qa_result_failure_diagnostic_fields_invalid")
        for event in diagnostic["denied_events"]:
            if (
                type(event) is not dict
                or set(event) != set(event_keys)
                or event.get("category") not in allowed_categories
                or event.get("event") not in allowed_events
                or type(event.get("extended_local_drive_prefix")) is not bool
                or type(event.get("normalized_to_run_dir")) is not bool
            ):
                raise ValueError("qa_result_failure_event_invalid")
        for frame in diagnostic["frames"]:
            if (
                type(frame) is not dict
                or set(frame) != set(frame_keys)
                or frame.get("source") not in _DIAGNOSTIC_FRAME_LABELS
                or type(frame.get("function")) is not str
                or len(frame["function"]) > 96
                or re.fullmatch(r"[A-Za-z0-9_<>.]+", frame["function"]) is None
                or type(frame.get("line")) is not int
                or frame["line"] < 1
            ):
                raise ValueError("qa_result_failure_frame_invalid")

    row_keys = schema.get("source_row_keys")
    expected_rows = schema.get("source_row_count")
    for rows_key in ("source_rows_before", "source_rows_after"):
        rows = result.get(rows_key)
        if (
            type(row_keys) is not list
            or type(expected_rows) is not int
            or type(rows) is not list
            or len(rows) > expected_rows
            or any(
                type(row) is not dict
                or set(row) != set(row_keys)
                or type(row.get("kind")) is not str
                or type(row.get("path")) is not str
                or type(row.get("bytes")) is not int
                or row.get("bytes", -1) < 0
                or type(row.get("sha256")) is not str
                or len(row.get("sha256", "")) != 64
                or any(character not in "0123456789abcdef" for character in row.get("sha256", ""))
                for row in rows
            )
        ):
            raise ValueError("qa_result_schema_source_rows_invalid")

    repo_keys = schema.get("repository_state_keys")
    for repo_key in ("repository_state_before", "repository_state_after"):
        repository = result.get(repo_key)
        if (
            type(repo_keys) is not list
            or type(repository) is not dict
            or (repository and set(repository) != set(repo_keys))
        ):
            raise ValueError("qa_result_schema_repository_state_invalid")
        if repository and (
            (repository.get("head_ref") is not None and type(repository.get("head_ref")) is not str)
            or type(repository.get("head_oid")) is not str
            or type(repository.get("head_file_sha256")) is not str
            or len(repository["head_file_sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in repository["head_file_sha256"])
            or type(repository.get("index_bytes")) is not int
            or type(repository.get("index_entry_count")) is not int
            or type(repository.get("index_sha256")) is not str
            or len(repository["index_sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in repository["index_sha256"])
        ):
            raise ValueError("qa_result_schema_repository_fields_invalid")

    if result["status"] == "PASS_SOURCE_FAKE_ONLY":
        expected_counts = schema.get("pass_counts")
        if (
            type(expected_counts) is not dict
            or counts != expected_counts
            or result["pytest_exit"] != 0
            or result["pytest_version"] is None
            or not result["python_executable_verified"]
            or result["python_origin"] != "fixed_qa_venv"
            or result["pytest_origin"] != "fixed_qa_venv"
            or not result["repository_checkpoint_verified_before"]
            or not result["repository_checkpoint_verified_after"]
            or not result["repository_head_and_index_unchanged"]
            or not result["source_pin_pre_post_equal"]
            or not result["source_origin_assertion_cases_collected"]
            or result["source_origin_assertion_case_count"] != 3
            or result["console_facade"] != "inert_colorama_facade"
            or not result["qa_packet_pre_post_equal"]
            or result["warning_count"] != 0
            or result["warnings_by_category"]
            or result["guard_attempts_by_category"]
            or result["failure_diagnostics"]
            or result["runner_stage_error"] is not None
            or result["repository_state_before"] != result["repository_state_after"]
            or not _repository_checkpoint_matches(result["repository_state_before"])
            or len(result["source_rows_before"]) != expected_rows
            or result["source_rows_before"] != result["source_rows_after"]
        ):
            raise ValueError("qa_result_schema_pass_gates_invalid")


def _input_rows(
    r1_artifacts: dict[str, Any],
    r5_artifacts: dict[str, Any],
    source_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for kind, packet, artifacts in (
        ("r1_qa_packet", R1_PACKET, r1_artifacts),
        ("r5_packet", R5_PACKET, r5_artifacts),
    ):
        for item in artifacts["artifacts"]:
            relative = _relative_path(item.get("path"))
            raw = _read_pinned(
                packet.joinpath(*relative.parts),
                item.get("bytes"),
                item.get("sha256"),
                allowed_root=packet,
            )
            result.append(
                {
                    "kind": kind,
                    "path": relative.as_posix(),
                    "bytes": len(raw),
                    "sha256": _sha(raw),
                }
            )
    for item in source_rows:
        relative = _relative_path(item.get("path"))
        raw = _read_pinned(
            ROOT.joinpath(*relative.parts),
            item.get("bytes"),
            item.get("sha256"),
            allowed_root=ROOT,
        )
        result.append(
            {"kind": "public_source", "path": relative.as_posix(), "bytes": len(raw), "sha256": _sha(raw)}
        )
    return result


def _git_metadata() -> dict[str, Any]:
    git_dir = ROOT / ".git"
    if not git_dir.is_dir():
        raise ValueError("git_metadata_directory_unavailable")
    head_raw = _read_small(git_dir / "HEAD", 4096)
    index_raw = _read_small(git_dir / "index", 32 * 1024 * 1024)
    head_text = head_raw.decode("ascii", errors="strict").strip()
    head_oid: str | None = None
    head_ref: str | None = None
    if head_text.startswith("ref: "):
        head_ref = head_text[5:]
        if not head_ref.startswith("refs/") or ".." in PurePosixPath(head_ref).parts:
            raise ValueError("git_head_ref_invalid")
        ref_path = git_dir.joinpath(*PurePosixPath(head_ref).parts)
        if ref_path.is_file():
            head_oid = _read_small(ref_path, 256).decode("ascii", errors="strict").strip()
        else:
            packed = _read_small(git_dir / "packed-refs", 16 * 1024 * 1024)
            for line in packed.decode("ascii", errors="strict").splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2 and parts[1] == head_ref:
                    head_oid = parts[0]
                    break
    else:
        head_oid = head_text
    if type(head_oid) is not str or len(head_oid) not in {40, 64} or any(ch not in "0123456789abcdefABCDEF" for ch in head_oid):
        raise ValueError("git_head_oid_unavailable")
    if len(index_raw) < 12 or index_raw[:4] != b"DIRC":
        raise ValueError("git_index_header_invalid")
    return {
        "head_ref": head_ref,
        "head_oid": head_oid.lower(),
        "head_file_sha256": _sha(head_raw),
        "index_bytes": len(index_raw),
        "index_entry_count": int.from_bytes(index_raw[8:12], "big"),
        "index_sha256": _sha(index_raw),
    }


def _read_small(path: Path, maximum_bytes: int) -> bytes:
    size = path.stat().st_size
    if size > maximum_bytes:
        raise ValueError("metadata_file_exceeds_bound")
    with path.open("rb") as stream:
        raw = stream.read(maximum_bytes + 1)
    if len(raw) != size:
        raise ValueError("metadata_file_read_mismatch")
    return raw


def _prepare_guards(run_dir: Path) -> _Guard:
    guard = _Guard(run_dir)
    # Python and pytest bootstrap from the selected QA environment; candidate
    # source code starts only after these guards are installed.
    original_ctypes = {name: getattr(ctypes, name, None) for name in ("CDLL", "PyDLL", "WinDLL")}

    def deny_native(*args: Any, **kwargs: Any) -> Any:
        guard._deny("native_library_load", event_name="native_loader")

    for name, original in original_ctypes.items():
        if original is not None:
            setattr(ctypes, name, deny_native)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        if hasattr(subprocess, name):
            setattr(
                subprocess,
                name,
                lambda *args, **kwargs: guard._deny(
                    "process_creation", event_name="process_creation_api"
                ),
            )
    for name in ("system", "startfile", "fork", "forkpty", "posix_spawn", "spawnv", "spawnve", "execv", "execve"):
        if hasattr(os, name):
            setattr(
                os,
                name,
                lambda *args, **kwargs: guard._deny(
                    "process_creation", event_name="process_creation_api"
                ),
            )
    for name in ("socket", "create_connection", "create_server", "getaddrinfo", "gethostbyname", "gethostbyaddr"):
        if hasattr(socket, name):
            setattr(
                socket,
                name,
                lambda *args, **kwargs: guard._deny("network_access", event_name="network_api"),
            )
    try:
        import multiprocessing.process

        multiprocessing.process.BaseProcess.start = lambda *args, **kwargs: guard._deny(
            "process_creation", event_name="process_creation_api"
        )
    except ImportError:
        pass
    sys.meta_path.insert(0, _NoProviderImports(guard))
    sys.addaudithook(guard.audit)
    return guard


def _audit_mutation_guard_selfcheck(guard: _Guard, run_id: str, run_dir: Path) -> bool:
    open_probe = ROOT / f".iteration41-v20-open-audit-selfcheck-{run_id}.tmp"
    rename_source = run_dir / f".iteration41-v20-rename-source-{run_id}.tmp"
    rename_target = ROOT / f".iteration41-v20-rename-target-{run_id}.tmp"
    mkdir_probe = run_dir / f"mkdir-{run_id}"
    rmdir_probe = run_dir / f"rmdir-{run_id}"
    rename_inside = run_dir / f"rename-{run_id}"
    replace_inside = run_dir / f"replace-{run_id}"
    all_probes = (
        open_probe,
        rename_source,
        rename_target,
        mkdir_probe,
        rmdir_probe,
        rename_inside,
        replace_inside,
    )
    if any(path.exists() for path in all_probes):
        return False

    def expect_denied(
        event: str,
        args: tuple[Any, ...],
        category: str,
        *,
        expected_extended: bool | None = None,
        expected_run_dir: bool | None = None,
    ) -> bool:
        previous_attempts = tuple(guard.attempts)
        previous_events = len(guard.denied_events)
        try:
            sys.audit(event, *args)
        except GuardViolation as exc:
            attempts = tuple(guard.attempts)
            expected_attempts = previous_attempts + (category,)
            if (
                exc.category != category
                or attempts != expected_attempts
                or len(guard.denied_events) != previous_events + 1
                or guard.denied_events[-1].get("event") != event
            ):
                return False
            event_row = guard.denied_events[-1]
            if expected_extended is not None and event_row.get(
                "extended_local_drive_prefix"
            ) is not expected_extended:
                return False
            if expected_run_dir is not None and event_row.get(
                "normalized_to_run_dir"
            ) is not expected_run_dir:
                return False
            del guard.attempts[len(previous_attempts) :]
            del guard.denied_events[previous_events:]
            return True
        return False

    if not expect_denied(
        "open",
        (str(open_probe), 0o200, os.O_WRONLY | os.O_CREAT),
        "write_outside_qa_output",
    ):
        return False
    if not expect_denied(
        "os.rename",
        (str(rename_source), str(rename_target), None, None),
        "write_outside_qa_output",
    ):
        return False
    if not expect_denied(
        "os.replace",
        (str(rename_source), str(rename_target), None, None),
        "write_outside_qa_output",
    ):
        return False
    if not expect_denied(
        "os.rename",
        (str(rename_source), str(rename_target), 7, None),
        "path_dir_fd_unverifiable",
    ):
        return False
    if not expect_denied(
        "os.replace",
        (str(rename_source), str(rename_target), None, False),
        "path_dir_fd_unverifiable",
    ):
        return False
    if not expect_denied(
        "os.remove",
        (str(rename_source), False),
        "path_dir_fd_unverifiable",
    ):
        return False

    extended_env_path = "\\\\?\\" + str(run_dir / ".env")
    previous_attempts = tuple(guard.attempts)
    previous_events = len(guard.denied_events)
    if not expect_denied(
        "open",
        (extended_env_path, "w", None),
        "private_config_access",
        expected_extended=True,
        expected_run_dir=True,
    ):
        return False
    if tuple(guard.attempts) != previous_attempts or len(guard.denied_events) != previous_events:
        return False

    previous_attempts = tuple(guard.attempts)
    allowed_events = (
        ("os.mkdir", (str(mkdir_probe), 0o700, -1)),
        ("os.remove", (str(rename_source), -1)),
        ("os.rmdir", (str(rmdir_probe), -1)),
        ("os.rename", (str(rename_source), str(rename_inside), -1, -1)),
        ("os.replace", (str(rename_source), str(replace_inside), -1, -1)),
    )
    try:
        for event, args in allowed_events:
            sys.audit(event, *args)
    except BaseException:
        return False
    if tuple(guard.attempts) != previous_attempts:
        return False
    return not any(path.exists() for path in all_probes)


def _main() -> int:
    sys.dont_write_bytecode = True
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTEST_ADDOPTS"] = ""
    os.environ["PYTEST_PLUGINS"] = ""
    qa_manifest, result_schema, qa_manifest_sha = _verify_qa_packet()
    r1_artifacts, r5_artifacts, source_manifest, source_rows = _read_metadata_inputs()
    before_rows = _input_rows(r1_artifacts, r5_artifacts, source_rows)
    before_git = _git_metadata()
    python_verified = _qa_interpreter_matches()
    checkpoint_before = _repository_checkpoint_contract_selfcheck() and _repository_checkpoint_matches(
        before_git
    )
    run_id = uuid4().hex
    run_dir = ROOT / ".codex-tmp" / "i41q" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    guard = _prepare_guards(run_dir)
    try:
        audit_mutation_guards_verified = _audit_mutation_guard_selfcheck(guard, run_id, run_dir)
    except BaseException:
        audit_mutation_guards_verified = False
    public_source_paths = {
        os.path.normcase(
            os.path.normpath(str(ROOT.joinpath(*_relative_path(row["path"]).parts).resolve()))
        )
        for row in source_rows
    }
    counts = _Counts(
        guard,
        public_source_paths=public_source_paths,
        test_path=ROOT / TEST_RELATIVE,
        runner_path=Path(__file__),
    )
    pytest_stdout = io.StringIO()
    pytest_stderr = io.StringIO()
    started = time.monotonic()
    pytest_exit: int | None = None
    pytest_version: str | None = None
    pytest_origin_kind: str | None = None
    console_facade_installed = False
    stage_error: str | None = None
    if not python_verified:
        stage_error = "qa_interpreter_contract_mismatch"
    elif not checkpoint_before:
        stage_error = "repository_checkpoint_mismatch"
    elif not audit_mutation_guards_verified:
        stage_error = "audit_mutation_guards_unverified"
    origin_test_names = frozenset(
        {
            "test_precheck_driver_snapshot_matches_outer_source_capture",
            "test_exact_component_loader_compiles_only_the_supplied_bytes",
            "test_full_preparation_uses_real_driver_lease_binder_and_precheck_validator",
        }
    )
    try:
        if stage_error is None:
            _install_inert_colorama_facade()
            console_facade_installed = True
            import pytest

            _Counts.pytest_runtest_makereport = pytest.hookimpl(hookwrapper=True)(
                _Counts.pytest_runtest_makereport
            )

            pytest_version = pytest.__version__
            pytest_file = Path(pytest.__file__).resolve()
            pytest_origin_kind = (
                "fixed_qa_venv"
                if guard._inside(pytest_file, QA_RUNTIME_ROOT.resolve())
                else "unexpected"
            )
            if pytest_origin_kind != "fixed_qa_venv":
                stage_error = "pytest_origin_outside_qa_venv"
            else:
                test_path = ROOT / TEST_RELATIVE
                log_path = run_dir / "pytest.log"
                if log_path.exists():
                    raise ValueError("qa_log_path_not_fresh")
                argv = [
                    str(test_path),
                    "-q",
                    "--tb=short",
                    "-c",
                    str(QA_CONFIG),
                    "--confcutdir",
                    str(EVIDENCE),
                    "--noconftest",
                    "-p",
                    "no:cacheprovider",
                    "-p",
                    "no:asyncio",
                    "--capture=sys",
                    "--log-file",
                    str(log_path),
                    "--log-file-mode",
                    "w",
                    "--color=no",
                    "--basetemp",
                    str(run_dir / "pytest-tmp"),
                ]
                from contextlib import redirect_stderr, redirect_stdout

                with redirect_stdout(pytest_stdout), redirect_stderr(pytest_stderr):
                    pytest_exit = int(pytest.main(argv, plugins=[counts]))
    except GuardViolation as exc:
        stage_error = exc.category
    except BaseException:
        stage_error = "qa_runner_exception"
    elapsed = round(time.monotonic() - started, 3)
    try:
        after_qa_manifest, after_schema, after_qa_manifest_sha = _verify_qa_packet()
        after_rows = _input_rows(r1_artifacts, r5_artifacts, source_rows)
        after_git = _git_metadata()
        qa_packet_unchanged = (
            qa_manifest == after_qa_manifest
            and result_schema == after_schema
            and qa_manifest_sha == after_qa_manifest_sha
        )
    except BaseException:
        after_qa_manifest = {}
        after_schema = {}
        after_qa_manifest_sha = ""
        after_rows = []
        after_git = {}
        qa_packet_unchanged = False
        stage_error = stage_error or "postrun_readback_failed"
    unchanged = before_rows == after_rows
    git_unchanged = before_git == after_git
    checkpoint_after = _repository_checkpoint_matches(after_git)
    guards_clear = not guard.attempts
    collected_test_names = {nodeid.rsplit("::", 1)[-1] for nodeid in counts.nodeids}
    origin_test_count = len(origin_test_names & collected_test_names)
    origin_tests_collected = origin_test_count == len(origin_test_names)
    passed = (
        stage_error is None
        and pytest_exit == 0
        and counts.collected == EXPECTED_QA_TEST_COUNT
        and counts.passed == EXPECTED_QA_TEST_COUNT
        and counts.failed == 0
        and counts.skipped == 0
        and counts.xfailed == 0
        and counts.xpassed == 0
        and counts.errors == 0
        and counts.deselected == 0
        and not counts.failure_diagnostics
        and sum(counts.warnings.values()) == 0
        and origin_tests_collected
        and python_verified
        and checkpoint_before
        and checkpoint_after
        and qa_packet_unchanged
        and unchanged
        and git_unchanged
        and guards_clear
    )
    result = {
        "schema": "iteration41.simnow.c01.v20.root-preparation-source-qa.r3",
        "status": "PASS_SOURCE_FAKE_ONLY" if passed else "BLOCKED_SOURCE_QA",
        "execution_scope": "SOURCE_FAKE_ONLY",
        "official_c01_pass_count": 0,
        "actual_gate_invoked": False,
        "candidate_process_created": False,
        "candidate_private_software_native_sdk_network_access_completed": False,
        "software_payload_read": False,
        "qa_run_id": run_id,
        "pytest_exit": pytest_exit,
        "pytest_version": pytest_version,
        "pytest_origin": pytest_origin_kind,
        "python_version": sys.version.split()[0],
        "python_origin": "fixed_qa_venv" if python_verified else "unexpected",
        "python_executable_verified": python_verified,
        "console_facade": "inert_colorama_facade" if console_facade_installed else "not_installed",
        "counts": {
            "collected": counts.collected,
            "passed": counts.passed,
            "failed": counts.failed,
            "skipped": counts.skipped,
            "xfailed": counts.xfailed,
            "xpassed": counts.xpassed,
            "errors": counts.errors,
            "deselected": counts.deselected,
        },
        "warnings_by_category": dict(sorted(counts.warnings.items())),
        "warning_count": sum(counts.warnings.values()),
        "guard_attempts_by_category": {
            key: guard.attempts.count(key) for key in sorted(set(guard.attempts))
        },
        "failure_diagnostics": counts.failure_diagnostics,
        "qa_packet_artifact_count": len(qa_manifest["artifacts"]),
        "qa_packet_manifest_sha256": qa_manifest_sha,
        "qa_packet_pre_post_equal": qa_packet_unchanged,
        "r1_packet_artifact_count": len(r1_artifacts["artifacts"]),
        "r5_packet_artifact_count": len(r5_artifacts["artifacts"]),
        "public_source_row_count": len(source_rows),
        "pre_post_pinned_input_row_count": len(before_rows),
        "source_origin_policy": "26 exact repo-relative rows loaded through the pinned production source loader",
        "software_metadata_row_count": len(source_manifest["software_source_rows"]),
        "source_origin_assertion_case_count": origin_test_count,
        "source_origin_assertion_cases_collected": origin_tests_collected,
        "source_pin_pre_post_equal": unchanged,
        "source_rows_before": before_rows,
        "source_rows_after": after_rows,
        "repository_state_before": before_git,
        "repository_state_after": after_git,
        "repository_head_and_index_unchanged": git_unchanged,
        "repository_checkpoint_verified_before": checkpoint_before,
        "repository_checkpoint_verified_after": checkpoint_after,
        "runner_stage_error": stage_error,
        "elapsed_seconds": elapsed,
    }
    result_path = run_dir / "result.json"
    _validate_result_schema(result, result_schema)
    result_raw = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2).encode("ascii") + b"\n"
    with result_path.open("xb") as stream:
        stream.write(result_raw)
    print(json.dumps({key: value for key, value in result.items() if key not in {"source_rows_before", "source_rows_after"}}, sort_keys=True))
    print("RESULT_PATH", result_path.relative_to(ROOT).as_posix())
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(_main())
