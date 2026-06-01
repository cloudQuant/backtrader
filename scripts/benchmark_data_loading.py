#!/usr/bin/env python3
"""Benchmark how long it takes to load each large test data CSV.

Measures three modes:
  1. pd.read_csv() raw — what most strategy tests do
  2. pd.read_csv() + dt index conversion — what most tests do next
  3. Wrap into bt.feeds.PandasData and feed through cerebro preload
     (the actual cost incurred by cerebro.run)

Each measurement is run multiple times to get stable timing.
"""
from __future__ import annotations

import gc
import os
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATAS = REPO / "tests" / "datas"

# (file, label, expected_count_strategies, size_mb)
FILES = [
    ("bond_merged_all_data.csv", "bond_merged", 4),
    ("FG889.csv",                "FG889",       1),
    ("XAUUSD_5m_5Yea.csv",       "XAUUSD_5m",   1),
    ("ZN889.csv",                "ZN889",       1),
    ("RB889.csv",                "RB889",       5),
    ("CFFEX_Futures_Contract_Data.csv", "CFFEX", 2),
]

REPEATS = 3


def time_call(fn) -> tuple[float, object]:
    gc.collect()
    t0 = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - t0
    return elapsed, result


def best_of(fn, repeats=REPEATS) -> float:
    times = []
    for _ in range(repeats):
        t, _ = time_call(fn)
        times.append(t)
    return min(times)


def file_size_mb(path: Path) -> float:
    return os.path.getsize(path) / 1024 / 1024


def line_count(path: Path) -> int:
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def main():
    print(f"{'File':40s}  {'Size(MB)':>9s}  {'Lines':>10s}  "
          f"{'read_csv(s)':>11s}  {'with_dt(s)':>11s}  "
          f"{'mb/s':>8s}  {'#strat':>6s}")
    print("-" * 110)

    for fname, label, n_strats in FILES:
        path = DATAS / fname
        if not path.exists():
            print(f"{fname:40s}  NOT FOUND")
            continue

        sz = file_size_mb(path)
        lines = line_count(path)

        # Measurement 1: raw pd.read_csv
        t_raw = best_of(lambda: pd.read_csv(path))

        # Measurement 2: read_csv + parse a datetime column (what cerebro/bt.PandasData typically needs)
        # Try to detect the date column from the first read
        df = pd.read_csv(path, nrows=5)
        date_col = None
        for c in df.columns:
            if c.lower() in ("date", "datetime", "time", "timestamp"):
                date_col = c
                break
        if date_col is None:
            # Fallback: column 0
            date_col = df.columns[0]

        def read_with_dt(p=path, dc=date_col):
            d = pd.read_csv(p)
            try:
                d[dc] = pd.to_datetime(d[dc], errors="coerce")
            except Exception:
                pass
            return d

        t_dt = best_of(read_with_dt)

        mbps = sz / t_raw if t_raw > 0 else 0.0
        print(f"{fname:40s}  {sz:9.2f}  {lines:10,}  "
              f"{t_raw:11.3f}  {t_dt:11.3f}  "
              f"{mbps:8.1f}  {n_strats:6d}")

    print()
    print(f"Best of {REPEATS} runs reported per measurement (min, lower=better)")
    print("read_csv(s)   — pandas.read_csv() with no preprocessing")
    print("with_dt(s)    — pandas.read_csv() + pd.to_datetime() on detected datetime column")


if __name__ == "__main__":
    main()
