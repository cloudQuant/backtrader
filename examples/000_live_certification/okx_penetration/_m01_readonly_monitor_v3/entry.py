"""Exact M01 V3 case entry; deployment admission precedes credential access."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path("D:/source_code/backtrader")
VENUE = ROOT / "examples/000_live_certification/okx_penetration"
PROFILE = "OKX_GLOBAL_DEMO_M01_CASE_V3"
_SAFE_REASON = re.compile(r"[a-z0-9_]{1,64}\Z")
_PINNED_PREIMPORTS = {
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py": "b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py": "d7cbd961ed06466f6bd2388d44a5951f92b0bb9f61d930cc9d26ec21be8d1a5c",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py": "cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py": "aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41",
    "examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py": "188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82",
    "examples/000_live_certification/okx_penetration/_certification/__init__.py": "a55f2a221bc45d1b840c15ca9ec8e5f46579e011728ec9e7c3b0748eacc7f7dc",
    "examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py": "1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db",
}


def _safe_result(status: str, reason: str) -> dict[str, Any]:
    if status not in {"PASS", "BLOCKED", "FAILED"}:
        status, reason = "BLOCKED", "m01_result_invalid"
    if type(reason) is not str or not _SAFE_REASON.fullmatch(reason):
        status, reason = "BLOCKED", "m01_case_blocked"
    return {
        "case_id": "M01",
        "status": status,
        "reason": reason,
        "receipt_count": 1 if status == "PASS" else 0,
        "observation_count": 1 if status == "PASS" else 0,
    }


def _print_result(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    if result["status"] == "PASS":
        return 0
    if result["status"] == "FAILED":
        return 1
    return 2


def _verify_preimports() -> None:
    for relative, expected in _PINNED_PREIMPORTS.items():
        if expected.startswith("PENDING_"):
            raise RuntimeError("source_pin_pending")
        path = ROOT / relative
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise RuntimeError("source_pin_mismatch")
    if str(VENUE) not in sys.path:
        sys.path.insert(0, str(VENUE))
    case_directory = VENUE / "cases" / "M01"
    if str(case_directory) not in sys.path:
        sys.path.insert(0, str(case_directory))
    for name, relative in (
        ("_m01_readonly_monitor_v2.current_types", "_m01_readonly_monitor_v2/current_types.py"),
        ("_m01_readonly_monitor_v2.worker", "_m01_readonly_monitor_v2/worker.py"),
        ("_m01_readonly_monitor_v2.job_supervisor", "_m01_readonly_monitor_v2/job_supervisor.py"),
    ):
        module = importlib.import_module(name)
        if Path(module.__file__).resolve() != (VENUE / relative).resolve():
            raise RuntimeError("module_origin_mismatch")


def main(argv: list[str] | None = None) -> int:
    """Run only the fixed M01 read-only route; caller flags/config are rejected."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments:
        return _print_result(_safe_result("BLOCKED", "fixed_m01_route_takes_no_arguments"))

    admission = None
    admission_owned = False
    try:
        _verify_preimports()
        from . import current_reader

        if (
            Path(current_reader.__file__).resolve()
            != (VENUE / "_m01_readonly_monitor_v3" / "current_reader.py").resolve()
        ):
            raise RuntimeError("current_reader_module_origin_mismatch")
        admission = current_reader.admit_source()
        admission_owned = True

        package = importlib.import_module("_m01_readonly_monitor_v3")
        package_path = Path(package.__file__).resolve()
        if package_path != (VENUE / "_m01_readonly_monitor_v3" / "__init__.py").resolve():
            raise RuntimeError("v3_package_origin_mismatch")
        issuer_name = "_m01_readonly_monitor_v3.issuer"
        if issuer_name in sys.modules:
            raise RuntimeError("issuer_module_preloaded")
        issuer = importlib.import_module(issuer_name)
        if (
            Path(issuer.__file__).resolve()
            != (VENUE / "_m01_readonly_monitor_v3" / "issuer.py").resolve()
        ):
            raise RuntimeError("issuer_module_origin_mismatch")
        admission_owned = False
        result = issuer.run_m01_case_v3(admission)
        model_module = importlib.import_module("_certification.models")
        if (
            type(result) is not model_module.CaseResult
            or type(result.status) is not model_module.Status
        ):
            raise RuntimeError("formal_case_result_required")
        return _print_result(_safe_result(result.status.value, result.reason))
    except BaseException as error:
        if admission_owned and admission is not None:
            try:
                from . import current_reader

                current_reader.release_admission(admission)
            except BaseException:
                current_reader._ORPHANED_SOURCE_ADMISSIONS.append(admission)
        code = getattr(error, "code", None) or getattr(error, "reason", None)
        reason = (
            code
            if type(code) is str and _SAFE_REASON.fullmatch(code)
            else "m01_source_or_run_blocked"
        )
        return _print_result(_safe_result("BLOCKED", reason))


if __name__ == "__main__":
    raise SystemExit(main())
