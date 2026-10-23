"""Run the native Alpha003 factor over a source-observed daily panel.

The research grid is derived only from ``_metadata/observed_calendar.csv``.
It represents source-observed sessions, not an official exchange calendar.
Each chunk contains the complete cross-section plus nine preceding grid rows.

Every chunk collects one :class:`~backtrader.research.FactorPanel` and writes a
single factor table (``factor_values.parquet``) holding exactly one row per
study cell.  Missing source bars stay ``NaN`` in that table; the removed
per-cell ``ready``/``valid``/``reason`` availability table is no longer
produced or verified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


FACTOR_NAME = "alpha003"
FACTOR_MODES = ("native", "build")
PERIOD = 10
LOOKBACK = PERIOD - 1
SOURCE_TIMEZONE = "Asia/Shanghai"
OHLC = ("open", "high", "low", "close")
FACTOR_INPUTS = ("open", "volume")
DAILY_FIELDS = OHLC + ("volume", "amount")
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
ORACLE_ATOL = 5e-12


class RunIdentityConflictError(RuntimeError):
    """Raised before an output directory owned by another run can be changed."""


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "backtrader" / "__init__.py").is_file():
            return parent
    raise RuntimeError("could not locate the Backtrader checkout")


def _add_checkout_root() -> Path:
    root = _repo_root()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _code_fingerprint(root: Path) -> Tuple[str, List[Dict[str, str]]]:
    files = [Path(__file__).resolve()]
    files.extend(path for path in (root / "backtrader").rglob("*.py") if path.is_file())
    files = sorted(set(files), key=lambda path: str(path.relative_to(root)).casefold())
    digest = hashlib.sha256()
    pins = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        content_hash = _sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\n")
        pins.append({"path": relative, "sha256": content_hash})
    return digest.hexdigest(), pins


def _git_head(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip()


def _module_source_path(module: Any) -> Optional[str]:
    """Return the real source file of ``module`` (or its name), or ``None``.

    Only an already imported module can answer this; the path is never
    fabricated from a guessed file name.
    """
    if isinstance(module, str):
        module = sys.modules.get(module)
    filename = getattr(module, "__file__", None)
    if not isinstance(filename, str) or not filename:
        return None
    return str(Path(filename).resolve())


def _parse_local_times(values: pd.Series, label: str) -> pd.DatetimeIndex:
    parsed = pd.to_datetime(values, errors="coerce")
    if parsed.isna().any() or getattr(parsed.dt, "tz", None) is not None:
        raise ValueError("%s must contain valid timezone-naive Shanghai timestamps" % label)
    return pd.DatetimeIndex(parsed.to_numpy(dtype="datetime64[ns]"))


def _read_manifest(data_dir: Path) -> Tuple[dict, pd.DataFrame, List[dict], str]:
    metadata_dir = data_dir / "_metadata"
    manifest_path = metadata_dir / "manifest.json"
    calendar_path = metadata_dir / "observed_calendar.csv"
    if not manifest_path.is_file() or not calendar_path.is_file():
        raise FileNotFoundError("expected _metadata/manifest.json and observed_calendar.csv")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    if manifest.get("status") != "complete":
        raise ValueError("daily aggregation manifest status must be 'complete'")
    output = manifest.get("output", manifest)
    entries = output.get("symbols") if isinstance(output, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError("manifest output.symbols must be a non-empty list")

    calendar = pd.read_csv(calendar_path, dtype={"trade_date": "string"})
    required_calendar = {
        "trade_date",
        "first_trade_time",
        "last_trade_time",
        "symbol_count",
        "minute_count",
    }
    if not required_calendar.issubset(calendar.columns) or not len(calendar):
        raise ValueError("observed_calendar.csv is empty or missing required columns")
    date_strings = calendar["trade_date"].astype(str)
    parsed_dates = pd.to_datetime(date_strings, format="%Y-%m-%d", errors="coerce")
    if (
        parsed_dates.isna().any()
        or not parsed_dates.is_monotonic_increasing
        or not parsed_dates.is_unique
    ):
        raise ValueError("observed calendar dates must be unique increasing YYYY-MM-DD values")
    calendar["trade_date"] = date_strings
    calendar["_date"] = parsed_dates.to_numpy(dtype="datetime64[D]")
    calendar["_open_local"] = _parse_local_times(
        calendar["first_trade_time"], "calendar first_trade_time"
    )
    calendar["_close_local"] = _parse_local_times(
        calendar["last_trade_time"], "calendar last_trade_time"
    )
    if bool((calendar["_open_local"].to_numpy() > calendar["_close_local"].to_numpy()).any()):
        raise ValueError("source-observed session open time follows its close time")
    closes = (
        pd.DatetimeIndex(calendar["_close_local"]).tz_localize(SOURCE_TIMEZONE).tz_convert("UTC")
    )
    if not closes.is_unique or not closes.is_monotonic_increasing:
        raise ValueError("observed close timestamps must be unique and strictly increasing")
    counts = pd.to_numeric(calendar["symbol_count"], errors="raise").to_numpy(dtype=np.int64)
    minutes = pd.to_numeric(calendar["minute_count"], errors="raise").to_numpy(dtype=np.int64)
    if (counts <= 0).any() or (minutes <= 0).any():
        raise ValueError("observed calendar counts must be positive")

    entries = sorted(entries, key=lambda item: str(item.get("symbol", "")))
    symbols = [entry.get("symbol") for entry in entries]
    if any(not isinstance(symbol, str) or not symbol for symbol in symbols):
        raise ValueError("manifest symbols must be non-empty strings")
    if len(symbols) != len(set(symbols)):
        raise ValueError("manifest contains duplicate symbols")
    if symbols != sorted(symbols):
        raise ValueError("manifest symbols are not in stable lexical order")
    input_digest = hashlib.sha256()
    input_digest.update(b"alpha003-daily-source-v1\0")
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    calendar_hash = _sha256_file(calendar_path)
    input_digest.update(manifest_hash.encode("ascii"))
    input_digest.update(calendar_hash.encode("ascii"))
    for entry in entries:
        relative = entry.get("file")
        expected_hash = entry.get("sha256")
        expected_size = entry.get("bytes")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise ValueError("each manifest symbol requires file and sha256")
        file_path = (data_dir / relative).resolve()
        if not file_path.is_relative_to(data_dir.resolve()) or not file_path.is_file():
            raise ValueError("manifest file must exist inside the data directory")
        actual_size = file_path.stat().st_size
        actual_hash = _sha256_file(file_path)
        if actual_hash != expected_hash or (
            expected_size is not None and actual_size != int(expected_size)
        ):
            raise ValueError("daily CSV pin mismatch for %s" % entry["symbol"])
        input_digest.update(entry["symbol"].encode("utf-8"))
        input_digest.update(b"\0")
        input_digest.update(relative.replace("\\", "/").encode("utf-8"))
        input_digest.update(b"\0")
        input_digest.update(str(actual_size).encode("ascii"))
        input_digest.update(b"\0")
        input_digest.update(actual_hash.encode("ascii"))
        input_digest.update(b"\n")
    return manifest, calendar, entries, input_digest.hexdigest()


def _parse_bool_column(values: pd.Series, label: str) -> np.ndarray:
    normalized = values.astype("string").str.strip().str.lower()
    if normalized.isna().any() or not normalized.isin(("true", "false")).all():
        raise ValueError("%s must contain only true/false" % label)
    return normalized.eq("true").to_numpy(dtype=bool)


def _load_source_arrays(
    data_dir: Path, calendar: pd.DataFrame, entries: Sequence[Mapping[str, Any]]
) -> Dict[str, Any]:
    dates = calendar["trade_date"].astype(str).to_numpy()
    symbols = tuple(str(entry["symbol"]) for entry in entries)
    date_count, symbol_count = len(dates), len(symbols)
    shape = (date_count, symbol_count)
    arrays: Dict[str, Any] = {
        name: np.full(shape, np.nan, dtype=np.float64) for name in DAILY_FIELDS
    }
    arrays.update(
        {
            "present": np.zeros(shape, dtype=bool),
            "invalid_day": np.zeros(shape, dtype=bool),
            "minute_count": np.full(shape, -1, dtype=np.int64),
            "missing_or_invalid_count": np.full(shape, -1, dtype=np.int64),
            "first_trade_time": np.full(shape, np.datetime64("NaT", "ms"), dtype="datetime64[ms]"),
            "last_trade_time": np.full(shape, np.datetime64("NaT", "ms"), dtype="datetime64[ms]"),
            "symbols": symbols,
            "dates": dates,
            "close_local": pd.DatetimeIndex(calendar["_close_local"]).to_numpy(
                dtype="datetime64[ms]"
            ),
        }
    )
    date_lookup = {value: index for index, value in enumerate(dates)}
    required = set(CSV_FIELDS)
    total_rows = 0
    invalid_rows = 0
    for symbol_index, entry in enumerate(entries):
        symbol = symbols[symbol_index]
        path = (data_dir / str(entry["file"])).resolve()
        frame = pd.read_csv(
            path, dtype={"trade_date": "string", "trade_time": "string", "symbol": "string"}
        )
        if not required.issubset(frame.columns):
            raise ValueError("%s is missing daily CSV columns" % path.name)
        if frame["symbol"].astype(str).ne(symbol).any():
            raise ValueError("daily CSV symbol does not match manifest: %s" % symbol)
        if len(frame) != int(entry.get("rows", len(frame))):
            raise ValueError("daily CSV row count does not match manifest: %s" % symbol)
        date_values = frame["trade_date"].astype(str).to_numpy()
        if len(date_values) and (
            not pd.Index(date_values).is_unique or not pd.Index(date_values).is_monotonic_increasing
        ):
            raise ValueError("daily dates must be unique increasing for %s" % symbol)
        try:
            date_indices = np.fromiter(
                (date_lookup[value] for value in date_values),
                dtype=np.int64,
                count=len(date_values),
            )
        except KeyError as exc:
            raise ValueError(
                "daily CSV date is absent from observed calendar: %s" % exc.args[0]
            ) from exc
        if len(date_indices) and (arrays["present"][date_indices, symbol_index]).any():
            raise ValueError("duplicate daily symbol/date row: %s" % symbol)
        trade_times = _parse_local_times(frame["trade_time"], "%s trade_time" % symbol)
        expected_close = pd.DatetimeIndex(calendar["_close_local"].iloc[date_indices])
        if not trade_times.equals(expected_close):
            raise ValueError(
                "daily trade_time does not match the common observed close for %s" % symbol
            )
        first = _parse_local_times(frame["first_trade_time"], "%s first_trade_time" % symbol)
        last = _parse_local_times(frame["last_trade_time"], "%s last_trade_time" % symbol)
        if (first > last).any() or (last > trade_times).any():
            raise ValueError("daily source first/last times are inconsistent for %s" % symbol)
        bad_day = _parse_bool_column(frame["invalid_day"], "%s invalid_day" % symbol)
        numeric: Dict[str, np.ndarray] = {}
        for column in DAILY_FIELDS:
            values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=np.float64)
            if np.isinf(values).any():
                raise ValueError("daily %s contains infinity for %s" % (column, symbol))
            numeric[column] = values
        if len(frame):
            ohlc_good = np.ones(len(frame), dtype=bool)
            for column in OHLC:
                ohlc_good &= np.isfinite(numeric[column])
            amount_good = np.isfinite(numeric["amount"])
            volume_good = np.isfinite(numeric["volume"])
            if ((~bad_day) & (~(ohlc_good & amount_good & volume_good))).any():
                raise ValueError("invalid daily values must set invalid_day=true for %s" % symbol)
            arrays["present"][date_indices, symbol_index] = True
            arrays["invalid_day"][date_indices, symbol_index] = bad_day
            for column, values in numeric.items():
                arrays[column][date_indices, symbol_index] = values
            for name, column in (
                ("minute_count", "minute_count"),
                ("missing_or_invalid_count", "missing_or_invalid_count"),
            ):
                values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=np.int64)
                if (values < 0).any():
                    raise ValueError("%s must be non-negative for %s" % (column, symbol))
                arrays[name][date_indices, symbol_index] = values
            arrays["first_trade_time"][date_indices, symbol_index] = first.to_numpy(
                dtype="datetime64[ms]"
            )
            arrays["last_trade_time"][date_indices, symbol_index] = last.to_numpy(
                dtype="datetime64[ms]"
            )
            invalid_rows += int(bad_day.sum())
        total_rows += len(frame)
        if entry.get("invalid_daily_rows") is not None and int(entry["invalid_daily_rows"]) != int(
            bad_day.sum()
        ):
            raise ValueError("invalid daily row count does not match manifest for %s" % symbol)
        if len(date_values):
            for key, observed in (
                ("first_trade_date", date_values[0]),
                ("last_trade_date", date_values[-1]),
            ):
                if entry.get(key) is not None and str(entry[key]) != observed:
                    raise ValueError("%s does not match manifest for %s" % (key, symbol))
        if (symbol_index + 1) % 500 == 0 or symbol_index + 1 == symbol_count:
            print("loaded %d/%d symbol CSVs" % (symbol_index + 1, symbol_count), flush=True)
    arrays["total_rows"] = total_rows
    arrays["invalid_rows"] = invalid_rows
    minute_totals = np.where(arrays["present"], arrays["minute_count"], 0).sum(axis=1)
    expected_minutes = pd.to_numeric(calendar["minute_count"], errors="raise").to_numpy(
        dtype=np.int64
    )
    if not np.array_equal(minute_totals, expected_minutes):
        raise ValueError("daily CSV minute counts differ from observed_calendar.csv")
    calendar_first = calendar["_open_local"].to_numpy(dtype="datetime64[ms]")
    calendar_last = calendar["_close_local"].to_numpy(dtype="datetime64[ms]")
    for day_index in range(date_count):
        present = arrays["present"][day_index]
        if not present.any():
            raise ValueError("observed calendar date has no daily symbol rows")
        first = arrays["first_trade_time"][day_index, present].min()
        last = arrays["last_trade_time"][day_index, present].max()
        if first != calendar_first[day_index] or last != calendar_last[day_index]:
            raise ValueError("per-symbol first/last times differ from observed_calendar.csv")
    return arrays


def _resolve_factor_mode(factor_mode: Optional[str]) -> str:
    mode = "native" if factor_mode is None else factor_mode
    if mode not in FACTOR_MODES:
        raise ValueError("factor_mode must be 'native' or 'build'")
    return mode


def _params(root: Path, factor_mode: str = "native") -> Dict[str, Any]:
    _add_checkout_root()
    import backtrader as bt
    from backtrader.research.alpha101 import get_alpha

    factor_mode = _resolve_factor_mode(factor_mode)
    indicator = get_alpha(3)
    return {
        "factor": FACTOR_NAME,
        "factor_mode": factor_mode,
        "formula": indicator.formula,
        "alpha_id": 3,
        "indicator": indicator.__module__ + "." + indicator.__qualname__,
        "operator_profile": indicator.operator_profile,
        "period": PERIOD,
        "lookback_h": LOOKBACK,
        "factor_inputs": list(FACTOR_INPUTS),
        "field_bindings": {name: "feed:target:" + name for name in FACTOR_INPUTS},
        "rank": "per source-observed session, pandas average-tie pct rank over finite values",
        "correlation": "negative 10-grid Pearson; complete finite window; constant window invalid",
        "universe": "all manifest symbols in one stable lexical order and one research group",
        "source_timezone": SOURCE_TIMEZONE,
        "grid_frequency": "1source_observed_session",
        "calendar_policy": "manifest observed_calendar only; not official exchange calendar",
        "missing_data_policy": "no fill; absent symbol rows remain absent and source field nulls remain NaN; open and volume are consumed independently",
        "price_basis": "source prices as provided; no adjustment applied by this run",
        "chunk_days_default": 20,
        "chunk_warmup_grid_rows": LOOKBACK,
        "runonce": False,
        "preload": True,
        "python": sys.version.split()[0],
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "backtrader": getattr(bt, "__version__", "source"),
    }


def _oracle(open_values: np.ndarray, volume_values: np.ndarray) -> np.ndarray:
    """Independent Pandas rank + batched NumPy rolling Pearson reference."""
    open_ranks = (
        pd.DataFrame(open_values)
        .rank(axis=1, method="average", pct=True)
        .to_numpy(dtype=np.float64)
    )
    volume_ranks = (
        pd.DataFrame(volume_values)
        .rank(axis=1, method="average", pct=True)
        .to_numpy(dtype=np.float64)
    )
    date_count, symbol_count = open_values.shape
    expected = np.full((date_count, symbol_count), np.nan, dtype=np.float64)
    window_count = date_count - PERIOD + 1
    if window_count <= 0:
        return expected
    block_size = 384
    for left in range(0, symbol_count, block_size):
        right = min(symbol_count, left + block_size)
        x = np.lib.stride_tricks.sliding_window_view(open_ranks[:, left:right], PERIOD, axis=0)
        y = np.lib.stride_tricks.sliding_window_view(volume_ranks[:, left:right], PERIOD, axis=0)
        valid = np.isfinite(x).all(axis=-1) & np.isfinite(y).all(axis=-1)
        valid &= np.max(x, axis=-1) > np.min(x, axis=-1)
        valid &= np.max(y, axis=-1) > np.min(y, axis=-1)
        x_centered = x - np.mean(x, axis=-1, keepdims=True)
        y_centered = y - np.mean(y, axis=-1, keepdims=True)
        covariance = np.sum(x_centered * y_centered, axis=-1)
        x_variance = np.sum(x_centered * x_centered, axis=-1)
        y_variance = np.sum(y_centered * y_centered, axis=-1)
        denominator = np.sqrt(x_variance * y_variance)
        valid &= np.isfinite(denominator) & (denominator > 0.0)
        correlation = np.divide(
            covariance,
            denominator,
            out=np.full_like(denominator, np.nan),
            where=valid,
        )
        if np.any(np.abs(correlation[valid]) > 1.0 + 1e-12):
            raise AssertionError("independent Pearson oracle exceeded [-1, 1]")
        expected[PERIOD - 1 :, left:right] = np.where(
            valid, -np.clip(correlation, -1.0, 1.0), np.nan
        )
    return expected


def _prepare_formula_inputs(arrays: Mapping[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    # Aggregation marks a whole row invalid when any output field is bad, while
    # retaining valid fields. Alpha003 consumes only open and volume, so preserve
    # those independently instead of discarding an otherwise usable input due
    # to (for example) a missing amount or high.
    return arrays["open"].copy(), arrays["volume"].copy()


def _chunk_bounds(date_count: int, chunk_days: int) -> List[Tuple[int, int, int]]:
    chunks = []
    for index, start in enumerate(range(0, date_count, chunk_days)):
        end = min(date_count, start + chunk_days)
        grid_start = max(0, start - LOOKBACK)
        chunks.append((index, grid_start, end))
    return chunks


def _cache_chunk(
    output_dir: Path,
    arrays: Mapping[str, Any],
    calendar: pd.DataFrame,
    *,
    chunk_index: int,
    grid_start: int,
    study_start: int,
    study_end: int,
    input_sha256: str,
    code_sha256: str,
    params_sha256: str,
    run_id: str,
) -> Tuple[Path, Path, dict]:
    chunk_dir = output_dir / "_chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    base = "chunk_%04d" % chunk_index
    parquet_path = chunk_dir / (base + ".parquet")
    meta_path = chunk_dir / (base + ".json")
    grid_dates = arrays["dates"][grid_start:study_end]
    study_dates = arrays["dates"][study_start:study_end]
    cache_identity = {
        "run_id": run_id,
        "input_sha256": input_sha256,
        "code_sha256": code_sha256,
        "params_sha256": params_sha256,
        "chunk_index": chunk_index,
        "grid_dates": grid_dates.tolist(),
        "study_dates": study_dates.tolist(),
        "symbols_sha256": hashlib.sha256("\n".join(arrays["symbols"]).encode("utf-8")).hexdigest(),
    }
    if parquet_path.exists() or meta_path.exists():
        if not parquet_path.is_file() or not meta_path.is_file():
            raise RuntimeError("incomplete temporary input cache for %s" % base)
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("identity") != cache_identity or _sha256_file(parquet_path) != metadata.get(
            "parquet_sha256"
        ):
            raise RuntimeError("temporary input cache identity or hash mismatch for %s" % base)
        return parquet_path, meta_path, metadata

    mask = arrays["present"][grid_start:study_end]
    local_days, asset_indices = np.nonzero(mask)
    absolute_days = local_days + grid_start
    cached = pd.DataFrame(
        {
            "trade_date": arrays["dates"][absolute_days],
            "trade_time": arrays["close_local"][absolute_days],
            "symbol": np.asarray(arrays["symbols"], dtype=object)[asset_indices],
            **{name: arrays[name][absolute_days, asset_indices] for name in DAILY_FIELDS},
            "minute_count": arrays["minute_count"][absolute_days, asset_indices],
            "first_trade_time": arrays["first_trade_time"][absolute_days, asset_indices],
            "last_trade_time": arrays["last_trade_time"][absolute_days, asset_indices],
            "missing_or_invalid_count": arrays["missing_or_invalid_count"][
                absolute_days, asset_indices
            ],
            "invalid_day": arrays["invalid_day"][absolute_days, asset_indices],
        }
    )
    temporary_parquet = parquet_path.with_suffix(".parquet.tmp")
    cached.to_parquet(temporary_parquet, index=False, compression="zstd")
    os.replace(temporary_parquet, parquet_path)
    metadata = {
        "identity": cache_identity,
        "parquet_sha256": _sha256_file(parquet_path),
        "row_count": int(len(cached)),
        "grid_count": int(len(grid_dates)),
        "study_count": int(len(study_dates)),
        "warmup_count": int(study_start - grid_start),
        "grid_first_date": str(grid_dates[0]),
        "grid_last_date": str(grid_dates[-1]),
        "study_first_date": str(study_dates[0]),
        "study_last_date": str(study_dates[-1]),
    }
    _write_json(meta_path, metadata)
    print(
        "cached %s: %d grid dates, %d warmup, %d source rows"
        % (base, len(grid_dates), study_start - grid_start, len(cached)),
        flush=True,
    )
    return parquet_path, meta_path, metadata


def _run_worker(config_path: Path) -> None:
    root = _add_checkout_root()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    factor_mode = _resolve_factor_mode(config.get("factor_mode"))
    params = _params(root, factor_mode)
    params["chunk_days"] = config["chunk_days"]
    expected_params_sha = hashlib.sha256(_canonical_json(params)).hexdigest()
    if expected_params_sha != config["params_sha256"]:
        raise RuntimeError("worker factor mode or parameter identity mismatch")
    factor_class_identity = params["indicator"]
    if factor_class_identity != config.get("factor_class"):
        raise RuntimeError("worker factor class differs from parent selection")
    actual_code_sha, _ = _code_fingerprint(root)
    if actual_code_sha != config["code_sha256"]:
        raise RuntimeError("production source changed after parent preflight")
    parquet_path = Path(config["parquet_path"]).resolve()
    if _sha256_file(parquet_path) != config["parquet_sha256"]:
        raise RuntimeError("worker chunk input parquet hash mismatch")
    print("worker %04d reading %s" % (config["chunk_index"], parquet_path.name), flush=True)
    chunk = pd.read_parquet(parquet_path)
    symbols = tuple(config["symbols"])
    grid = config["grid"]
    grid_close_local = pd.DatetimeIndex(pd.to_datetime([row["close_time"] for row in grid]))
    grid_index = grid_close_local.tz_localize(SOURCE_TIMEZONE).tz_convert("UTC")
    grid_index = pd.DatetimeIndex(grid_index, name="close_time")
    open_local = pd.DatetimeIndex(pd.to_datetime([row["open_time"] for row in grid]))
    open_utc = open_local.tz_localize(SOURCE_TIMEZONE).tz_convert("UTC")
    research_grid = pd.DataFrame({"open_time": open_utc}, index=grid_index)

    _add_checkout_root()
    import backtrader as bt
    from backtrader.brokers.bbroker import BackBroker
    from backtrader.research import (
        FactorSpec,
        FactorStrategy,
        MemorySink,
        ResearchSpec,
        align_to_grid,
    )
    from backtrader.research.alpha101 import get_alpha

    start_close = (
        pd.Timestamp(config["study_first_close"]).tz_localize(SOURCE_TIMEZONE).tz_convert("UTC")
    )
    end_close = (
        pd.Timestamp(config["study_last_close"]).tz_localize(SOURCE_TIMEZONE).tz_convert("UTC")
    )
    # ``FactorStrategy`` samples the research window ``start..end`` only, while
    # ``FactorPanel`` requires the whole calculation grid (warm-up through the
    # research end) x targets.  The chunk's warm-up rows are therefore part of
    # the research window here and are dropped again when the study cells are
    # extracted below; the chunk still computes every factor with its
    # ``LOOKBACK`` preceding grid rows.
    research = ResearchSpec(
        grid=research_grid,
        start=grid_index[0],
        end=end_close,
        targets=symbols,
        source_timezone=SOURCE_TIMEZONE,
        snapshot_id=config["snapshot_id"],
        price_basis="source prices as provided; no adjustment applied by this run",
        calendar_id="source-observed-global-minute-close-v1",
        frequency="1source_observed_session",
        groups=dict.fromkeys(symbols, "all_symbols"),
    )

    grouped = chunk.groupby("symbol", sort=False)
    cerebro = bt.Cerebro(stdstats=False, runonce=False)

    class NoOrderBroker(BackBroker):
        def __init__(self):
            super().__init__()
            self.submit_count = 0
            self.cancel_count = 0

        def submit(self, *args, **kwargs):
            self.submit_count += 1
            raise AssertionError("research-only Alpha003 attempted broker submit")

        def cancel(self, *args, **kwargs):
            self.cancel_count += 1
            raise AssertionError("research-only Alpha003 attempted broker cancel")

    broker = NoOrderBroker()
    cerebro.broker = broker
    for symbol in symbols:
        if symbol not in grouped.groups:
            source = pd.DataFrame(
                columns=OHLC + ("volume",), index=pd.DatetimeIndex([], name="close_time")
            )
        else:
            rows = grouped.get_group(symbol)
            rows = rows.sort_values("trade_time", kind="stable").copy()
            source = rows.set_index("trade_time").loc[:, list(OHLC) + ["volume"]]
            source.index = pd.DatetimeIndex(pd.to_datetime(source.index))
            source.index.name = "close_time"
        aligned = align_to_grid(
            source,
            research,
            symbol,
            data_version="alpha003-daily-run:" + config["run_id"],
        )
        if int(aligned.feed.p.compression) != 1 or int(aligned.feed.p.timeframe) != int(
            bt.TimeFrame.Days
        ):
            raise RuntimeError("align_to_grid did not provide the daily Days/1 feed default")
        cerebro.adddata(aligned.feed, name=symbol)

    factor_class = get_alpha(3)
    actual_factor_class = factor_class.__module__ + "." + factor_class.__qualname__
    if actual_factor_class != config["factor_class"]:
        raise RuntimeError("worker selected a different Alpha003 implementation")
    factor_spec = FactorSpec(
        name=FACTOR_NAME,
        indicator=factor_class,
        mode=factor_mode,
        panel_line="factor",
        field_bindings={field: "feed:target:" + field for field in FACTOR_INPUTS},
    )
    cerebro.addstrategy(
        FactorStrategy,
        research=research,
        factors={FACTOR_NAME: factor_spec},
        sink=MemorySink(),
    )
    print(
        "worker %04d running Cerebro for %d symbols / %d grid dates"
        % (config["chunk_index"], len(symbols), len(grid)),
        flush=True,
    )
    strategy = cerebro.run(runonce=False, preload=True)[0]
    resolved_spec = strategy._factor_specs_by_name[FACTOR_NAME]
    factor_instances = strategy._factor_instances_by_name[FACTOR_NAME]
    if resolved_spec.mode != factor_mode or not factor_instances:
        raise RuntimeError("worker Alpha003 spec did not retain its configured mode")
    if any(instance.factor_mode != factor_mode for instance in factor_instances):
        raise RuntimeError("worker Alpha003 instance selected an unexpected mode")
    actual_factor_mode = factor_instances[0].factor_mode
    panel = strategy.get_panel()
    raw = panel.factors.reset_index()
    raw = raw.loc[
        (raw["time"] >= start_close) & (raw["time"] <= end_close),
        ["time", "asset", FACTOR_NAME],
    ].copy()
    raw["time"] = pd.to_datetime(raw["time"], utc=True)
    expected_cells = len(config["study_dates"]) * len(symbols)
    if len(raw) != expected_cells:
        raise RuntimeError("FactorStrategy did not return one factor row per study cell")
    if raw.duplicated(["time", "asset"]).any():
        raise RuntimeError("FactorStrategy returned duplicate factor cells")
    raw = raw.sort_values(["time", "asset"], kind="stable")
    chunk_dir = config_path.parent
    factor_path = chunk_dir / "factor_values.parquet"
    factor_tmp = factor_path.with_suffix(".parquet.tmp")
    raw.to_parquet(factor_tmp, index=False, compression="zstd")
    os.replace(factor_tmp, factor_path)
    result = {
        "status": "SUCCEEDED",
        "run_id": config["run_id"],
        "input_sha256": config["input_sha256"],
        "code_sha256": config["code_sha256"],
        "params_sha256": config["params_sha256"],
        "factor_mode": actual_factor_mode,
        "factor_class": actual_factor_class,
        "chunk_index": config["chunk_index"],
        "study_dates": config["study_dates"],
        "grid_dates": config["grid_dates"],
        "warmup_count": config["warmup_count"],
        "symbol_count": len(symbols),
        "cell_count": expected_cells,
        "factor_file": factor_path.name,
        "factor_sha256": _sha256_file(factor_path),
        "finite_count": int(np.isfinite(raw[FACTOR_NAME].to_numpy(dtype=float)).sum()),
        "broker_submit_count": broker.submit_count,
        "broker_cancel_count": broker.cancel_count,
        "runonce": False,
        "feed_timeframe": "Days/1 default from align_to_grid PandasData",
    }
    if broker.submit_count or broker.cancel_count:
        raise AssertionError("broker order counts must remain zero")
    _write_json(chunk_dir / "result.json", result)
    print(
        "worker %04d complete: %d cells, %d finite"
        % (config["chunk_index"], expected_cells, result["finite_count"]),
        flush=True,
    )


def _verify_chunk(
    chunk_dir: Path,
    config: Mapping[str, Any],
    expected: np.ndarray,
    dates: np.ndarray,
    symbols: Sequence[str],
) -> Tuple[pd.DataFrame, dict]:
    result_path = chunk_dir / "result.json"
    if not result_path.is_file():
        raise RuntimeError("worker did not produce a successful chunk result")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    for name in (
        "run_id",
        "input_sha256",
        "code_sha256",
        "params_sha256",
        "factor_mode",
        "factor_class",
        "chunk_index",
        "study_dates",
        "grid_dates",
        "warmup_count",
        "symbol_count",
        "cell_count",
    ):
        if result.get(name) != config[name]:
            raise RuntimeError("cached chunk result does not match %s" % name)
    if result.get("status") != "SUCCEEDED":
        raise RuntimeError("chunk status is not SUCCEEDED")
    factor_path = chunk_dir / str(result["factor_file"])
    if _sha256_file(factor_path) != result.get("factor_sha256"):
        raise RuntimeError("chunk result output hash mismatch")
    factors = pd.read_parquet(factor_path)
    factors["time"] = pd.to_datetime(factors["time"], utc=True)
    if len(factors) != int(config["cell_count"]):
        raise RuntimeError("chunk output cell count mismatch")
    if tuple(factors.columns) != ("time", "asset", FACTOR_NAME):
        raise RuntimeError("chunk factor output columns differ from the public schema")
    if set(factors["asset"].astype(str)) != set(symbols):
        raise RuntimeError("chunk universe differs from the fixed manifest universe")
    if factors.duplicated(["time", "asset"]).any():
        raise RuntimeError("chunk factor output contains duplicate study cells")
    factor_values = factors[FACTOR_NAME].to_numpy(dtype=np.float64)
    if np.isinf(factor_values).any():
        raise RuntimeError("native Alpha003 output contains infinity")
    finite_values = np.isfinite(factor_values)
    if np.any(finite_values & (np.abs(factor_values) > 1.0)):
        raise RuntimeError("native Alpha003 values must remain within [-1, 1]")

    date_lookup = {str(value): index for index, value in enumerate(dates)}
    symbol_lookup = {symbol: index for index, symbol in enumerate(symbols)}
    factor_dates = factors["time"].dt.tz_convert(SOURCE_TIMEZONE).dt.strftime("%Y-%m-%d").to_numpy()
    # The chunk must describe exactly its own study window, one row per cell.
    if set(factor_dates) != {str(value) for value in config["study_dates"]}:
        raise RuntimeError("chunk factor output does not cover the chunk study window")
    row_indices = np.fromiter(
        (date_lookup[value] for value in factor_dates), dtype=np.int64, count=len(factor_dates)
    )
    col_indices = np.fromiter(
        (symbol_lookup[str(value)] for value in factors["asset"]),
        dtype=np.int64,
        count=len(factors),
    )
    oracle_values = expected[row_indices, col_indices]
    oracle_valid = np.isfinite(oracle_values)
    if not np.array_equal(finite_values, oracle_valid):
        raise RuntimeError("native Alpha003 finite mask differs from independent full-panel oracle")
    errors = np.abs(factor_values[finite_values] - oracle_values[finite_values])
    max_error = float(errors.max()) if len(errors) else 0.0
    if max_error > ORACLE_ATOL:
        raise RuntimeError("native Alpha003 differs from independent oracle: %.17g" % max_error)
    factors["trade_date"] = factor_dates
    factors["oracle_alpha003"] = oracle_values
    factors["abs_error"] = np.where(finite_values, np.abs(factor_values - oracle_values), np.nan)
    factors = factors.loc[
        :, ["time", "trade_date", "asset", FACTOR_NAME, "oracle_alpha003", "abs_error"]
    ]
    result["max_abs_error"] = max_error
    result["oracle_mask_matches"] = True
    result["oracle_values_match"] = True
    return factors, result


def _worker_config(
    *,
    chunk_dir: Path,
    cache_metadata: Mapping[str, Any],
    arrays: Mapping[str, Any],
    calendar: pd.DataFrame,
    chunk_index: int,
    grid_start: int,
    study_start: int,
    study_end: int,
    run_id: str,
    input_sha256: str,
    code_sha256: str,
    params_sha256: str,
    factor_mode: str,
    factor_class: str,
    chunk_days: int,
    snapshot_id: str,
) -> dict:
    grid_rows = []
    for grid_index in range(grid_start, study_end):
        row = calendar.iloc[grid_index]
        grid_rows.append(
            {
                "trade_date": str(row["trade_date"]),
                "open_time": pd.Timestamp(row["_open_local"]).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                "close_time": pd.Timestamp(row["_close_local"]).strftime("%Y-%m-%d %H:%M:%S.%f")[
                    :-3
                ],
            }
        )
    study_dates = arrays["dates"][study_start:study_end].tolist()
    grid_dates = arrays["dates"][grid_start:study_end].tolist()
    study_first_close = grid_rows[study_start - grid_start]["close_time"]
    study_last_close = grid_rows[-1]["close_time"]
    return {
        "run_id": run_id,
        "input_sha256": input_sha256,
        "code_sha256": code_sha256,
        "params_sha256": params_sha256,
        "factor_mode": factor_mode,
        "factor_class": factor_class,
        "chunk_days": chunk_days,
        "chunk_index": chunk_index,
        "study_dates": study_dates,
        "grid_dates": grid_dates,
        "warmup_count": study_start - grid_start,
        "symbol_count": len(arrays["symbols"]),
        "cell_count": len(study_dates) * len(arrays["symbols"]),
        "symbols": list(arrays["symbols"]),
        "grid": grid_rows,
        "study_first_close": study_first_close,
        "study_last_close": study_last_close,
        "snapshot_id": snapshot_id,
        "parquet_path": str((chunk_dir.parent / ("chunk_%04d.parquet" % chunk_index)).resolve()),
        "parquet_sha256": cache_metadata["parquet_sha256"],
    }


def _run_parent(
    data_dir: Path, output_dir: Path, chunk_days: int, factor_mode: str = "native"
) -> dict:
    root = _add_checkout_root()
    factor_mode = _resolve_factor_mode(factor_mode)
    if type(chunk_days) is not int or chunk_days <= 0:
        raise ValueError("chunk_days must be a positive integer")
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    if not data_dir.is_dir():
        raise NotADirectoryError(data_dir)
    if data_dir == output_dir or data_dir in output_dir.parents:
        raise ValueError("output directory must not be the input data directory or its descendant")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest, calendar, entries, input_sha256 = _read_manifest(data_dir)
    code_sha256, code_pins = _code_fingerprint(root)
    params = _params(root, factor_mode)
    params["chunk_days"] = chunk_days
    params_sha256 = hashlib.sha256(_canonical_json(params)).hexdigest()
    run_identity = {
        "input_sha256": input_sha256,
        "code_sha256": code_sha256,
        "params_sha256": params_sha256,
        "factor_mode": factor_mode,
        "params": params,
        "symbol_count": len(entries),
        "grid_count": int(len(calendar)),
        "first_trade_date": str(calendar["trade_date"].iloc[0]),
        "last_trade_date": str(calendar["trade_date"].iloc[-1]),
    }
    run_id = hashlib.sha256(_canonical_json(run_identity)).hexdigest()
    run_identity["run_id"] = run_id
    run_identity["code_pins"] = code_pins
    summary_path = output_dir / "run_summary.json"
    state_path = output_dir / "run_state.json"
    if any(output_dir.iterdir()):
        if not state_path.is_file():
            raise FileExistsError(
                "output directory must be new or contain this runner's run_state.json"
            )
        prior = json.loads(state_path.read_text(encoding="utf-8"))
        if prior.get("run_id") != run_id or prior.get("identity") != run_identity:
            raise RunIdentityConflictError(
                "existing output belongs to a different input/code/parameter identity"
            )
        if prior.get("status") == "COMPLETED":
            if not summary_path.is_file() or _sha256_file(summary_path) != prior.get(
                "summary_sha256"
            ):
                raise RuntimeError("completed run summary hash mismatch")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("status") != "COMPLETED" or summary.get("run_id") != run_id:
                raise RuntimeError("completed run summary identity mismatch")
            for key in ("factor_values.parquet", "factor_values.csv"):
                if _sha256_file(output_dir / key) != summary["output_sha256"][key]:
                    raise RuntimeError("completed output file hash mismatch: %s" % key)
            print("COMPLETED: matching prior run %s" % run_id, flush=True)
            resumed = dict(summary)
            resumed["actual_chunk_runs_this_invocation"] = 0
            resumed["reused_successful_chunks"] = len(prior.get("completed_chunks", []))
            return resumed
    _write_json(
        state_path,
        {"status": "RUNNING", "run_id": run_id, "identity": run_identity, "completed_chunks": []},
    )
    _write_json(
        summary_path,
        {"status": "RUNNING", "run_id": run_id, "source_path": str(data_dir)},
    )
    print("input identity %s; loading %d symbol CSVs" % (input_sha256, len(entries)), flush=True)
    arrays = _load_source_arrays(data_dir, calendar, entries)
    open_values, volume_values = _prepare_formula_inputs(arrays)
    expected = _oracle(open_values, volume_values)
    del open_values, volume_values
    print("independent full-panel oracle ready: %d dates x %d symbols" % expected.shape, flush=True)

    chunks = _chunk_bounds(len(calendar), chunk_days)
    if not np.array_equal(
        arrays["present"].sum(axis=1, dtype=np.int64),
        pd.to_numeric(calendar["symbol_count"], errors="raise").to_numpy(dtype=np.int64),
    ):
        raise ValueError("daily CSV symbol counts differ from observed_calendar.csv")
    chunk_specs = []
    for chunk_index, grid_start, study_end in chunks:
        study_start = chunk_index * chunk_days
        parquet_path, _, cache_metadata = _cache_chunk(
            output_dir,
            arrays,
            calendar,
            chunk_index=chunk_index,
            grid_start=grid_start,
            study_start=study_start,
            study_end=study_end,
            input_sha256=input_sha256,
            code_sha256=code_sha256,
            params_sha256=params_sha256,
            run_id=run_id,
        )
        chunk_dir = parquet_path.parent / ("chunk_%04d" % chunk_index)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        worker_config = _worker_config(
            chunk_dir=chunk_dir,
            cache_metadata=cache_metadata,
            arrays=arrays,
            calendar=calendar,
            chunk_index=chunk_index,
            grid_start=grid_start,
            study_start=study_start,
            study_end=study_end,
            run_id=run_id,
            input_sha256=input_sha256,
            code_sha256=code_sha256,
            params_sha256=params_sha256,
            factor_mode=factor_mode,
            factor_class=params["indicator"],
            chunk_days=chunk_days,
            snapshot_id=(
                "source-observed-daily-alpha003-v1:"
                + str(calendar["trade_date"].iloc[0])
                + ":"
                + str(calendar["trade_date"].iloc[-1])
            ),
        )
        # Worker outputs live beside the chunk input to keep resumable chunks self-contained.
        worker_config["parquet_path"] = str(parquet_path.resolve())
        config_path = chunk_dir / "worker.json"
        if config_path.exists():
            prior_config = json.loads(config_path.read_text(encoding="utf-8"))
            if prior_config != worker_config:
                raise RuntimeError("existing worker chunk configuration differs")
        else:
            _write_json(config_path, worker_config)
        worker_config["config_path"] = str(config_path.resolve())
        chunk_specs.append(
            (chunk_index, grid_start, study_start, study_end, chunk_dir, worker_config)
        )

    completed = []
    max_abs_error = 0.0
    actual_runs = 0
    reused_runs = 0
    finite_total = 0
    first_finite_date = None
    expected_total = 0
    submit_total = 0
    cancel_total = 0
    factor_partial = output_dir / "factor_values.csv.partial"
    parquet_partial = output_dir / "factor_values.parquet.partial"
    for path in (factor_partial, parquet_partial):
        if path.exists():
            path.unlink()

    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet_writer = None
    try:
        for chunk_index, grid_start, study_start, study_end, chunk_dir, config in chunk_specs:
            result_path = chunk_dir / "result.json"
            reused = result_path.is_file()
            result_preview = None
            if reused:
                result_preview = json.loads(result_path.read_text(encoding="utf-8"))
                if result_preview.get("run_id") != run_id:
                    raise RuntimeError("cached worker result belongs to another run")
                reused_runs += 1
                print("reusing successful chunk %04d" % chunk_index, flush=True)
            else:
                actual_runs += 1
                print(
                    "starting chunk %04d (%s..%s; warmup=%d)"
                    % (
                        chunk_index,
                        config["study_dates"][0],
                        config["study_dates"][-1],
                        config["warmup_count"],
                    ),
                    flush=True,
                )
                command = [
                    sys.executable,
                    "-u",
                    str(Path(__file__).resolve()),
                    "--_worker-config",
                    config["config_path"],
                ]
                with subprocess.Popen(
                    command,
                    cwd=str(root),
                    stdout=subprocess.PIPE,
                    stderr=None,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                ) as process:
                    assert process.stdout is not None
                    for line in process.stdout:
                        print(line.rstrip("\r\n"), flush=True)
                    return_code = process.wait()
                if return_code != 0:
                    raise RuntimeError("chunk %04d worker exited %d" % (chunk_index, return_code))

            factors, result = _verify_chunk(
                chunk_dir,
                config,
                expected,
                arrays["dates"],
                arrays["symbols"],
            )
            max_abs_error = max(max_abs_error, float(result["max_abs_error"]))
            expected_total += len(factors)
            finite = np.isfinite(factors[FACTOR_NAME].to_numpy(dtype=float))
            finite_total += int(finite.sum())
            if finite.any() and first_finite_date is None:
                first_finite_date = str(factors.loc[finite, "trade_date"].iloc[0])
            submit_total += int(result["broker_submit_count"])
            cancel_total += int(result["broker_cancel_count"])
            if submit_total or cancel_total:
                raise RuntimeError("a research chunk recorded a broker submit or cancel")

            factor_table = pa.Table.from_pandas(factors, preserve_index=False)
            if parquet_writer is None:
                parquet_writer = pq.ParquetWriter(
                    parquet_partial, factor_table.schema, compression="zstd"
                )
            else:
                factor_table = factor_table.cast(parquet_writer.schema)
            parquet_writer.write_table(factor_table)
            factors.to_csv(
                factor_partial,
                mode="a",
                index=False,
                header=not factor_partial.exists(),
                encoding="utf-8",
            )
            completed.append(
                {
                    "chunk_index": chunk_index,
                    "study_first_date": config["study_dates"][0],
                    "study_last_date": config["study_dates"][-1],
                    "grid_first_date": config["grid_dates"][0],
                    "grid_last_date": config["grid_dates"][-1],
                    "warmup_grid_rows": config["warmup_count"],
                    "cells": int(result["cell_count"]),
                    "finite": int(result["finite_count"]),
                    "max_abs_error": float(result["max_abs_error"]),
                    "reused_successful_chunk": reused,
                }
            )
            _write_json(
                state_path,
                {
                    "status": "RUNNING",
                    "run_id": run_id,
                    "identity": run_identity,
                    "completed_chunks": completed,
                    "actual_chunk_runs": actual_runs,
                    "reused_chunk_runs": reused_runs,
                },
            )
            print(
                "verified chunk %04d: max error %.3g" % (chunk_index, result["max_abs_error"]),
                flush=True,
            )
    finally:
        if parquet_writer is not None:
            parquet_writer.close()

    expected_cells = len(calendar) * len(entries)
    if expected_total != expected_cells or finite_total != int(np.isfinite(expected).sum()):
        raise RuntimeError("completed output grid or finite count differs from the full oracle")
    if finite_total == 0:
        raise RuntimeError("full Alpha003 panel contains no valid finite factor values")
    if not completed:
        raise RuntimeError("no chunks were run")
    if max_abs_error > ORACLE_ATOL or submit_total or cancel_total:
        raise RuntimeError("final oracle or no-order broker acceptance failed")
    final_factor_csv = output_dir / "factor_values.csv"
    final_factor_parquet = output_dir / "factor_values.parquet"
    os.replace(factor_partial, final_factor_csv)
    os.replace(parquet_partial, final_factor_parquet)
    commit = _git_head(root)
    factor_class = _params(root, factor_mode)["indicator"]
    from backtrader.research import align as research_align
    from backtrader.research.alpha101 import get_alpha

    # Resolve real module files instead of guessing removed/renamed paths.
    factor_source_path = _module_source_path(get_alpha(3).__module__)
    alignment_source_path = _module_source_path(research_align)
    summary = {
        "status": "COMPLETED",
        "evidence_level": "SOURCE_OBSERVED_DAILY_ALPHA003_PRODUCTION_FACTORSTRATEGY",
        "acceptance": "ALL_CHUNKS_MATCHED_INDEPENDENT_FULL_PANEL_ORACLE",
        "run_id": run_id,
        "input_sha256": input_sha256,
        "code_sha256": code_sha256,
        "params_sha256": params_sha256,
        "source_path": str(data_dir),
        "source_manifest": str(data_dir / "_metadata" / "manifest.json"),
        "source_observed_calendar": str(data_dir / "_metadata" / "observed_calendar.csv"),
        "calendar_policy": "source-observed global daily rows; not official exchange calendar",
        "source_timezone": SOURCE_TIMEZONE,
        "price_basis": "source prices as provided; no adjustment applied by this run",
        "source_commit": commit,
        "factor_class": factor_class,
        "factor_mode": factor_mode,
        "factor_strategy_source_path": str(
            (root / "backtrader" / "research" / "factor_strategy.py").resolve()
        ),
        "symbol_count": len(entries),
        "symbols_sha256": hashlib.sha256("\n".join(arrays["symbols"]).encode("utf-8")).hexdigest(),
        "grid_count": len(calendar),
        "grid_first_date": str(calendar["trade_date"].iloc[0]),
        "grid_last_date": str(calendar["trade_date"].iloc[-1]),
        "panel_cell_count": expected_cells,
        "source_daily_row_count": int(arrays["total_rows"]),
        "invalid_daily_row_count": int(arrays["invalid_rows"]),
        "finite_factor_count": finite_total,
        "first_finite_trade_date": first_finite_date,
        "oracle": {
            "implementation": "independent pandas average-tie row ranks plus batched numpy centered Pearson",
            "uses_production_operators": False,
            "period": PERIOD,
            "finite_mask_matches": True,
            "max_abs_error": max_abs_error,
            "absolute_tolerance": ORACLE_ATOL,
            "factor_range": [-1.0, 1.0],
        },
        "broker_submit_count": submit_total,
        "broker_cancel_count": cancel_total,
        "chunk_days": chunk_days,
        "chunk_count": len(completed),
        "actual_chunk_runs_this_invocation": actual_runs,
        "reused_successful_chunks": reused_runs,
        "chunks": completed,
        "output_files": ["factor_values.parquet", "factor_values.csv"],
        "output_sha256": {
            "factor_values.parquet": _sha256_file(final_factor_parquet),
            "factor_values.csv": _sha256_file(final_factor_csv),
        },
    }
    if factor_source_path is not None:
        summary["factor_source_path"] = factor_source_path
    if alignment_source_path is not None:
        summary["input_alignment_source_path"] = alignment_source_path
    _write_json(summary_path, summary)
    _write_json(
        state_path,
        {
            "status": "COMPLETED",
            "run_id": run_id,
            "identity": run_identity,
            "completed_chunks": completed,
            "actual_chunk_runs": actual_runs,
            "reused_chunk_runs": reused_runs,
            "summary_sha256": _sha256_file(summary_path),
        },
    )
    print(
        "COMPLETED: %d cells, %d finite, max oracle error %.3g"
        % (expected_cells, finite_total, max_abs_error),
        flush=True,
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--chunk-days", type=int, default=20)
    parser.add_argument("--factor-mode", choices=FACTOR_MODES, default="native")
    parser.add_argument("--_worker-config", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker_config is not None:
        _run_worker(args._worker_config.resolve())
        return 0
    if args.data_dir is None or args.output_dir is None:
        parser.error("--data-dir and --output-dir are required")
    output_dir = args.output_dir.resolve()
    try:
        _run_parent(args.data_dir, output_dir, args.chunk_days, args.factor_mode)
    except RunIdentityConflictError:
        raise
    except BaseException as exc:
        if output_dir.exists() and (output_dir / "run_state.json").exists():
            try:
                state = json.loads((output_dir / "run_state.json").read_text(encoding="utf-8"))
                if state.get("status") != "COMPLETED":
                    state["status"] = "FAILED"
                    state["failure_type"] = type(exc).__name__
                    state["failure_message"] = str(exc)
                    _write_json(output_dir / "run_state.json", state)
                    summary_path = output_dir / "run_summary.json"
                    if summary_path.exists():
                        summary = json.loads(summary_path.read_text(encoding="utf-8"))
                        summary["status"] = "FAILED"
                        summary["failure_type"] = type(exc).__name__
                        summary["failure_message"] = str(exc)
                        _write_json(summary_path, summary)
            except Exception:
                pass
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
