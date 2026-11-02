#!/usr/bin/env python
"""Retired Iteration 53 runtime CLI; use this example's run.py entrypoint."""

from __future__ import annotations

import json


def main(argv=None) -> int:
    """Report retirement without loading runtime configuration or providers."""

    del argv
    print(
        json.dumps(
            {
                "status": "RETIRED",
                "reason": "BACKTRADER_RUNTIME_RETIRED",
                "replacement": "run.py",
                "message": "Use run.py for the supported replay or managed entrypoint.",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
