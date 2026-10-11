"""Run the L02 certification case (dry by default; --live to execute).

    python run.py                          # dry self-check
    python run.py --live --allow-write     # bounded order + cancel
"""

from __future__ import annotations

import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
VENUE_ROOT = CASE_DIR.parents[1]
for local_path in (str(CASE_DIR), str(VENUE_ROOT)):
    if local_path not in sys.path:
        sys.path.insert(0, local_path)

from certlib.runner import main_case  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main_case())
