"""Fail-closed response for retired CTP config-first entrypoints.

The old ``bt-runtime`` configuration registry has no equivalent CTP runtime
in the supported Backtrader/SDK surface. This module deliberately does not
read retained example config, import a provider, or create a Cerebro.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence


RETIRED_RUNTIME_CODE = "CTP_LEGACY_RUNTIME_RETIRED"


class LegacyCtpRuntimeUnavailable(RuntimeError):
    """Finite error returned by historical CTP runtime entrypoints."""

    code = RETIRED_RUNTIME_CODE

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__("{}:{}".format(RETIRED_RUNTIME_CODE, source))


def legacy_direct_execution_error(source: str) -> LegacyCtpRuntimeUnavailable:
    """Return a value-free error for one explicitly retired CTP callsite."""

    return LegacyCtpRuntimeUnavailable(source)


def run_retired_ctp_runtime_cli(
    runtime_dir: Optional[Path], argv: Optional[Sequence[str]] = None
) -> int:
    """Reject the old config-first command without reading its config file."""

    parser = argparse.ArgumentParser(
        description="Retired CTP config-first runtime; no config file is read.",
        allow_abbrev=False,
    )
    parser.add_argument("--runtime-dir", type=Path, default=runtime_dir)
    parser.parse_args(argv)
    sys.stderr.write(
        json.dumps(
            {
                "status": "NOT_SUPPORTED",
                "error_code": RETIRED_RUNTIME_CODE,
                "runtime_config_read": False,
                "external_request_counts": {"network": 0, "order_write": 0},
                "message": (
                    "No supported managed CTP runtime is registered for this historical "
                    "example; the bt-runtime command is retired."
                ),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        + "\n"
    )
    return 2
