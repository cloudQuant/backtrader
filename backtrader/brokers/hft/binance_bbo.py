from __future__ import annotations

import bisect
import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional

import numpy as np

try:
    from hftbacktest import FuseMarketDepth
except Exception:
    FuseMarketDepth = None

EXCH_EVENT = 1 << 31
LOCAL_EVENT = 1 << 30
BUY_EVENT = 1 << 29
SELL_EVENT = 1 << 28
DEPTH_EVENT = 1
TRADE_EVENT = 2
DEPTH_BBO_EVENT = 5

EVENT_DTYPE = np.dtype(
    [
        ("ev", "u8"),
        ("exch_ts", "i8"),
        ("local_ts", "i8"),
        ("px", "f8"),
        ("qty", "f8"),
        ("order_id", "u8"),
        ("ival", "i8"),
        ("fval", "f8"),
    ],
    align=True,
)

_LATENCY_DTYPE = np.dtype(
    [("req_ts", "i8"), ("exch_ts", "i8"), ("resp_ts", "i8"), ("_padding", "i8")],
    align=True,
)

_FILENAME_RE = re.compile(
    r"^(?P<symbol>[A-Z0-9]+)-(?P<kind>[A-Za-z]+)-(?P<date>\d{4}-\d{2}-\d{2})\.zip$"
)


@dataclass(frozen=True)
class BinanceBBOConversionResult:
    symbol: str
    bt_symbol: str
    date: str
    hft_npz_path: Path
    backtrader_ticks_path: Path
    backtrader_orderbook_path: Path
    base_event_count: int
    final_event_count: int
    book_rows: int
    trade_rows: int


@dataclass(frozen=True)
class BinanceBBOLatencyResult:
    latency_npz_path: Path
    row_count: int


@dataclass(frozen=True)
class _BookRow:
    exch_ms: int
    local_ms: int
    bid_price: float
    bid_qty: float
    ask_price: float
    ask_qty: float


