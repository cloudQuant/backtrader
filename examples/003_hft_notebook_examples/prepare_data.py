from __future__ import annotations

import argparse
import csv
import io
import json
import math
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from backtrader.brokers.hft import convert_binance_bbo_zip_pair, generate_latency_from_hft_events

EXAMPLE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_ROOT = EXAMPLE_ROOT / "data"
DEFAULT_BINANCE_PROJECT_ROOT = Path("J:/binance-public-data")
DEFAULT_BINANCE_SOURCE_ROOT = DEFAULT_BINANCE_PROJECT_ROOT / "data"
BINANCE_DATA_ROOT_URL = "https://data.binance.vision/data"
_INTERVAL_NS = 100_000_000
_ROLLING_WINDOW = 3000
_SHIFT = 1500


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare local datasets for migrated hftbacktest notebook strategies from a local binance-public-data checkout")
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--binance-project-root", default=str(DEFAULT_BINANCE_PROJECT_ROOT))
    parser.add_argument("--binance-source-root", default=str(DEFAULT_BINANCE_SOURCE_ROOT))
    parser.add_argument("--btc-date", default="2024-09-01")
    parser.add_argument("--eth-date", default="2024-01-01")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--prepare-btc-alpha", action="store_true")
    parser.add_argument("--prepare-glft", action="store_true")
    return parser


def _open_zip_csv(zip_path: Path):
    archive = zipfile.ZipFile(zip_path)
    names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(names) != 1:
        archive.close()
        raise ValueError(f"Expected exactly one CSV entry in {zip_path}")
    raw = archive.open(names[0], "r")
    text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
    return archive, text


def _iter_book_ticker_rows(zip_path: Path):
    archive, text = _open_zip_csv(zip_path)
    try:
        reader = csv.DictReader(text)
        for row in reader:
            yield row
    finally:
        text.close()
        archive.close()


def _iter_csv_values(zip_path: Path):
    archive, text = _open_zip_csv(zip_path)
    try:
        reader = csv.reader(text)
        for row in reader:
            yield row
    finally:
        text.close()
        archive.close()


def _timestamp_to_ns(value: str | int) -> int:
    raw = int(value)
    if raw >= 10**15:
        return raw * 1000
    if raw >= 10**12:
        return raw * 1_000_000
    return raw * 1_000_000_000


def _day_bounds(date_text: str) -> tuple[int, int]:
    day = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ms = int(day.timestamp() * 1000)
    end_ms = int((day + timedelta(days=1)).timestamp() * 1000)
    return start_ms, end_ms


