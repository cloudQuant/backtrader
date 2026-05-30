"""Funding rate data channel for perpetual contract funding rates.

Provides FundingRateChannel for loading, validating, and buffering
funding rate data from CSV/JSONL files or other sources.

Example:
    Loading funding rate data from CSV::

        channel = FundingRateChannel(
            symbol='BTC/USDT',
            dataname='data/btc_funding_20210101.csv'
        )
        for event in channel.load():
            print(event.rate, event.mark_price)
"""

import csv
import gzip
import json
import logging
import math
from typing import Iterator

from ..channel import DataChannel, DataValidationResult
from ..events import FundingEvent

logger = logging.getLogger(__name__)


class FundingRateChannel(DataChannel):
    """Funding rate data channel for perpetual contracts.

    Loads funding rate data from CSV or JSONL files. Validates funding
    rate ranges and mark price consistency.

    CSV format expects columns: timestamp, rate, mark_price
    Optional columns: next_funding_time, predicted_rate, symbol, exchange

    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        dataname: Path to the data file (CSV or JSONL).
        maxlen: Maximum buffer size.
        validate: Whether to validate incoming events.
        auto_fix: Whether to auto-fix invalid data.
        rate_threshold: Max absolute funding rate for anomaly warning.
        **kwargs: Additional parameters passed to DataChannel.
    """

    channel_type = "funding"

    def __init__(
        self,
        symbol,
        dataname=None,
        maxlen=10000,
        validate=True,
        auto_fix=True,
        rate_threshold=0.01,
        **kwargs,
    ):
        """Initialize the funding rate channel.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT').
            dataname: Optional data name for the feed.
            maxlen: Maximum number of events to buffer.
            validate: Whether to validate incoming events.
            auto_fix: Whether to attempt auto-fixing invalid data.
            rate_threshold: Maximum allowed rate difference threshold.
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
        self._rate_threshold = rate_threshold
        self._last_rate = None

    def _validate_event(self, event) -> DataValidationResult:
        """Validate funding rate specific fields beyond base validation.

        Additional checks:
            - Rate change anomaly detection
        """
        result = super()._validate_event(event)
        if not result.valid:
            return result

        # Rate anomaly detection
        if self._last_rate is not None and abs(event.rate) > self._rate_threshold:
            result.warnings.append(
                f"High funding rate: {event.rate} (threshold: {self._rate_threshold})"
            )

        self._last_rate = event.rate
        return result

    def load(self) -> Iterator[FundingEvent]:
        """Load funding rate events from file.

        Supports CSV and JSONL formats.

        Yields:
            FundingEvent instances.
        """
        if self._dataname is None:
            raise ValueError("dataname (file path) is required for loading")

        if self._dataname.endswith(".jsonl") or self._dataname.endswith(".jsonl.gz"):
            yield from self._load_jsonl()
        else:
            yield from self._load_csv()

    def _load_csv(self) -> Iterator[FundingEvent]:
        """Load funding rate events from CSV format.

        Supports both plain CSV and gzip-compressed CSV (.csv.gz).
        Expects columns: timestamp, rate, mark_price. Optional columns:
        next_funding_time, predicted_rate, symbol, exchange.

        Yields:
            FundingEvent instances.
        """
        open_func = gzip.open if self._dataname.endswith(".gz") else open
        open_kwargs = (
            {"mode": "rt", "encoding": "utf-8"}
            if self._dataname.endswith(".gz")
            else {"mode": "r", "encoding": "utf-8", "newline": ""}
        )

        with open_func(self._dataname, **open_kwargs) as f:
            reader = csv.DictReader(f)

            required = {"timestamp", "rate", "mark_price"}
            if reader.fieldnames:
                missing = required - set(reader.fieldnames)
                if missing:
                    raise ValueError(
                        f"Missing required columns: {missing}. Found: {reader.fieldnames}"
                    )

            for row in reader:
                try:
                    fe = FundingEvent(
                        timestamp=_parse_required_float(row["timestamp"]),
                        symbol=row.get("symbol", self.symbol),
                        exchange=row.get("exchange", ""),
                        asset_type=row.get("asset_type", "swap"),
                        rate=_parse_required_float(row["rate"]),
                        mark_price=_parse_required_float(row["mark_price"]),
                        next_funding_time=_parse_optional_float(row.get("next_funding_time"))
                        or 0.0,
                        predicted_rate=_parse_optional_float(row.get("predicted_rate")) or 0.0,
                    )
                    yield fe
                except (ValueError, KeyError) as e:
                    logger.warning("Skipping invalid funding row: %s (error: %s)", row, e)
                    continue

    def _load_jsonl(self) -> Iterator[FundingEvent]:
        """Load funding rate events from JSONL format.

        Supports both plain JSONL and gzip-compressed JSONL (.jsonl.gz).
        Each line should contain a JSON object with timestamp, rate,
        mark_price, and optional fields.

        Yields:
            FundingEvent instances.
        """
        open_func = gzip.open if self._dataname.endswith(".gz") else open
        open_kwargs = {"mode": "rt", "encoding": "utf-8"}

        with open_func(self._dataname, **open_kwargs) as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    fe = FundingEvent(
                        timestamp=_parse_required_float(data["timestamp"]),
                        symbol=data.get("symbol", self.symbol),
                        exchange=data.get("exchange", ""),
                        asset_type=data.get("asset_type", "swap"),
                        rate=_parse_required_float(data["rate"]),
                        mark_price=_parse_required_float(data["mark_price"]),
                        next_funding_time=_parse_optional_float(data.get("next_funding_time"))
                        or 0.0,
                        predicted_rate=_parse_optional_float(data.get("predicted_rate")) or 0.0,
                    )
                    yield fe
                except (ValueError, KeyError, json.JSONDecodeError) as e:
                    logger.warning("Skipping invalid funding JSONL line %d: %s", line_num, e)
                    continue

    def __repr__(self):
        """Return a string representation of the channel.

        Returns:
            str: Representation showing symbol, dataname, and buffer stats.
        """
        return (
            f"FundingRateChannel(symbol={self.symbol!r}, "
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
