import csv
import hashlib
import json
import math
from datetime import datetime

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from scripts.aggregate_stock_minute_parquet import AggregationError, aggregate


INPUT_SCHEMA = pa.schema(
    [
        pa.field("trade_time", pa.timestamp("ms")),
        pa.field("symbol", pa.string()),
        pa.field("open", pa.float64()),
        pa.field("high", pa.float64()),
        pa.field("low", pa.float64()),
        pa.field("close", pa.float64()),
        pa.field("vol", pa.float64()),
        pa.field("amount", pa.float64()),
    ],
    metadata={
        b"aiquant.source.bar_time_semantics": b"KLINE_END_TIME",
        b"aiquant.source.volume_unit": b"SOURCE_NATIVE",
    },
)


def _row(timestamp, symbol, open_, high, low, close, vol, amount):
    return {
        "trade_time": datetime.fromisoformat(timestamp),
        "symbol": symbol,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": vol,
        "amount": amount,
    }


def _write_source(path, rows, row_group_size=2, schema=INPUT_SCHEMA):
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, row_group_size=row_group_size)


def _read_stock_csv(output, manifest, symbol):
    item = next(item for item in manifest["output"]["symbols"] if item["symbol"] == symbol)
    with (output / item["file"]).open(encoding="utf-8", newline="") as source_csv:
        rows = list(csv.DictReader(source_csv))
    return item, rows


def test_aggregates_sorted_rows_across_row_groups_and_records_observed_calendar(tmp_path):
    source = tmp_path / "minutes.parquet"
    output = tmp_path / "daily"
    rows = [
        _row("2025-01-02 09:30:00", "600000.SH", 10, 11, 9, 10.5, 2, 20),
        _row("2025-01-02 09:30:00", "600001.SH", 20, 21, 19, 20.5, 3, 60),
        _row("2025-01-02 09:31:00", "600000.SH", 10.5, 12, 10, 11, 4, 44),
        _row("2025-01-03 09:30:00", "600000.SH", 11, 11.5, 10.5, 11.2, 6, 67.2),
    ]
    _write_source(source, rows, row_group_size=1)

    manifest = aggregate(source, output, batch_size=1)

    manifest_path = output / "_metadata" / "manifest.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == manifest
    first_file, daily = _read_stock_csv(output, manifest, "600000.SH")
    assert first_file["file"] == "sh600000.csv"
    assert [(row["trade_date"], row["symbol"]) for row in daily] == [
        ("2025-01-02", "600000.SH"),
        ("2025-01-03", "600000.SH"),
    ]
    first = daily[0]
    assert tuple(float(first[name]) for name in ("open", "high", "low", "close")) == (10, 12, 9, 11)
    assert float(first["volume"]) == 6
    assert float(first["amount"]) == 64
    assert first["first_trade_time"] == "2025-01-02 09:30:00.000"
    assert first["last_trade_time"] == "2025-01-02 09:31:00.000"
    assert first["trade_time"] == "2025-01-02 09:31:00.000"
    assert first["minute_count"] == "2"
    assert first["missing_or_invalid_count"] == "0"
    assert first["invalid_day"] == "False"

    second_file, second_symbol = _read_stock_csv(output, manifest, "600001.SH")
    assert second_file["file"] == "sh600001.csv"
    assert second_symbol[0]["last_trade_time"] == "2025-01-02 09:30:00.000"
    assert second_symbol[0]["trade_time"] == "2025-01-02 09:31:00.000"
    assert first_file["rows"] == 2
    assert first_file["bytes"] == (output / first_file["file"]).stat().st_size
    assert (
        first_file["sha256"]
        == hashlib.sha256((output / first_file["file"]).read_bytes()).hexdigest()
    )

    with (output / "_metadata" / "observed_calendar.csv").open(
        encoding="utf-8", newline=""
    ) as source_calendar:
        calendar = list(csv.DictReader(source_calendar))
    assert [row["trade_date"] for row in calendar] == ["2025-01-02", "2025-01-03"]
    assert calendar[0]["minute_count"] == "3"
    assert calendar[0]["symbol_count"] == "2"
    assert calendar[0]["first_trade_time"] == "2025-01-02 09:30:00.000"
    assert calendar[0]["last_trade_time"] == "2025-01-02 09:31:00.000"
    assert calendar[1]["minute_count"] == "1"

    assert manifest["source"]["rows"] == 4
    assert manifest["source"]["row_groups"] == 4
    assert manifest["source"]["sha256"]
    assert manifest["source"]["stat_unchanged"] is True
    assert manifest["output"]["daily_rows"] == 3
    assert manifest["output"]["date_range"] == {"first": "2025-01-02", "last": "2025-01-03"}
    assert [item["symbol"] for item in manifest["output"]["symbols"]] == [
        "600000.SH",
        "600001.SH",
    ]
    assert manifest["output"]["observed_dates"] == 2
    assert manifest["output"]["csv_file_count"] == 2
    assert not (output / "daily.parquet").exists()
    metadata = {
        item.get("key_utf8"): item.get("value_utf8")
        for item in manifest["source_schema"]["metadata_raw"]
    }
    assert metadata["aiquant.source.bar_time_semantics"] == "KLINE_END_TIME"


