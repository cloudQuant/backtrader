"""Incomplete tick rows must not prevent later valid rows from loading."""

import csv

import pytest

from backtrader.channels.tick import TickChannel


@pytest.mark.parametrize("missing", ["timestamp", "price", "volume", "direction"])
def test_missing_required_cell_skips_row_and_loads_next(tmp_path, missing):
    fields = [name for name in ("timestamp", "price", "volume", "direction") if name != missing]
    fields.append(missing)
    row = {"timestamp": "1", "price": "100", "volume": "2", "direction": "buy"}
    path = tmp_path / "ticks.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerow([row[field] for field in fields[:-1]])
        row["timestamp"] = "2"
        writer.writerow([row[field] for field in fields])

    ticks = list(TickChannel(symbol="TEST", dataname=str(path)).load())
    assert len(ticks) == 1
    assert ticks[0].timestamp == 2
    assert ticks[0].price == 100
    assert ticks[0].direction == "buy"


def test_missing_optional_cell_does_not_discard_tick(tmp_path):
    path = tmp_path / "ticks.csv"
    path.write_text(
        "timestamp,price,volume,direction,bid_price\n1,100,2,buy\n", encoding="utf-8"
    )

    ticks = list(TickChannel(symbol="TEST", dataname=str(path)).load())
    assert len(ticks) == 1
    assert ticks[0].bid_price is None
