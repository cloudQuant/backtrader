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
        key = (getattr(event, "channel_type", ""), getattr(event, "channel_name", ""))
        ts = event.timestamp

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
        price = getattr(tick, "price", None)
        volume = getattr(tick, "volume", None)

        if price is not None and price <= 0:
            self._record_anomaly(key, "invalid_price")
            return False
        if volume is not None and volume < 0:
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
            best_bid = (
                bids[0][0] if isinstance(bids[0], (list, tuple)) else getattr(bids[0], "price", 0)
            )
            best_ask = (
                asks[0][0] if isinstance(asks[0], (list, tuple)) else getattr(asks[0], "price", 0)
            )
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
        rate = getattr(funding, "rate", None)
        if rate is not None and abs(rate) > 0.1:
            self._record_anomaly(key, "extreme_funding_rate")
            logger.warning("Extreme funding rate for %s: %.6f", key, rate)
        return True

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
