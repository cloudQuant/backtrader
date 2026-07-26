#!/usr/bin/env python
"""Shortcut: run ALL 33 certification cases in spec order.

Equivalent to:  python run_case.py --all
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure suite dir is importable
_SUITE_DIR = Path(__file__).resolve().parent
if str(_SUITE_DIR) not in sys.path:
    sys.path.insert(0, str(_SUITE_DIR))

from run_case import CASE_ORDER, main as _run_main

if __name__ == "__main__":
    # Inject --all so run_case.main() executes the full suite
    sys.argv = [sys.argv[0], "--all"] + sys.argv[1:]
    _run_main()
