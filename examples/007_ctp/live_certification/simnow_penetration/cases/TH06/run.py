"""Run one case through the suite-root managed entry point."""

from pathlib import Path
import sys

_SUITE_ROOT = Path(__file__).resolve().parents[2]
if str(_SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUITE_ROOT))

import managed_case_entry  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(managed_case_entry.main('TH06', __file__))