def test_duplicate_timestamp_symbol_is_rejected_across_row_groups(tmp_path):
    source = tmp_path / "duplicate.parquet"
    output = tmp_path / "daily"
    duplicate = _row("2025-01-02 09:30:00", "600000.SH", 10, 11, 9, 10, 1, 10)
    _write_source(source, [duplicate, duplicate], row_group_size=1)

    with pytest.raises(AggregationError, match="duplicate \(trade_time, symbol\)"):
        aggregate(source, output, batch_size=1)

    assert not output.exists()
    assert not list(tmp_path.glob(".daily.tmp-*"))


def test_unsorted_source_is_rejected(tmp_path):
    source = tmp_path / "unsorted.parquet"
    output = tmp_path / "daily"
    rows = [
        _row("2025-01-02 09:31:00", "600000.SH", 10, 11, 9, 10, 1, 10),
        _row("2025-01-02 09:30:00", "600000.SH", 10, 11, 9, 10, 1, 10),
    ]
    _write_source(source, rows, row_group_size=2)

    with pytest.raises(AggregationError, match="not ordered by \(trade_time, symbol\)"):
        aggregate(source, output, batch_size=2)

    assert not output.exists()
    assert not list(tmp_path.glob(".daily.tmp-*"))


@pytest.mark.parametrize("missing", ["trade_time", "symbol"])
def test_null_time_or_symbol_is_rejected(tmp_path, missing):
    source = tmp_path / "null-key.parquet"
    output = tmp_path / "daily"
    row = _row("2025-01-02 09:30:00", "600000.SH", 10, 11, 9, 10, 1, 10)
    row[missing] = None
    _write_source(source, [row])

    with pytest.raises(AggregationError, match="null or empty symbol|null trade_time"):
        aggregate(source, output, batch_size=1)

    assert not output.exists()
    assert not list(tmp_path.glob(".daily.tmp-*"))


def test_invalid_first_open_and_negative_volume_mark_daily_row_invalid(tmp_path):
    source = tmp_path / "invalid.parquet"
    output = tmp_path / "daily"
    rows = [
        _row("2025-01-02 09:30:00", "600000.SH", math.nan, 11, 9, 10, 1, 2),
        _row("2025-01-02 09:31:00", "600000.SH", 10, 12, 9.5, 11, -1, 3),
    ]
    _write_source(source, rows, row_group_size=1)

    manifest = aggregate(source, output, batch_size=1)

    _, rows = _read_stock_csv(output, manifest, "600000.SH")
    row = rows[0]
    assert row["open"] == ""
    assert row["high"] == ""
    assert row["low"] == ""
    assert row["close"] == ""
    assert row["volume"] == ""
    assert float(row["amount"]) == 5
    assert row["minute_count"] == "2"
    assert row["missing_or_invalid_count"] == "2"
    assert row["invalid_day"] == "True"
    assert manifest["aggregation"]["invalid_rows_by_category"] == {
        "negative_volume": 1,
        "non_finite_price": 1,
    }


def test_missing_required_column_fails_before_creating_output(tmp_path):
    source = tmp_path / "missing-column.parquet"
    output = tmp_path / "daily"
    schema = pa.schema([field for field in INPUT_SCHEMA if field.name != "amount"])
    row = _row("2025-01-02 09:30:00", "600000.SH", 10, 11, 9, 10, 1, 10)
    _write_source(source, [row], schema=schema)

    with pytest.raises(AggregationError, match="missing required columns: amount"):
        aggregate(source, output)

    assert not output.exists()
    assert not list(tmp_path.glob(".daily.tmp-*"))


def test_exchange_prefix_symbol_filename_is_lowercase(tmp_path):
    source = tmp_path / "minutes.parquet"
    output = tmp_path / "daily"
    row = _row("2025-01-02 09:30:00", "SH600000", 10, 11, 9, 10, 1, 10)
    _write_source(source, [row])

    manifest = aggregate(source, output, batch_size=1)

    assert manifest["output"]["symbols"][0]["file"] == "sh600000.csv"
    assert (output / "sh600000.csv").is_file()


def test_existing_output_directory_is_never_overwritten(tmp_path):
    source = tmp_path / "minutes.parquet"
    output = tmp_path / "daily"
    _write_source(
        source,
        [_row("2025-01-02 09:30:00", "600000.SH", 10, 11, 9, 10, 1, 10)],
    )
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(AggregationError, match="output already exists"):
        aggregate(source, output)

    assert sentinel.read_text(encoding="utf-8") == "preserve"
