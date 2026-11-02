#!/usr/bin/env python
"""Retired registered-runtime wrapper for example 015.

The former ``backtrader_runtime`` integration is no longer available. Keep
local fixture replay through ``run.py --replay``; this file rejects the retired
entry without reading runtime configuration.
"""

from __future__ import annotations

import json
from typing import Optional, Sequence


def run_runtime(*args: object, **kwargs: object) -> None:
    """Reject callers of the removed registered-runtime API."""

    del args, kwargs
    raise RuntimeError("REGISTERED_RUNTIME_RETIRED_USE_RUN_PY_REPLAY")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Report retirement without parsing arguments or opening configuration."""

    del argv
    print(
        json.dumps(
            {
                "status": "BLOCKED",
                "reason": "REGISTERED_RUNTIME_RETIRED",
                "provider_configuration": "not_read",
                "provider_runtime": "not_started",
                "replay_entry": "python run.py --replay",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
