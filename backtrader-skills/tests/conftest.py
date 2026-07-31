from __future__ import annotations

import sys
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PRODUCT_ROOT / "src"
REPOSITORY_ROOT = PRODUCT_ROOT.parent
sys.path.insert(0, str(SOURCE_ROOT))
