#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
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

import time
import threading
from datetime import datetime

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
        super(CCXTFeed, self).__init__()

        self._state = None
        # Use provided store or create a new one
        if store is not None:
            self.store = store
        else:
            self.store = self._store(**kwargs)

        self._data = queue.Queue(maxsize=1000)  # data queue for price data
        self._last_id = ""
        self._last_ts = self.utc_to_ts(datetime.utcnow())
        self._last_update_bar_time = 0

        # WebSocket related
        self._websocket_manager = None
        self._ws_connected = False
        self._ws_thread = None
        self._ws_lock = threading.Lock()

        # Threading related
        self._threaded_data_manager = None

    def utc_to_ts(self, dt):
        """Convert datetime to timestamp in milliseconds."""
        fromdate = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute)
        epoch = datetime(1970, 1, 1)
        return int((fromdate - epoch).total_seconds() * 1000)

    def start(self):
        """Start the CCXT data feed."""
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
        """Start WebSocket connection for real-time data."""
        if not HAS_CCXT_ENHANCEMENTS or CCXTWebSocketManager is None:
            print("[WS] WebSocket not available. Install ccxt.pro: pip install ccxtpro")
            return

        try:
            config = getattr(self.store.exchange, 'config', {})
            # Pass pre-loaded markets from store to avoid REST API call in WebSocket
            markets = getattr(self.store.exchange, 'markets', None)
            self._websocket_manager = CCXTWebSocketManager(
                self.store.exchange_id,
                config,
                markets=markets
            )
            self._websocket_manager.start()

            # Subscribe to OHLCV updates
            granularity = self.store.get_granularity(self._timeframe, self._compression)
            self._websocket_manager.subscribe_ohlcv(
                self.p.dataname,
                granularity,
                self._on_websocket_ohlcv
            )

            print(f"[WS] WebSocket started for {self.p.dataname}")

        except Exception as e:
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
                for bar in ohlcv_data:
                    # bar format: [timestamp, open, high, low, close, volume]
                    if len(bar) >= 6 and bar[0] > self._last_ts:
                        self._data.put(bar)
                        self._last_ts = bar[0]
                        self._last_update_bar_time = bar[0]

                        # Log occasionally
                        if self.p.debug:
                            bar_time = datetime.utcfromtimestamp(bar[0] // 1000)
                            print(f"[WS] New bar: {bar_time} O={bar[1]:.6f} H={bar[2]:.6f} "
                                  f"L={bar[3]:.6f} C={bar[4]:.6f} V={bar[5]:.0f}")

                self._ws_connected = True

        except Exception as e:
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
                # WebSocket mode: data comes from background thread
                if self.p.use_websocket and self._ws_connected:
                    # Data is pushed by WebSocket callback
                    return self._load_bar()

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

    def _update_bar(self, fromdate=None, livemode=False):
        """Fetch OHLCV data into self._data queue.

        Args:
            fromdate: Start datetime for fetching.
            livemode: True if in live mode (fetches less data).
        """
        granularity = self.store.get_granularity(self._timeframe, self._compression)

        if fromdate:
            self._last_ts = self.utc_to_ts(fromdate)

        # In live mode, fetch fewer bars to reduce latency
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
        dtime = datetime.utcfromtimestamp(tstamp // 1000)
        self.lines.datetime[0] = date2num(dtime)
        self.lines.open[0] = open_
        self.lines.high[0] = high
        self.lines.low[0] = low
        self.lines.close[0] = close
        self.lines.volume[0] = volume
        return True

    def haslivedata(self):
        """Check if live data is available."""
        return self._state == self._ST_LIVE and not self._data.empty()

    def islive(self):
        """Check if feed is in live mode."""
        return not self.p.historical

    def stop(self):
        """Stop the data feed and cleanup resources."""
        # Stop WebSocket
        if self._websocket_manager:
            self._websocket_manager.stop()
            self._websocket_manager = None
            print("[WS] WebSocket stopped")

        # Stop threaded data manager
        if self._threaded_data_manager:
            self._threaded_data_manager.stop()

        # Stop store
        if hasattr(self.store, 'stop'):
            self.store.stop()


# Register CCXTFeed with CCXTStore
ccxtstore.CCXTStore.DataCls = CCXTFeed
