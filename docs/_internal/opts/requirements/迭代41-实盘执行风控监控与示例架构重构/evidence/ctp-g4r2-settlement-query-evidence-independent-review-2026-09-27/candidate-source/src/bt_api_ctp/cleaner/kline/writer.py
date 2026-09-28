"""Append bars to a K-line file, atomically and idempotently.

A K-line file holds every day ever synthesised for one instrument/period, so
the append is a read-merge-write: the existing rows are loaded, the new bars
overwrite their own bucket (re-running a day must not duplicate it), and the
result replaces the file in one ``os.replace``.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from bt_api_ctp.cleaner.kline.schema import BAR_ARROW_SCHEMA, Bar, bar_to_row


def kline_path(
    kline_root: Path | str, exchange_id: str, symbol: str, instrument_id: str, period: int
) -> Path:
    """``<kline_root>/<exchange>/<symbol>/<instrument>_<period>min.parquet``."""
    return Path(kline_root) / exchange_id / symbol / f"{instrument_id}_{period}min.parquet"


def _load_existing(path: Path) -> dict[int, dict[str, Any]]:
    """Existing rows keyed by their bucket, using the timestamp column as int64 ns."""
    if not path.exists():
        return {}
    table = pq.read_table(path)
    keys = table.column("datetime").cast(pa.int64()).to_pylist()
    rows = table.to_pylist()
    return {int(key): row for key, row in zip(keys, rows)}


def _write_atomically(path: Path, rows: list[dict[str, Any]]) -> None:
    table = pa.Table.from_pylist(rows, schema=BAR_ARROW_SCHEMA)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def append_bars(path: Path | str, bars: Iterable[Bar]) -> int:
    """Merge ``bars`` into the file and return the file's total row count."""
    target = Path(path)
    merged = _load_existing(target)
    for bar in bars:
        merged[bar.datetime] = bar_to_row(bar)
    if not merged:
        return 0
    rows = [merged[key] for key in sorted(merged)]
    _write_atomically(target, rows)
    return len(rows)


__all__ = ["append_bars", "kline_path"]
