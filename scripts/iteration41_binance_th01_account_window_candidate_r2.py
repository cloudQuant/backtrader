"""Cold-source Root launcher for a bounded Binance USDⓈ-M read candidate.

The Root operator must verify this launcher and both implementation pins
before invocation.  There is no certification CLI registration.  On Windows
spawn, the child re-executes this same script and exact-loads the accepted
fixed-GET owner target into its main namespace before multiprocessing resolves
the worker name.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import ModuleType
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
OWNER_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_root_protected_owner_r1.py"
)
CANDIDATE_PATH = (
    ROOT
    / "examples"
    / "000_live_certification"
    / "binance_penetration"
    / "_certification"
    / "th01_account_window_candidate_r2.py"
)
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
CANDIDATE_SHA256 = "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63"
MAX_SOURCE_BYTES = 250_000
_CANDIDATE_MODULE_PREFIX = "_iteration41_th01_account_window_candidate_r2_"


class _LauncherBlocked(Exception):
    pass


def _fail() -> None:
    raise _LauncherBlocked()


def _read_pinned_public_source(path: Path, expected_sha256: str, maximum: int) -> bytes:
    """Shape-check before reading and bind the exact bytes compiled below."""
    try:
        lexical = Path(os.path.abspath(str(path)))
        relative = lexical.relative_to(ROOT)
        if not relative.parts or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            _fail()
        directories = list(reversed(ROOT.parents)) + [ROOT]
        current = ROOT
        for part in relative.parts[:-1]:
            current = current / part
            directories.append(current)
        for directory in directories:
            info = directory.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                _fail()
        before = lexical.lstat()
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or getattr(before, "st_file_attributes", 0) & 0x400
            or getattr(before, "st_nlink", 1) != 1
            or before.st_size <= 0
            or before.st_size > maximum
        ):
            _fail()
        descriptor = os.open(str(lexical), os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            opened = os.fstat(descriptor)
            identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                getattr(before, "st_mtime_ns", None),
                getattr(before, "st_ctime_ns", None),
            )
            opened_identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                getattr(opened, "st_mtime_ns", None),
                getattr(opened, "st_ctime_ns", None),
            )
            if identity != opened_identity or getattr(opened, "st_nlink", 1) != 1:
                _fail()
            buffer = bytearray()
            while len(buffer) <= maximum:
                part = os.read(descriptor, min(65536, maximum + 1 - len(buffer)))
                if not part:
                    break
                buffer.extend(part)
            after_handle = os.fstat(descriptor)
            after_path = lexical.lstat()
            after_identity = (
                after_handle.st_dev,
                after_handle.st_ino,
                after_handle.st_size,
                getattr(after_handle, "st_mtime_ns", None),
                getattr(after_handle, "st_ctime_ns", None),
            )
            path_identity = (
                after_path.st_dev,
                after_path.st_ino,
                after_path.st_size,
                getattr(after_path, "st_mtime_ns", None),
                getattr(after_path, "st_ctime_ns", None),
            )
            if (
                after_identity != identity
                or path_identity != identity
                or stat.S_ISLNK(after_path.st_mode)
                or getattr(after_path, "st_file_attributes", 0) & 0x400
                or getattr(after_path, "st_nlink", 1) != 1
            ):
                _fail()
        finally:
            os.close(descriptor)
        raw = bytes(buffer)
        if len(raw) != before.st_size or len(raw) > maximum:
            _fail()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            _fail()
        return raw
    except _LauncherBlocked:
        raise
    except Exception:
        _fail()


def _load_fixed_get_owner(namespace: dict[str, object]) -> None:
    raw = _read_pinned_public_source(OWNER_PATH, OWNER_SHA256, MAX_SOURCE_BYTES)
    saved_file = namespace.get("__file__")
    namespace["__file__"] = str(OWNER_PATH)
    try:
        exec(compile(raw, str(OWNER_PATH), "exec", dont_inherit=True), namespace)
    finally:
        namespace["__file__"] = saved_file
    namespace["__th01_verified_owner_source_sha256__"] = OWNER_SHA256
    namespace["__th01_verified_owner_source_path__"] = str(OWNER_PATH)


def _load_candidate_module() -> ModuleType:
    raw = _read_pinned_public_source(CANDIDATE_PATH, CANDIDATE_SHA256, 100_000)
    name = _CANDIDATE_MODULE_PREFIX + uuid4().hex
    module = ModuleType(name)
    module.__file__ = str(CANDIDATE_PATH)
    module.__package__ = ""
    module.__dict__["__th01_verified_candidate_source_sha256__"] = CANDIDATE_SHA256
    sys.modules[name] = module
    try:
        exec(compile(raw, str(CANDIDATE_PATH), "exec", dont_inherit=True), module.__dict__)
    except Exception:
        if sys.modules.get(name) is module:
            sys.modules.pop(name, None)
        _fail()
    return module


def _safe_json(document: dict[str, object]) -> None:
    print(json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True))


def _bootstrap_public_sources() -> ModuleType:
    _load_fixed_get_owner(globals())
    candidate = _load_candidate_module()
    if (
        globals().get("ROOT") != ROOT
        or globals().get("__th01_verified_owner_source_sha256__") != OWNER_SHA256
        or globals().get("_root_fixed_signed_get_worker") is None
        or globals()["_root_fixed_signed_get_worker"].__module__ != globals().get("__name__")
    ):
        _fail()
    return candidate


try:
    _CANDIDATE_MODULE = _bootstrap_public_sources()
except Exception:
    _safe_json(
        {
            "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
            "status": "BLOCKED_ACCOUNT_SNAPSHOT",
            "first_failure": {"stage": "source_preflight", "category": "source_binding_invalid"},
            "account_read_started": False,
            "account_full_snapshot_issued": False,
            "formal_case_pass": False,
            "request_absence_inference": False,
        }
    )
    raise SystemExit(2)


def _source_only_qa() -> int:
    try:
        source_hashes = _CANDIDATE_MODULE.source_preflight(ROOT)
        _CANDIDATE_MODULE._verify_candidate_source_binding()
    except Exception:
        _safe_json(
            {
                "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
                "status": "BLOCKED_SOURCE_QA",
                "source_preflight_complete": False,
                "provider_read_started": False,
            }
        )
        return 2
    _safe_json(
        {
            "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
            "status": "SOURCE_ONLY_QA",
            "owner_source_bound": True,
            "candidate_source_bound": True,
            "protected_source_pins_checked": len(source_hashes) == 3,
            "runtime_package_loaded": "backtrader_runtime" in sys.modules,
            "private_helper_loaded": False,
            "protected_credential_read": False,
            "provider_read_started": False,
            "trading_write_started": False,
            "account_full_snapshot_issued": False,
            "formal_case_pass": False,
        }
    )
    return 0


def _root_read(history_start_ms: int, phase_cutoff_ms: int) -> int:
    try:
        candidate = _CANDIDATE_MODULE.create_root_read_candidate(
            history_start_ms=history_start_ms,
            phase_cutoff_ms=phase_cutoff_ms,
        )
        _safe_json(candidate.public_document())
        return 0
    except _CANDIDATE_MODULE.AccountWindowBlocked as exc:
        projection = getattr(exc, "public_projection", None)
        if type(projection) is dict:
            _safe_json(projection)
        else:
            _safe_json(
                {
                    "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
                    "status": "BLOCKED_ACCOUNT_SNAPSHOT",
                    "first_failure": {"stage": "root_read", "category": "unexpected_failure"},
                    "account_read_started": False,
                    "account_full_snapshot_issued": False,
                    "formal_case_pass": False,
                    "request_absence_inference": False,
                }
            )
        return 0
    except Exception:
        _safe_json(
            {
                "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
                "status": "BLOCKED_ACCOUNT_SNAPSHOT",
                "first_failure": {"stage": "root_read", "category": "unexpected_failure"},
                "account_read_started": False,
                "account_full_snapshot_issued": False,
                "formal_case_pass": False,
                "request_absence_inference": False,
            }
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments == ["--qa-source-only"]:
        return _source_only_qa()
    if len(arguments) == 3 and arguments[0] == "--root-read-only-window":
        try:
            start_ms = int(arguments[1])
            cutoff_ms = int(arguments[2])
        except Exception:
            _safe_json(
                {
                    "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
                    "status": "BLOCKED_ACCOUNT_SNAPSHOT",
                    "first_failure": {"stage": "window_validation", "category": "invalid_window"},
                    "account_read_started": False,
                    "account_full_snapshot_issued": False,
                    "formal_case_pass": False,
                    "request_absence_inference": False,
                }
            )
            return 0
        return _root_read(start_ms, cutoff_ms)
    _safe_json(
        {
            "schema": "iteration41.binance.th01.account-window-candidate-public.r2",
            "status": "BLOCKED_SOURCE_QA",
            "first_failure": {"stage": "launcher", "category": "unsupported_invocation"},
            "provider_read_started": False,
            "account_full_snapshot_issued": False,
            "formal_case_pass": False,
        }
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
