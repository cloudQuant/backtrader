import csv
import io
import json
import zipfile
from pathlib import Path

import numpy as np

from backtrader.brokers.hft import convert_binance_bbo_zip_pair, generate_latency_from_hft_events
from backtrader.channels.orderbook import OrderBookChannel
from backtrader.channels.tick import TickChannel


def _write_zip_csv(path: Path, member_name: str, rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, buffer.getvalue())


def test_convert_binance_bbo_zip_pair_writes_hft_and_backtrader_outputs(tmp_path):
    book_zip = tmp_path / "ETHUSDT-bookTicker-2024-01-01.zip"
    trades_zip = tmp_path / "ETHUSDT-trades-2024-01-01.zip"

    _write_zip_csv(
        book_zip,
        "ETHUSDT-bookTicker-2024-01-01.csv",
        [
            {
                "update_id": "1",
                "best_bid_price": "2283.84",
                "best_bid_qty": "40.95",
                "best_ask_price": "2283.85",
                "best_ask_qty": "18.61",
                "transaction_time": "1704067200012",
                "event_time": "1704067200019",
            },
            {
                "update_id": "2",
                "best_bid_price": "2283.80",
                "best_bid_qty": "41.00",
                "best_ask_price": "2283.90",
                "best_ask_qty": "18.50",
                "transaction_time": "1704067201012",
                "event_time": "1704067201018",
            },
        ],
    )
    _write_zip_csv(
        trades_zip,
        "ETHUSDT-trades-2024-01-01.csv",
        [
            {
                "id": "3478498074",
                "price": "2283.84",
                "qty": "0.022",
                "quote_qty": "50.24448",
                "time": "1704067200312",
                "is_buyer_maker": "true",
            },
            {
                "id": "3478498075",
                "price": "2283.90",
                "qty": "0.100",
                "quote_qty": "228.39",
                "time": "1704067201312",
                "is_buyer_maker": "false",
            },
        ],
    )

    result = convert_binance_bbo_zip_pair(book_zip, trades_zip, tmp_path)

    assert result.symbol == "ETHUSDT"
    assert result.bt_symbol == "ETH/USDT"
    assert result.book_rows == 2
    assert result.trade_rows == 2
    assert result.hft_npz_path.exists()
    assert result.backtrader_ticks_path.exists()
    assert result.backtrader_orderbook_path.exists()

    npz = np.load(result.hft_npz_path)["data"]
    assert len(npz) >= 6
    assert np.any((npz["ev"] & (1 << 31)) == (1 << 31))
    assert np.any((npz["ev"] & (1 << 30)) == (1 << 30))

    ticks = list(TickChannel(symbol="ETH/USDT", dataname=str(result.backtrader_ticks_path)).load())
    books = list(OrderBookChannel(symbol="ETH/USDT", dataname=str(result.backtrader_orderbook_path), depth=1).load())

    assert len(ticks) == 2
    assert ticks[0].direction == "sell"
    assert ticks[1].direction == "buy"
    assert len(books) == 2
    assert books[0].best_bid == 2283.84
    assert books[0].best_ask == 2283.85

    latency_result = generate_latency_from_hft_events(result.hft_npz_path, tmp_path / "latency_20240101.npz")
    assert latency_result.row_count > 0
    assert latency_result.latency_npz_path.exists()
    latency = np.load(latency_result.latency_npz_path)["data"]
    assert np.all(latency["req_ts"] <= latency["exch_ts"])
    assert np.all(latency["exch_ts"] <= latency["resp_ts"])

    with result.backtrader_orderbook_path.open("r", encoding="utf-8") as handle:
        first_line = json.loads(handle.readline())
    assert first_line["symbol"] == "ETH/USDT"
    assert first_line["bids"][0] == [2283.84, 40.95]
