#!/usr/bin/env python
"""CCXT Data Feed Module - Cryptocurrency exchange data.

This module provides the CCXTFeed for connecting to cryptocurrency
exchanges through the CCXT library.

Features:
    - REST API polling (default)
    - WebSocket streaming (requires ccxt.pro)
    - Multi-threaded data management
    - Automatic reconnection

Classes:
    CCXTFeed: Live and historical data from crypto exchanges.

Example:
    >>> store = bt.stores.CCXTStore(exchange='binance')
    >>> data = bt.feeds.CCXT(
    ...     symbol='BTC/USDT',
    ...     timeframe=bt.TimeFrame.Minutes,
    ...     store=store,
    ...     use_websocket=True  # Use WebSocket for real-time data
    ... )
    >>> cerebro.adddata(data)
"""

import logging
import threading
import time
from datetime import datetime, timezone

from backtrader.feed import DataBase
from backtrader.stores import ccxtstore
from backtrader.utils.py3 import queue

from ..utils import date2num

logger = logging.getLogger(__name__)

# Import ccxt errors for error handling
try:
    from ccxt.base.errors import ExchangeError, ExchangeNotAvailable, NetworkError

    HAS_CCXT_ERRORS = True
except ImportError:
    HAS_CCXT_ERRORS = False
    NetworkError = Exception
    ExchangeError = Exception
    ExchangeNotAvailable = Exception

# Import enhancement modules
try:
    from ..ccxt.threading import ThreadedDataManager
    from ..ccxt.websocket import CCXTWebSocketManager

    HAS_CCXT_ENHANCEMENTS = True
except ImportError:
    HAS_CCXT_ENHANCEMENTS = False
    ThreadedDataManager = None
    CCXTWebSocketManager = None


