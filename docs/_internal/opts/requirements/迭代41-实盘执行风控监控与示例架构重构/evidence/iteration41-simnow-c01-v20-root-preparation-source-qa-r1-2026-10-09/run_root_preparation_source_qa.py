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
import socket
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[7]
EVIDENCE = ROOT / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
QA_PACKET = EVIDENCE / "iteration41-simnow-c01-v20-root-preparation-source-qa-r1-2026-10-09"
R5_PACKET = EVIDENCE / "iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09"
REVIEW_PATH = EVIDENCE / (
    "iteration41-simnow-c01-v20-root-credential-free-caller-r5-independent-static-review-r1-2026-10-09/README.md"
)
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

EXPECTED_R5_ARTIFACT_PINS = "62ddd86cc141a4b94dbe5eee6736c7b13099133f890e77a0f931f90d31bfef16"
EXPECTED_SOURCE_PINS = "e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387"
EXPECTED_REVIEW = "4dd6725c42dfc2b8f8ef6a2d8cb7952f4bde27a7995fb867fd6e916eab6fbfba"
EXPECTED_QA_TEST_COUNT = 12
EXPECTED_QA_PACKET_FILES = frozenset(
    {
        "README.md",
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
        self.allowed_roots = tuple(
            path.resolve()
            for path in {ROOT.resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}
        )

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _deny(self, category: str) -> None:
        self.attempts.append(category)
        raise GuardViolation(category)

    def _path(self, value: Any) -> Path | None:
        if not isinstance(value, (str, bytes, os.PathLike)):
            return None
        try:
            return Path(os.fsdecode(value)).resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            self._deny("unresolvable_file_path")
        return None

    def _check_file(self, value: Any, mode: Any = "r") -> None:
        path = self._path(value)
        if path is None:
            return
        normalized = os.path.normcase(str(path)).replace("\\", "/").casefold()
        if normalized in _BLOCKED_SOFTWARE_PATHS or normalized.startswith("d:/temp/"):
            self._deny("software_payload_access")
        if path.name.casefold() in _SENSITIVE_NAMES:
            self._deny("private_config_access")
        if any(part.casefold() in _PRIVATE_DIRECTORY_NAMES for part in path.parts):
            self._deny("private_capture_access")
        if not any(self._inside(path, root) for root in self.allowed_roots) and not self._inside(
            path, self.run_dir
        ):
            self._deny("file_outside_public_qa_roots")
        writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
        if type(mode) is int:
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
            writing = bool(mode & write_flags)
        if writing:
            if not self._inside(path, self.run_dir):
                self._deny("write_outside_qa_output")

    def audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event == "open" and args:
            mode = args[1] if len(args) > 1 else "r"
            self._check_file(args[0], mode)
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
        elif event in {"os.remove", "os.rename", "os.replace", "os.rmdir", "os.chmod"} and args:
            self._check_file(args[0], "w")
        elif event == "os.mkdir" and args:
            self._check_file(args[0], "w")


class _NoProviderImports(importlib.abc.MetaPathFinder):
    def __init__(self, guard: _Guard) -> None:
        self._guard = guard

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        root = fullname.split(".", 1)[0].casefold()
        if root in _FORBIDDEN_IMPORT_ROOTS or root.startswith("bt_api_"):
            self._guard._deny("provider_or_sdk_import")
        return None


class _Counts:
    def __init__(self) -> None:
        self.collected = 0
        self.nodeids: list[str] = []
        self.passed = 0
        self.failed = 0
        self.skipped = 0
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
            if report.outcome == "passed":
                self.passed += 1
            elif report.outcome == "failed":
                self.failed += 1
            elif report.outcome == "skipped":
                self.skipped += 1
        elif report.failed:
            self.errors += 1

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


def _read_metadata_inputs() -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    r5_artifact_bytes = _read_pinned(
        R5_PIN_COPY, 1437, EXPECTED_R5_ARTIFACT_PINS, allowed_root=QA_PACKET
    )
    source_pin_bytes = _read_pinned(
        SOURCE_PIN_COPY, 9069, EXPECTED_SOURCE_PINS, allowed_root=QA_PACKET
    )
    _read_pinned(REVIEW_COPY, 2519, EXPECTED_REVIEW, allowed_root=QA_PACKET)
    _read_pinned(REVIEW_PATH, 2519, EXPECTED_REVIEW, allowed_root=EVIDENCE)
    artifacts = json.loads(r5_artifact_bytes)
    source_manifest = json.loads(source_pin_bytes)
    if (
        type(artifacts.get("artifact_count")) is not int
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
    return artifacts, source_manifest, rows


def _verify_qa_packet() -> None:
    manifest = json.loads(_read_small(QA_ARTIFACT_PINS, 64 * 1024))
    artifacts = manifest.get("artifacts")
    if (
        type(manifest.get("artifact_count")) is not int
        or manifest.get("artifact_count") != 8
        or type(artifacts) is not list
        or len(artifacts) != 8
    ):
        raise ValueError("qa_packet_artifact_count_invalid")
    paths = [_relative_path(item.get("path")).as_posix() for item in artifacts]
    if len(set(paths)) != len(paths) or set(paths) != EXPECTED_QA_PACKET_FILES:
        raise ValueError("qa_packet_artifact_paths_invalid")
    for item in artifacts:
        relative = _relative_path(item.get("path"))
        candidate = QA_PACKET.joinpath(*relative.parts)
        _read_pinned(
            candidate,
            item.get("bytes"),
            item.get("sha256"),
            allowed_root=QA_PACKET,
        )


def _input_rows(artifacts: dict[str, Any], source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in artifacts["artifacts"]:
        relative = _relative_path(item.get("path"))
        raw = _read_pinned(
            R5_PACKET.joinpath(*relative.parts),
            item.get("bytes"),
            item.get("sha256"),
            allowed_root=R5_PACKET,
        )
        result.append(
            {"kind": "r5_packet", "path": relative.as_posix(), "bytes": len(raw), "sha256": _sha(raw)}
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
        guard._deny("native_library_load")

    for name, original in original_ctypes.items():
        if original is not None:
            setattr(ctypes, name, deny_native)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        if hasattr(subprocess, name):
            setattr(subprocess, name, lambda *args, **kwargs: guard._deny("process_creation"))
    for name in ("system", "startfile", "fork", "forkpty", "posix_spawn", "spawnv", "spawnve", "execv", "execve"):
        if hasattr(os, name):
            setattr(os, name, lambda *args, **kwargs: guard._deny("process_creation"))
    for name in ("socket", "create_connection", "create_server", "getaddrinfo", "gethostbyname", "gethostbyaddr"):
        if hasattr(socket, name):
            setattr(socket, name, lambda *args, **kwargs: guard._deny("network_access"))
    try:
        import multiprocessing.process

        multiprocessing.process.BaseProcess.start = lambda *args, **kwargs: guard._deny("process_creation")
    except ImportError:
        pass
    sys.meta_path.insert(0, _NoProviderImports(guard))
    sys.addaudithook(guard.audit)
    return guard


def _main() -> int:
    sys.dont_write_bytecode = True
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ["PYTEST_ADDOPTS"] = ""
    os.environ["PYTEST_PLUGINS"] = ""
    _verify_qa_packet()
    artifacts, source_manifest, source_rows = _read_metadata_inputs()
    before_rows = _input_rows(artifacts, source_rows)
    before_git = _git_metadata()
    run_id = uuid4().hex
    run_dir = QA_PACKET / "runs" / run_id
    (run_dir / "pytest-tmp").mkdir(parents=True, exist_ok=False)
    guard = _prepare_guards(run_dir)
    counts = _Counts()
    pytest_stdout = io.StringIO()
    pytest_stderr = io.StringIO()
    started = time.monotonic()
    pytest_exit: int | None = None
    pytest_version: str | None = None
    pytest_origin_kind: str | None = None
    stage_error: str | None = None
    origin_test_names = frozenset(
        {
            "test_precheck_driver_snapshot_matches_outer_source_capture",
            "test_exact_component_loader_compiles_only_the_supplied_bytes",
            "test_full_preparation_uses_real_driver_lease_binder_and_precheck_validator",
        }
    )
    try:
        import pytest

        pytest_version = pytest.__version__
        pytest_file = Path(pytest.__file__).resolve()
        pytest_origin_kind = (
            "qa_interpreter_prefix"
            if any(guard._inside(pytest_file, root) for root in guard.allowed_roots if root != ROOT.resolve())
            else "unexpected"
        )
        if pytest_origin_kind != "qa_interpreter_prefix":
            raise ValueError("pytest_origin_outside_qa_interpreter")
        test_path = ROOT / TEST_RELATIVE
        argv = [
            str(test_path),
            "-q",
            "--tb=short",
            "-c",
            str(QA_CONFIG),
            "--confcutdir",
            str(EVIDENCE),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:asyncio",
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
        after_rows = _input_rows(artifacts, source_rows)
        after_git = _git_metadata()
    except BaseException:
        after_rows = []
        after_git = {}
        stage_error = stage_error or "postrun_readback_failed"
    unchanged = before_rows == after_rows
    git_unchanged = before_git == after_git
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
        and counts.errors == 0
        and counts.deselected == 0
        and origin_tests_collected
        and unchanged
        and git_unchanged
        and guards_clear
    )
    result = {
        "schema": "iteration41.simnow.c01.v20.root-preparation-source-qa.r1",
        "status": "PASS_SOURCE_FAKE_ONLY" if passed else "BLOCKED_SOURCE_QA",
        "execution_scope": "SOURCE_FAKE_ONLY",
        "official_c01_pass_count": 0,
        "actual_gate_invoked": False,
        "candidate_process_created": False,
        "native_provider_sdk_network_or_private_access": False,
        "software_payload_read": False,
        "qa_run_id": run_id,
        "pytest_exit": pytest_exit,
        "pytest_version": pytest_version,
        "pytest_origin": pytest_origin_kind,
        "python_version": sys.version.split()[0],
        "python_origin": "root-selected-qa-interpreter",
        "counts": {
            "collected": counts.collected,
            "passed": counts.passed,
            "failed": counts.failed,
            "skipped": counts.skipped,
            "errors": counts.errors,
            "deselected": counts.deselected,
        },
        "warnings_by_category": dict(sorted(counts.warnings.items())),
        "warning_count": sum(counts.warnings.values()),
        "guard_attempts_by_category": {
            key: guard.attempts.count(key) for key in sorted(set(guard.attempts))
        },
        "packet_artifact_count": len(artifacts["artifacts"]),
        "public_source_row_count": len(source_rows),
        "source_origin_policy": "26 exact repo-relative rows loaded through the pinned production source loader",
        "source_origin_assertions_included": counts.collected == EXPECTED_QA_TEST_COUNT,
        "software_metadata_row_count": len(source_manifest["software_source_rows"]),
        "source_origin_assertion_case_count": origin_test_count,
        "source_origin_assertion_cases_collected": origin_tests_collected,
        "source_pin_pre_post_equal": unchanged,
        "source_rows_before": before_rows,
        "source_rows_after": after_rows,
        "repository_state_before": before_git,
        "repository_state_after": after_git,
        "repository_head_and_index_unchanged": git_unchanged,
        "runner_stage_error": stage_error,
        "elapsed_seconds": elapsed,
    }
    result_path = run_dir / "result.json"
    result_raw = json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2).encode("ascii") + b"\n"
    with result_path.open("xb") as stream:
        stream.write(result_raw)
    print(json.dumps({key: value for key, value in result.items() if key not in {"source_rows_before", "source_rows_after"}}, sort_keys=True))
    print("RESULT_PATH", result_path.relative_to(ROOT).as_posix())
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(_main())
