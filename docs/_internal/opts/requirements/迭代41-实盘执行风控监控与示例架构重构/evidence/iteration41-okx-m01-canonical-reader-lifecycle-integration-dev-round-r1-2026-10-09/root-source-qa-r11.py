"""Public guarded Root QA for the canonical M01 reader integration.

This runs only two reviewed source-fake pytest files in an isolated Python
interpreter with pytest conftest loading disabled. It preloads optional
terminal color support before native API denials, then installs scoped API and
open-path checks before importing pytest or candidate/test modules. Those
checks apply to this reviewed suite; they are not a general filesystem sandbox
and do not claim to deny every metadata query. The harness never invokes the
actual Root gate or reads deployment metadata/software payloads.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import uuid
import zipfile


ROOT = Path("D:/source_code/backtrader")
EVIDENCE_ROOT = (
    ROOT
    / "docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence"
)
PACKET = EVIDENCE_ROOT / "iteration41-okx-m01-root-helper-lifecycle-integration-r1-2026-10-09"
OLD_PACKET = EVIDENCE_ROOT / "iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09"
QA = Path("D:/mq-okx-m01-reader-lifecycle-r11-" + uuid.uuid4().hex[:8])
PYTHON = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe")
SITE = Path("D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages")
RESULT_PATH = ROOT / ".codex-tmp/okx_m01_reader_lifecycle_integration_root_qa_r11_20261009.json"
CHILD_DIAGNOSTIC_PATH = (
    ROOT / ".codex-tmp/okx_m01_reader_lifecycle_integration_root_qa_r11_child_diagnostic_20261009.json"
)
MAX_CHILD_OUTPUT_BYTES = 64 * 1024
MAX_COLLECTION_REPORTS = 8
MAX_COLLECTION_LONGREPR_BYTES = 4096
MAX_TEST_FAILURE_REPORTS = 8
MAX_TEST_FAILURE_RECORD_BYTES = 4096
MAX_DENIAL_CALL_SITES = 8

PACKET_PINS = {
    "README.md": (3219, "5a718a0e209a7e967b2104bb09ac9291741d2aa8f92ebc8c0d773ec1471156c6"),
    "delivery-scope.json": (
        8427,
        "c8d2839e6d11a9638b4f6b6008ac46187b06c1b10eda8a0f3f334eb71ae554e0",
    ),
    "qa-command.txt": (837, "3345e8b3c3a83c80c567b6d84ed8022575b281b9dfe7904ac5949ce033d6792f"),
    "source-index.json": (9970, "8cd0360bb9519daf785412a6176091d2ca0ff4471e2bf65aba011aeec3444564"),
    "source-map.json": (2877, "07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3"),
    "source-qa-result.json": (
        1673,
        "03aa50336c57b79b984684e0cb53771af7e9d350b07d4ed0d911ed51eb0ee3b2",
    ),
    "source.zip": (151736, "337d8f48eed1de8e7f880d6c8a24cf41e3707649cd0b0c3be87cc0b0948d39b3"),
}
SOURCE_MAP_SHA256 = PACKET_PINS["source-map.json"][1]
SOURCE_INDEX_SHA256 = PACKET_PINS["source-index.json"][1]
SOURCE_ZIP_SHA256 = PACKET_PINS["source.zip"][1]
OLD_SOURCE_MAP_SHA256 = "db7b351656a0e26aac3778332ed7eb838a92a73605a5bb3604cb4b770c06ebe3"
OLD_SOURCE_ZIP_SHA256 = "fb319aa4b066a839dc8681d2ac30897374bece35d90bf29d6c26b28c40b7ee35"
OLD_READER_SHA256 = "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734"
OLD_READER_BYTES = 63711
READER_RELATIVE = (
    "examples/000_live_certification/okx_penetration/"
    "_m01_readonly_monitor_v3/current_reader.py"
)
TESTS = (
    "tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py",
    "tests/unit/scripts/test_iteration41_okx_m01_reader_lifecycle_integration_r1.py",
)
PUBLIC_ROOT_RUNNER = ".codex-tmp/okx_m01_local_lifecycle_root_actual_20261009.py"
PUBLIC_ROOT_RUNNER_PIN = (
    12373,
    "3ae21d1e8540686016205e7383f7d6d55c0466b25b8ebb8e29982337e239e897",
)
MAX_PUBLIC_SOURCE_BYTES = 2 * 1024 * 1024
REQUIRED_EXECUTION_PATHS = (
    *TESTS,
    "scripts/iteration41_okx_m01_local_source_lease_reconciliation_r7.py",
    "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py",
    "scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py",
    "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py",
    "tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r7.py",
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _output_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace")
    return bytes(value)


def _persist_bounded_output(path: Path, value: object) -> dict[str, object]:
    raw = _output_bytes(value)
    truncated = len(raw) > MAX_CHILD_OUTPUT_BYTES
    if truncated:
        marker = f"\n[truncated; complete output bytes={len(raw)}]\n".encode("ascii")
        payload = raw[: MAX_CHILD_OUTPUT_BYTES - len(marker)] + marker
    else:
        payload = raw
    with path.open("xb") as stream:
        stream.write(payload)
    return {
        "path": str(path),
        "total_bytes": len(raw),
        "saved_bytes": len(payload),
        "sha256": _sha(raw),
        "saved_sha256": _sha(payload),
        "truncated": truncated,
    }


def _bounded_read(path: Path, maximum: int) -> bytes:
    resolved = path.resolve(strict=True)
    allowed_roots = (ROOT.resolve(strict=True), QA.resolve(strict=False))
    resolved_text = os.path.normcase(str(resolved))
    assert any(
        os.path.commonpath((resolved_text, os.path.normcase(str(root))))
        == os.path.normcase(str(root))
        for root in allowed_roots
    ), f"public_read_outside_allowed_roots:{path.as_posix()}"
    size = path.stat().st_size
    assert 0 <= size <= maximum, f"bounded_size:{path.as_posix()}"
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    assert len(raw) == size and len(raw) <= maximum, f"bounded_read:{path.as_posix()}"
    return raw


_SAFE_DENIAL_CATEGORIES = {
    "blocked_sdk_import",
    "other_guarded_denial",
}
_SAFE_IMPORT_ROOT_COUNTS = {"_winapi", "other"}


def _safe_symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 96
        and value.isascii()
        and value.isidentifier()
    )


def _safe_denial_audit(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    trip_count = value.get("trip_count")
    if type(trip_count) is not int or trip_count < 0:
        return None
    counts = value.get("category_counts")
    if not isinstance(counts, dict) or set(counts) != _SAFE_DENIAL_CATEGORIES:
        return None
    if not all(type(count) is int and count >= 0 for count in counts.values()):
        return None
    import_roots = value.get("blocked_import_root_counts")
    if not isinstance(import_roots, dict) or set(import_roots) != _SAFE_IMPORT_ROOT_COUNTS:
        return None
    if not all(type(count) is int and count >= 0 for count in import_roots.values()):
        return None
    call_sites = value.get("call_sites")
    if not isinstance(call_sites, list) or len(call_sites) > MAX_DENIAL_CALL_SITES:
        return None
    safe_sites = []
    for site in call_sites:
        if not isinstance(site, dict):
            return None
        category = site.get("category")
        callsite = site.get("callsite")
        line = site.get("line")
        if category not in _SAFE_DENIAL_CATEGORIES or not _safe_symbol(callsite):
            return None
        if type(line) is not int or line < 0:
            return None
        safe_sites.append({"category": category, "callsite": callsite, "line": line})
    truncated = value.get("call_sites_truncated")
    if type(truncated) is not int or truncated < 0:
        return None
    return {
        "trip_count": trip_count,
        "category_counts": dict(counts),
        "blocked_import_root_counts": dict(import_roots),
        "call_sites": safe_sites,
        "call_sites_truncated": truncated,
    }


def _safe_failure_record(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    test_file = value.get("test_file")
    if test_file not in {"m01_monitor", "m01_reader_lifecycle_integration"}:
        return None
    test_name = value.get("test_name")
    if not _safe_symbol(test_name):
        return None
    phase = value.get("phase")
    if phase not in {"setup", "call", "teardown", "other"}:
        return None
    exception_type = value.get("exception_type")
    if not _safe_symbol(exception_type):
        return None
    if value.get("outcome") != "failed":
        return None
    frames = value.get("frames")
    if not isinstance(frames, list) or len(frames) > 8:
        return None
    safe_frames = []
    for frame in frames:
        if not isinstance(frame, dict):
            return None
        function = frame.get("function")
        line = frame.get("line")
        if not _safe_symbol(function) or type(line) is not int or line < 0:
            return None
        safe_frames.append({"function": function, "line": line})
    denial_audit = _safe_denial_audit(value.get("denial_audit"))
    if denial_audit is None:
        return None
    record = {
        "test_file": test_file,
        "test_name": test_name,
        "phase": phase,
        "outcome": "failed",
        "exception_type": exception_type,
        "frames": safe_frames,
        "denial_audit": denial_audit,
    }
    line = "ROOT_M01_TEST_FAILURE=" + json.dumps(
        record, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    if len(line.encode("ascii")) > MAX_TEST_FAILURE_RECORD_BYTES:
        return None
    return record


def _safe_archive_name(name: str) -> bool:
    member = PurePosixPath(name)
    return (
        not member.is_absolute()
        and all(part not in ("", ".", "..") for part in member.parts)
        and "\\" not in name
        and ":" not in name
    )


def _git(*args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _check_packet() -> tuple[dict, dict, dict[str, dict]]:
    packet_bytes = {}
    for name, (size, digest) in PACKET_PINS.items():
        raw = _bounded_read(PACKET / name, size)
        assert len(raw) == size and _sha(raw) == digest, f"packet_pin:{name}"
        packet_bytes[name] = raw

    source_map_raw = packet_bytes["source-map.json"]
    source_index_raw = packet_bytes["source-index.json"]
    source_zip_raw = packet_bytes["source.zip"]
    source_map = json.loads(source_map_raw.decode("ascii"))
    source_index = json.loads(source_index_raw.decode("ascii"))
    canonical_map = json.dumps(
        source_map, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    assert source_map_raw == canonical_map + b"\n"
    assert source_index["schema"] == "iteration41.okx.m01.root-helper-lifecycle-integration-source-index.v1"
    assert source_index["source_map_path"] == "source-map.json"
    assert source_index["source_map_file_sha256"] == SOURCE_MAP_SHA256
    assert source_index["source_map_sha256"] == SOURCE_MAP_SHA256
    assert source_index["source_map_canonical_sha256"] == _sha(canonical_map)
    assert source_index["source_map_bytes"] == len(source_map_raw) == 2877
    assert source_index["source_zip_path"] == "source.zip"
    assert source_index["source_zip_sha256"] == SOURCE_ZIP_SHA256
    assert source_index["archive_member_count"] == 26
    assert source_index["runtime_source_count"] == 19
    assert len(source_map["source_pins"]) == 19

    rows = source_index["rows"]
    assert type(rows) is list and len(rows) == 26
    by_path = {}
    runtime_rows = {}
    for row in rows:
        relative = row["path"]
        assert type(relative) is str and _safe_archive_name(relative)
        assert relative not in by_path
        assert type(row["bytes"]) is int and 0 <= row["bytes"] <= MAX_PUBLIC_SOURCE_BYTES
        assert len(row["sha256"]) == 64
        assert row["role"] in {
            "runtime_source",
            "frozen_source_close_reconciler",
            "reviewed_lifecycle_gate_source",
            "reviewed_reader_transform_source",
            "canonical_source_fake_test",
            "historical_source_fake_integration_test",
            "reviewed_transform_fake_test",
            "reviewed_lifecycle_gate_fake_test",
        }
        by_path[relative] = row
        if row["role"] == "runtime_source":
            runtime_rows[relative] = row["sha256"]
    assert runtime_rows == source_map["source_pins"]
    assert set(source_map["source_pins"]) == set(runtime_rows)
    assert source_index["historical_fixture"] == {
        "reader_bytes": OLD_READER_BYTES,
        "reader_path": READER_RELATIVE,
        "reader_sha256": OLD_READER_SHA256,
        "source_archive_path": (
            "docs/_internal/opts/requirements/"
            "迭代41-实盘执行风控监控与示例架构重构/evidence/"
            "iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09/source.zip"
        ),
        "source_archive_sha256": OLD_SOURCE_ZIP_SHA256,
        "source_map_sha256": OLD_SOURCE_MAP_SHA256,
    }

    source_snapshots = {}
    source_bytes = {}
    for relative, row in by_path.items():
        raw = _bounded_read(ROOT / relative, row["bytes"])
        assert len(raw) == row["bytes"] and _sha(raw) == row["sha256"], f"physical_source_pin:{relative}"
        source_bytes[relative] = raw
        source_snapshots[relative] = {"path": relative, "size": len(raw), "sha256": _sha(raw)}

    with zipfile.ZipFile(io.BytesIO(source_zip_raw)) as archive:
        names = archive.namelist()
        assert len(names) == 26 and len(names) == len(set(names))
        assert set(names) == set(by_path)
        for name in names:
            assert _safe_archive_name(name)
            raw = archive.read(name)
            row = by_path[name]
            assert len(raw) == row["bytes"] and _sha(raw) == row["sha256"], f"zip_member_pin:{name}"

    old_map_raw = _bounded_read(OLD_PACKET / "source-map.json", 256 * 1024)
    old_zip_raw = _bounded_read(OLD_PACKET / "source.zip", 2 * 1024 * 1024)
    assert _sha(old_map_raw) == OLD_SOURCE_MAP_SHA256
    assert _sha(old_zip_raw) == OLD_SOURCE_ZIP_SHA256
    old_pins = json.loads(old_map_raw.decode("ascii"))["source_pins"]
    assert set(old_pins) == set(source_map["source_pins"])
    with zipfile.ZipFile(io.BytesIO(old_zip_raw)) as archive:
        names = archive.namelist()
        assert len(names) == 20 and len(names) == len(set(names))
        assert all(_safe_archive_name(name) for name in names)
        old_reader = archive.read(READER_RELATIVE)
        assert len(old_reader) == OLD_READER_BYTES and _sha(old_reader) == OLD_READER_SHA256
    assert old_pins[READER_RELATIVE] == OLD_READER_SHA256
    old_packet_relative = OLD_PACKET.relative_to(ROOT).as_posix()
    source_snapshots[old_packet_relative + "/source-map.json"] = {
        "path": old_packet_relative + "/source-map.json",
        "size": len(old_map_raw),
        "sha256": _sha(old_map_raw),
    }
    source_snapshots[old_packet_relative + "/source.zip"] = {
        "path": old_packet_relative + "/source.zip",
        "size": len(old_zip_raw),
        "sha256": _sha(old_zip_raw),
    }

    qa_result = json.loads(packet_bytes["source-qa-result.json"].decode("ascii"))
    assert qa_result["evidence_level"] == "SOURCE_FAKE_ONLY"
    assert qa_result["focused_pytest"]["passed"] == 16
    assert qa_result["focused_pytest"]["failed"] == 0
    assert qa_result["prohibited_effects"]["WinAPI_calls"] is False
    assert qa_result["prohibited_effects"]["account_calls"] is False
    assert qa_result["prohibited_effects"]["native_calls"] is False
    assert qa_result["prohibited_effects"]["provider_calls"] is False
    assert qa_result["prohibited_effects"]["real_process_spawn"] is False
    assert qa_result["prohibited_effects"]["protected_metadata_read"] is False
    assert source_index["archive_member_count"] == len(source_bytes) == 26
    source_snapshots[PUBLIC_ROOT_RUNNER] = {
        "path": PUBLIC_ROOT_RUNNER,
        "size": PUBLIC_ROOT_RUNNER_PIN[0],
        "sha256": PUBLIC_ROOT_RUNNER_PIN[1],
    }
    runner_raw = _bounded_read(ROOT / PUBLIC_ROOT_RUNNER, PUBLIC_ROOT_RUNNER_PIN[0])
    assert len(runner_raw) == PUBLIC_ROOT_RUNNER_PIN[0]
    assert _sha(runner_raw) == PUBLIC_ROOT_RUNNER_PIN[1]
    return source_map, source_index, source_snapshots


def _child_program(
    arguments: list[str],
    module_paths: dict[str, str],
    pinned_source_paths: list[str],
    required_exec_paths: list[str],
) -> str:
    config = {
        "root": str(ROOT),
        "metadata_listing_roots": {
            "repository_parent": str(ROOT.parent),
            "drive_root": str(Path(ROOT.anchor)),
        },
        "site": str(SITE),
        "qa": str(QA),
        "root_runner": str(ROOT / PUBLIC_ROOT_RUNNER),
        "origin_report": str(QA / "origin-report.json"),
        "max_test_failure_reports": MAX_TEST_FAILURE_REPORTS,
        "max_test_failure_record_bytes": MAX_TEST_FAILURE_RECORD_BYTES,
        "max_denial_call_sites": MAX_DENIAL_CALL_SITES,
        "arguments": arguments,
        "module_paths": module_paths,
        "pinned_source_paths": pinned_source_paths,
        "required_exec_paths": required_exec_paths,
        "max_collection_reports": MAX_COLLECTION_REPORTS,
        "max_collection_longrepr_bytes": MAX_COLLECTION_LONGREPR_BYTES,
    }
    return (
        "CONFIG = "
        + repr(config)
        + r'''
import builtins
import ctypes
import ctypes.util
import http.client
import importlib
import json
import multiprocessing
import multiprocessing.connection
import multiprocessing.context
import os
import pathlib
import socket
import ssl
import subprocess
import sys
import urllib.request

try:
    import _winapi
except ImportError:
    _winapi = None

assert os.name == "nt", "root_source_fake_qa_requires_windows"
# Standard library fixture dependencies load before repository paths and guards.
import unittest.mock
import asyncio
STDLIB_FIXTURE_PRELOADED = True
for _stdlib_fixture in (unittest.mock, asyncio):
    _stdlib_origin = os.path.normcase(os.path.abspath(_stdlib_fixture.__file__))
    _stdlib_base = os.path.normcase(os.path.abspath(sys.base_prefix))
    assert os.path.commonpath((_stdlib_origin, _stdlib_base)) == _stdlib_base
sys.path[:0] = [CONFIG["root"], CONFIG["site"]]
COLORAMA_PRELOADED = False
sys.path.insert(0, CONFIG["site"])
try:
    import colorama
    import colorama.ansitowin32
    import colorama.win32
except ImportError:
    pass
else:
    COLORAMA_PRELOADED = True
finally:
    del sys.path[0]
ROOT_N = os.path.normcase(os.path.abspath(CONFIG["root"])).replace(chr(92), "/").rstrip("/")
SITE_N = os.path.normcase(os.path.abspath(CONFIG["site"])).replace(chr(92), "/").rstrip("/")
QA_N = os.path.normcase(os.path.abspath(CONFIG["qa"])).replace(chr(92), "/").rstrip("/")
PREFIX_N = os.path.normcase(os.path.abspath(sys.prefix)).replace(chr(92), "/").rstrip("/")
BASE_PREFIX_N = os.path.normcase(os.path.abspath(sys.base_prefix)).replace(chr(92), "/").rstrip("/")
ROOT_RUNNER_N = os.path.normcase(os.path.abspath(CONFIG["root_runner"])).replace(chr(92), "/").rstrip("/")
ALLOWED_ROOTS = tuple(dict.fromkeys((ROOT_N, SITE_N, QA_N, PREFIX_N, BASE_PREFIX_N)))
DENIED_EXACT = {
    "c:/anaconda3/python.exe",
    "c:/anaconda3/python311.dll",
    "d:/temp/iteration41-root-public-custody-v2.py",
}
DENIED_MODULES = {
    "bt_api", "bt_api_py", "ccxt", "okx", "binance", "binance_sdk",
    "binance_common", "bitget", "bybit", "gate_api", "websocket", "websockets",
    "requests", "httpx", "aiohttp", "urllib3", "vnpy", "ctp", "tqsdk",
    "win32api", "win32file", "win32pipe", "win32process",
    "win32security", "win32job", "pywintypes", "_winapi",
}
PRELOADED_GUARDED_MODULES = {"_winapi"}
DENIED_NAMES = {".env", "config.yaml", "config.yml", "secrets.yaml", "credentials.yaml"}
DENIED_MARKERS = (
    "/iteration41-okx-m01-v3-deployment/",
    "/iteration41-m01-v3-deployment/",
    "/private-captures/",
    "/private_captures/",
    "/private-capture/",
    "/private_capture/",
    "/m01-private-events-",
)
DENIAL_TRIPS = 0
GUARD_INSTALLED = False
ORIGIN_REPORT = {"verified": False, "modules": []}
COLLECTION_REPORT_LIMIT = CONFIG["max_collection_reports"]
COLLECTION_LONGREPR_LIMIT = CONFIG["max_collection_longrepr_bytes"]
COLLECTION_FAILURES_REPORTED = 0
TEST_FAILURE_REPORT_LIMIT = CONFIG["max_test_failure_reports"]
TEST_FAILURE_RECORD_LIMIT = CONFIG["max_test_failure_record_bytes"]
MAX_DENIAL_CALL_SITES = CONFIG["max_denial_call_sites"]
TEST_FAILURE_REPORTS_SEEN = 0
TEST_FAILURE_REPORTS_EMITTED = 0
DENIAL_CATEGORY_COUNTS = {
    "blocked_sdk_import": 0,
    "other_guarded_denial": 0,
}
DENIAL_IMPORT_ROOT_COUNTS = {"_winapi": 0, "other": 0}
DENIAL_CALL_SITES = []
EXECUTED_SOURCE_FILES = set()
PINNED_SOURCE_N = {
    os.path.normcase(os.path.abspath(path)).replace(chr(92), "/").rstrip("/")
    for path in CONFIG["pinned_source_paths"]
}
REQUIRED_EXEC_N = {
    os.path.normcase(os.path.abspath(path)).replace(chr(92), "/").rstrip("/")
    for path in CONFIG["required_exec_paths"]
}

def _norm(value):
    raw = os.fsdecode(os.fspath(value))
    return os.path.normcase(os.path.abspath(raw)).replace(chr(92), "/").rstrip("/")

METADATA_LISTING_PATHS = {
    _norm(path): category
    for category, path in CONFIG["metadata_listing_roots"].items()
}
ALLOWED_METADATA_LISTING_COUNTS = {"repository_parent": 0, "drive_root": 0}
REJECTED_METADATA_LISTING_COUNTS = {
    "forbidden_or_private_path": 0,
    "outside_reviewed_roots": 0,
}
assert set(METADATA_LISTING_PATHS.values()) == {"repository_parent", "drive_root"}
assert len(METADATA_LISTING_PATHS) == 2
assert METADATA_LISTING_PATHS[_norm(os.path.dirname(CONFIG["root"]))] == "repository_parent"
assert METADATA_LISTING_PATHS[
    _norm(os.path.splitdrive(CONFIG["root"])[0] + os.sep)
] == "drive_root"

def _under(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")

def _is_forbidden_path(value):
    normalized = _norm(value)
    basename = normalized.rsplit("/", 1)[-1]
    if basename.startswith(".env") or basename in DENIED_NAMES or normalized in DENIED_EXACT:
        return True
    if basename.endswith((".yaml", ".yml")) and any(
        marker in basename for marker in ("config", "secret", "credential")
    ):
        return True
    if any(marker in normalized for marker in DENIED_MARKERS):
        return True
    if "/.codex-tmp/" in normalized and normalized != ROOT_RUNNER_N:
        return True
    return False

def _path_allowed(value):
    normalized = _norm(value)
    return any(_under(normalized, root) for root in ALLOWED_ROOTS)

def _self_check_guards():
    slash = chr(92)
    assert _norm(CONFIG["root"]) == _norm(CONFIG["root"].replace("/", slash))
    assert _is_forbidden_path("D:" + slash + "ignored" + slash + ".env")
    assert _is_forbidden_path("D:" + slash + "ignored" + slash + ".env.local")
    assert _is_forbidden_path("D:" + slash + "config.yaml")
    assert _is_forbidden_path("D:" + slash + "ignored" + slash + "config.private.yaml")
    assert _is_forbidden_path("C:" + slash + "Anaconda3" + slash + "python.exe")
    assert _is_forbidden_path("C:" + slash + "Anaconda3" + slash + "python311.dll")
    assert _is_forbidden_path("D:" + slash + "temp" + slash + "iteration41-root-public-custody-v2.py")
    assert not _is_forbidden_path(pathlib.Path(CONFIG["root"]) / "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py")
    assert _path_allowed(pathlib.Path(CONFIG["root"]) / "scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r7.py")

_self_check_guards()

def _safe_symbol(value):
    if isinstance(value, str) and len(value) <= 96 and value.isascii() and value.isidentifier():
        return value
    return "other"

def _denial_audit_snapshot():
    return {
        "trip_count": DENIAL_TRIPS,
        "category_counts": dict(DENIAL_CATEGORY_COUNTS),
        "blocked_import_root_counts": dict(DENIAL_IMPORT_ROOT_COUNTS),
        "call_sites": list(DENIAL_CALL_SITES),
        "call_sites_truncated": max(0, DENIAL_TRIPS - len(DENIAL_CALL_SITES)),
    }

def _safe_exception_type(report):
    longrepr = getattr(report, "longrepr", None)
    crash = getattr(longrepr, "reprcrash", None)
    message = getattr(crash, "message", None)
    if isinstance(message, str):
        candidate = message.split(":", 1)[0].strip().rsplit(".", 1)[-1]
        if candidate.isascii() and candidate.isidentifier() and candidate.endswith(("Error", "Exception")):
            return candidate
    return "unknown_exception"

def _safe_test_identity(report):
    nodeid = str(getattr(report, "nodeid", ""))
    source_token = nodeid.split("::", 1)[0].replace(chr(92), "/").rsplit("/", 1)[-1]
    if source_token == "test_okx_m01_readonly_monitor_v3.py":
        source_label = "m01_monitor"
    elif source_token == "test_iteration41_okx_m01_reader_lifecycle_integration_r1.py":
        source_label = "m01_reader_lifecycle_integration"
    else:
        source_label = "selected_test_other"
    name_token = nodeid.rsplit("::", 1)[-1].split("[", 1)[0]
    return source_label, _safe_symbol(name_token)

def _safe_failure_frames(report):
    result = []
    traceback_repr = getattr(getattr(report, "longrepr", None), "reprtraceback", None)
    try:
        entries = iter(getattr(traceback_repr, "reprentries", ()))
    except Exception:
        entries = iter(())
    for index, entry in enumerate(entries):
        if index >= 8:
            break
        name = _safe_symbol(getattr(entry, "name", None))
        file_location = getattr(entry, "reprfileloc", None)
        line = getattr(file_location, "lineno", 0)
        if type(line) is not int or line < 0:
            line = 0
        result.append({"function": name, "line": line})
    return result

def _test_failure_record(report):
    test_file, test_name = _safe_test_identity(report)
    phase = getattr(report, "when", None)
    if phase not in {"setup", "call", "teardown"}:
        phase = "other"
    record = {
        "test_file": test_file,
        "test_name": test_name,
        "phase": phase,
        "outcome": "failed",
        "exception_type": _safe_exception_type(report),
        "frames": _safe_failure_frames(report),
        "denial_audit": _denial_audit_snapshot(),
    }
    payload = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    while len(("ROOT_M01_TEST_FAILURE=" + payload).encode("ascii")) > TEST_FAILURE_RECORD_LIMIT and record["frames"]:
        record["frames"].pop()
        payload = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return record

def _emit_public_marker(prefix, record):
    line = prefix + json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    for stream in (getattr(sys, "__stdout__", None), getattr(sys, "__stderr__", None)):
        if stream is None:
            continue
        try:
            stream.write("\n" + line + "\n")
            stream.flush()
            return True
        except Exception:
            continue
    return False

def _deny(*_args, **_kwargs):
    global DENIAL_TRIPS
    DENIAL_TRIPS += 1
    category = "other_guarded_denial"
    callsite = "other"
    line_number = 0
    import_root = None
    try:
        caller = sys._getframe(1)
        caller_name = caller.f_code.co_name
        if caller_name == "_audit":
            candidate = caller.f_locals.get("_denial_category")
            if candidate in DENIAL_CATEGORY_COUNTS:
                category = candidate
            import_root = caller.f_locals.get("_blocked_import_root")
        elif caller_name == "_guarded_import":
            category = "blocked_sdk_import"
            import_name = caller.f_locals.get("name")
            if isinstance(import_name, str):
                import_root = import_name.split(".", 1)[0]
        callsite = _safe_symbol(caller_name)
        if type(caller.f_lineno) is int and caller.f_lineno >= 0:
            line_number = caller.f_lineno
    except Exception:
        pass
    DENIAL_CATEGORY_COUNTS[category] += 1
    if import_root in DENIED_MODULES:
        root_category = "_winapi" if import_root == "_winapi" else "other"
        DENIAL_IMPORT_ROOT_COUNTS[root_category] += 1
    if len(DENIAL_CALL_SITES) < MAX_DENIAL_CALL_SITES:
        DENIAL_CALL_SITES.append(
            {"category": category, "callsite": callsite, "line": line_number}
        )
    raise AssertionError("root_source_qa_guard_denied_operation")

def _blocked_module(name):
    if not isinstance(name, str):
        return False
    return name.split(".", 1)[0].casefold() in DENIED_MODULES

_real_import = builtins.__import__
def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if _blocked_module(name):
        return _deny()
    return _real_import(name, globals, locals, fromlist, level)

def _allowed_mutation_path(value):
    if not isinstance(value, (str, bytes, os.PathLike)):
        return True
    normalized = _norm(value)
    return _under(normalized, QA_N)

def _audit(event, args):
    if event == "import" and args and _blocked_module(args[0]):
        _denial_category = "blocked_sdk_import"
        _blocked_import_root = args[0].split(".", 1)[0] if isinstance(args[0], str) else None
        _deny()
    if event == "open" and args:
        path = args[0]
        if isinstance(path, (str, bytes, os.PathLike)):
            if _is_forbidden_path(path) or not _path_allowed(path):
                _deny()
            mode = args[1] if len(args) > 1 else "r"
            flags = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            writing = isinstance(mode, str) and any(char in mode for char in "wax+")
            writing = writing or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            if writing and not _allowed_mutation_path(path):
                _deny()
    if event == "exec" and args:
        code = args[0]
        filename = getattr(code, "co_filename", None)
        if isinstance(filename, str):
            normalized = os.path.normcase(os.path.abspath(filename)).replace(chr(92), "/").rstrip("/")
            if normalized in PINNED_SOURCE_N:
                EXECUTED_SOURCE_FILES.add(normalized)
    if event in {"os.listdir", "os.scandir"} and args and isinstance(args[0], (str, bytes, os.PathLike)):
        normalized = _norm(args[0])
        if _is_forbidden_path(args[0]):
            REJECTED_METADATA_LISTING_COUNTS["forbidden_or_private_path"] += 1
            _deny()
        metadata_category = METADATA_LISTING_PATHS.get(normalized)
        if metadata_category is not None:
            ALLOWED_METADATA_LISTING_COUNTS[metadata_category] += 1
        elif not _path_allowed(args[0]):
            REJECTED_METADATA_LISTING_COUNTS["outside_reviewed_roots"] += 1
            _deny()
    if event in {"os.remove", "os.unlink", "os.mkdir", "os.rmdir", "os.chmod", "os.chown", "os.truncate", "os.utime"}:
        if args and not _allowed_mutation_path(args[0]):
            _deny()
    if event in {"os.rename", "os.replace", "os.link", "os.symlink"}:
        if len(args) > 1 and (not _allowed_mutation_path(args[0]) or not _allowed_mutation_path(args[1])):
            _deny()
    if event in {
        "subprocess.Popen", "os.system", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty",
        "os.exec", "os.startfile", "socket.connect", "socket.connect_ex", "socket.getaddrinfo",
        "socket.bind", "socket.listen", "socket.sendto", "socket.sendmsg", "ctypes.dlopen",
    }:
        _deny()

def _install_api_denials():
    builtins.__import__ = _guarded_import
    for name in ("CDLL", "PyDLL", "WinDLL", "OleDLL", "_dlopen"):
        if hasattr(ctypes, name):
            setattr(ctypes, name, _deny)
    ctypes.util.find_library = _deny
    try:
        import _ctypes
    except ImportError:
        _ctypes = None
    if _ctypes is not None and hasattr(_ctypes, "dlopen"):
        _ctypes.dlopen = _deny
    for name in ("system", "popen", "startfile", "fork", "forkpty", "pipe", "pipe2", "openpty", "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "execv", "execve", "execvp", "execvpe"):
        if hasattr(os, name):
            setattr(os, name, _deny)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        setattr(subprocess, name, _deny)
    for name in ("socket", "create_connection", "getaddrinfo", "gethostbyname", "gethostbyaddr", "socketpair"):
        if hasattr(socket, name):
            setattr(socket, name, _deny)
    for name in ("create_default_context", "wrap_socket"):
        if hasattr(ssl, name):
            setattr(ssl, name, _deny)
    urllib.request.urlopen = _deny
    http.client.HTTPConnection.connect = _deny
    http.client.HTTPSConnection.connect = _deny
    for name in ("Process", "Pipe", "Queue", "JoinableQueue", "SimpleQueue", "Pool", "Manager", "get_context", "set_start_method"):
        if hasattr(multiprocessing, name):
            setattr(multiprocessing, name, _deny)
    for name in ("Pipe", "Client", "Listener"):
        if hasattr(multiprocessing.connection, name):
            setattr(multiprocessing.connection, name, _deny)
    for name in ("Process", "Pipe", "Queue", "JoinableQueue", "SimpleQueue", "Pool", "Manager"):
        if hasattr(multiprocessing.context.BaseContext, name):
            setattr(multiprocessing.context.BaseContext, name, _deny)
    if _winapi is None:
        assert os.name != "nt", "windows_winapi_module_missing"
    else:
        for name in (
            "CreateProcess", "CreatePipe", "CreateNamedPipe", "ConnectNamedPipe", "CreateFile",
            "ReadFile", "WriteFile", "PeekNamedPipe", "GetNamedPipeInfo", "SetNamedPipeHandleState",
            "CallNamedPipe", "OpenProcess", "OpenThread", "TerminateProcess", "ResumeThread",
            "WaitForSingleObject", "WaitForMultipleObjects", "DuplicateHandle", "CloseHandle",
            "InitializeProcThreadAttributeList", "UpdateProcThreadAttribute", "DeleteProcThreadAttributeList",
        ):
            if hasattr(_winapi, name):
                setattr(_winapi, name, _deny)
    sys.addaudithook(_audit)

_install_api_denials()
GUARD_INSTALLED = True
assert not any(name == "_certification" or name.startswith("_certification.") for name in sys.modules)
assert not any(name == "_m01_readonly_monitor_v2" or name.startswith("_m01_readonly_monitor_v2.") for name in sys.modules)
assert not any(name == "_m01_readonly_monitor_v3" or name.startswith("_m01_readonly_monitor_v3.") for name in sys.modules)
assert _deny is not None and builtins.__import__ is _guarded_import
assert subprocess.Popen is _deny and socket.socket is _deny and ctypes.WinDLL is _deny
assert multiprocessing.Pipe is _deny
print(
    "ROOT_M01_SETUP="
    + json.dumps(
        {
            "colorama_preloaded_before_native_denials": COLORAMA_PRELOADED,
            "stdlib_fixture_dependencies_preloaded_before_guards": STDLIB_FIXTURE_PRELOADED,
            "api_guards_installed_before_pytest_candidate_imports": GUARD_INSTALLED,
            "pytest_conftest_loading_disabled": True,
        },
        sort_keys=True,
    )
)

import pytest

EXPECTED_MODULE_PATHS = {
    name: _norm(path) for name, path in CONFIG["module_paths"].items()
}
REQUIRED_MODULES = {
    "_certification",
    "_certification.m01_private_monitor_v2",
    "_m01_readonly_monitor_v2",
    "_m01_readonly_monitor_v2.current_types",
    "_m01_readonly_monitor_v2.job_supervisor",
    "_m01_readonly_monitor_v2.worker",
    "_m01_readonly_monitor_v3",
    "_m01_readonly_monitor_v3.current_reader",
    "_m01_readonly_monitor_v3.entry",
    "_m01_readonly_monitor_v3.issuer",
}

def _loaded_repository_conftests():
    found = set()
    for module in tuple(sys.modules.values()):
        file_name = getattr(module, "__file__", None)
        if not isinstance(file_name, str):
            continue
        if pathlib.Path(file_name).name.casefold() != "conftest.py":
            continue
        normalized = _norm(file_name)
        if _under(normalized, ROOT_N):
            found.add(normalized)
    return sorted(found)

def _emit_metadata_listing_audit():
    record = {
        "allowed_exact_ancestor_listing_counts": dict(ALLOWED_METADATA_LISTING_COUNTS),
        "rejected_listing_category_counts": dict(REJECTED_METADATA_LISTING_COUNTS),
        "scope": "Exact repository-parent and drive-root listdir/scandir metadata only.",
        "path_values_recorded": False,
    }
    line = "ROOT_M01_METADATA_LISTING_AUDIT=" + json.dumps(
        record, sort_keys=True, separators=(",", ":")
    )
    try:
        sys.__stdout__.write(line + "\n")
        sys.__stdout__.flush()
    except Exception:
        fallback = getattr(sys, "__stderr__", None)
        if fallback is not None:
            try:
                fallback.write(line + "\n")
                fallback.flush()
            except Exception:
                pass

PINNED_SOURCE_ORIGIN_N = {
    os.path.normcase(os.path.abspath(path)).replace(chr(92), "/").rstrip("/")
    for path in CONFIG["pinned_source_paths"]
}

class _OriginGuard:
    def _verify(self, *, require_all):
        observed = []
        for name, expected in sorted(EXPECTED_MODULE_PATHS.items()):
            module = sys.modules.get(name)
            if module is None:
                continue
            file_name = getattr(module, "__file__", None)
            spec = getattr(module, "__spec__", None)
            origin = getattr(spec, "origin", None)
            assert isinstance(file_name, str) and _norm(file_name) == expected, f"module_file_origin:{name}"
            assert isinstance(origin, str) and _norm(origin) == expected, f"module_spec_origin:{name}"
            observed.append({"module": name, "file": _norm(file_name), "origin": _norm(origin)})
        for name, module in tuple(sys.modules.items()):
            file_name = getattr(module, "__file__", None)
            if not isinstance(file_name, str) or _norm(file_name) not in PINNED_SOURCE_ORIGIN_N:
                continue
            spec = getattr(module, "__spec__", None)
            origin = getattr(spec, "origin", None)
            assert isinstance(origin, str) and _norm(origin) == _norm(file_name), f"pinned_module_spec_origin:{name}"
            if not any(item["module"] == name for item in observed):
                observed.append({"module": name, "file": _norm(file_name), "origin": _norm(origin)})
        loaded = {item["module"] for item in observed}
        if require_all:
            assert REQUIRED_MODULES <= loaded, f"required_module_origins_missing:{sorted(REQUIRED_MODULES - loaded)}"
        assert not any(
            _blocked_module(name) and name not in PRELOADED_GUARDED_MODULES
            for name in sys.modules
        ), "blocked_sdk_module_loaded"
        return observed

    def pytest_collection_finish(self, session):
        assert GUARD_INSTALLED, "guard_not_installed_before_collection"
        assert not _loaded_repository_conftests(), "repository_conftest_loaded"
        self._verify(require_all=True)

    def pytest_collectreport(self, report):
        global COLLECTION_FAILURES_REPORTED
        if not report.failed:
            return
        COLLECTION_FAILURES_REPORTED += 1
        if COLLECTION_FAILURES_REPORTED > COLLECTION_REPORT_LIMIT:
            return
        try:
            rendered = str(report.longrepr)
        except Exception as error:
            rendered = "<longrepr rendering failed: " + type(error).__name__ + ">"
        encoded = rendered.encode("utf-8", errors="replace")
        truncated = len(encoded) > COLLECTION_LONGREPR_LIMIT
        if truncated:
            rendered = encoded[:COLLECTION_LONGREPR_LIMIT].decode("utf-8", errors="ignore")
        record = {
            "nodeid": str(report.nodeid)[:512],
            "when": str(report.when)[:64],
            "longrepr": rendered,
            "longrepr_truncated": truncated,
            "longrepr_saved_bytes": len(rendered.encode("utf-8", errors="replace")),
        }
        line = "ROOT_M01_COLLECTION_FAILURE=" + json.dumps(
            record, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        try:
            sys.__stdout__.write(line + "\n")
            sys.__stdout__.flush()
        except Exception:
            fallback = getattr(sys, "__stderr__", None)
            if fallback is not None:
                try:
                    fallback.write(line + "\n")
                    fallback.flush()
                except Exception:
                    pass

    def pytest_runtest_logreport(self, report):
        global TEST_FAILURE_REPORTS_SEEN, TEST_FAILURE_REPORTS_EMITTED
        if not report.failed:
            return
        if _safe_test_identity(report)[0] not in {
            "m01_monitor",
            "m01_reader_lifecycle_integration",
        }:
            return
        TEST_FAILURE_REPORTS_SEEN += 1
        if TEST_FAILURE_REPORTS_SEEN > TEST_FAILURE_REPORT_LIMIT:
            return
        record = _test_failure_record(report)
        line = "ROOT_M01_TEST_FAILURE=" + json.dumps(
            record, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        )
        if len(line.encode("ascii")) <= TEST_FAILURE_RECORD_LIMIT:
            if _emit_public_marker("ROOT_M01_TEST_FAILURE=", record):
                TEST_FAILURE_REPORTS_EMITTED += 1

    def pytest_sessionfinish(self, session, exitstatus):
        _emit_public_marker("ROOT_M01_DENIAL_AUDIT=", _denial_audit_snapshot())
        assert not _loaded_repository_conftests(), "repository_conftest_loaded"
        observed = self._verify(require_all=True)
        missing_exec = REQUIRED_EXEC_N - EXECUTED_SOURCE_FILES
        assert not missing_exec, f"required_pinned_source_not_executed:{sorted(missing_exec)}"
        ORIGIN_REPORT["verified"] = True
        ORIGIN_REPORT["modules"] = observed
        ORIGIN_REPORT["executed_pinned_source_paths"] = sorted(EXECUTED_SOURCE_FILES)
        ORIGIN_REPORT["required_executed_pinned_source_paths"] = sorted(REQUIRED_EXEC_N)
        ORIGIN_REPORT["all_required_sources_executed"] = True
        ORIGIN_REPORT["repository_conftest_modules_loaded"] = []
        ORIGIN_REPORT["guard_installed_before_candidate_imports"] = GUARD_INSTALLED
        ORIGIN_REPORT["colorama_preloaded_before_native_denials"] = COLORAMA_PRELOADED
        ORIGIN_REPORT["denial_trip_count"] = DENIAL_TRIPS
        ORIGIN_REPORT["guard_self_checks"] = True
        assert DENIAL_TRIPS == 0, "a_forbidden_operation_was_attempted"
        pathlib.Path(CONFIG["origin_report"]).write_text(
            json.dumps(ORIGIN_REPORT, sort_keys=True), encoding="ascii", newline="\n"
        )

assert GUARD_INSTALLED
arguments = CONFIG["arguments"]
try:
    exit_code = int(pytest.main(arguments, plugins=[_OriginGuard()]))
finally:
    _emit_metadata_listing_audit()
assert exit_code == 0, "focused_source_fake_pytest_failed"
assert ORIGIN_REPORT["verified"] is True
assert ORIGIN_REPORT["guard_installed_before_candidate_imports"] is True
assert ORIGIN_REPORT["denial_trip_count"] == 0
print("ROOT_M01_GUARD_SELF_CHECKS=passed")
sys.exit(exit_code)
'''
    )


def main() -> None:
    assert ROOT.is_dir() and PACKET.is_dir() and OLD_PACKET.is_dir()
    assert PYTHON.is_file() and SITE.is_dir()
    assert _git("branch", "--show-current").strip() == b"dev"
    assert not _git("diff", "--cached", "--name-only", "-z")
    parent = _git("rev-parse", "HEAD").strip().decode("ascii")

    source_map, source_index, source_pre_pins = _check_packet()
    module_paths = {}
    package_prefix = "examples/000_live_certification/okx_penetration/"
    for relative in source_map["source_pins"]:
        if not relative.startswith(package_prefix):
            continue
        module_path = relative[len(package_prefix) :]
        if not (
            module_path.startswith("_certification/")
            or module_path.startswith("_m01_readonly_monitor_v2/")
            or module_path.startswith("_m01_readonly_monitor_v3/")
        ):
            continue
        if module_path.endswith("/__init__.py"):
            module_name = module_path[: -len("/__init__.py")].replace("/", ".")
        elif module_path.endswith(".py"):
            module_name = module_path[:-3].replace("/", ".")
        else:
            continue
        module_paths[module_name] = str(ROOT / relative)
    required_modules = {
        "_certification",
        "_certification.m01_private_monitor_v2",
        "_m01_readonly_monitor_v2",
        "_m01_readonly_monitor_v2.current_types",
        "_m01_readonly_monitor_v2.job_supervisor",
        "_m01_readonly_monitor_v2.worker",
        "_m01_readonly_monitor_v3",
        "_m01_readonly_monitor_v3.current_reader",
        "_m01_readonly_monitor_v3.entry",
        "_m01_readonly_monitor_v3.issuer",
    }
    assert required_modules <= set(module_paths), "required_canonical_module_paths_missing"
    indexed_paths = {row["path"] for row in source_index["rows"]}
    assert set(REQUIRED_EXECUTION_PATHS) <= indexed_paths
    required_exec_paths = [str(ROOT / relative) for relative in REQUIRED_EXECUTION_PATHS]
    required_exec_paths.extend(module_paths[name] for name in sorted(required_modules))
    pinned_source_paths = [
        str(ROOT / row["path"]) for row in source_index["rows"]
    ] + [str(ROOT / PUBLIC_ROOT_RUNNER)]

    QA.mkdir(parents=True, exist_ok=False)
    pytest_ini = QA / "pytest.ini"
    pytest_ini.write_text("[pytest]\n", encoding="ascii", newline="\n")
    test_args = [
        str(ROOT / TESTS[0]),
        str(ROOT / TESTS[1]),
        "--noconftest",
        "--collect-in-virtualenv",
        "--capture=sys",
        "-o",
        "log_file=" + str(QA / "pytest.log"),
        "-q",
        "--tb=short",
        "-c",
        str(pytest_ini),
        "-p",
        "no:asyncio",
        "-p",
        "no:cacheprovider",
        "--basetemp=" + str(QA / "pytest-tmp"),
    ]
    child_source = _child_program(
        test_args,
        module_paths,
        pinned_source_paths,
        required_exec_paths,
    )
    child_script = QA / "child.py"
    child_bytes = child_source.encode("utf-8")
    with child_script.open("xb") as stream:
        stream.write(child_bytes)
    assert child_script.read_bytes() == child_bytes
    child_script_pin = {"path": str(child_script), "size_bytes": len(child_bytes), "sha256": _sha(child_bytes)}
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR")
        if key in os.environ
    }
    env.update(
        {
            "PATH": str(PYTHON.parent),
            "TEMP": str(QA),
            "TMP": str(QA),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1",
            "PY_COLORS": "0",
        }
    )
    command = [
        str(PYTHON),
        "-I",
        "-S",
        "-B",
        "-X",
        "utf8",
        str(child_script),
    ]
    timed_out = False
    launch_error_type = None
    return_code = None
    stdout_raw = b""
    stderr_raw = b""
    try:
        completed = subprocess.run(
            command,
            cwd=QA,
            env=env,
            capture_output=True,
            timeout=120,
        )
        return_code = completed.returncode
        stdout_raw = _output_bytes(completed.stdout)
        stderr_raw = _output_bytes(completed.stderr)
    except subprocess.TimeoutExpired as error:
        timed_out = True
        stdout_raw = _output_bytes(error.stdout)
        stderr_raw = _output_bytes(error.stderr)
    except Exception as error:
        launch_error_type = type(error).__name__

    assert child_script.read_bytes() == child_bytes, "executed_child_source_changed"
    stdout_path = QA / "child.stdout.txt"
    stderr_path = QA / "child.stderr.txt"
    stdout_artifact = _persist_bounded_output(stdout_path, stdout_raw)
    stderr_artifact = _persist_bounded_output(stderr_path, stderr_raw)
    setup_status = None
    collection_reports = []
    metadata_listing_audit = None
    failed_test_reports = []
    denial_audit = None
    child_output_lines = (stdout_raw + b"\n" + stderr_raw).decode("utf-8", errors="replace").splitlines()
    for output_line in child_output_lines:
        if output_line.startswith("ROOT_M01_SETUP="):
            setup_status = json.loads(output_line[len("ROOT_M01_SETUP=") :])
        elif output_line.startswith("ROOT_M01_COLLECTION_FAILURE="):
            report = json.loads(output_line[len("ROOT_M01_COLLECTION_FAILURE=") :])
            if isinstance(report, dict) and len(collection_reports) < MAX_COLLECTION_REPORTS:
                longrepr = report.get("longrepr")
                if isinstance(longrepr, str) and len(longrepr.encode("utf-8", errors="replace")) <= MAX_COLLECTION_LONGREPR_BYTES:
                    collection_reports.append(report)
        elif output_line.startswith("ROOT_M01_METADATA_LISTING_AUDIT="):
            audit = json.loads(output_line[len("ROOT_M01_METADATA_LISTING_AUDIT=") :])
            if isinstance(audit, dict) and audit.get("path_values_recorded") is False:
                allowed_counts = audit.get("allowed_exact_ancestor_listing_counts")
                rejected_counts = audit.get("rejected_listing_category_counts")
                if (
                    isinstance(allowed_counts, dict)
                    and set(allowed_counts) == {"repository_parent", "drive_root"}
                    and all(type(value) is int and value >= 0 for value in allowed_counts.values())
                    and isinstance(rejected_counts, dict)
                    and set(rejected_counts)
                    == {"forbidden_or_private_path", "outside_reviewed_roots"}
                    and all(type(value) is int and value >= 0 for value in rejected_counts.values())
                ):
                    metadata_listing_audit = {
                        "allowed_exact_ancestor_listing_counts": dict(allowed_counts),
                        "rejected_listing_category_counts": dict(rejected_counts),
                        "scope": "Exact repository-parent and drive-root listdir/scandir metadata only.",
                        "path_values_recorded": False,
                    }
        elif output_line.startswith("ROOT_M01_TEST_FAILURE="):
            try:
                report = _safe_failure_record(
                    json.loads(output_line[len("ROOT_M01_TEST_FAILURE=") :])
                )
            except Exception:
                continue
            if report is not None and len(failed_test_reports) < MAX_TEST_FAILURE_REPORTS:
                failed_test_reports.append(report)
        elif output_line.startswith("ROOT_M01_DENIAL_AUDIT="):
            try:
                denial_audit = _safe_denial_audit(
                    json.loads(output_line[len("ROOT_M01_DENIAL_AUDIT=") :])
                )
            except Exception:
                continue
    if denial_audit is None and failed_test_reports:
        denial_audit = failed_test_reports[-1]["denial_audit"]
    failure_report_source = "child_output" if failed_test_reports else "none"
    if launch_error_type is not None:
        child_status = "launch_failed"
        failure_category = "child_launch_exception"
    elif timed_out:
        child_status = "timed_out"
        failure_category = "child_timeout"
    elif return_code != 0:
        child_status = "nonzero_exit"
        failure_category = "isolated_source_fake_exit_nonzero"
    else:
        child_status = "exit_zero_observed"
        failure_category = None
    diagnostic_record = {
        "schema": "iteration41.okx.m01.reader_lifecycle_integration_root_qa_r11_child_diagnostic.v1",
        "scope": "PUBLIC_SOURCE_FAKE_CHILD_DIAGNOSTIC_ONLY",
        "status": child_status,
        "suite_acceptance": "UNVERIFIED",
        "failure_category": failure_category,
        "exit_code": return_code,
        "timed_out": timed_out,
        "launch_error_type": launch_error_type,
        "expected_focused_tests": 16,
        "configured_pytest_capture_mode": "sys",
        "bounded_output_limit_bytes_each": MAX_CHILD_OUTPUT_BYTES,
        "executed_child_source": child_script_pin,
        "child_invocation_mode": "exact_generated_script_file",
        "executed_child_source_pre_post_matched": True,
        "stdout": stdout_artifact,
        "stderr": stderr_artifact,
        "failed_collection_reports": collection_reports,
        "collection_report_limit_count": MAX_COLLECTION_REPORTS,
        "collection_longrepr_limit_bytes": MAX_COLLECTION_LONGREPR_BYTES,
        "failed_test_reports": failed_test_reports,
        "failed_test_report_limit_count": MAX_TEST_FAILURE_REPORTS,
        "failed_test_record_limit_bytes": MAX_TEST_FAILURE_RECORD_BYTES,
        "failure_report_source": failure_report_source,
        "denial_audit": denial_audit,
        "failure_diagnostic_path_values_recorded": False,
        "failure_diagnostic_argument_values_recorded": False,
        "metadata_listing_audit": metadata_listing_audit,
        "exact_public_ancestor_metadata_exception": True,
        "pre_pytest_setup_observation": setup_status,
        "candidate_invocation": False,
        "actual_root_gate": False,
        "account_provider_operations": False,
        "native_api_denials_installed_before_pytest_candidate_imports": (
            setup_status.get("api_guards_installed_before_pytest_candidate_imports")
            if isinstance(setup_status, dict)
            else None
        ),
        "target_process_or_pipe_calls": False,
        "pytest_conftest_loading_disabled": (
            setup_status.get("pytest_conftest_loading_disabled")
            if isinstance(setup_status, dict)
            else None
        ),
        "colorama_preloaded_before_native_denials": (
            setup_status.get("colorama_preloaded_before_native_denials")
            if isinstance(setup_status, dict)
            else None
        ),
        "guard_scope": "Reviewed selected-suite enforcement; not a general filesystem sandbox.",
        "filesystem_metadata_queries_generally_denied": False,
    }
    with CHILD_DIAGNOSTIC_PATH.open("x", encoding="ascii", newline="\n") as stream:
        json.dump(diagnostic_record, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    print(
        "ROOT_M01_CHILD_DIAGNOSTIC_PATHS="
        + json.dumps(
            {
                "record": str(CHILD_DIAGNOSTIC_PATH),
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
                "status": child_status,
            },
            sort_keys=True,
        )
    )
    assert launch_error_type is None, (
        f"isolated_source_fake_launch_failed:{launch_error_type}; "
        f"diagnostic={CHILD_DIAGNOSTIC_PATH}; stdout={stdout_path}; stderr={stderr_path}"
    )
    assert not timed_out, (
        f"isolated_source_fake_timed_out; diagnostic={CHILD_DIAGNOSTIC_PATH}; "
        f"stdout={stdout_path}; stderr={stderr_path}"
    )
    assert setup_status is not None and setup_status.get("stdlib_fixture_dependencies_preloaded_before_guards") is True
    assert return_code == 0, (
        f"isolated_source_fake_exit_nonzero:{return_code}; "
        f"diagnostic={CHILD_DIAGNOSTIC_PATH}; stdout={stdout_path}; stderr={stderr_path}"
    )
    stdout = stdout_raw.decode("utf-8", errors="replace")
    stderr = stderr_raw.decode("utf-8", errors="replace")
    combined = stdout + stderr
    assert isinstance(setup_status, dict), (
        f"pre_pytest_setup_observation_missing; diagnostic={CHILD_DIAGNOSTIC_PATH}; "
        f"stdout={stdout_path}; stderr={stderr_path}"
    )
    assert setup_status.get("api_guards_installed_before_pytest_candidate_imports") is True
    assert setup_status.get("pytest_conftest_loading_disabled") is True
    assert "16 passed" in combined, "expected_sixteen_focused_tests"
    assert "ROOT_M01_GUARD_SELF_CHECKS=passed" in combined
    assert "warning" not in combined.casefold(), "unexpected_pytest_warning"
    origin_report_raw = _bounded_read(QA / "origin-report.json", 64 * 1024)
    origin_report = json.loads(origin_report_raw.decode("ascii"))
    assert origin_report["verified"] is True
    assert origin_report["guard_installed_before_candidate_imports"] is True
    assert origin_report["guard_self_checks"] is True
    assert origin_report["denial_trip_count"] == 0
    assert origin_report["all_required_sources_executed"] is True
    assert origin_report["repository_conftest_modules_loaded"] == []
    assert set(origin_report["required_executed_pinned_source_paths"]) == {
        os.path.normcase(os.path.abspath(path)).replace(chr(92), "/").rstrip("/")
        for path in required_exec_paths
    }

    source_post_pins = {}
    for relative, expected in source_pre_pins.items():
        raw = _bounded_read(ROOT / relative, expected["size"])
        actual = {"path": relative, "size": len(raw), "sha256": _sha(raw)}
        assert actual == expected, f"source_post_pin:{relative}"
        source_post_pins[relative] = actual
    assert source_post_pins == source_pre_pins
    for name, (size, digest) in PACKET_PINS.items():
        raw = _bounded_read(PACKET / name, size)
        assert len(raw) == size and _sha(raw) == digest, f"packet_post_pin:{name}"
    assert _git("rev-parse", "HEAD").strip().decode("ascii") == parent
    assert _git("branch", "--show-current").strip() == b"dev"
    assert not _git("diff", "--cached", "--name-only", "-z")

    result = {
        "schema": "iteration41.okx.m01.reader_lifecycle_integration_root_qa.v11",
        "scope": "PUBLIC_SOURCE_FAKE_QA_ONLY",
        "executed_child_source": child_script_pin,
        "child_invocation_mode": "exact_generated_script_file",
        "executed_child_source_pre_post_matched": True,
        "branch": "dev",
        "parent": parent,
        "candidate_invocation": False,
        "actual_root_gate": False,
        "account_provider_operations": False,
        "native_api_denials_installed_before_pytest_candidate_imports": True,
        "target_process_or_pipe_calls": False,
        "private_inputs_or_ignored_configs_read": False,
        "public_root_runner_source_verified": True,
        "opaque_external_software_payload_read": False,
        "isolated_pytest_interpreter_launched": True,
        "selected_api_and_open_path_guards_before_candidate_imports": True,
        "guard_scope": (
            "Reviewed selected-suite enforcement only; open-path/API checks do not form a general filesystem sandbox."
        ),
        "filesystem_metadata_queries_generally_denied": False,
        "metadata_listing_exception_scope": (
            "Exact ROOT.parent and drive-root listdir/scandir metadata only; path values are not recorded."
        ),
        "metadata_listing_audit": metadata_listing_audit,
        "denial_audit": denial_audit,
        "failed_test_reports": failed_test_reports,
        "failure_report_source": failure_report_source,
        "failure_diagnostic_path_values_recorded": False,
        "failure_diagnostic_argument_values_recorded": False,
        "pytest_conftest_loading_disabled": True,
        "pytest_capture_mode": "sys",
        "repository_conftests_loaded": False,
        "colorama_preloaded_before_native_denials": origin_report[
            "colorama_preloaded_before_native_denials"
        ],
        "selected_test_paths": list(TESTS),
        "windows_path_chr92_normalization_self_checks": True,
        "current_source_map_rows": 19,
        "archive_index_rows": 26,
        "source_test_dependency_rows": 27,
        "historical_archive_provenance_rows": 2,
        "source_index_sha256": SOURCE_INDEX_SHA256,
        "source_map_sha256": SOURCE_MAP_SHA256,
        "source_zip_sha256": SOURCE_ZIP_SHA256,
        "source_zip_member_count_verified": 26,
        "old_r2_archive_provenance_only": {
            "source_map_sha256": OLD_SOURCE_MAP_SHA256,
            "source_zip_sha256": OLD_SOURCE_ZIP_SHA256,
            "old_reader_sha256": OLD_READER_SHA256,
            "counts_as_current_runtime_or_account_proof": False,
        },
        "focused_pytest": {
            "passed": 16,
            "failed": 0,
            "exit_code": return_code,
            "warning_count": 0,
            "stdout_sha256": _sha(stdout_raw),
            "stderr_sha256": _sha(stderr_raw),
            "output_bytes": len(stdout_raw) + len(stderr_raw),
            "stdout_artifact": stdout_artifact,
            "stderr_artifact": stderr_artifact,
            "child_diagnostic_path": str(CHILD_DIAGNOSTIC_PATH),
            "pre_pytest_setup_observation": setup_status,
            "command": command,
        },
        "canonical_module_origins_verified": origin_report,
        "child_diagnostic_record_path": str(CHILD_DIAGNOSTIC_PATH),
        "pre_pytest_setup_observation": setup_status,
        "stdlib_fixture_dependencies_preloaded_before_guards": setup_status.get("stdlib_fixture_dependencies_preloaded_before_guards") is True,
        "colorama_preloaded_before_native_denials": origin_report[
            "colorama_preloaded_before_native_denials"
        ],
        "required_pinned_source_execution_verified": True,
        "public_source_dependency_and_historical_archive_pre_post_pins_match": True,
        "public_source_dependency_and_historical_archive_pins": [
            source_pre_pins[path] for path in sorted(source_pre_pins)
        ],
        "packet_files_pre_post_pins_match": True,
        "packet_file_pins": [
            {"path": name, "size": size, "sha256": digest}
            for name, (size, digest) in sorted(PACKET_PINS.items())
        ],
        "git_index_empty": True,
        "formal_m01_pass_count": 0,
    }
    with RESULT_PATH.open("x", encoding="ascii", newline="\n") as stream:
        json.dump(result, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key not in {"source_test_dependency_pins", "packet_file_pins", "canonical_module_origins_verified"}}, sort_keys=True))


if __name__ == "__main__":
    main()