def convert_binance_bbo_zip_pair(
    book_ticker_zip_path,
    trades_zip_path,
    output_directory,
    bt_symbol: Optional[str] = None,
    exchange: str = "binance",
    asset_type: str = "futures",
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    max_book_rows: Optional[int] = None,
    max_trade_rows: Optional[int] = None,
    tick_size: float = 0.01,
    lot_size: float = 0.001,
) -> BinanceBBOConversionResult:
    book_ticker_zip_path = Path(book_ticker_zip_path)
    trades_zip_path = Path(trades_zip_path)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)

    symbol, date = _extract_symbol_and_date(book_ticker_zip_path)
    trade_symbol, trade_date = _extract_symbol_and_date(trades_zip_path)
    if trade_symbol != symbol or trade_date != date:
        raise ValueError("bookTicker and trades zip files must have the same symbol and date")

    bt_symbol = bt_symbol or _default_bt_symbol(symbol)

    ticks_path = output_directory / f"tick_{symbol}_{date.replace('-', '')}.csv"
    orderbook_path = output_directory / f"orderbook_{symbol}_{date.replace('-', '')}.jsonl"
    hft_npz_path = output_directory / f"{symbol}_{date.replace('-', '')}.npz"

    depth_events = []
    trade_events = []
    book_rows = []
    latency_lookup_ts = []
    latency_lookup_ms = []

    with ticks_path.open("w", encoding="utf-8", newline="") as tick_file, orderbook_path.open(
        "w", encoding="utf-8"
    ) as orderbook_file:
        tick_writer = csv.DictWriter(
            tick_file,
            fieldnames=[
                "timestamp",
                "symbol",
                "exchange",
                "asset_type",
                "price",
                "volume",
                "direction",
                "trade_id",
                "bid_price",
                "ask_price",
                "bid_volume",
                "ask_volume",
            ],
        )
        tick_writer.writeheader()

        for row in _iter_book_ticker_rows(book_ticker_zip_path):
            exch_ms = row["transaction_time"]
            if not _in_window(exch_ms, start_ms, end_ms):
                continue
            local_ms = max(row["event_time"], exch_ms)
            book_row = _BookRow(
                exch_ms=exch_ms,
                local_ms=local_ms,
                bid_price=row["best_bid_price"],
                bid_qty=row["best_bid_qty"],
                ask_price=row["best_ask_price"],
                ask_qty=row["best_ask_qty"],
            )
            book_rows.append(book_row)
            latency_lookup_ts.append(exch_ms)
            latency_lookup_ms.append(local_ms - exch_ms)
            depth_events.append(
                (
                    DEPTH_BBO_EVENT | SELL_EVENT,
                    exch_ms * 1_000_000,
                    local_ms * 1_000_000,
                    book_row.ask_price,
                    book_row.ask_qty,
                    0,
                    0,
                    0.0,
                )
            )
            depth_events.append(
                (
                    DEPTH_BBO_EVENT | BUY_EVENT,
                    exch_ms * 1_000_000,
                    local_ms * 1_000_000,
                    book_row.bid_price,
                    book_row.bid_qty,
                    0,
                    0,
                    0.0,
                )
            )
            if max_book_rows is not None and len(book_rows) >= max_book_rows:
                break

        if not book_rows:
            raise ValueError("No bookTicker rows matched the selected window")

        book_rows.sort(key=lambda row: (row.local_ms, row.exch_ms))
        for book_row in book_rows:
            orderbook_file.write(
                json.dumps(
                    {
                        "timestamp": book_row.local_ms / 1000.0,
                        "symbol": bt_symbol,
                        "exchange": exchange,
                        "asset_type": asset_type,
                        "bids": [[book_row.bid_price, book_row.bid_qty]],
                        "asks": [[book_row.ask_price, book_row.ask_qty]],
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )

        book_event_times = [row.local_ms for row in book_rows]

        trade_rows = 0
        for row in _iter_trades_rows(trades_zip_path):
            exch_ms = row["time"]
            if not _in_window(exch_ms, start_ms, end_ms):
                continue
            latency_ms = _lookup_latency_ms(exch_ms, latency_lookup_ts, latency_lookup_ms)
            local_ms = exch_ms + latency_ms
            side = "sell" if row["is_buyer_maker"] else "buy"
            trade_flag = SELL_EVENT if side == "sell" else BUY_EVENT
            book_row = _lookup_book_row(local_ms, book_event_times, book_rows)
            tick_writer.writerow(
                {
                    "timestamp": f"{local_ms / 1000.0:.6f}",
                    "symbol": bt_symbol,
                    "exchange": exchange,
                    "asset_type": asset_type,
                    "price": _format_decimal(row["price"]),
                    "volume": _format_decimal(row["qty"]),
                    "direction": side,
                    "trade_id": row["id"],
                    "bid_price": _format_decimal(book_row.bid_price),
                    "ask_price": _format_decimal(book_row.ask_price),
                    "bid_volume": _format_decimal(book_row.bid_qty),
                    "ask_volume": _format_decimal(book_row.ask_qty),
                }
            )
            trade_events.append(
                (
                    TRADE_EVENT | trade_flag,
                    exch_ms * 1_000_000,
                    local_ms * 1_000_000,
                    row["price"],
                    row["qty"],
                    0,
                    0,
                    0.0,
                )
            )
            trade_rows += 1
            if max_trade_rows is not None and trade_rows >= max_trade_rows:
                break

    depth_array = np.array(depth_events, dtype=EVENT_DTYPE)
    trade_array = np.array(trade_events, dtype=EVENT_DTYPE)
    fused_depth_array = _fuse_depth_events(depth_array, tick_size=tick_size, lot_size=lot_size)
    base_array = np.empty(len(trade_array) + len(fused_depth_array), dtype=EVENT_DTYPE)
    if len(trade_array) > 0:
        base_array[: len(trade_array)] = trade_array
    if len(fused_depth_array) > 0:
        base_array[len(trade_array) :] = fused_depth_array
    base_array = _correct_local_timestamp(base_array)
    data = _correct_event_order(base_array)
    np.savez_compressed(hft_npz_path, data=data)

    return BinanceBBOConversionResult(
        symbol=symbol,
        bt_symbol=bt_symbol,
        date=date,
        hft_npz_path=hft_npz_path,
        backtrader_ticks_path=ticks_path,
        backtrader_orderbook_path=orderbook_path,
        base_event_count=len(base_array),
        final_event_count=len(data),
        book_rows=len(book_rows),
        trade_rows=trade_rows,
    )


def generate_latency_from_hft_events(
    hft_npz_path,
    output_path,
    mul_entry: float = 4.0,
    offset_entry_ns: int = 0,
    mul_resp: float = 3.0,
    offset_resp_ns: int = 0,
) -> BinanceBBOLatencyResult:
    hft_npz_path = Path(hft_npz_path)
    output_path = Path(output_path)
    data = np.load(hft_npz_path)["data"]
    mask = (data["ev"] & EXCH_EVENT == EXCH_EVENT) & (data["ev"] & LOCAL_EVENT == LOCAL_EVENT)
    rows = data[mask]
    if len(rows) == 0:
        raise ValueError("No dual-marked feed events available for latency generation")

    order_latency = np.zeros(
        len(rows),
        dtype=_LATENCY_DTYPE,
    )
    for index, row in enumerate(rows):
        feed_latency = max(int(row["local_ts"] - row["exch_ts"]), 0)
        entry_latency = int(feed_latency * mul_entry) + int(offset_entry_ns)
        resp_latency = int(feed_latency * mul_resp) + int(offset_resp_ns)
        req_ts = int(row["local_ts"])
        exch_ts = req_ts + entry_latency
        resp_ts = exch_ts + resp_latency
        order_latency[index] = (req_ts, exch_ts, resp_ts, 0)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, data=order_latency)
    return BinanceBBOLatencyResult(latency_npz_path=output_path, row_count=len(order_latency))


def _iter_book_ticker_rows(zip_path: Path) -> Iterator[dict]:
    for row in _iter_zip_csv_rows(zip_path):
        yield {
            "transaction_time": int(row["transaction_time"]),
            "event_time": int(row["event_time"]),
            "best_bid_price": float(row["best_bid_price"]),
            "best_bid_qty": float(row["best_bid_qty"]),
            "best_ask_price": float(row["best_ask_price"]),
            "best_ask_qty": float(row["best_ask_qty"]),
        }


def _iter_trades_rows(zip_path: Path) -> Iterator[dict]:
    for row in _iter_zip_csv_rows(zip_path):
        yield {
            "id": row["id"],
            "price": float(row["price"]),
            "qty": float(row["qty"]),
            "time": int(row["time"]),
            "is_buyer_maker": row["is_buyer_maker"].strip().lower() == "true",
        }


def _iter_zip_csv_rows(zip_path: Path) -> Iterable[dict]:
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"Expected exactly one CSV entry in {zip_path}")
        with archive.open(names[0], "r") as raw:
            text_stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            reader = csv.DictReader(text_stream)
            for row in reader:
                yield row


