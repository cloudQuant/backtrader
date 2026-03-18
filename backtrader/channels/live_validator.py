"""Live data validator for real-time event streams.

Validates incoming events for data quality issues such as out-of-order
timestamps, time jumps, invalid prices/volumes, and stale data detection.

Example::

    validator = LiveDataValidator()
    if validator.validate(event):
        process(event)
    else:
        log_rejected(event)

    print(validator.get_anomaly_report())
"""

import logging
import math
import time

logger = logging.getLogger(__name__)

__all__ = ["LiveDataValidator"]


class LiveDataValidator:
    """Real-time data quality validator.

    Checks each incoming event for:
    - Out-of-order timestamps
    - Large time jumps (>1 hour by default)
    - Invalid prices (<=0) or volumes (<0) for tick data
    - Invalid order book structure
    - Stale data detection

    Args:
        max_time_jump: Maximum allowed timestamp gap in seconds (default: 3600).
        max_clock_drift: Maximum allowed drift from wall clock in seconds (default: 60).
        enable_clock_check: Whether to check against wall clock time (default: False).
    """

    def __init__(self, max_time_jump=3600, max_clock_drift=60.0, enable_clock_check=False):
        """Initialize the live data validator.

        Args:
            max_time_jump: Maximum allowed time jump between events (seconds).
            max_clock_drift: Maximum allowed clock drift across symbols (seconds).
            enable_clock_check: Whether to enable clock synchronization checks.
        """
        max_time_jump = self._coerce_number(max_time_jump)
        max_clock_drift = self._coerce_number(max_clock_drift)
        if max_time_jump is None or max_time_jump < 0:
            raise ValueError("max_time_jump must be a non-negative number")
        if max_clock_drift is None or max_clock_drift < 0:
            raise ValueError("max_clock_drift must be a non-negative number")
        self._max_time_jump = max_time_jump
        self._max_clock_drift = max_clock_drift
        self._enable_clock_check = enable_clock_check
        self._last_timestamps = {}
        self._anomaly_count = {}
        self._total_validated = 0
        self._total_rejected = 0

    def validate(self, event):
        """Validate an incoming event.

        Args:
            event: Event wrapper with timestamp, channel_type, channel_name, data.

        Returns:
            True if the event passes validation, False if rejected.
        """
        self._total_validated += 1
        key = self._event_key(event)
        if event is None:
            self._record_anomaly(key, "invalid_event")
            self._total_rejected += 1
            return False
        ts = self._coerce_number(getattr(event, "timestamp", None))
        if ts is None or ts < 0:
            self._record_anomaly(key, "invalid_timestamp")
            self._total_rejected += 1
            return False

        # 1. Timestamp order check
        last_ts = self._last_timestamps.get(key, 0)
        if last_ts > 0 and ts < last_ts:
            self._record_anomaly(key, "out_of_order")
            self._total_rejected += 1
            return False

        # 2. Time jump check (warn but don't reject unless extreme)
        if last_ts > 0 and ts - last_ts > self._max_time_jump:
            self._record_anomaly(key, "time_jump")
            logger.warning(
                "Time jump detected for %s: %.1fs gap",
                key,
                ts - last_ts,
            )

        # 3. Wall clock drift check
        if self._enable_clock_check:
            now = time.time()
            drift = abs(ts - now)
            if drift > self._max_clock_drift:
                self._record_anomaly(key, "clock_drift")
                logger.warning(
                    "Clock drift for %s: %.1fs from wall clock",
                    key,
                    drift,
                )

        # 4. Data-specific validation
        data = getattr(event, "data", None)
        channel_type = getattr(event, "channel_type", "")

        if data is not None:
            if channel_type == "tick":
                if not self._validate_tick(key, data):
                    self._total_rejected += 1
                    return False
            elif channel_type == "orderbook":
                if not self._validate_orderbook(key, data):
                    self._total_rejected += 1
                    return False
            elif channel_type == "funding":
                if not self._validate_funding(key, data):
                    self._total_rejected += 1
                    return False

        self._last_timestamps[key] = ts
        return True

    def _validate_tick(self, key, tick):
        """Validate tick data for price and volume constraints.

        Checks that price is positive and volume is non-negative. Rejects
        ticks that violate these constraints and records the anomaly.

        Args:
            key: Tuple of (channel_type, channel_name) for tracking.
            tick: TickEvent instance to validate.

        Returns:
            True if the tick is valid, False otherwise.
        """
        raw_price = getattr(tick, "price", None)
        raw_volume = getattr(tick, "volume", None)
        price = self._coerce_number(raw_price) if raw_price is not None else None
        volume = self._coerce_number(raw_volume) if raw_volume is not None else None

        if raw_price is not None and (price is None or price <= 0):
            self._record_anomaly(key, "invalid_price")
            return False
        if raw_volume is not None and (volume is None or volume < 0):
            self._record_anomaly(key, "invalid_volume")
            return False
        return True

    def _validate_orderbook(self, key, ob):
        """Validate order book data structure and integrity.

        Checks that the order book is not empty and that there are no
        crossed books (best bid >= best ask), which would indicate
        data corruption or invalid market state.

        Args:
            key: Tuple of (channel_type, channel_name) for tracking.
            ob: OrderBookSnapshot instance to validate.

        Returns:
            True if the order book is valid, False otherwise.
        """
        bids = getattr(ob, "bids", None)
        asks = getattr(ob, "asks", None)

        if not bids and not asks:
            self._record_anomaly(key, "empty_orderbook")
            return False

        # Check crossed book (best bid >= best ask)
        if bids and asks:
            best_bid = self._extract_orderbook_price(bids[0])
            best_ask = self._extract_orderbook_price(asks[0])
            if best_bid is None or best_ask is None:
                self._record_anomaly(key, "invalid_orderbook_price")
                return False
            if best_bid >= best_ask:
                self._record_anomaly(key, "crossed_book")
                logger.warning(
                    "Crossed order book for %s: bid=%.2f >= ask=%.2f", key, best_bid, best_ask
                )
        return True

    def _validate_funding(self, key, funding):
        """Validate funding rate data for extreme values.

        Checks if the funding rate is within reasonable bounds
        (absolute value <= 0.1). Extreme funding rates are logged
        as warnings but not rejected.

        Args:
            key: Tuple of (channel_type, channel_name) for tracking.
            funding: FundingEvent instance to validate.

        Returns:
            Always returns True (warnings are logged, not rejected).
        """
        raw_rate = getattr(funding, "rate", None)
        if raw_rate is None:
            return True
        rate = self._coerce_number(raw_rate)
        if rate is None:
            self._record_anomaly(key, "invalid_funding_rate")
            return False
        if abs(rate) > 0.1:
            self._record_anomaly(key, "extreme_funding_rate")
            logger.warning("Extreme funding rate for %s: %.6f", key, rate)
        return True

    @staticmethod
    def _coerce_number(value):
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return number

    @staticmethod
    def _event_key(event):
        return (
            str(getattr(event, "channel_type", "") or ""),
            str(getattr(event, "channel_name", "") or ""),
        )

    def _extract_orderbook_price(self, level):
        if isinstance(level, (list, tuple)):
            if not level:
                return None
            return self._coerce_number(level[0])
        return self._coerce_number(getattr(level, "price", None))

    def _record_anomaly(self, key, anomaly_type):
        """Record an anomaly occurrence for later reporting.

        Args:
            key: Tuple of (channel_type, channel_name) for tracking.
            anomaly_type: String identifying the type of anomaly.
        """
        if key not in self._anomaly_count:
            self._anomaly_count[key] = {}
        self._anomaly_count[key][anomaly_type] = self._anomaly_count[key].get(anomaly_type, 0) + 1

    def get_anomaly_report(self):
        """Get the anomaly report.

        Returns:
            Dict mapping (channel_type, channel_name) to {anomaly_type: count}.
        """
        return dict(self._anomaly_count)

    @property
    def stats(self):
        """Validation statistics."""
        return {
            "total_validated": self._total_validated,
            "total_rejected": self._total_rejected,
            "rejection_rate": (
                self._total_rejected / self._total_validated if self._total_validated > 0 else 0.0
            ),
            "anomaly_types": {str(k): v for k, v in self._anomaly_count.items()},
        }

    def reset(self):
        """Reset all state."""
        self._last_timestamps.clear()
        self._anomaly_count.clear()
        self._total_validated = 0
        self._total_rejected = 0

    def __repr__(self):
        """Return a string representation of the validator.

        Returns:
            str: Representation showing validation statistics.
        """
        return (
            f"LiveDataValidator(validated={self._total_validated}, rejected={self._total_rejected})"
        )
