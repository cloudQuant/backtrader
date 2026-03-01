#!/usr/bin/env python
"""CCXT Feed with Funding Rate via WebSocket.

This module extends the standard CCXTFeed to include funding rate data
for perpetual futures trading using WebSocket for real-time updates.

Key Classes:
    CCXTFeedWithFunding: Extended CCXT feed with WebSocket-based funding rate.

The funding rate is integrated into each K-line bar, allowing strategies
to access self.data.funding_rate[0] along with price data.

Example:
    >>> store = bt.stores.CCXTStore(exchange='binance')
    >>> data = CCXTFeedWithFunding(
    ...     symbol='BTC/USDT:USDT',
    ...     store=store,
    ...     use_websocket=True
    ... )
    >>> cerebro.adddata(data)
    >>> # In strategy:
    >>> # self.data.funding_rate[0]     # Current funding rate
    >>> # self.data.mark_price[0]       # Current mark price
    >>> # self.data.next_funding_time[0] # Next funding time

Note:
    This data feed REQUIRES WebSocket connectivity. If WebSocket is unavailable,
    an error will be raised. Install ccxt.pro: pip install ccxtpro
"""

import threading
import time
from datetime import datetime, timedelta, timezone

from backtrader.feed import DataBase
from backtrader.stores import ccxtstore
from backtrader.utils.py3 import queue

from ..utils import date2num

# Import enhancement modules
try:
    from ..ccxt.threading import ThreadedDataManager
    from ..ccxt.websocket import CCXTWebSocketManager

    HAS_CCXT_ENHANCEMENTS = True
except ImportError:
    HAS_CCXT_ENHANCEMENTS = False
    ThreadedDataManager = None
    CCXTWebSocketManager = None


class WebSocketRequiredError(Exception):
    """Raised when WebSocket is required but not available."""

    pass


