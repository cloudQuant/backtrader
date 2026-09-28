"""Run L04 through the suite-managed case entry point."""

from pathlib import Path
import sys

_SUITE_ROOT = Path(__file__).resolve().parents[2]
if str(_SUITE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUITE_ROOT))

from managed_case_entry import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main("L04", __file__))
