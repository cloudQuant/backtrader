#!/usr/bin/env python
"""Retired direct-execution shell for the historical CTP sample.

The former version of this file imported ``ctpbeebt.CTPStore`` at module
import time, loaded ``params_01.json`` from the current working directory, and
could dispatch ``beeapi.action`` calls directly. That route predated the
configuration-first runtime contract and bypassed the Backtrader/SDK execution
boundary. It is deliberately *not* an Iteration 41 execution route.

The former ``backtrader_runtime`` config-first replay profile has no equivalent
supported CTP entrypoint and is retired. The retained runtime example config is
not read. Backtrader's native replay APIs remain available for ordinary local
data replay; they do not enable this historical CTP execution path.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, Optional

HERE = Path(__file__).resolve().parent
STRATEGY_ID = "example.sample.ctp_legacy"
DEFAULT_RUNTIME_DIR = HERE / "sample" / "runtime"
LOCAL_SCENARIO = "no_action"
LEGACY_PARAMS_FILENAME = "params_01.json"


# These constants and the time helper remain pure local compatibility helpers.
# They do not authorize a provider session or turn the migration shell into a
# CTP runner.
DAY_START = time(8, 45)
DAY_END = time(15, 0)
NIGHT_START = time(20, 45)
NIGHT_END = time(2, 45)


class Origin:
    """Retained data-name adapter with no provider or execution behavior."""

    def __init__(self, data: Any) -> None:
        self.symbol = data._dataname.split(".")[0]
        self.exchange = data._name.split(".")[1]


def is_trading_period(now: Optional[datetime] = None) -> bool:
    """Return the historical CTP session-window calculation without I/O."""

    current_time = (datetime.now() if now is None else now).time()
    return (
        DAY_START <= current_time <= DAY_END
        or current_time >= NIGHT_START
        or current_time <= NIGHT_END
    )


class LegacyDirectExecutionDisabled(RuntimeError):
    """Raised before a historical direct action can reach an external object."""

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(
            "legacy direct CTP action '{0}' is disabled; use a separately reviewed "
            "managed SDK/execution migration".format(action)
        )


def _reject_legacy_direct_execution(action: str) -> None:
    """Reject a legacy action without dereferencing ``beeapi`` or ``action``."""

    raise LegacyDirectExecutionDisabled(action)


class SmaCross:
    """Compatibility shell for the historical sample's direct action names.

    It intentionally no longer subclasses ``bt.Strategy``: importing the old
    framework/provider path merely to make a disabled direct writer available
    would violate the fail-closed startup boundary. The names remain here so
    old callers receive a deterministic rejection before any fake or real
    ``beeapi.action`` object can be touched.
    """

    lines = ("sma",)
    params = {"smaperiod": 5, "store": None}

    def open_long(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("buy")

    def open_short(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("short")

    def close_long(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("cover")

    def close_short(self, price: Any, size: Any, data: Any) -> None:
        del price, size, data
        _reject_legacy_direct_execution("sell")


def run_runtime(
    runtime_dir: Optional[Path] = DEFAULT_RUNTIME_DIR,
    *,
    registry: Optional[object] = None,
    effective: Optional[object] = None,
    runtime_directory: Optional[object] = None,
) -> Dict[str, Any]:
    """Reject the retired config-first CTP route without reading its config."""

    del runtime_dir, registry, effective, runtime_directory
    raise LegacyDirectExecutionDisabled("retired_config_first_runtime")


def main(argv: Optional[tuple[str, ...]] = None) -> int:
    """Report retirement without reading configuration or loading providers."""

    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIR,
        help="retired compatibility option; no configuration file is read",
    )
    args = parser.parse_args(argv)
    try:
        run_runtime(args.runtime_dir)
    except LegacyDirectExecutionDisabled as exc:
        print(
            json.dumps(
                {
                    "status": "NOT_SUPPORTED",
                    "error_code": "CTP_LEGACY_RUNTIME_RETIRED",
                    "runtime_config_read": False,
                    "external_request_counts": {"network": 0, "order_write": 0},
                    "message": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    raise AssertionError("retired CTP runtime unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