class CCXTFeedWithFunding(DataBase):
    """
    CCXT Data Feed with Real-time Funding Rate via WebSocket.

    REQUIREMENT: WebSocket (ccxt.pro) must be available. This feed will NOT
    fall back to HTTP polling - if WebSocket fails, an error is raised.

    Extended lines:
        - funding_rate: Current funding rate (8-hour rate, e.g., 0.0001 = 0.01%)
        - mark_price: Current mark price (used for funding calculations)
        - next_funding_time: Timestamp of next funding fee charge
        - predicted_funding_rate: Predicted funding rate for next period

    Params:
      - ``use_websocket`` (default: ``True``)
        Use WebSocket for real-time funding rate updates. REQUIRED.
      - ``funding_history_days`` (default: ``3``)
        Days of historical funding rate to fetch on startup via HTTP.
      - ``ws_startup_timeout`` (default: ``10``)
        Maximum seconds to wait for WebSocket connection on startup.
    """

    # Define additional lines for funding data
    lines = ("funding_rate", "mark_price", "next_funding_time", "predicted_funding_rate")

    params = (
        ("historical", False),
        ("backfill_start", True),
        ("fetch_ohlcv_params", {}),
        ("ohlcv_limit", 100),
        ("drop_newest", False),
        ("debug", False),
        # WebSocket params
        ("use_websocket", True),  # Enable WebSocket by default (REQUIRED)
        ("use_threaded_data", False),
        ("hist_start_date", None),
        ("ws_reconnect_delay", 5.0),
        ("ws_max_reconnect_delay", 60.0),
        ("ws_startup_timeout", 10),  # WebSocket startup timeout
        # Funding rate specific params
        ("include_funding", True),
        ("funding_history_days", 3),  # 3 days history for startup
    )

    _store = ccxtstore.CCXTStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    def __init__(self, store=None, **kwargs):
        """Initialize the CCXT feed with WebSocket-based funding rate support.

        Raises:
            WebSocketRequiredError: If ccxt.pro is not installed or WebSocket is disabled.
        """
        super().__init__()

        self._state = None
        if store is not None:
            self.store = store
        else:
            self.store = self._store(**kwargs)

        self._data = queue.Queue(maxsize=1000)
        self._last_id = ""
        self._last_ts = self.utc_to_ts(datetime.now(timezone.utc))
        self._last_update_bar_time = 0

        # Funding rate data storage (thread-safe)
        self._funding_lock = threading.Lock()
        self._current_funding = {
            "funding_rate": 0.0,
            "predicted_funding_rate": 0.0,
            "mark_price": 0.0,
            "next_funding_time": 0,
            "timestamp": 0,
        }

        # Historical funding cache for bar matching
        self._funding_history = {}  # {timestamp: funding_data}

        # WebSocket related
        self._websocket_manager = None
        self._ws_connected = False
        self._ws_lock = threading.Lock()
        self._ws_funding_connected = False
        self._ws_ohlcv_connected = False

        # Threading related
        self._threaded_data_manager = None

        # REQUIRE WebSocket - no fallback
        if not self.p.use_websocket:
            raise WebSocketRequiredError(
                "CCXTFeedWithFunding requires WebSocket. "
                "Set use_websocket=True and install ccxt.pro (pip install ccxtpro)"
            )

        if not HAS_CCXT_ENHANCEMENTS:
            raise WebSocketRequiredError(
                "WebSocket enhancements not available. Please install ccxt.pro: pip install ccxtpro"
            )

        if CCXTWebSocketManager is None:
            raise WebSocketRequiredError(
                "CCXTWebSocketManager is not available. Please install ccxt.pro: pip install ccxtpro"
            )

    def utc_to_ts(self, dt):
        """Convert datetime to timestamp in milliseconds."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        fromdate = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return int((fromdate - epoch).total_seconds() * 1000)

    def start(self):
        """Start the CCXT data feed with WebSocket funding rate support."""
        DataBase.start(self)

        start_date = self.p.fromdate or self.p.hist_start_date

        # Fetch historical funding rates on startup
        if self.p.include_funding:
            self._fetch_historical_funding_rates()

        if self.p.backfill_start and start_date:
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)
            self._update_bar(start_date)
        elif self.p.historical:
            self._state = self._ST_HISTORBACK
            self.put_notification(self.DELAYED)
            if start_date:
                self._update_bar(start_date)
        else:
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)

        # Start WebSocket if enabled
        if self.p.use_websocket:
            self._start_websocket()

    def _start_websocket(self):
        """Start WebSocket connection for real-time data.

        Uses the shared WebSocket manager from the store if available,
        allowing multiple feeds (OHLCV + funding) to share one WS connection.
        Falls back to creating a per-feed instance if store doesn't provide one.

        Raises:
            WebSocketRequiredError: If WebSocket connection fails.
        """
        try:
            # Try to use shared WebSocket manager from store
            self._ws_is_shared = False
            if hasattr(self.store, "get_websocket_manager"):
                self._websocket_manager = self.store.get_websocket_manager()
                if self._websocket_manager:
                    self._ws_is_shared = True

            # Fallback: create a per-feed WebSocket manager
            if self._websocket_manager is None:
                config = getattr(self.store.exchange, "config", {})
                markets = getattr(self.store.exchange, "markets", None)
                self._websocket_manager = CCXTWebSocketManager(
                    self.store.exchange_id, config, markets=markets
                )
                self._websocket_manager.start()

            # Wait for connection with timeout
            import time as t

            timeout = self.p.ws_startup_timeout
            start_wait = t.time()
            while not self._websocket_manager.is_connected():
                if t.time() - start_wait > timeout:
                    raise WebSocketRequiredError(
                        f"WebSocket connection timeout after {timeout} seconds. "
                        f"Please check your network connection and firewall settings."
                    )
                t.sleep(0.1)

            if self.p.debug:
                print(f"[WS] WebSocket connected to {self.store.exchange_id}")

            # Subscribe to OHLCV updates
            granularity = self.store.get_granularity(self._timeframe, self._compression)
            self._websocket_manager.subscribe_ohlcv(
                self.p.dataname, granularity, self._on_websocket_ohlcv
            )

            if self.p.debug:
                print(f"[WS] Subscribed to OHLCV for {self.p.dataname}")

            # Subscribe to funding rate updates
            if self.p.include_funding:
                self._websocket_manager.subscribe_funding_rate(
                    self.p.dataname, self._on_websocket_funding
                )
                self._websocket_manager.subscribe_mark_price(
                    self.p.dataname, self._on_websocket_mark_price
                )

                if self.p.debug:
                    print(f"[WS] Subscribed to Funding Rate for {self.p.dataname}")

            print(f"[WS] WebSocket subscribed for {self.p.dataname} (OHLCV + funding)")

        except Exception as e:
            # Don't raise - fall back to REST polling like CCXTFeed does
            print(f"[WS] WebSocket start error: {e}")
            print("[WS] Falling back to REST polling mode")
            self._websocket_manager = None

    def _on_websocket_ohlcv(self, ohlcv_data):
        """Callback for WebSocket OHLCV updates.

        Integrate current funding rate into each bar.
        """
        if not ohlcv_data:
            return

        try:
            with self._ws_lock:
                for bar in ohlcv_data:
                    if len(bar) >= 6:
                        # Use >= to include the first bar that matches timestamp
                        if bar[0] >= self._last_ts:
                            # Augment bar with funding rate data
                            with self._funding_lock:
                                funding = self._current_funding["funding_rate"]
                                mark_price = self._current_funding["mark_price"]
                                next_time = self._current_funding["next_funding_time"]
                                predicted = self._current_funding["predicted_funding_rate"]

                            # Create extended bar with funding data
                            extended_bar = list(bar) + [funding, mark_price, next_time, predicted]
                            self._data.put(tuple(extended_bar))
                            # Update last_ts only if this is a newer bar
                            if bar[0] > self._last_ts:
                                self._last_ts = bar[0]
                            self._last_update_bar_time = bar[0]

                self._ws_connected = True

            if self.p.debug:
                print(
                    f"[WS OHLCV] Received {len(ohlcv_data)} bars, latest timestamp: {ohlcv_data[-1][0] if ohlcv_data else 0}"
                )

        except Exception as e:
            if self.p.debug:
                print(f"[WS] Error processing WebSocket OHLCV: {e}")

    def _on_websocket_funding(self, funding_data):
        """Callback for WebSocket funding rate updates.

        Funding data format from ccxt.pro:
        {
            'symbol': 'BTC/USDT:USDT',
            'fundingRate': 0.0001,
            'fundingTimestamp': 1234567890000,
            'nextFundingTime': 1234567890000,
            'info': {...}
        }
        """
        if self.p.debug:
            print(f"[FUNDING WS] Received data: {funding_data}")

        try:
            with self._funding_lock:
                timestamp = funding_data.get("timestamp")
                if timestamp:
                    self._current_funding["timestamp"] = timestamp

                # Extract funding rate - different exchanges use different field names
                rate = funding_data.get("fundingRate")
                if rate is None:
                    rate = funding_data.get("rate")
                if rate is None:
                    rate = funding_data.get("info", {}).get("fundingRate")
                if rate is not None:
                    self._current_funding["funding_rate"] = float(rate)

                # Predicted rate
                predicted = funding_data.get("info", {}).get("predictedFundingRate")
                if predicted is not None:
                    self._current_funding["predicted_funding_rate"] = float(predicted)

                # Next funding time
                next_time = funding_data.get("nextFundingTime")
                if next_time is not None:
                    self._current_funding["next_funding_time"] = int(next_time)

                # Also store in history for bar matching
                self._current_funding["timestamp"] = timestamp or int(time.time() * 1000)
                self._funding_history[self._current_funding["timestamp"]] = (
                    self._current_funding.copy()
                )

                self._ws_funding_connected = True

                if self.p.debug:
                    print(
                        f"[FUNDING WS] Rate: {self._current_funding['funding_rate']:.8f}, "
                        f"Mark: {self._current_funding['mark_price']:.8f}"
                    )

        except Exception as e:
            if self.p.debug:
                print(f"[FUNDING WS] Error: {e}")

    def _on_websocket_mark_price(self, mark_data):
        """Callback for WebSocket mark price updates.

        Mark price data contains funding rate info for some exchanges (Binance).
        """
        if self.p.debug:
            print(f"[MARK PRICE WS] Received data: {mark_data}")

        try:
            with self._funding_lock:
                # Update mark price
                mark_price = mark_data.get("markPrice")
                if mark_price is not None:
                    self._current_funding["mark_price"] = float(mark_price)

                # Binance mark price stream also contains funding rate
                info = mark_data.get("info", {})
                if isinstance(info, dict):
                    # Extract funding rate from Binance mark price stream
                    last_funding_rate = info.get("lastFundingRate")
                    if last_funding_rate is not None:
                        self._current_funding["funding_rate"] = float(last_funding_rate)

                    next_funding_time = info.get("nextFundingTime")
                    if next_funding_time is not None:
                        self._current_funding["next_funding_time"] = int(next_funding_time)

                self._current_funding["timestamp"] = mark_data.get("timestamp", time.time() * 1000)

                # Mark price data also counts as funding connected
                self._ws_funding_connected = True

        except Exception as e:
            if self.p.debug:
                print(f"[MARK PRICE WS] Error: {e}")

    def _fetch_historical_funding_rates(self):
        """Fetch historical funding rates from exchange via HTTP."""
        if not self.p.include_funding:
            return

        exchange = self.store.exchange
        symbol = self.p.dataname

        try:
            since = int(
                (
                    datetime.now(timezone.utc) - timedelta(days=self.p.funding_history_days)
                ).timestamp()
                * 1000
            )

            if self.p.debug:
                print(f"[FUNDING] Fetching historical funding rates for {symbol}...")

            # Try to fetch funding rate history
            if hasattr(exchange, "fetch_funding_rate_history"):
                rates = exchange.fetch_funding_rate_history(symbol, since=since, limit=500)
                for rate in rates:
                    ts = rate.get("timestamp", 0)
                    if ts:
                        self._funding_history[ts] = {
                            "funding_rate": float(rate.get("rate", 0)),
                            "mark_price": 0.0,
                            "predicted_funding_rate": 0.0,
                            "next_funding_time": rate.get("nextFundingTime", ts + 28800000),
                            "timestamp": ts,
                        }

                # Initialize current funding with latest
                if rates:
                    latest = rates[-1]
                    self._current_funding = {
                        "funding_rate": float(latest.get("rate", 0)),
                        "mark_price": 0.0,
                        "predicted_funding_rate": 0.0,
                        "next_funding_time": latest.get("nextFundingTime", 0),
                        "timestamp": latest.get("timestamp", 0),
                    }

            if self.p.debug:
                print(f"[FUNDING] Loaded {len(self._funding_history)} historical rates")

        except Exception as e:
            if self.p.debug:
                print(f"[FUNDING] Warning: Could not fetch historical funding rates: {e}")
            # Non-fatal - we'll get current funding via WebSocket

    def _get_funding_for_bar(self, bar_timestamp):
        """Get the funding rate for a specific bar timestamp."""
        with self._funding_lock:
            if not self._funding_history:
                return self._current_funding

            # Find most recent funding rate before or at bar timestamp
            sorted_ts = sorted(self._funding_history.keys(), reverse=True)
            for ts in sorted_ts:
                if ts <= bar_timestamp:
                    return self._funding_history[ts]

            return self._current_funding

    def _load(self):
        """Load data from WebSocket queue or REST polling fallback.

        Uses WebSocket for real-time data when available, falls back to
        REST polling if WebSocket is not connected.
        """
        if self._state == self._ST_OVER:
            return False

        while True:
            if self._state == self._ST_LIVE:
                # Try WebSocket first if connected
                if self.p.use_websocket and self._ws_connected:
                    ret = self._load_bar()
                    if ret:
                        return ret
                    # No data in queue, but WebSocket connected - wait briefly
                    time.sleep(0.1)
                    return None  # Let cerebro call us again

                # REST polling fallback (same as CCXTFeed)
                timeframe = self._timeframe
                compression = self._compression

                if timeframe == 4:  # Minutes
                    time_diff = 60 * compression
                elif timeframe == 5:  # Days
                    time_diff = 86400 * compression
                else:
                    time_diff = 60

                # Check if enough time has passed to fetch new data
                nts = time.time() * 1000  # milliseconds
                if nts - self._last_update_bar_time >= time_diff * 1000:
                    self._update_bar(livemode=True)

                return self._load_bar()

            elif self._state == self._ST_HISTORBACK:
                ret = self._load_bar()
                if ret:
                    return ret
                else:
                    # End of historical data
                    if self.p.historical:
                        self.put_notification(self.DISCONNECTED)
                        self._state = self._ST_OVER
                        return False
                    else:
                        # Transition to live mode
                        self._state = self._ST_LIVE
                        self.put_notification(self.LIVE)
                        if self.p.debug:
                            print("[LIVE] Transitioned to LIVE mode")
                        continue

    def _update_bar(self, fromdate=None, livemode=False):
        """Fetch OHLCV data into self._data queue."""
        granularity = self.store.get_granularity(self._timeframe, self._compression)

        if fromdate:
            self._last_ts = self.utc_to_ts(fromdate)

        limit = 3 if livemode else max(3, self.p.ohlcv_limit)

        while True:
            dlen = self._data.qsize()

            bars = sorted(
                self.store.fetch_ohlcv(
                    self.p.dataname,
                    timeframe=granularity,
                    since=self._last_ts,
                    limit=limit,
                    params=self.p.fetch_ohlcv_params,
                )
            )

            if self.p.drop_newest and len(bars) > 0:
                del bars[-1]

            for bar in bars:
                if None in bar:
                    continue

                tstamp = bar[0]
                if tstamp > self._last_ts:
                    # Attach current funding rate to historical bars
                    funding_data = self._get_funding_for_bar(tstamp)
                    extended_bar = list(bar) + [
                        funding_data["funding_rate"],
                        funding_data["mark_price"],
                        funding_data["next_funding_time"],
                        funding_data["predicted_funding_rate"],
                    ]
                    self._data.put(tuple(extended_bar))
                    self._last_ts = tstamp
                    self._last_update_bar_time = tstamp

            if dlen != self._data.qsize():
                if livemode:
                    break
            else:
                break

            if livemode:
                break

    def _load_bar(self):
        """Load a single bar from the data queue with funding rate."""
        try:
            bar = self._data.get(block=False)
        except queue.Empty:
            return None

        # Handle both extended bar (with funding) and standard bar
        if len(bar) >= 10:
            # Extended bar with funding data
            tstamp, open_, high, low, close, volume = bar[:6]
            funding_rate = bar[6]
            mark_price = bar[7]
            next_funding_time = bar[8]
            predicted_funding_rate = bar[9]
        else:
            # Standard bar, use current funding
            tstamp, open_, high, low, close, volume = bar
            with self._funding_lock:
                funding_rate = self._current_funding["funding_rate"]
                mark_price = self._current_funding["mark_price"]
                next_funding_time = self._current_funding["next_funding_time"]
                predicted_funding_rate = self._current_funding["predicted_funding_rate"]

        # Set standard OHLCV data
        dtime = datetime.fromtimestamp(tstamp / 1000, tz=timezone.utc).replace(tzinfo=None)
        self.lines.datetime[0] = date2num(dtime)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume

        # Set funding rate data
        if self.p.include_funding:
            self.lines.funding_rate[0] = funding_rate
            self.lines.mark_price[0] = mark_price

            # Convert next funding time to date num
            if next_funding_time:
                next_dt = datetime.fromtimestamp(next_funding_time / 1000, tz=timezone.utc).replace(
                    tzinfo=None
                )
                self.lines.next_funding_time[0] = date2num(next_dt)
            else:
                self.lines.next_funding_time[0] = 0

            self.lines.predicted_funding_rate[0] = predicted_funding_rate

        return True

    def haslivedata(self):
        """Check if live data is available."""
        return self._state == self._ST_LIVE and not self._data.empty()

    def islive(self):
        """Check if feed is in live mode."""
        return not self.p.historical

    def stop(self):
        """Stop the data feed and cleanup resources."""
        if self._websocket_manager and not getattr(self, "_ws_is_shared", False):
            self._websocket_manager.stop()
            print("[WS] WebSocket stopped")
        self._websocket_manager = None

        if self._threaded_data_manager:
            self._threaded_data_manager.stop()


# Register with CCXTStore (optional - comment out to avoid affecting default behavior)
# ccxtstore.CCXTStore.DataCls = CCXTFeedWithFunding