class CCXTFeed(DataBase):
    """
    CryptoCurrency eXchange Trading Library Data Feed.

    Params:
      - ``historical`` (default: ``False``)
        If set to ``True`` the data feed will stop after doing the first
        download of data.
      - ``backfill_start`` (default: ``True``)
        Perform backfilling at the start.
      - ``use_websocket`` (default: ``False``)
        Use WebSocket for real-time data (requires ccxt.pro).
      - ``use_threaded_data`` (default: ``False``)
        Use threaded manager for data fetching.
      - ``ohlcv_limit`` (default: ``20``)
        Maximum bars to fetch per request.
      - ``drop_newest`` (default: ``False``)
        Drop the most recent bar (may be incomplete).
      - ``ws_reconnect_delay`` (default: ``5.0``)
        WebSocket reconnection delay in seconds.
      - ``ws_max_reconnect_delay`` (default: ``60.0``)
        Maximum WebSocket reconnection delay.
    """

    params = (
        ("historical", False),
        ("backfill_start", True),
        ("fetch_ohlcv_params", {}),
        ("ohlcv_limit", 100),
        ("drop_newest", False),
        ("debug", False),
        ("use_websocket", False),
        ("use_threaded_data", False),
        ("hist_start_date", None),
        ("ws_reconnect_delay", 5.0),
        ("ws_max_reconnect_delay", 60.0),
        ("max_fetch_retries", 3),
        ("fetch_retry_delay", 1.0),
        ("ws_health_check_interval", 30.0),
    )

    _store = ccxtstore.CCXTStore

    # States for the Finite State Machine in _load
    _ST_LIVE, _ST_HISTORBACK, _ST_OVER = range(3)

    def __init__(self, store=None, **kwargs):
        """Initialize the CCXT data feed.

        Args:
            store: Optional CCXTStore instance.
            **kwargs: Keyword arguments for data feed configuration.
        """
        super().__init__()

        self._state = None
        # Use provided store or create a new one
        if store is not None:
            self.store = store
        else:
            self.store = self._store(**kwargs)

        self._data = queue.Queue(maxsize=1000)  # data queue for price data
        self._last_id = ""
        self._last_ts = self.utc_to_ts(datetime.now(timezone.utc))
        self._last_update_bar_time = 0

        # WebSocket related
        self._websocket_manager = None
        self._ws_connected = False
        self._ws_thread = None
        self._ws_lock = threading.Lock()
        self._ws_last_data_time = 0
        self._ws_disconnected_since = 0
        self._ws_backfill_needed = False

        # Threading related
        self._threaded_data_manager = None

        # Error tracking
        self._consecutive_fetch_errors = 0
        self._max_consecutive_errors = 10
        self._last_error_time = 0

    def utc_to_ts(self, dt):
        """Convert a datetime object to a Unix timestamp in milliseconds.

        Args:
            dt: datetime object to convert. Should be timezone-aware or
                treated as UTC.

        Returns:
            int: Unix timestamp in milliseconds since epoch (1970-01-01).
        """
        fromdate = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        epoch = datetime(1970, 1, 1)
        return int((fromdate - epoch).total_seconds() * 1000)

    def start(self):
        """Start the CCXT data feed and initialize data fetching.

        Sets up the initial state based on configuration:
        - Historical mode: Fetches historical data and stops
        - Backfill mode: Fetches historical data then continues live
        - Live mode: Starts live data fetching immediately

        Also initializes WebSocket connection if use_websocket is True.
        """
        DataBase.start(self)

        start_date = self.p.fromdate or self.p.hist_start_date

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
            # Start in live mode
            self._state = self._ST_LIVE
            self.put_notification(self.LIVE)

        # Start WebSocket if enabled
        if self.p.use_websocket:
            self._start_websocket()

    def _start_websocket(self):
        """Start WebSocket connection for real-time data.

        Uses the shared WebSocket manager from the store if available,
        allowing multiple feeds to share a single WS connection.
        Falls back to creating a per-feed instance if store doesn't provide one.
        """
        if not HAS_CCXT_ENHANCEMENTS or CCXTWebSocketManager is None:
            print("[WS] WebSocket not available. Install ccxt.pro: pip install ccxtpro")
            return

        try:
            # Try to use shared WebSocket manager from store
            self._ws_is_shared = False
            if hasattr(self.store, "get_websocket_manager"):
                self._websocket_manager = self.store.get_websocket_manager()
                if self._websocket_manager is not None:
                    self._ws_is_shared = True

            # Fallback: create a per-feed WebSocket manager
            if self._websocket_manager is None:
                config = getattr(self.store.exchange, "config", {})
                markets = getattr(self.store.exchange, "markets", None)
                self._websocket_manager = CCXTWebSocketManager(self.store.exchange_id, config, markets=markets)
                self._websocket_manager.start()

            # Subscribe to OHLCV updates for this feed's symbol
            granularity = self.store.get_granularity(self._timeframe, self._compression)
            self._websocket_manager.subscribe_ohlcv(self.p.dataname, granularity, self._on_websocket_ohlcv)

            print(f"[WS] WebSocket subscribed for {self.p.dataname} ({granularity})")

        except (NetworkError, ExchangeError, OSError, ImportError) as e:
            print(f"[WS] WebSocket start error: {e}")
            self._websocket_manager = None

    def _on_websocket_ohlcv(self, ohlcv_data):
        """Callback for WebSocket OHLCV updates.

        Args:
            ohlcv_data: List of OHLCV bars from WebSocket.
        """
        if not ohlcv_data:
            return

        try:
            with self._ws_lock:
                was_disconnected = not self._ws_connected

                for bar in ohlcv_data:
                    # bar format: [timestamp, open, high, low, close, volume]
                    if len(bar) >= 6 and bar[0] > self._last_ts:
                        self._data.put(bar)
                        self._last_ts = bar[0]
                        self._last_update_bar_time = bar[0]

                        # Log occasionally
                        if self.p.debug:
                            bar_time = datetime.fromtimestamp(bar[0] / 1000, tz=timezone.utc)
                            logger.debug(
                                f"[WS] New bar: {bar_time} O={bar[1]:.6f} H={bar[2]:.6f} "
                                f"L={bar[3]:.6f} C={bar[4]:.6f} V={bar[5]:.0f}"
                            )

                self._ws_connected = True
                self._ws_last_data_time = time.time()

                # If we were disconnected and got data again, backfill might be needed
                if was_disconnected and self._ws_disconnected_since > 0:
                    gap_seconds = time.time() - self._ws_disconnected_since
                    if gap_seconds > 60:  # Only backfill if gap > 1 minute
                        self._ws_backfill_needed = True
                        if self.p.debug:
                            print(f"[WS] Reconnected after {gap_seconds:.0f}s gap, backfill needed")
                    self._ws_disconnected_since = 0

        except (ValueError, TypeError, KeyError, queue.Full) as e:
            print(f"[WS] Error processing WebSocket data: {e}")

    def _load(self):
        """
        Load data from queue or fetch new data.

        Returns:
            True: Successfully got data.
            False: Data source closed.
            None: No data available right now.
        """
        if self._state == self._ST_OVER:
            return False

        while True:
            if self._state == self._ST_LIVE:
                # WebSocket mode: check health and handle backfill
                if self.p.use_websocket:
                    self._check_ws_health()

                    # Perform backfill if needed after WS reconnection
                    if self._ws_backfill_needed:
                        self._ws_backfill_needed = False
                        if self.p.debug:
                            print("[WS] Performing backfill after reconnection")
                        self._update_bar(livemode=True)

                    if self._ws_connected:
                        # Data is pushed by WebSocket callback
                        return self._load_bar()
                    else:
                        # WebSocket disconnected, fall back to REST polling
                        if self.p.debug and self._ws_disconnected_since == 0:
                            print("[WS] Disconnected, falling back to REST polling")
                        if self._ws_disconnected_since == 0:
                            self._ws_disconnected_since = time.time()

                # REST polling mode: check if we need to fetch
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
                        self._state = self._ST_LIVE
                        self.put_notification(self.LIVE)

                        # Start WebSocket if enabled (after historical data loaded)
                        if self.p.use_websocket and not self._websocket_manager:
                            self._start_websocket()

                        continue

    def _check_ws_health(self):
        """Check WebSocket connection health and detect stale connections.

        If no data received for ws_health_check_interval seconds, mark as disconnected.
        This catches cases where the WS connection is alive but not receiving data.
        """
        if not self._ws_connected or not self._websocket_manager:
            return

        now = time.time()
        # Check if WebSocket manager reports disconnected
        if hasattr(self._websocket_manager, "is_connected") and not self._websocket_manager.is_connected():
            self._ws_connected = False
            return

        # Check for stale data (no updates for too long)
        if self._ws_last_data_time > 0:
            silence = now - self._ws_last_data_time
            if silence > self.p.ws_health_check_interval:
                if self.p.debug:
                    print(f"[WS] No data for {silence:.0f}s, marking as disconnected")
                self._ws_connected = False

    def _update_bar(self, fromdate=None, livemode=False):
        """Fetch OHLCV data into self._data queue with error handling.

        Args:
            fromdate: Start datetime for fetching.
            livemode: True if in live mode (fetches less data).
        """
        # Check connection before fetching
        if hasattr(self.store, "is_connected") and not self.store.is_connected():
            if self.p.debug:
                print("[CCXTFeed] Store disconnected, skipping fetch")
            return

        granularity = self.store.get_granularity(self._timeframe, self._compression)

        if fromdate:
            self._last_ts = self.utc_to_ts(fromdate)

        # In live mode, fetch fewer bars to reduce latency
        limit = 3 if livemode else max(3, self.p.ohlcv_limit)

        while True:
            dlen = self._data.qsize()

            try:
                bars = sorted(
                    self._fetch_ohlcv_with_retry(
                        self.p.dataname,
                        timeframe=granularity,
                        since=self._last_ts,
                        limit=limit,
                        params=self.p.fetch_ohlcv_params,
                    )
                )
                self._consecutive_fetch_errors = 0
            except (NetworkError, ExchangeError, ExchangeNotAvailable, OSError) as e:
                self._consecutive_fetch_errors += 1
                self._last_error_time = time.time()
                if self._consecutive_fetch_errors <= 3 or self.p.debug:
                    print(f"[CCXTFeed] Fetch error ({self._consecutive_fetch_errors}): {e}")
                if self._consecutive_fetch_errors >= self._max_consecutive_errors:
                    print(f"[CCXTFeed] Too many consecutive errors ({self._consecutive_fetch_errors}), backing off...")
                break

            # Drop newest bar if requested (may be incomplete)
            if self.p.drop_newest and len(bars) > 0:
                del bars[-1]

            # Add new bars to queue
            for bar in bars:
                if None in bar:
                    continue

                tstamp = bar[0]
                if tstamp > self._last_ts:
                    self._data.put(bar)
                    self._last_ts = tstamp
                    self._last_update_bar_time = tstamp

            # Check if we got new data
            if dlen != self._data.qsize():
                # Got new data, break for now
                if livemode:
                    break
            else:
                # No new data, this is the latest bar
                break

            # In live mode, only fetch once per call
            if livemode:
                break

    def _fetch_ohlcv_with_retry(self, symbol, timeframe, since, limit, params=None):
        """Fetch OHLCV data with retry logic.

        Args:
            symbol: Trading pair symbol.
            timeframe: Timeframe string.
            since: Start timestamp in milliseconds.
            limit: Maximum bars to fetch.
            params: Additional parameters.

        Returns:
            List of OHLCV bars.

        Raises:
            The last exception if all retries fail.
        """
        last_exception = None
        for attempt in range(self.p.max_fetch_retries):
            try:
                return self.store.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=since,
                    limit=limit,
                    params=params if params else {},
                )
            except (NetworkError, ExchangeNotAvailable) as e:
                last_exception = e
                if attempt < self.p.max_fetch_retries - 1:
                    delay = self.p.fetch_retry_delay * (2**attempt)
                    if self.p.debug:
                        print(f"[CCXTFeed] Fetch retry {attempt + 1}/{self.p.max_fetch_retries} in {delay:.1f}s: {e}")
                    time.sleep(delay)
            except ExchangeError:
                # Exchange errors should not retry
                raise
        raise last_exception

    def _load_bar(self):
        """Load a single bar from the data queue.

        Returns:
            True: Bar loaded successfully.
            None: No data available.
        """
        try:
            bar = self._data.get(block=False)
        except queue.Empty:
            return None

        tstamp, open_, high, low, close, volume = bar
        dtime = datetime.fromtimestamp(tstamp / 1000, tz=timezone.utc).replace(tzinfo=None)
        self.lines.datetime[0] = date2num(dtime)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume
        return True

    def haslivedata(self):
        """Check if live data is currently available.

        Returns:
            bool: True if the feed is in live mode and has data in the queue.
        """
        return self._state == self._ST_LIVE and not self._data.empty()

    def islive(self):
        """Check if the feed is operating in live mode.

        Returns:
            bool: True if the feed is live (not historical only).
        """
        return not self.p.historical

    def stop(self):
        """Stop the data feed and cleanup resources.

        Stops WebSocket connection (if not shared), stops threaded data
        manager, and stops the associated store.
        """
        # Stop WebSocket only if it's not shared with other feeds
        if self._websocket_manager and not getattr(self, "_ws_is_shared", False):
            self._websocket_manager.stop()
            print("[WS] WebSocket stopped")
        self._websocket_manager = None

        # Stop threaded data manager
        if self._threaded_data_manager:
            self._threaded_data_manager.stop()

        # Stop store
        if hasattr(self.store, "stop"):
            self.store.stop()


# Register CCXTFeed with CCXTStore
ccxtstore.CCXTStore.DataCls = CCXTFeed
