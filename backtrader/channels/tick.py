"""Tick data channel for trade-level market data.

Provides TickChannel for loading, validating, and buffering tick/trade data
from CSV files or other sources.

Example:
    Loading tick data from CSV::

        channel = TickChannel(
            symbol='BTC/USDT',
            dataname='data/btc_ticks_20210101.csv'
        )
        for event in channel.load():
            print(event.price, event.volume)
"""

import csv
import gzip
import logging
import math
from typing import Iterator

from ..channel import DataChannel, DataValidationResult
from ..events import TickEvent

logger = logging.getLogger(__name__)


class TickChannel(DataChannel):
    """Tick/trade data channel.

    Loads tick data from CSV files (plain or gzip-compressed) and provides
    validated, buffered access to tick events.

    Expected CSV columns: timestamp, price, volume, direction
    Optional columns: trade_id, symbol, exchange, asset_type,
                      bid_price, ask_price, bid_volume, ask_volume

    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        dataname: Path to the CSV data file.
        maxlen: Maximum buffer size.
        validate: Whether to validate incoming events.
        auto_fix: Whether to auto-fix invalid data.
        price_change_threshold: Max allowed price change ratio for anomaly detection.
        **kwargs: Additional parameters passed to DataChannel.
    """

    channel_type = "tick"

    def __init__(
        self,
        symbol,
        dataname=None,
        maxlen=10000,
        validate=True,
        auto_fix=True,
        price_change_threshold=0.1,
        **kwargs,
    ):
        """Initialize the tick data channel.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT').
            dataname: Optional data name for the feed.
            maxlen: Maximum number of events to buffer.
            validate: Whether to validate incoming events.
            auto_fix: Whether to attempt auto-fixing invalid data.
            price_change_threshold: Maximum allowed price change (percentage).
            **kwargs: Additional arguments passed to parent.
        """
        super().__init__(
            symbol=symbol,
            maxlen=maxlen,
            validate=validate,
            auto_fix=auto_fix,
            dataname=dataname,
            **kwargs,
        )
        self._dataname = dataname
        self._price_change_threshold = price_change_threshold
        self._last_price = None

    def _validate_event(self, event) -> DataValidationResult:
        """Validate tick-specific fields beyond base validation.

        Additional checks:
            - Price change within threshold (anomaly detection)
            - Direction is valid
            - Price and volume are positive
        """
        result = super()._validate_event(event)
        if not result.valid:
            return result

        # Price anomaly detection
        if self._last_price is not None and self._last_price > 0:
            change_ratio = abs(event.price - self._last_price) / self._last_price
            if change_ratio > self._price_change_threshold:
                result.warnings.append(
                    f"Large price change: {self._last_price} -> {event.price} ({change_ratio:.2%})"
                )

        self._last_price = event.price
        return result

    def load(self) -> Iterator[TickEvent]:
        """Load tick events from CSV file.

        Supports both plain CSV and gzip-compressed CSV (.csv.gz).
        The file must have at minimum: timestamp, price, volume, direction.

        Yields:
            TickEvent instances.

        Raises:
            FileNotFoundError: If dataname file does not exist.
            ValueError: If required columns are missing.
        """
        if self._dataname is None:
            raise ValueError("dataname (file path) is required for loading")

        open_func = gzip.open if self._dataname.endswith(".gz") else open
        open_kwargs = (
            {"mode": "rt", "encoding": "utf-8"}
            if self._dataname.endswith(".gz")
            else {"mode": "r", "encoding": "utf-8", "newline": ""}
        )

        with open_func(self._dataname, **open_kwargs) as f:
            reader = csv.DictReader(f)

            # Validate required columns
            required = {"timestamp", "price", "volume", "direction"}
            if reader.fieldnames:
                missing = required - set(reader.fieldnames)
                if missing:
                    raise ValueError(
                        f"Missing required columns: {missing}. Found: {reader.fieldnames}"
                    )

            for row in reader:
                try:
                    tick = TickEvent(
                        timestamp=_parse_required_float(row["timestamp"]),
                        symbol=row.get("symbol", self.symbol),
                        exchange=row.get("exchange", ""),
                        asset_type=row.get("asset_type", "spot"),
                        price=_parse_required_float(row["price"]),
                        volume=_parse_required_float(row["volume"]),
                        direction=row["direction"].strip().lower(),
                        trade_id=row.get("trade_id", ""),
                        bid_price=_parse_optional_float(row.get("bid_price")),
                        ask_price=_parse_optional_float(row.get("ask_price")),
                        bid_volume=_parse_optional_float(row.get("bid_volume")),
                        ask_volume=_parse_optional_float(row.get("ask_volume")),
                    )
                    yield tick
                except (ValueError, KeyError) as e:
                    logger.warning("Skipping invalid tick row: %s (error: %s)", row, e)
                    continue

    def __repr__(self):
        """Return a string representation of the channel.

        Returns:
            str: Representation showing symbol and buffer stats.
        """
        return (
            f"TickChannel(symbol={self.symbol!r}, "
            f"dataname={self._dataname!r}, "
            f"events={self._event_count}, "
            f"buffered={len(self._buffer)})"
        )


def _parse_optional_float(value) -> float:
    """Parse an optional float value, returning None for empty/missing.

    Args:
        value: The value to parse as a float. Can be None, empty string,
            or any value that can be converted to float.

    Returns:
        The float value if parsing succeeds, None otherwise.
    """
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _parse_required_float(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite float value: {value}")
    return number
