"""Stream a sorted China A-share 1-minute Parquet file into daily bars.

The input timestamps are naive and are interpreted as Asia/Shanghai local
times. This script preserves every source row; it does not adjust prices,
fill gaps, or infer an exchange calendar.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("trade_time", "symbol", "open", "high", "low", "close", "vol", "amount")
NUMERIC_COLUMNS = ("open", "high", "low", "close", "vol", "amount")
HASH_CHUNK_SIZE = 8 * 1024 * 1024
DEFAULT_BATCH_SIZE = 250000
CSV_FIELDS = (
    "trade_date",
    "trade_time",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "minute_count",
    "first_trade_time",
    "last_trade_time",
    "missing_or_invalid_count",
    "invalid_day",
)


class AggregationError(ValueError):
    """Raised when the source cannot be safely aggregated."""


def _stat_signature(path: Path) -> Dict[str, int]:
    stat = path.stat()
    return {
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
    }


def _require_direct_child(parent: Path, candidate: Path, *, label: str, must_exist: bool) -> Path:
    """Resolve a path and require it to be a direct child of a fixed parent."""
    parent = Path(parent).resolve(strict=True)
    candidate = Path(candidate).absolute()
    try:
        candidate_parent = candidate.parent.resolve(strict=True)
        resolved = candidate.resolve(strict=must_exist)
    except OSError as exc:
        raise AggregationError("cannot resolve {} path: {}".format(label, candidate)) from exc

    same_name = os.path.normcase(candidate.name) == os.path.normcase(resolved.name)
    if (
        not candidate.name
        or candidate.is_symlink()
        or candidate_parent != parent
        or resolved.parent != parent
        or not same_name
    ):
        raise AggregationError(
            "{} path must resolve to a direct child of {}: {}".format(label, parent, candidate)
        )
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _json_metadata(metadata: Optional[Dict[bytes, bytes]]) -> List[Dict[str, Any]]:
    result = []
    for key, value in sorted((metadata or {}).items()):
        item = {
            "key_base64": base64.b64encode(key).decode("ascii"),
            "value_base64": base64.b64encode(value).decode("ascii"),
        }
        try:
            item["key_utf8"] = key.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            item["value_utf8"] = value.decode("utf-8")
        except UnicodeDecodeError:
            pass
        result.append(item)
    return result


def _validate_schema(schema: pa.Schema) -> None:
    missing = [name for name in REQUIRED_COLUMNS if name not in schema.names]
    if missing:
        raise AggregationError("missing required columns: " + ", ".join(missing))

    timestamp_type = schema.field("trade_time").type
    if not pa.types.is_timestamp(timestamp_type) or timestamp_type.unit != "ms":
        raise AggregationError("trade_time must be timestamp[ms]")
    if timestamp_type.tz is not None:
        raise AggregationError("trade_time must be timezone-naive; interpret it as Asia/Shanghai")

    symbol_type = schema.field("symbol").type
    if not (pa.types.is_string(symbol_type) or pa.types.is_large_string(symbol_type)):
        raise AggregationError("symbol must be a string column")
    for name in NUMERIC_COLUMNS:
        if not pa.types.is_floating(schema.field(name).type):
            raise AggregationError("{} must be a floating-point column".format(name))


def _new_day_state() -> Dict[str, Any]:
    return {
        "first_trade_time": None,
        "last_trade_time": None,
        "minute_count": 0,
        "missing_or_invalid_count": 0,
        "price_valid": True,
        "volume_valid": True,
        "amount_valid": True,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume_sum": 0.0,
        "amount_sum": 0.0,
        "volume_compensation": 0.0,
        "amount_compensation": 0.0,
    }


def _kahan_add(state: Dict[str, Any], value_key: str, compensation_key: str, value: float) -> None:
    total = state[value_key]
    compensation = state[compensation_key]
    adjusted = value - compensation
    updated = total + adjusted
    state[compensation_key] = (updated - total) - adjusted
    state[value_key] = updated


def _batch_validity(batch: pa.RecordBatch, frame: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Build vectorized row masks and finite category counts for one bounded batch."""
    masks = {}
    for name in NUMERIC_COLUMNS:
        column_index = batch.schema.get_field_index(name)
        masks[name + "_null"] = batch.column(column_index).is_null().to_numpy(zero_copy_only=False)
        masks[name] = frame[name].to_numpy(dtype=np.float64, na_value=np.nan)

    price_names = ("open", "high", "low", "close")
    price_null = np.column_stack([masks[name + "_null"] for name in price_names]).any(axis=1)
    price_finite_each = np.column_stack([np.isfinite(masks[name]) for name in price_names])
    price_finite = price_finite_each.all(axis=1)
    price_non_finite = (
        ~price_finite_each & ~np.column_stack([masks[name + "_null"] for name in price_names])
    ).any(axis=1)
    price_non_positive = np.column_stack(
        [np.isfinite(masks[name]) & (masks[name] <= 0) for name in price_names]
    ).any(axis=1)
    open_values, high_values, low_values, close_values = [masks[name] for name in price_names]
    price_positive = np.column_stack([masks[name] > 0 for name in price_names]).all(axis=1)
    price_valid = price_finite & price_positive & ~price_null
    inconsistent = price_valid & (
        (high_values < low_values)
        | (high_values < np.maximum(open_values, close_values))
        | (low_values > np.minimum(open_values, close_values))
    )
    price_valid &= ~inconsistent

    valid = {"price": price_valid}
    issue_masks = {
        "missing_price": price_null,
        "non_finite_price": price_non_finite,
        "non_positive_price": price_non_positive,
        "ohlc_inconsistent": inconsistent,
    }
    for name in ("vol", "amount"):
        value = masks[name]
        missing = masks[name + "_null"]
        finite = np.isfinite(value)
        non_finite = ~finite & ~missing
        negative = finite & (value < 0)
        metric_valid = finite & ~missing & ~negative
        valid[name] = metric_valid
        issue_masks["missing_" + ("volume" if name == "vol" else "amount")] = missing
        issue_masks["non_finite_" + ("volume" if name == "vol" else "amount")] = non_finite
        issue_masks["negative_" + ("volume" if name == "vol" else "amount")] = negative

    invalid = np.zeros(len(frame), dtype=bool)
    issue_counts = {}
    for issue, mask in issue_masks.items():
        count = int(mask.sum())
        if count:
            issue_counts[issue] = count
        invalid |= mask
    valid["invalid"] = invalid
    valid["issue_masks"] = issue_masks
    valid["issue_counts"] = issue_counts
    valid["values"] = {name: masks[name] for name in NUMERIC_COLUMNS}
    return valid


