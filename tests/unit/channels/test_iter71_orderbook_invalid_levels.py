"""Invalid order book levels should not abort loading subsequent rows."""

import csv
import json

import pytest

from backtrader.channels.orderbook import OrderBookChannel


@pytest.mark.parametrize("side", ["bids", "asks"])
@pytest.mark.parametrize("file_format", ["jsonl", "csv"])
@pytest.mark.parametrize("bad_levels", [None, [None], [[None, 1]], {"bad": 1}])
def test_invalid_levels_are_skipped_before_next_valid_snapshot(
    tmp_path, side, file_format, bad_levels
):
    path = tmp_path / f"book.{file_format}"
    bad = {"timestamp": 1, "bids": [[100, 1]], "asks": [[101, 2]]}
    bad[side] = bad_levels
    good = {"timestamp": 2, "bids": [[100, 1]], "asks": [[101, 2]]}
    if file_format == "jsonl":
        path.write_text(json.dumps(bad) + "\n" + json.dumps(good) + "\n", encoding="utf-8")
    else:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["timestamp", "bids", "asks"])
            writer.writeheader()
            for row in (bad, good):
                writer.writerow(
                    {**row, "bids": json.dumps(row["bids"]), "asks": json.dumps(row["asks"])}
                )

    snapshots = list(OrderBookChannel(symbol="TEST", dataname=str(path)).load())
    assert len(snapshots) == 1
    assert snapshots[0].timestamp == 2
    assert snapshots[0].bids == [(100.0, 1.0)]
