#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Shared data-loading helpers for functional tests and examples."""

from __future__ import absolute_import, division, print_function, unicode_literals

from functools import lru_cache
from pathlib import Path

_BASE_COLUMNS = ["open", "high", "low", "close", "volume", "openinterest"]
_AUGMENT_COLUMNS = ("tick_volume", "real_volume", "spread")


def resolve_repo_paths(node, repo=None, placeholder="{repo}"):
    """Resolve repo placeholders inside nested config data."""
    if repo is None:
        return node

    repo_text = str(repo)

    if isinstance(node, dict):
        return {
            key: resolve_repo_paths(value, repo=repo_text, placeholder=placeholder)
            for key, value in node.items()
        }

    if isinstance(node, list):
        return [
            resolve_repo_paths(value, repo=repo_text, placeholder=placeholder) for value in node
        ]

    if isinstance(node, tuple):
        return tuple(
            resolve_repo_paths(value, repo=repo_text, placeholder=placeholder) for value in node
        )

    if isinstance(node, str):
        return node.replace(placeholder, repo_text)

    return node


def load_config(config, repo=None, placeholder="{repo}"):
    """Return a deep-copied inline config with repo placeholders resolved."""
    import copy

    return resolve_repo_paths(
        copy.deepcopy(config),
        repo=repo,
        placeholder=placeholder,
    )


def _first_non_empty_line(filepath):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if line:
                return line.strip('"')

    raise ValueError("MT5 CSV file is empty: %s" % filepath)


def _read_cleaned_mt5_csv(filepath, sep):
    import io

    import pandas as pd

    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle if line.strip()]

    if not lines:
        raise ValueError("MT5 CSV file is empty: %s" % filepath)

    return pd.read_csv(io.StringIO("\n".join(lines)), sep=sep)


def _needs_cleaned_read(df):
    if "time" in df.columns:
        return False
    return "<DATE>" not in df.columns or "<TIME>" not in df.columns


def _read_mt5_csv(filepath, bar_shift_minutes=0):
    """Read MT5 data and keep standard plus known raw columns."""
    path = Path(filepath)
    stat = path.stat()
    return _read_mt5_csv_cached(
        str(path),
        stat.st_mtime_ns,
        stat.st_size,
        int(bar_shift_minutes or 0),
    )


@lru_cache(maxsize=32)
def _read_mt5_csv_cached(filepath, mtime_ns, size, bar_shift_minutes):
    """Read MT5 data once per file version and timestamp shift."""
    import pandas as pd

    sep = "\t" if "\t" in _first_non_empty_line(filepath) else ","
    df = pd.read_csv(filepath, sep=sep, encoding="utf-8", encoding_errors="ignore")
    if _needs_cleaned_read(df):
        df = _read_cleaned_mt5_csv(filepath, sep)

    if "time" in df.columns:
        parsed = pd.to_datetime(df["time"], errors="coerce", utc=True).dt.tz_convert(None)
    else:
        dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
        if parsed.isna().any():
            parsed = pd.to_datetime(
                dt_text,
                format="%Y.%m.%d %H:%M:%S",
                errors="coerce",
            )
        if parsed.isna().any():
            parsed = pd.to_datetime(dt_text, errors="coerce")

    if bar_shift_minutes:
        parsed = parsed + pd.to_timedelta(int(bar_shift_minutes), unit="m")

    df["datetime"] = parsed
    df = df.rename(
        columns={
            "<OPEN>": "open",
            "<HIGH>": "high",
            "<LOW>": "low",
            "<CLOSE>": "close",
            "<TICKVOL>": "tick_volume",
            "<VOL>": "real_volume",
            "<SPREAD>": "spread",
        }
    )

    if "volume" not in df.columns:
        if "tick_volume" in df.columns:
            df["volume"] = df["tick_volume"]
        elif "real_volume" in df.columns:
            df["volume"] = df["real_volume"]
        else:
            df["volume"] = 0
    if "openinterest" not in df.columns:
        df["openinterest"] = df["real_volume"] if "real_volume" in df.columns else 0

    columns = ["datetime"] + _BASE_COLUMNS
    columns.extend(column for column in _AUGMENT_COLUMNS if column in df.columns)

    return df[columns].dropna(subset=["datetime"]).set_index("datetime").sort_index()


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5 CSV data into a normalized OHLCV DataFrame."""
    df = _read_mt5_csv(filepath, bar_shift_minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df.loc[:, _BASE_COLUMNS].copy()


def augment_mt5_csv_columns(frame, filepath, columns, bar_shift_minutes=0):
    """Add selected raw MT5 columns to a DataFrame returned by ``load_mt5_csv``."""
    raw = _read_mt5_csv(filepath, bar_shift_minutes=bar_shift_minutes)
    result = frame.copy()

    for column in columns:
        if column not in _AUGMENT_COLUMNS:
            raise ValueError("Unsupported MT5 augment column: %s" % column)
        if column in raw.columns:
            result[column] = raw[column].reindex(result.index).fillna(0)
        else:
            result[column] = 0

    return result
