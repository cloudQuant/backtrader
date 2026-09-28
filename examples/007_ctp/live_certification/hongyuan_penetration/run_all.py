#!/usr/bin/env python
"""Shortcut: run ALL 33 certification cases in spec order.

Equivalent to:  python run_case.py --all
"""
from __future__ import annotations

# This fence must remain before every legacy framework, CTP, or provider import.
import sys as _iteration41_sys
from pathlib import Path as _Iteration41Path

_ITERATION41_RUNTIME_DIR = _Iteration41Path(__file__).resolve().parents[2] / "runtime"
_ITERATION41_REPOSITORY_ROOT = _ITERATION41_RUNTIME_DIR.parents[2]
if str(_ITERATION41_REPOSITORY_ROOT) not in _iteration41_sys.path:
    _iteration41_sys.path.insert(0, str(_ITERATION41_REPOSITORY_ROOT))

from backtrader_runtime.legacy import (  # noqa: E402
    legacy_direct_execution_error as _iteration41_legacy_direct_execution_error,
    run_legacy_config_first_cli as _iteration41_run_legacy_config_first_cli,
)


def _run_config_first_cli(argv=None) -> int:
    return _iteration41_run_legacy_config_first_cli(_ITERATION41_RUNTIME_DIR, argv)


def main(*args, **kwargs):
    del args, kwargs
    raise _iteration41_legacy_direct_execution_error("examples/007_ctp/live_certification/hongyuan_penetration/run_all.py")


if __name__ == "__main__":
    raise SystemExit(_run_config_first_cli())

import sys
from pathlib import Path

# Ensure suite dir is importable
_SUITE_DIR = Path(__file__).resolve().parent
if str(_SUITE_DIR) not in sys.path:
    sys.path.insert(0, str(_SUITE_DIR))

from run_case import CASE_ORDER, main as _run_main

# Iteration 41 retains this historical body for review only; direct execution is disabled.
if False:  # pragma: no cover - retired direct entrypoint

    # Inject --all so run_case.main() executes the full suite
    sys.argv = [sys.argv[0], "--all"] + sys.argv[1:]
    _run_main()
