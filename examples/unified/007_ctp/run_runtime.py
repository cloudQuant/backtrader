#!/usr/bin/env python
"""Retired config-first route for the historical CTP examples.

The former ``backtrader_runtime`` command validated a local schema-v4 profile
and emitted a no-action report. It did not construct Cerebro or execute a
Backtrader replay. No equivalent CTP-specific config-first runtime is
registered, so this entrypoint is retired. Native Backtrader replay APIs remain
available separately. This command does not read configuration or credentials.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional


HERE = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR = HERE / "runtime"
REPOSITORY_ROOT = HERE.parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from iteration41_007_ctp_retired_runtime import (  # noqa: E402
    legacy_direct_execution_error,
    run_retired_ctp_runtime_cli,
)


def runtime_registry() -> None:
    """Reject the removed registry instead of returning a dead placeholder."""

    raise legacy_direct_execution_error("examples/unified/007_ctp/runtime_registry")


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[object] = None,
    effective: Optional[object] = None,
    runtime_directory: Optional[object] = None,
) -> None:
    """Reject the retired route without opening the supplied directory."""

    del runtime_dir, registry, effective, runtime_directory
    raise legacy_direct_execution_error("examples/unified/007_ctp/run_runtime")


def main(argv: Optional[tuple[str, ...]] = None) -> int:
    return run_retired_ctp_runtime_cli(DEFAULT_RUNTIME_DIR, argv)


if __name__ == "__main__":
    raise SystemExit(main())