def _extract_symbol_and_date(zip_path: Path) -> tuple[str, str]:
    match = _FILENAME_RE.match(zip_path.name)
    if match is None:
        raise ValueError(f"Unsupported zip filename format: {zip_path.name}")
    return match.group("symbol"), match.group("date")


def _default_bt_symbol(symbol: str) -> str:
    for quote in ("USDT", "USDC", "BUSD", "FDUSD", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[:-len(quote)]}/{quote}"
    return symbol


def _in_window(timestamp_ms: int, start_ms: Optional[int], end_ms: Optional[int]) -> bool:
    if start_ms is not None and timestamp_ms < start_ms:
        return False
    if end_ms is not None and timestamp_ms > end_ms:
        return False
    return True


def _lookup_latency_ms(timestamp_ms: int, lookup_ts: list[int], lookup_latency: list[int]) -> int:
    if not lookup_ts:
        return 0
    index = bisect.bisect_right(lookup_ts, timestamp_ms) - 1
    if index < 0:
        return lookup_latency[0]
    return lookup_latency[index]


def _lookup_book_row(
    timestamp_ms: int, book_event_times: list[int], book_rows: list[_BookRow]
) -> _BookRow:
    index = bisect.bisect_right(book_event_times, timestamp_ms) - 1
    if index < 0:
        return book_rows[0]
    return book_rows[index]


