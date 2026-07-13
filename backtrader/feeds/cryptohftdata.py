#!/usr/bin/env python
"""Historical cryptocurrency data feed backed by CryptoHFTData."""

import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterator

import pandas as pd

from ..dataseries import TimeFrame
from ..feed import DataBase
from ..utils import date2num

__all__ = ["CryptoHFTData"]


_TIMEFRAME_RULES = {
    TimeFrame.Seconds: "s",
    TimeFrame.Minutes: "min",
    TimeFrame.Days: "D",
}


class CryptoHFTData(DataBase):
    """Load historical exchange trades from CryptoHFTData.

    Tick requests emit one OHLCV-shaped backtrader bar per trade. Second,
    minute, and daily requests aggregate the same trades into UTC-aligned
    bars. Use ``TimeFrame.Minutes`` with ``compression=60`` for hourly bars.

    ``fromdate`` and ``todate`` are required to avoid accidental unbounded
    high-frequency downloads. Naive datetimes are interpreted as UTC.
    """

    params = (
        ("exchange", None),
        ("api_key", None),
        ("client", None),
        ("timeframe", TimeFrame.Minutes),
        ("compression", 1),
    )

    def __init__(self):
        """Initialize an empty historical row iterator."""
        super().__init__()
        self._rows: Iterator[Dict[str, Any]] = iter(())

    def start(self):
        """Download the requested trades and prepare chronological bars."""
        super().start()
        if not self.p.dataname:
            raise ValueError("CryptoHFTData requires dataname to be a symbol such as BTCUSDT")
        if not self.p.exchange:
            raise ValueError("CryptoHFTData requires an exchange such as binance_futures")
        if self.p.fromdate is None or self.p.todate is None:
            raise ValueError("CryptoHFTData requires both fromdate and todate")
        if self.p.compression < 1:
            raise ValueError("CryptoHFTData compression must be at least 1")

        start = _as_utc(self.p.fromdate)
        end = _as_utc(self.p.todate)
        if end < start:
            raise ValueError("CryptoHFTData todate must not precede fromdate")

        client = self.p.client or self._create_client()
        trades = client.get_trades(
            symbol=str(self.p.dataname).upper(),
            exchange=self.p.exchange,
            start_date=start.date().isoformat(),
            end_date=end.date().isoformat(),
        )
        self._rows = iter(self._prepare_rows(trades, start, end))

    def _create_client(self):
        """Create the optional CryptoHFTData SDK client lazily."""
        try:
            from cryptohftdata import CryptoHFTDataClient
        except ImportError as exc:
            raise ImportError(
                "CryptoHFTData feed requires the optional dependency; "
                "install backtrader[cryptohftdata]"
            ) from exc

        api_key = self.p.api_key or os.getenv("CRYPTOHFTDATA_API_KEY") or None
        return CryptoHFTDataClient(api_key=api_key)

    def _prepare_rows(self, trades, start: datetime, end: datetime):
        """Normalize SDK trades and optionally aggregate them into bars."""
        required = {"trade_time", "trade_id", "price", "quantity"}
        missing = required.difference(trades.columns)
        if missing:
            raise ValueError(
                "CryptoHFTData response is missing required columns: " + ", ".join(sorted(missing))
            )
        if trades.empty:
            return []

        frame = trades.copy()
        frame["datetime"] = pd.to_datetime(frame["trade_time"], unit="ms", utc=True)
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        frame["quantity"] = pd.to_numeric(frame["quantity"], errors="coerce")
        frame = frame.dropna(subset=["datetime", "price", "quantity"])
        frame = frame.loc[
            (frame["datetime"] >= pd.Timestamp(start)) & (frame["datetime"] <= pd.Timestamp(end))
        ]
        frame = frame.sort_values(["trade_time", "trade_id"], kind="stable")

        if self.p.timeframe == TimeFrame.Ticks:
            frame = frame.assign(
                open=frame["price"],
                high=frame["price"],
                low=frame["price"],
                close=frame["price"],
                volume=frame["quantity"],
            )
            return frame[["datetime", "open", "high", "low", "close", "volume"]].to_dict("records")

        suffix = _TIMEFRAME_RULES.get(self.p.timeframe)
        if suffix is None:
            name = TimeFrame.getname(self.p.timeframe, self.p.compression)
            raise ValueError(f"CryptoHFTData does not support the {name} timeframe")
        rule = f"{self.p.compression}{suffix}"
        bars = (
            frame.set_index("datetime")
            .resample(rule, label="left", closed="left")
            .agg(
                open=("price", "first"),
                high=("price", "max"),
                low=("price", "min"),
                close=("price", "last"),
                volume=("quantity", "sum"),
            )
            .dropna(subset=["open"])
            .reset_index()
        )
        return bars.to_dict("records")

    def _load(self):
        """Emit the next normalized trade or bar."""
        try:
            row = next(self._rows)
        except StopIteration:
            return False

        timestamp = row["datetime"].to_pydatetime().astimezone(timezone.utc).replace(tzinfo=None)
        self.lines.datetime[0] = date2num(timestamp)
        self.lines.open[0] = float(row["open"])
        self.lines.high[0] = float(row["high"])
        self.lines.low[0] = float(row["low"])
        self.lines.close[0] = float(row["close"])
        self.lines.volume[0] = float(row["volume"])
        self.lines.openinterest[0] = 0.0
        return True


def _as_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime, interpreting naive values as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
