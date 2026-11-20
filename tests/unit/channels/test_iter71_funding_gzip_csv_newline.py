"""Gzip funding CSV preserves newlines inside quoted fields."""

import csv
import gzip
import io

import pytest

from backtrader.channels.funding import FundingRateChannel


@pytest.mark.parametrize("embedded_newline", ["\n", "\r\n", "\r"])
def test_gzip_csv_roundtrip_preserves_quoted_embedded_newlines(
    tmp_path, embedded_newline
):
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\r\n")
    writer.writerow(["timestamp", "rate", "mark_price", "exchange"])
    writer.writerow(["1700000000", "0.001", "100", f"desk{embedded_newline}floor"])
    csv_text = csv_buffer.getvalue()

    plain_path = tmp_path / "funding.csv"
    with plain_path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(csv_text)

    gzip_path = tmp_path / "funding.csv.gz"
    with gzip.open(gzip_path, "wt", encoding="utf-8", newline="") as stream:
        stream.write(csv_text)

    plain_event = next(FundingRateChannel("BTC/USDT", str(plain_path)).load())
    gzip_event = next(FundingRateChannel("BTC/USDT", str(gzip_path)).load())

    assert plain_event.exchange == f"desk{embedded_newline}floor"
    assert gzip_event.exchange == plain_event.exchange
    assert (gzip_event.timestamp, gzip_event.rate, gzip_event.mark_price) == (
        plain_event.timestamp,
        plain_event.rate,
        plain_event.mark_price,
    )
