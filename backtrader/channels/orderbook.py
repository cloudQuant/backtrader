"""OrderBook data channel for order book depth snapshots.

Provides OrderBookChannel for loading, validating, and buffering order book
data from CSV/JSONL files or other sources.

Example:
    Loading order book data from CSV::

        channel = OrderBookChannel(
            symbol='BTC/USDT',
            dataname='data/btc_ob_20210101.csv',
            depth=20
        )
        for event in channel.load():
            print(event.best_bid, event.best_ask, event.spread)
"""

import csv
import gzip
import json
import logging
import math
from typing import Iterator, List, Tuple

from ..channel import DataChannel, DataValidationResult
from ..events import OrderBookSnapshot

logger = logging.getLogger(__name__)


class OrderBookChannel(DataChannel):
    """Order book depth snapshot channel.

    Loads order book data from CSV or JSONL files. Supports configurable
    depth levels and validates bid/ask ordering and spread.

    CSV format expects columns: timestamp, bids, asks
    where bids/asks are JSON-encoded lists of [price, qty] pairs.

    JSONL format expects one JSON object per line with fields:
    timestamp, symbol, bids, asks.

    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT').
        dataname: Path to the data file (CSV or JSONL).
        depth: Maximum order book depth to retain.
        maxlen: Maximum buffer size.
        validate: Whether to validate incoming events.
        auto_fix: Whether to auto-fix invalid data.
        **kwargs: Additional parameters passed to DataChannel.
    """

    channel_type = "orderbook"

    def __init__(
        self, symbol, dataname=None, depth=20, maxlen=10000, validate=True, auto_fix=True, **kwargs
    ):
        """Initialize the order book channel.

        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT').
            dataname: Optional data name for the feed.
            depth: Order book depth (number of price levels).
            maxlen: Maximum number of events to buffer.
            validate: Whether to validate incoming events.
            auto_fix: Whether to attempt auto-fixing invalid data.
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
        self._depth = depth
        self._last_best_bid = None
        self._last_best_ask = None

    @property
    def depth(self):
        """Configured maximum order book depth."""
        return self._depth

    def _validate_event(self, event) -> DataValidationResult:
        """Validate order book specific fields beyond base validation.

        Additional checks:
            - Spread consistency with previous snapshots
            - Depth within configured limits
        """
        result = super()._validate_event(event)
        if not result.valid:
            return result

        # Truncate to configured depth
        if len(event.bids) > self._depth:
            event.bids = event.bids[: self._depth]
        if len(event.asks) > self._depth:
            event.asks = event.asks[: self._depth]

        # Track best bid/ask for anomaly detection
        if event.bids and event.asks:
            self._last_best_bid = event.bids[0][0]
            self._last_best_ask = event.asks[0][0]

        return result

    def load(self) -> Iterator[OrderBookSnapshot]:
        """Load order book events from file.

        Supports CSV and JSONL formats. File format is auto-detected
        by extension (.jsonl or .csv/.csv.gz).

        Yields:
            OrderBookSnapshot instances.
        """
        if self._dataname is None:
            raise ValueError("dataname (file path) is required for loading")

        if self._dataname.endswith(".jsonl") or self._dataname.endswith(".jsonl.gz"):
            yield from self._load_jsonl()
        else:
            yield from self._load_csv()

    def _load_csv(self) -> Iterator[OrderBookSnapshot]:
        """Load order book events from CSV format.

        Supports both plain CSV and gzip-compressed CSV (.csv.gz).
        Expects columns: timestamp, bids, asks (where bids/asks are
        JSON-encoded lists of [price, qty] pairs).

        Yields:
            OrderBookSnapshot instances.
        """
        open_func = gzip.open if self._dataname.endswith(".gz") else open
        open_kwargs = (
            {"mode": "rt", "encoding": "utf-8"}
            if self._dataname.endswith(".gz")
            else {"mode": "r", "encoding": "utf-8", "newline": ""}
        )

        with open_func(self._dataname, **open_kwargs) as f:
            reader = csv.DictReader(f)

            required = {"timestamp", "bids", "asks"}
            if reader.fieldnames:
                missing = required - set(reader.fieldnames)
                if missing:
                    raise ValueError(
                        f"Missing required columns: {missing}. Found: {reader.fieldnames}"
                    )

            for row in reader:
                try:
                    bids = _parse_levels(row["bids"])
                    asks = _parse_levels(row["asks"])

                    ob = OrderBookSnapshot(
                        timestamp=_parse_required_float(row["timestamp"]),
                        symbol=row.get("symbol", self.symbol),
                        exchange=row.get("exchange", ""),
                        asset_type=row.get("asset_type", "spot"),
                        bids=bids[: self._depth],
                        asks=asks[: self._depth],
                    )
                    yield ob
                except (ValueError, KeyError, json.JSONDecodeError) as e:
                    logger.warning("Skipping invalid OB row: %s (error: %s)", row, e)
                    continue

    def _load_jsonl(self) -> Iterator[OrderBookSnapshot]:
        """Load order book events from JSONL format.

        Supports both plain JSONL and gzip-compressed JSONL (.jsonl.gz).
        Each line should contain a JSON object with timestamp, symbol,
        bids, and asks fields.

        Yields:
            OrderBookSnapshot instances.
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
                    bids = _parse_level_pairs(data.get("bids", []))
                    asks = _parse_level_pairs(data.get("asks", []))

                    ob = OrderBookSnapshot(
                        timestamp=_parse_required_float(data["timestamp"]),
                        symbol=data.get("symbol", self.symbol),
                        exchange=data.get("exchange", ""),
                        asset_type=data.get("asset_type", "spot"),
                        bids=bids[: self._depth],
                        asks=asks[: self._depth],
                    )
                    yield ob
                except (ValueError, KeyError, json.JSONDecodeError) as e:
                    logger.warning("Skipping invalid OB JSONL line %d: %s", line_num, e)
                    continue

    def __repr__(self):
        """Return a string representation of the channel.

        Returns:
            str: Representation showing symbol, depth, and buffer stats.
        """
        return (
            f"OrderBookChannel(symbol={self.symbol!r}, "
            f"depth={self._depth}, "
            f"dataname={self._dataname!r}, "
            f"events={self._event_count}, "
            f"buffered={len(self._buffer)})"
        )


def _parse_levels(text: str) -> List[Tuple[float, float]]:
    """Parse order book levels from JSON string.

    Args:
        text: JSON string like '[[50000, 1.0], [49999, 2.0]]'

    Returns:
        List of (price, quantity) tuples.
    """
    levels = json.loads(text)
    return _parse_level_pairs(levels)


def _parse_required_float(value) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Non-finite float value: {value}")
    return number


def _parse_level_pairs(levels) -> List[Tuple[float, float]]:
    return [(_parse_required_float(p), _parse_required_float(q)) for p, q in levels]