def _format_decimal(value: float) -> str:
    return format(value, ".15g")


def _fuse_depth_events(depth_array: np.ndarray, tick_size: float, lot_size: float) -> np.ndarray:
    if len(depth_array) == 0:
        return depth_array
    if FuseMarketDepth is None:
        fused = depth_array.copy()
        fused["ev"] = (fused["ev"] & ~np.uint64(DEPTH_BBO_EVENT)) | np.uint64(DEPTH_EVENT)
        return fused

    fuse = FuseMarketDepth(float(tick_size), float(lot_size))
    try:
        for index in range(len(depth_array)):
            fuse.process_event(depth_array, index, True)
        return np.array(fuse.fused_events, dtype=EVENT_DTYPE, copy=True)
    finally:
        fuse.close()


def _correct_local_timestamp(base_array: np.ndarray, base_latency_ns: int = 0) -> np.ndarray:
    if len(base_array) == 0:
        return base_array
    min_latency = int(np.min(base_array["local_ts"] - base_array["exch_ts"]))
    if min_latency >= 0:
        return base_array
    corrected = base_array.copy()
    corrected["local_ts"] += -min_latency + int(base_latency_ns)
    return corrected


def _correct_event_order(base_array: np.ndarray) -> np.ndarray:
    sorted_exch_index = np.argsort(base_array["exch_ts"], kind="mergesort")
    sorted_local_index = np.argsort(base_array["local_ts"], kind="mergesort")
    output = np.zeros(len(base_array) * 2, dtype=EVENT_DTYPE)

    out_pos = 0
    exch_pos = 0
    local_pos = 0
    total = len(base_array)

    while exch_pos < total or local_pos < total:
        exch_row = base_array[sorted_exch_index[exch_pos]] if exch_pos < total else None
        local_row = base_array[sorted_local_index[local_pos]] if local_pos < total else None

        if exch_row is not None and local_row is not None:
            same_event = (
                exch_row["ev"] == local_row["ev"]
                and exch_row["exch_ts"] == local_row["exch_ts"]
                and exch_row["local_ts"] == local_row["local_ts"]
                and exch_row["px"] == local_row["px"]
                and exch_row["qty"] == local_row["qty"]
            )
            if same_event:
                output[out_pos] = exch_row
                output[out_pos]["ev"] = int(output[out_pos]["ev"]) | EXCH_EVENT | LOCAL_EVENT
                out_pos += 1
                exch_pos += 1
                local_pos += 1
                continue

            if exch_row["exch_ts"] < local_row["exch_ts"] or (
                exch_row["exch_ts"] == local_row["exch_ts"]
                and exch_row["local_ts"] < local_row["local_ts"]
            ):
                output[out_pos] = exch_row
                output[out_pos]["ev"] = int(output[out_pos]["ev"]) | EXCH_EVENT
                out_pos += 1
                exch_pos += 1
                continue

            output[out_pos] = local_row
            output[out_pos]["ev"] = int(output[out_pos]["ev"]) | LOCAL_EVENT
            out_pos += 1
            local_pos += 1
            continue

        if exch_row is not None:
            output[out_pos] = exch_row
            output[out_pos]["ev"] = int(output[out_pos]["ev"]) | EXCH_EVENT
            out_pos += 1
            exch_pos += 1
            continue

        output[out_pos] = local_row
        output[out_pos]["ev"] = int(output[out_pos]["ev"]) | LOCAL_EVENT
        out_pos += 1
        local_pos += 1

    return output[:out_pos]
