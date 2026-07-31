"""Thin source-checkout forwarder to the canonical CLI."""

from __future__ import annotations

import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCT_ROOT / "src"))

from backtrader_skills.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["--target", str(PRODUCT_ROOT.parent), "doctor", *sys.argv[1:]]))