def _resample_last(points: list[tuple[int, float]]) -> tuple[np.ndarray, np.ndarray]:
    if not points:
        raise ValueError("No source rows were collected for resampling")
    bucket_starts = []
    bucket_values = []
    for timestamp_ns, value in points:
        bucket = (int(timestamp_ns) // _INTERVAL_NS) * _INTERVAL_NS
        if bucket_starts and bucket == bucket_starts[-1]:
            bucket_values[-1] = float(value)
        else:
            bucket_starts.append(bucket)
            bucket_values.append(float(value))
    start = int(bucket_starts[0])
    end = int(bucket_starts[-1])
    grid = np.arange(start, end + _INTERVAL_NS, _INTERVAL_NS, dtype=np.int64)
    values = np.empty(len(grid), dtype=np.float64)
    current = math.nan
    index = 0
    for grid_index, bucket in enumerate(grid):
        while index < len(bucket_starts) and bucket_starts[index] <= bucket:
            current = float(bucket_values[index])
            index += 1
        values[grid_index] = current
    mask = np.isfinite(values)
    return grid[mask], values[mask]


def _load_book_ticker_series(zip_path: Path) -> tuple[np.ndarray, np.ndarray]:
    points = []
    for row in _iter_book_ticker_rows(zip_path):
        transaction_time = int(row["transaction_time"])
        event_time = int(row.get("event_time", transaction_time))
        local_ts_ns = _timestamp_to_ns(max(transaction_time, event_time))
        mid_price = (float(row["best_bid_price"]) + float(row["best_ask_price"])) / 2.0
        points.append((local_ts_ns, mid_price))
    return _resample_last(points)


def _load_trade_price_series(zip_path: Path, date_text: str) -> tuple[np.ndarray, np.ndarray]:
    start_ms, end_ms = _day_bounds(date_text)
    points = []
    for row in _iter_csv_values(zip_path):
        if not row:
            continue
        if not row[0] or not row[0][0].isdigit():
            continue
        if len(row) >= 8:
            timestamp_ms = int(row[5])
            price = float(row[1])
        elif len(row) == 6:
            timestamp_ms = int(row[4])
            price = float(row[1])
        elif len(row) >= 7:
            timestamp_ms = int(row[4])
            price = float(row[1])
        else:
            continue
        if timestamp_ms < start_ms or timestamp_ms >= end_ms:
            continue
        points.append((_timestamp_to_ns(timestamp_ms), price))
    return _resample_last(points)


def _align_resampled_series(left_ts: np.ndarray, left_values: np.ndarray, right_ts: np.ndarray, right_values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    start = max(int(left_ts[0]), int(right_ts[0]))
    end = min(int(left_ts[-1]), int(right_ts[-1]))
    if end < start:
        raise ValueError("No overlapping timestamps between spot and futures series")
    common_ts = np.arange(start, end + _INTERVAL_NS, _INTERVAL_NS, dtype=np.int64)
    left_index = ((common_ts - int(left_ts[0])) // _INTERVAL_NS).astype(np.int64)
    right_index = ((common_ts - int(right_ts[0])) // _INTERVAL_NS).astype(np.int64)
    return common_ts, left_values[left_index], right_values[right_index]


def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=np.float64)
    if len(values) < window:
        return output
    prefix = np.cumsum(np.insert(values, 0, 0.0))
    output[window - 1 :] = (prefix[window:] - prefix[:-window]) / float(window)
    return output


def _shift(values: np.ndarray, periods: int) -> np.ndarray:
    output = np.full(len(values), np.nan, dtype=np.float64)
    if periods <= 0:
        output[:] = values
        return output
    if periods < len(values):
        output[periods:] = values[:-periods]
    return output


def _save_basis_precompute(spot_source_zip: Path, futures_book_zip: Path, date_text: str, output_path: Path) -> Path:
    spot_ts, spot_values = _load_trade_price_series(spot_source_zip, date_text)
    futures_ts, futures_values = _load_book_ticker_series(futures_book_zip)
    common_ts, spot_values, futures_values = _align_resampled_series(spot_ts, spot_values, futures_ts, futures_values)
    basis = _rolling_mean(futures_values - spot_values, _ROLLING_WINDOW)
    mask = np.isfinite(basis)
    data = np.column_stack((common_ts[mask].astype(np.float64), spot_values[mask], basis[mask]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, data=data)
    return output_path


def _save_apt_precompute(spot_source_zip: Path, futures_book_zip: Path, date_text: str, output_path: Path) -> Path:
    spot_ts, spot_values = _load_trade_price_series(spot_source_zip, date_text)
    futures_ts, futures_values = _load_book_ticker_series(futures_book_zip)
    common_ts, spot_values, futures_values = _align_resampled_series(spot_ts, spot_values, futures_ts, futures_values)
    spot_past = _shift(_rolling_mean(spot_values, _ROLLING_WINDOW), _SHIFT)
    futures_past = _shift(_rolling_mean(futures_values, _ROLLING_WINDOW), _SHIFT)
    spot_return = spot_values / spot_past - 1.0
    futures_return = futures_values / futures_past - 1.0
    mask = np.isfinite(spot_return) & np.isfinite(spot_past) & np.isfinite(futures_return) & np.isfinite(futures_past)
    data = np.column_stack(
        (
            common_ts[mask].astype(np.float64),
            spot_return[mask],
            spot_past[mask],
            futures_return[mask],
            futures_past[mask],
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, data=data)
    return output_path


def _stage_raw_file(source_path: Path, raw_dir: Path, staged_name: str | None = None) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    destination = raw_dir / (staged_name or source_path.name)
    if not destination.exists():
        shutil.copy2(source_path, destination)
    return destination


def _local_futures_daily_path(source_root: Path, symbol: str, data_type: str, date_text: str) -> Path:
    return source_root / "futures" / "um" / "daily" / data_type / symbol / f"{symbol}-{data_type}-{date_text}.zip"


def _local_spot_monthly_candidates(source_root: Path, symbol: str, date_text: str) -> list[Path]:
    month_text = date_text[:7]
    return [
        source_root / "spot" / "monthly" / "trades" / symbol / f"{symbol}-trades-{month_text}.zip",
        source_root / "spot" / "monthly" / "aggTrades" / symbol / f"{symbol}-aggTrades-{month_text}.zip",
    ]


def _local_spot_daily_candidates(source_root: Path, symbol: str, date_text: str) -> list[Path]:
    return [
        source_root / "spot" / "daily" / "trades" / symbol / f"{symbol}-trades-{date_text}.zip",
        source_root / "spot" / "daily" / "aggTrades" / symbol / f"{symbol}-aggTrades-{date_text}.zip",
    ]


def _run_local_downloader(project_root: Path, script_name: str, symbol: str, date_text: str, source_root: Path) -> None:
    script_path = project_root / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Missing local downloader script: {script_path}")
    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "-s",
            symbol,
            "-startDate",
            date_text,
            "-endDate",
            date_text,
            "-folder",
            str(source_root),
        ],
        check=True,
        cwd=str(project_root),
    )


def _direct_download_futures_daily(source_root: Path, symbol: str, data_type: str, date_text: str) -> Path:
    candidate = _local_futures_daily_path(source_root, symbol, data_type, date_text)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BINANCE_DATA_ROOT_URL}/futures/um/daily/{data_type}/{symbol}/{symbol}-{data_type}-{date_text}.zip"
    with urllib.request.urlopen(url) as response, candidate.open("wb") as handle:
        handle.write(response.read())
    return candidate


def _direct_download_spot_daily(source_root: Path, symbol: str, data_type: str, date_text: str) -> Path:
    if data_type == "trades":
        candidate = source_root / "spot" / "daily" / "trades" / symbol / f"{symbol}-trades-{date_text}.zip"
        url = f"{BINANCE_DATA_ROOT_URL}/spot/daily/trades/{symbol}/{symbol}-trades-{date_text}.zip"
    else:
        candidate = source_root / "spot" / "daily" / "aggTrades" / symbol / f"{symbol}-aggTrades-{date_text}.zip"
        url = f"{BINANCE_DATA_ROOT_URL}/spot/daily/aggTrades/{symbol}/{symbol}-aggTrades-{date_text}.zip"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, candidate.open("wb") as handle:
        handle.write(response.read())
    return candidate


def _ensure_local_futures_daily(source_root: Path, project_root: Path, symbol: str, data_type: str, date_text: str, skip_download: bool) -> Path:
    candidate = _local_futures_daily_path(source_root, symbol, data_type, date_text)
    if candidate.exists():
        return candidate
    if skip_download:
        raise FileNotFoundError(f"Missing local futures file: {candidate}")
    script_name = f"download-futures-um-daily-{data_type}.py"
    try:
        _run_local_downloader(project_root, script_name, symbol, date_text, source_root)
    except Exception:
        pass
    if not candidate.exists():
        _direct_download_futures_daily(source_root, symbol, data_type, date_text)
    if not candidate.exists():
        raise FileNotFoundError(f"Local downloader did not produce expected file: {candidate}")
    return candidate


def _resolve_local_spot_source(source_root: Path, symbol: str, date_text: str, skip_download: bool) -> Path:
    for candidate in _local_spot_daily_candidates(source_root, symbol, date_text):
        if candidate.exists():
            return candidate
    if not skip_download:
        for data_type in ("trades", "aggTrades"):
            try:
                candidate = _direct_download_spot_daily(source_root, symbol, data_type, date_text)
                if candidate.exists():
                    return candidate
            except Exception:
                pass
    for candidate in _local_spot_monthly_candidates(source_root, symbol, date_text):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Missing spot source file. Checked: "
        + ", ".join(
            str(candidate)
            for candidate in [
                *_local_spot_daily_candidates(source_root, symbol, date_text),
                *_local_spot_monthly_candidates(source_root, symbol, date_text),
            ]
        )
    )


def _prepare_btc_alpha_dataset(data_root: Path, source_root: Path, project_root: Path, btc_date: str, skip_download: bool) -> dict[str, str]:
    yyyymmdd = btc_date.replace("-", "")
    target_dir = data_root / f"btcusdt_{yyyymmdd}"
    raw_dir = target_dir / "raw"
    futures_book_source = _ensure_local_futures_daily(source_root, project_root, "BTCUSDT", "bookTicker", btc_date, skip_download)
    futures_trades_source = _ensure_local_futures_daily(source_root, project_root, "BTCUSDT", "trades", btc_date, skip_download)
    spot_source = _resolve_local_spot_source(source_root, "BTCUSDT", btc_date, skip_download)
    futures_book_zip = _stage_raw_file(futures_book_source, raw_dir)
    futures_trades_zip = _stage_raw_file(futures_trades_source, raw_dir)
    spot_source_zip = _stage_raw_file(spot_source, raw_dir, staged_name=f"spot-{spot_source.name}")
    conversion = convert_binance_bbo_zip_pair(
        book_ticker_zip_path=futures_book_zip,
        trades_zip_path=futures_trades_zip,
        output_directory=target_dir,
        bt_symbol="BTC/USDT",
        exchange="binance",
        asset_type="futures",
        tick_size=0.1,
        lot_size=0.001,
    )
    latency = generate_latency_from_hft_events(conversion.hft_npz_path, target_dir / f"latency_{yyyymmdd}.npz")
    basis_path = _save_basis_precompute(spot_source_zip, futures_book_zip, btc_date, target_dir / "px_basis_BTCUSDT_5m.npz")
    apt_path = _save_apt_precompute(spot_source_zip, futures_book_zip, btc_date, target_dir / "precompute_px_return_BTCUSDT_5m.npz")
    return {
        "market_data": str(conversion.hft_npz_path),
        "orderbook": str(conversion.backtrader_orderbook_path),
        "ticks": str(conversion.backtrader_ticks_path),
        "latency": str(latency.latency_npz_path),
        "basis_precompute": str(basis_path),
        "apt_precompute": str(apt_path),
        "spot_source": str(spot_source_zip),
        "futures_book_source": str(futures_book_zip),
        "futures_trades_source": str(futures_trades_zip),
    }


def _prepare_glft_dataset(data_root: Path, source_root: Path, project_root: Path, eth_date: str, skip_download: bool) -> dict[str, str]:
    yyyymmdd = eth_date.replace("-", "")
    target_dir = data_root / f"ethusdt_{yyyymmdd}"
    raw_dir = target_dir / "raw"
    futures_book_source = _ensure_local_futures_daily(source_root, project_root, "ETHUSDT", "bookTicker", eth_date, skip_download)
    futures_trades_source = _ensure_local_futures_daily(source_root, project_root, "ETHUSDT", "trades", eth_date, skip_download)
    futures_book_zip = _stage_raw_file(futures_book_source, raw_dir)
    futures_trades_zip = _stage_raw_file(futures_trades_source, raw_dir)
    conversion = convert_binance_bbo_zip_pair(
        book_ticker_zip_path=futures_book_zip,
        trades_zip_path=futures_trades_zip,
        output_directory=target_dir,
        bt_symbol="ETH/USDT",
        exchange="binance",
        asset_type="futures",
        tick_size=0.01,
        lot_size=0.001,
    )
    latency = generate_latency_from_hft_events(conversion.hft_npz_path, target_dir / f"latency_{yyyymmdd}.npz")
    return {
        "market_data": str(conversion.hft_npz_path),
        "orderbook": str(conversion.backtrader_orderbook_path),
        "ticks": str(conversion.backtrader_ticks_path),
        "latency": str(latency.latency_npz_path),
        "futures_book_source": str(futures_book_zip),
        "futures_trades_source": str(futures_trades_zip),
    }


def main() -> int:
    args = _build_parser().parse_args()
    data_root = Path(args.data_root)
    source_root = Path(args.binance_source_root)
    project_root = Path(args.binance_project_root)
    prepare_btc_alpha = args.prepare_btc_alpha or (not args.prepare_btc_alpha and not args.prepare_glft)
    prepare_glft = args.prepare_glft or (not args.prepare_btc_alpha and not args.prepare_glft)
    payload = {}
    if prepare_btc_alpha:
        payload["btc_alpha"] = _prepare_btc_alpha_dataset(data_root, source_root, project_root, args.btc_date, args.skip_download)
    if prepare_glft:
        payload["glft"] = _prepare_glft_dataset(data_root, source_root, project_root, args.eth_date, args.skip_download)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