def _to_datetime(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime()
    return value


def _validate_batch_order(
    frame: pd.DataFrame,
    batch_row_start: int,
    previous_time: Optional[datetime],
    previous_symbol: Optional[str],
) -> Tuple[datetime, str, datetime, str]:
    """Validate required key values and sorted/unique keys within and across batches."""
    null_time = frame["trade_time"].isna().to_numpy()
    if null_time.any():
        index = int(np.flatnonzero(null_time)[0])
        raise AggregationError(
            "null trade_time at source row {}".format(batch_row_start + index + 1)
        )
    symbols = frame["symbol"]
    empty_symbol = symbols.isna() | symbols.fillna("").astype(str).str.strip().eq("")
    if empty_symbol.any():
        index = int(np.flatnonzero(empty_symbol.to_numpy())[0])
        raise AggregationError(
            "null or empty symbol at source row {}".format(batch_row_start + index + 1)
        )

    duplicate = frame.duplicated(subset=["trade_time", "symbol"], keep=False).to_numpy()
    if duplicate.any():
        index = int(np.flatnonzero(duplicate)[0])
        timestamp = _to_datetime(frame.at[index, "trade_time"])
        symbol = frame.at[index, "symbol"]
        raise AggregationError(
            "duplicate (trade_time, symbol) at source row {}: {} {}".format(
                batch_row_start + index + 1, timestamp.isoformat(sep=" "), symbol
            )
        )

    time_decreased = frame["trade_time"].diff().lt(pd.Timedelta(0)).fillna(False).to_numpy()
    same_time = frame["trade_time"].eq(frame["trade_time"].shift()).fillna(False)
    symbol_decreased = (same_time & symbols.lt(symbols.shift().fillna("")).fillna(False)).to_numpy()
    bad_order = time_decreased | symbol_decreased
    if bad_order.any():
        index = int(np.flatnonzero(bad_order)[0])
        raise AggregationError(
            "source is not ordered by (trade_time, symbol) at row {}".format(
                batch_row_start + index + 1
            )
        )

    first_time = _to_datetime(frame.iloc[0]["trade_time"])
    first_symbol = frame.iloc[0]["symbol"]
    last_time = _to_datetime(frame.iloc[-1]["trade_time"])
    last_symbol = frame.iloc[-1]["symbol"]
    if previous_time is not None:
        if first_time < previous_time:
            raise AggregationError(
                "source is not globally ordered by trade_time at row {}".format(batch_row_start + 1)
            )
        if first_time == previous_time:
            if first_symbol < previous_symbol:
                raise AggregationError(
                    "source is not ordered by (trade_time, symbol) at row {}".format(
                        batch_row_start + 1
                    )
                )
            if first_symbol == previous_symbol:
                raise AggregationError(
                    "duplicate (trade_time, symbol) at source row {}: {} {}".format(
                        batch_row_start + 1, first_time.isoformat(sep=" "), first_symbol
                    )
                )
    return first_time, first_symbol, last_time, last_symbol


def _merge_day_batch(
    day_frame: pd.DataFrame,
    validity: Dict[str, Any],
    stocks: Dict[str, Dict[str, Any]],
) -> None:
    """Vectorize minute validation and aggregation, then merge one daily symbol slice."""
    start = int(day_frame.index[0])
    end = int(day_frame.index[-1]) + 1
    day_frame = day_frame[["symbol", "trade_time", "open", "close"]].copy()
    group_validity = {
        "_price_valid": validity["price"][start:end],
        "_volume_valid": validity["vol"][start:end],
        "_amount_valid": validity["amount"][start:end],
        "_invalid_row": validity["invalid"][start:end],
    }
    for name, values in group_validity.items():
        day_frame[name] = values
    numeric = validity["values"]
    day_frame["_valid_high"] = np.where(
        group_validity["_price_valid"], numeric["high"][start:end], np.nan
    )
    day_frame["_valid_low"] = np.where(
        group_validity["_price_valid"], numeric["low"][start:end], np.nan
    )
    day_frame["_volume_for_sum"] = np.where(
        group_validity["_volume_valid"], numeric["vol"][start:end], 0.0
    )
    day_frame["_amount_for_sum"] = np.where(
        group_validity["_amount_valid"], numeric["amount"][start:end], 0.0
    )

    grouped = day_frame.groupby("symbol", sort=False, observed=True)
    summary = grouped.agg(
        minute_count=("trade_time", "size"),
        missing_or_invalid_count=("_invalid_row", "sum"),
        price_valid=("_price_valid", "all"),
        volume_valid=("_volume_valid", "all"),
        amount_valid=("_amount_valid", "all"),
        high=("_valid_high", "max"),
        low=("_valid_low", "min"),
        volume_sum=("_volume_for_sum", "sum"),
        amount_sum=("_amount_for_sum", "sum"),
        first_trade_time=("trade_time", "first"),
        last_trade_time=("trade_time", "last"),
    )
    # nth() can return rows indexed by the original frame index, while groupby
    # first/last skip NaN values. Keep the actual boundary rows so a bad first
    # open or last close cannot silently be replaced by a later valid value.
    first_open = day_frame.drop_duplicates(subset=["symbol"], keep="first").set_index("symbol")[
        "open"
    ]
    last_close = day_frame.drop_duplicates(subset=["symbol"], keep="last").set_index("symbol")[
        "close"
    ]
    for symbol, partial in summary.iterrows():
        state = stocks.get(symbol)
        if state is None:
            state = _new_day_state()
            stocks[symbol] = state
        first_time = _to_datetime(partial["first_trade_time"])
        last_time = _to_datetime(partial["last_trade_time"])
        if state["minute_count"] == 0:
            state["first_trade_time"] = first_time
            state["open"] = first_open.loc[symbol]
        state["last_trade_time"] = last_time
        state["close"] = last_close.loc[symbol]
        state["minute_count"] += int(partial["minute_count"])
        state["missing_or_invalid_count"] += int(partial["missing_or_invalid_count"])

        if not bool(partial["price_valid"]):
            state["price_valid"] = False
        else:
            high = float(partial["high"])
            low = float(partial["low"])
            state["high"] = high if state["high"] is None else max(state["high"], high)
            state["low"] = low if state["low"] is None else min(state["low"], low)

        if not bool(partial["volume_valid"]):
            state["volume_valid"] = False
        else:
            _kahan_add(state, "volume_sum", "volume_compensation", float(partial["volume_sum"]))
        if not bool(partial["amount_valid"]):
            state["amount_valid"] = False
        else:
            _kahan_add(state, "amount_sum", "amount_compensation", float(partial["amount_sum"]))


def _format_time(value: datetime) -> str:
    return value.isoformat(sep=" ", timespec="milliseconds")


def _csv_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _format_time(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


class _StockCsvSink:
    """Buffer daily CSV text in memory, then write each stock file exactly once."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.buffers = {}
        self.writers = {}
        self.filename_by_symbol = {}
        self.symbol_by_filename = {}
        self.stats = {}

    def _filename(self, symbol: str) -> str:
        cached = self.filename_by_symbol.get(symbol)
        if cached is not None:
            return cached
        exchange_suffix = re.fullmatch(r"(?i)([0-9]{6})\.(sh|sz|bj)", symbol)
        exchange_prefix = re.fullmatch(r"(?i)(sh|sz|bj)([0-9]{6})", symbol)
        if exchange_suffix:
            filename_stem = exchange_suffix.group(2).lower() + exchange_suffix.group(1)
        elif exchange_prefix:
            filename_stem = exchange_prefix.group(1).lower() + exchange_prefix.group(2)
        else:
            filename_stem = quote(
                symbol, safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
            )
        if filename_stem.casefold() in {
            "con",
            "prn",
            "aux",
            "nul",
            "com1",
            "com2",
            "com3",
            "com4",
            "com5",
            "com6",
            "com7",
            "com8",
            "com9",
            "lpt1",
            "lpt2",
            "lpt3",
            "lpt4",
            "lpt5",
            "lpt6",
            "lpt7",
            "lpt8",
            "lpt9",
        }:
            filename_stem = "_" + filename_stem
        filename = filename_stem + ".csv"
        collision_key = filename.casefold()
        previous = self.symbol_by_filename.get(collision_key)
        if previous is not None and previous != symbol:
            raise AggregationError(
                "symbols {!r} and {!r} map to the same Windows filename".format(previous, symbol)
            )
        self.symbol_by_filename[collision_key] = symbol
        self.filename_by_symbol[symbol] = filename
        return filename

    def _writer(self, symbol: str):
        if symbol in self.writers:
            return self.writers[symbol]
        filename = self._filename(symbol)
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_FIELDS)
        self.buffers[symbol] = buffer
        self.writers[symbol] = writer
        self.stats[symbol] = {
            "file": filename,
            "rows": 0,
            "invalid_daily_rows": 0,
            "first_trade_date": None,
            "last_trade_date": None,
        }
        return writer

    def write(self, row: Dict[str, Any]) -> None:
        symbol = row["symbol"]
        writer = self._writer(symbol)
        writer.writerow([_csv_value(row[field]) for field in CSV_FIELDS])
        stats = self.stats[symbol]
        stats["rows"] += 1
        stats["invalid_daily_rows"] += int(row["invalid_day"])
        if stats["first_trade_date"] is None:
            stats["first_trade_date"] = row["trade_date"].isoformat()
        stats["last_trade_date"] = row["trade_date"].isoformat()

    def finish(self) -> List[Dict[str, Any]]:
        entries = []
        for symbol in sorted(self.stats):
            item = dict(self.stats[symbol])
            output_path = self.root / item["file"]
            with output_path.open("w", encoding="utf-8", newline="") as output_file:
                buffer = self.buffers[symbol]
                buffer.seek(0)
                while True:
                    chunk = buffer.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    output_file.write(chunk)
            self.buffers[symbol].close()
            item["bytes"] = output_path.stat().st_size
            item["sha256"] = _sha256_file(output_path)
            entries.append({"symbol": symbol, **item})
        return entries

    def close(self) -> None:
        for buffer in self.buffers.values():
            if not buffer.closed:
                buffer.close()
        self.buffers.clear()
        self.writers.clear()


def _finish_day(
    day: date,
    stocks: Dict[str, Dict[str, Any]],
    csv_sink: _StockCsvSink,
    calendar_writer: csv.writer,
    coverage: Counter,
    symbols_seen: set,
    totals: Dict[str, Any],
) -> None:
    if not stocks:
        return

    minute_rows = 0
    first_time = None
    last_time = None
    invalid_daily_rows = 0
    daily_grid_time = max(state["last_trade_time"] for state in stocks.values())
    for symbol in sorted(stocks):
        state = stocks[symbol]
        minute_count = state["minute_count"]
        invalid_count = state["missing_or_invalid_count"]
        price_valid = state["price_valid"] and all(
            state[name] is not None for name in ("open", "high", "low", "close")
        )
        volume_valid = state["volume_valid"] and math.isfinite(state["volume_sum"])
        amount_valid = state["amount_valid"] and math.isfinite(state["amount_sum"])
        row_time = state["last_trade_time"]
        row = {
            "trade_date": day,
            "trade_time": daily_grid_time,
            "symbol": symbol,
            "open": state["open"] if price_valid else None,
            "high": state["high"] if price_valid else None,
            "low": state["low"] if price_valid else None,
            "close": state["close"] if price_valid else None,
            "volume": state["volume_sum"] if volume_valid else None,
            "amount": state["amount_sum"] if amount_valid else None,
            "first_trade_time": state["first_trade_time"],
            "last_trade_time": row_time,
            "minute_count": minute_count,
            "missing_or_invalid_count": invalid_count,
            "invalid_day": invalid_count > 0 or not (price_valid and volume_valid and amount_valid),
        }
        csv_sink.write(row)
        invalid_daily_rows += int(row["invalid_day"])
        minute_rows += minute_count
        coverage[minute_count] += 1
        symbols_seen.add(symbol)
        if first_time is None or state["first_trade_time"] < first_time:
            first_time = state["first_trade_time"]
        if last_time is None or row_time > last_time:
            last_time = row_time

    calendar_writer.writerow(
        [
            day.isoformat(),
            _format_time(first_time),
            _format_time(last_time),
            len(stocks),
            minute_rows,
        ]
    )
    totals["daily_rows"] += len(stocks)
    totals["observed_dates"] += 1
    totals["invalid_daily_rows"] += invalid_daily_rows


def aggregate(
    input_path: Path, output_dir: Path, batch_size: int = DEFAULT_BATCH_SIZE
) -> Dict[str, Any]:
    """Aggregate the source file and return its completed manifest."""
    input_path = Path(input_path).expanduser().absolute()
    requested_output_dir = Path(output_dir).expanduser().absolute()
    if not input_path.is_file():
        raise AggregationError("input is not a regular file: {}".format(input_path))
    if batch_size <= 0:
        raise AggregationError("batch_size must be positive")

    requested_output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_parent = requested_output_dir.parent.resolve(strict=True)
    output_dir = _require_direct_child(
        output_parent,
        output_parent / requested_output_dir.name,
        label="output target",
        must_exist=False,
    )
    if os.path.lexists(str(output_dir)):
        raise AggregationError(
            "output already exists; refusing to overwrite: {}".format(output_dir)
        )

    before_stat = _stat_signature(input_path)
    source_hash = _sha256_file(input_path)
    after_hash_stat = _stat_signature(input_path)
    if before_stat != after_hash_stat:
        raise AggregationError("source changed while its SHA-256 was being computed")

    temp_dir = Path(
        tempfile.mkdtemp(prefix="." + output_dir.name + ".tmp-", dir=str(output_parent))
    )
    metadata_dir = temp_dir / "_metadata"
    calendar_path = metadata_dir / "observed_calendar.csv"
    manifest_path = metadata_dir / "manifest.json"
    totals = {"source_rows": 0, "daily_rows": 0, "invalid_daily_rows": 0, "observed_dates": 0}
    invalid_counts = Counter()
    coverage = Counter()
    symbols_seen = set()
    min_date = None
    max_date = None
    previous_time = None
    previous_symbol = None
    current_date = None
    current_stocks = {}
    first_source_time = None
    last_source_time = None
    row_group_count = 0
    parquet_file = None

    try:
        temp_dir = _require_direct_child(
            output_parent, temp_dir, label="temporary output", must_exist=True
        )
        metadata_dir.mkdir()
        parquet_file = pq.ParquetFile(input_path)
        source_schema = parquet_file.schema_arrow
        _validate_schema(source_schema)
        csv_sink = _StockCsvSink(temp_dir)
        try:
            with calendar_path.open("w", encoding="utf-8", newline="") as calendar_file:
                calendar_writer = csv.writer(calendar_file, lineterminator="\n")
                calendar_writer.writerow(
                    [
                        "trade_date",
                        "first_trade_time",
                        "last_trade_time",
                        "symbol_count",
                        "minute_count",
                    ]
                )
                columns = list(REQUIRED_COLUMNS)
                for row_group_index in range(parquet_file.num_row_groups):
                    row_group_count += 1
                    for batch in parquet_file.iter_batches(
                        batch_size=batch_size,
                        row_groups=[row_group_index],
                        columns=columns,
                        use_threads=False,
                    ):
                        if batch.num_rows == 0:
                            continue
                        batch_row_start = totals["source_rows"]
                        frame = batch.to_pandas().reset_index(drop=True)
                        first_time, first_symbol, last_time, last_symbol = _validate_batch_order(
                            frame, batch_row_start, previous_time, previous_symbol
                        )
                        previous_time, previous_symbol = last_time, last_symbol
                        validity = _batch_validity(batch, frame)
                        for issue, count in validity["issue_counts"].items():
                            invalid_counts[issue] += count
                        frame["_valid_price"] = validity["price"]
                        frame["_valid_volume"] = validity["vol"]
                        frame["_valid_amount"] = validity["amount"]
                        frame["_invalid_row"] = validity["invalid"]
                        frame["_valid_high"] = np.where(
                            validity["price"], validity["values"]["high"], np.nan
                        )
                        frame["_valid_low"] = np.where(
                            validity["price"], validity["values"]["low"], np.nan
                        )
                        frame["_volume_for_sum"] = np.where(
                            validity["vol"], validity["values"]["vol"], 0.0
                        )
                        frame["_amount_for_sum"] = np.where(
                            validity["amount"], validity["values"]["amount"], 0.0
                        )

                        date_values = frame["trade_time"].dt.normalize()
                        boundaries = np.flatnonzero(
                            date_values.ne(date_values.shift()).fillna(True).to_numpy()
                        ).tolist()
                        boundaries.append(len(frame))
                        for boundary_index in range(len(boundaries) - 1):
                            start = boundaries[boundary_index]
                            end = boundaries[boundary_index + 1]
                            day_frame = frame.iloc[start:end]
                            local_date = day_frame.iloc[0]["trade_time"].date()
                            if current_date is None:
                                current_date = local_date
                            elif local_date != current_date:
                                _finish_day(
                                    current_date,
                                    current_stocks,
                                    csv_sink,
                                    calendar_writer,
                                    coverage,
                                    symbols_seen,
                                    totals,
                                )
                                current_stocks = {}
                                current_date = local_date
                            _merge_day_batch(day_frame, validity, current_stocks)

                        totals["source_rows"] += len(frame)
                        first_python_time = _to_datetime(first_time)
                        last_python_time = _to_datetime(last_time)
                        if first_source_time is None:
                            first_source_time = first_python_time
                        last_source_time = last_python_time
                        first_date = first_python_time.date()
                        last_date = last_python_time.date()
                        min_date = first_date if min_date is None else min(min_date, first_date)
                        max_date = last_date if max_date is None else max(max_date, last_date)

                    if row_group_count % 10 == 0 or row_group_count == parquet_file.num_row_groups:
                        print(
                            "processed row groups {}/{}; rows={:,}; daily_rows={:,}".format(
                                row_group_count,
                                parquet_file.num_row_groups,
                                totals["source_rows"],
                                totals["daily_rows"],
                            ),
                            file=sys.stderr,
                            flush=True,
                        )

                if totals["source_rows"] == 0:
                    raise AggregationError("source contains no minute rows")
                _finish_day(
                    current_date,
                    current_stocks,
                    csv_sink,
                    calendar_writer,
                    coverage,
                    symbols_seen,
                    totals,
                )

            after_stat = _stat_signature(input_path)
            if before_stat != after_stat:
                raise AggregationError("source file stat changed during aggregation")
            symbol_files = csv_sink.finish()
        finally:
            csv_sink.close()

        metadata = source_schema.metadata or {}
        manifest = {
            "status": "complete",
            "source": {
                "path": str(input_path),
                "sha256": source_hash,
                "stat_before": before_stat,
                "stat_after": after_stat,
                "stat_unchanged": before_stat == after_stat,
                "row_groups": row_group_count,
                "rows": totals["source_rows"],
                "first_trade_time": first_source_time.isoformat(sep=" "),
                "last_trade_time": last_source_time.isoformat(sep=" "),
            },
            "output": {
                "format": "one UTF-8 CSV per symbol; no combined daily table",
                "metadata_directory": "_metadata",
                "observed_calendar_csv": "_metadata/observed_calendar.csv",
                "daily_rows": totals["daily_rows"],
                "invalid_daily_rows": totals["invalid_daily_rows"],
                "date_range": {"first": min_date.isoformat(), "last": max_date.isoformat()},
                "observed_dates": totals["observed_dates"],
                "symbol_count": len(symbols_seen),
                "csv_file_count": len(symbol_files),
                "symbols": symbol_files,
            },
            "aggregation": {
                "timezone_assumption": "Asia/Shanghai; naive source trade_time is local time",
                "source_bar_time_semantics": "KLINE_END_TIME",
                "daily_trade_time": "last observed source trade_time across all symbols for that date; shared grid timestamp",
                "price_adjustment": "none",
                "gap_policy": "preserve all source minutes; no filling or calendar-based missing-minute inference",
                "volume_unit": "SOURCE_NATIVE",
                "daily_fields": "first open, maximum high, minimum low, last close, sum volume and amount",
                "invalid_row_policy": (
                    "A row with any missing/non-finite/non-positive/inconsistent OHLC or missing/non-finite/"
                    "negative vol/amount increments missing_or_invalid_count. Any invalid OHLC makes all daily "
                    "OHLC fields null; invalid vol or amount makes that daily metric null. invalid_day is true."
                ),
                "missing_or_invalid_count_scope": (
                    "counts source rows with one or more invalid required numeric values; absent exchange minutes "
                    "cannot be inferred without an external trading calendar"
                ),
                "invalid_rows_by_category": dict(sorted(invalid_counts.items())),
                "minute_coverage_distribution": {
                    "daily_symbol_rows": totals["daily_rows"],
                    "min_minutes": min(coverage) if coverage else None,
                    "max_minutes": max(coverage) if coverage else None,
                    "minute_count_histogram": {str(k): coverage[k] for k in sorted(coverage)},
                },
            },
            "source_schema": {
                "arrow_schema": str(source_schema),
                "serialized_schema_base64": base64.b64encode(
                    source_schema.serialize().to_pybytes()
                ).decode("ascii"),
                "metadata_raw": _json_metadata(metadata),
            },
        }
        with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2, sort_keys=True)
            manifest_file.write("\n")

        safe_temp_dir = _require_direct_child(
            output_parent, temp_dir, label="temporary output", must_exist=True
        )
        safe_output_dir = _require_direct_child(
            output_parent, output_dir, label="output target", must_exist=False
        )
        if os.path.lexists(str(safe_output_dir)):
            raise AggregationError(
                "output appeared during aggregation; refusing to overwrite: {}".format(
                    safe_output_dir
                )
            )
        os.rename(str(safe_temp_dir), str(safe_output_dir))
        return manifest
    except Exception:
        if parquet_file is not None:
            parquet_file.close()
            parquet_file = None
        if os.path.lexists(str(temp_dir)):
            try:
                safe_temp_dir = _require_direct_child(
                    output_parent, temp_dir, label="temporary output cleanup", must_exist=True
                )
                shutil.rmtree(str(safe_temp_dir), ignore_errors=True)
            except Exception as cleanup_error:
                print(
                    "refused unsafe temporary-output cleanup: {}".format(cleanup_error),
                    file=sys.stderr,
                    flush=True,
                )
        raise
    finally:
        if parquet_file is not None:
            parquet_file.close()


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="sorted minute Parquet source")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="new output directory; must not exist"
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        manifest = aggregate(args.input, args.output_dir, batch_size=args.batch_size)
    except (AggregationError, OSError, pa.ArrowException) as exc:
        print("aggregation failed: {}".format(exc), file=sys.stderr, flush=True)
        return 2
    print(
        "wrote {:,} daily rows for {:,} symbols across {:,} observed dates to {}".format(
            manifest["output"]["daily_rows"],
            manifest["output"]["symbol_count"],
            manifest["output"]["observed_dates"],
            Path(args.output_dir).absolute(),
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
