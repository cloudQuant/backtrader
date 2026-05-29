#!/usr/bin/env python3
"""Build the C++ feature cache from the Python data-preparation path."""

from __future__ import annotations

from pathlib import Path

import backtrader as bt

import run


BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    config = run.load_config()
    frame = run.load_data(config)
    out = frame["data"].reset_index().copy()
    out["datetime_num"] = out["datetime"].map(lambda x: f"{bt.date2num(x.to_pydatetime()):.15f}")
    cols = [
        "datetime_num",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
        "vol",
        "position_pct",
    ]
    output_path = BASE_DIR / "cpp" / "features.csv"
    out[cols].to_csv(output_path, index=False)
    print(f"Written {len(out)} rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
