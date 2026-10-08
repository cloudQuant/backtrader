"""Run only the fixed, source-admitted OKX M01 read-only route."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys


CASE_DIRECTORY = Path(__file__).resolve().parent
VENUE_ROOT = CASE_DIRECTORY.parents[1]
ENTRY_PATH = VENUE_ROOT / "_m01_readonly_monitor_v3" / "entry.py"
PACKAGE_INIT_PATH = VENUE_ROOT / "_m01_readonly_monitor_v3" / "__init__.py"
ENTRY_SHA256 = "a5ac85ff1b4c19a542abff56e728696eedee3959e5e7e4df8d6ac7cec0332575"
PACKAGE_INIT_SHA256 = "ae66c18bb4d289dd2e09e9ac637af8a6ef017f4f6cc5edec4a23ee23d7e560e6"


def _blocked(reason: str = "m01_source_or_run_blocked") -> int:
    print(
        json.dumps(
            {
                "case_id": "M01",
                "status": "BLOCKED",
                "reason": reason,
                "receipt_count": 0,
                "observation_count": 0,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2


def main() -> int:
    if CASE_DIRECTORY.name != "M01" or sys.argv[1:]:
        return _blocked("fixed_m01_route_takes_no_arguments")
    if (
        not ENTRY_PATH.is_file()
        or hashlib.sha256(ENTRY_PATH.read_bytes()).hexdigest() != ENTRY_SHA256
    ):
        return _blocked("v3_entry_source_pin_mismatch")
    if (
        not PACKAGE_INIT_PATH.is_file()
        or hashlib.sha256(PACKAGE_INIT_PATH.read_bytes()).hexdigest() != PACKAGE_INIT_SHA256
    ):
        return _blocked("v3_package_source_pin_mismatch")
    for path in (str(VENUE_ROOT), str(CASE_DIRECTORY)):
        if path not in sys.path:
            sys.path.insert(0, path)
    try:
        entry = importlib.import_module("_m01_readonly_monitor_v3.entry")
        if Path(entry.__file__).resolve() != ENTRY_PATH.resolve():
            return _blocked("v3_entry_module_origin_mismatch")
        return entry.main([])
    except BaseException:
        return _blocked()


if __name__ == "__main__":
    raise SystemExit(main())
