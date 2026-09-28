"""Compatibility entrypoint for the source-tree 013_3 offline L2 fixture.

The implementation is package-owned so the exact same fake-provider route can
be installed for an isolated consumer test.  This thin wrapper preserves the
source runtime directory and central source registry used by existing example
commands; it never introduces a live/provider route.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from backtrader_runtime._iteration41_l2_fixture import managed_013_3 as _fixture
from backtrader_runtime.errors import RuntimeConfigError
from backtrader_runtime.registry import EffectiveRuntimeConfig, RuntimeRegistry
from backtrader_runtime.runner import (
    dispatch_configured_runtime,
    resolve_runner_effective_config,
)

HERE = Path(__file__).resolve().parent
DEFAULT_RUNTIME_DIR = HERE / "runtime-managed-replay"
STRATEGY_ID = "example.013_3.sa_midfreq_simnow"


def runtime_registry() -> RuntimeRegistry:
    """Return the reviewed source-tree inventory for legacy source commands."""

    from backtrader_runtime.inventory import iteration41_runtime_registry

    return iteration41_runtime_registry()


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[RuntimeRegistry] = None,
    effective: Optional[EffectiveRuntimeConfig] = None,
    runtime_directory: Optional[object] = None,
) -> dict[str, Any]:
    """Forward the source registration to the package-owned offline fixture."""

    trusted_registry = runtime_registry() if registry is None else registry
    sealed = resolve_runner_effective_config(runtime_dir, trusted_registry, effective=effective)
    return _fixture.run_runtime(
        None,
        registry=trusted_registry,
        effective=sealed,
        runtime_directory=runtime_directory,
    )


def main(argv: Optional[list[str]] = None) -> int:
    """Run the source-tree registered offline fixture or print a safe rejection."""

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    args = parser.parse_args(argv)
    try:
        report = dispatch_configured_runtime(args.runtime_dir, runtime_registry())
    except RuntimeConfigError as error:
        print(json.dumps({"status": "REJECTED", "error": error.as_dict()}, sort_keys=True))
        return 2
    print(json.dumps(report, default=str, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
