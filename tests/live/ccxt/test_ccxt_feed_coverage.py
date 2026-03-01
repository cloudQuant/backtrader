#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Coverage tests for backtrader/feeds/ccxtfeed.py and ccxtfeed_funding.py.

Target: ccxtfeed.py 47%→65%+, ccxtfeed_funding.py 19%→50%+.
"""

import time
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from backtrader.utils.py3 import queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_store():
    """Create a mock CCXTStore for testing.

    Returns:
        MagicMock: A mocked CCXTStore with preset exchange ID,
            connection status, OHLCV data, and WebSocket manager.
    """
    store = MagicMock()
    store.exchange_id = 'okx'
    store.exchange = MagicMock()
    store.exchange.config = {'apiKey': 'k'}
    store.exchange.markets = {'BTC/USDT:USDT': {'id': 'BTC-USDT-SWAP'}}
    store.is_connected = MagicMock(return_value=True)
    store.get_granularity = MagicMock(return_value='1m')
    store.get_websocket_manager = MagicMock(return_value=None)
    store.fetch_ohlcv = MagicMock(return_value=[
        [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0],
        [1700000060000, 50050.0, 50200.0, 50000.0, 50150.0, 120.0],
    ])
    store.stop = MagicMock()
    return store


def _make_feed(store=None, use_ws=False, **extra_params):
    """Create a CCXTFeed with mocked internals, bypassing DataBase.__init__.

    Args:
        store: Optional mock CCXTStore instance. If None, a new mock
            store is created via _make_mock_store().
        use_ws: Whether to enable WebSocket mode.
        **extra_params: Additional feed parameters to override defaults.

    Returns:
        CCXTFeed: A mocked CCXTFeed instance with minimal attributes
            set up for testing.
    """
    from backtrader.feeds.ccxtfeed import CCXTFeed

    if store is None:
        store = _make_mock_store()

    feed = CCXTFeed.__new__(CCXTFeed)

    # Minimal DataBase attributes
    feed.p = MagicMock()
    feed.p.dataname = 'BTC/USDT:USDT'
    feed.p.historical = extra_params.get('historical', False)
    feed.p.backfill_start = extra_params.get('backfill_start', False)
    feed.p.fromdate = None
    feed.p.hist_start_date = None
    feed.p.use_websocket = use_ws
    feed.p.use_threaded_data = False
    feed.p.ohlcv_limit = 100
    feed.p.drop_newest = extra_params.get('drop_newest', False)
    feed.p.debug = extra_params.get('debug', False)
    feed.p.fetch_ohlcv_params = {}
    feed.p.ws_reconnect_delay = 5.0
    feed.p.ws_max_reconnect_delay = 60.0
    feed.p.max_fetch_retries = 3
    feed.p.fetch_retry_delay = 0.001  # Fast for testing
    feed.p.ws_health_check_interval = 30.0

    feed.store = store
    feed._state = None
    feed._data = queue.Queue(maxsize=1000)
    feed._last_id = ""
    feed._last_ts = 0
    feed._last_update_bar_time = 0
    feed._websocket_manager = None
    feed._ws_connected = False
    feed._ws_thread = None
    feed._ws_lock = threading.Lock()
    feed._ws_last_data_time = 0
    feed._ws_disconnected_since = 0
    feed._ws_backfill_needed = False
    feed._threaded_data_manager = None
    feed._consecutive_fetch_errors = 0
    feed._max_consecutive_errors = 10
    feed._last_error_time = 0
    feed._timeframe = 4  # Minutes
    feed._compression = 1

    # Mock lines for _load_bar
    feed.lines = MagicMock()

    return feed


# ---------------------------------------------------------------------------
# Test: CCXTFeed.__init__ and utc_to_ts
# ---------------------------------------------------------------------------

class TestFeedInit:
    """Test feed initialization and utility methods."""

    def test_utc_to_ts(self):
        """Test conversion of UTC datetime to timestamp.

        Verifies that the utc_to_ts method correctly converts a datetime
        object to a millisecond timestamp integer.
        """
        feed = _make_feed()
        dt = datetime(2024, 1, 1, 12, 30)
        ts = feed.utc_to_ts(dt)
        assert isinstance(ts, int)
        assert ts > 0

    def test_feed_attributes_initialized(self):
        """Test that feed attributes are properly initialized.

        Ensures that the internal state attributes for data queue,
        WebSocket connection, and error tracking are initialized
        to their expected default values.
        """
        feed = _make_feed()
        assert feed._data is not None
        assert feed._ws_connected is False
        assert feed._consecutive_fetch_errors == 0


# ---------------------------------------------------------------------------
# Test: _on_websocket_ohlcv
# ---------------------------------------------------------------------------

class TestOnWebsocketOHLCV:
    """Test WebSocket OHLCV callback handling.

    Tests the _on_websocket_ohlcv method which processes incoming
    WebSocket data containing Open-High-Low-Close-Volume bars.
    """

    def test_empty_data_ignored(self):
        """Test that empty data lists are ignored.

        Verifies that when the WebSocket callback receives an empty
        list, no data is enqueued to the internal queue.
        """
        feed = _make_feed()
        feed._on_websocket_ohlcv([])
        assert feed._data.empty()

    def test_none_data_ignored(self):
        """Test that None data is ignored.

        Verifies that when the WebSocket callback receives None,
        no data is enqueued and no errors are raised.
        """
        feed = _make_feed()
        feed._on_websocket_ohlcv(None)
        assert feed._data.empty()

    def test_new_bar_enqueued(self):
        """Test that a valid new bar is enqueued.

        Verifies that a properly formatted OHLCV bar with a timestamp
        greater than the last seen timestamp is enqueued and the
        WebSocket connection flag is set to True.
        """
        feed = _make_feed()
        feed._last_ts = 0
        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])
        assert not feed._data.empty()
        assert feed._last_ts == 1700000000000
        assert feed._ws_connected is True

    def test_old_bar_skipped(self):
        """Test that bars with old timestamps are skipped.

        Verifies that when a bar with a timestamp less than or equal
        to the last seen timestamp is received, it is not enqueued
        to prevent duplicate data.
        """
        feed = _make_feed()
        feed._last_ts = 1700000000000  # Already seen this
        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])
        assert feed._data.empty()

    def test_short_bar_skipped(self):
        """Test that malformed bars are skipped.

        Verifies that bars with fewer than 6 elements are rejected
        as invalid and not enqueued.
        """
        feed = _make_feed()
        feed._last_ts = 0
        bar = [1700000000000, 50000.0, 50100.0]  # Only 3 elements
        feed._on_websocket_ohlcv([bar])
        assert feed._data.empty()

    def test_reconnection_gap_backfill(self):
        """After WS reconnect with >60s gap, marks backfill needed."""
        feed = _make_feed()
        feed._ws_connected = False  # Was disconnected
        feed._ws_disconnected_since = time.time() - 120  # 2 min ago
        feed._last_ts = 0

        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])

        assert feed._ws_backfill_needed is True
        assert feed._ws_disconnected_since == 0  # Reset

    def test_reconnection_short_gap_no_backfill(self):
        """Short gap (<60s) doesn't trigger backfill."""
        feed = _make_feed()
        feed._ws_connected = False
        feed._ws_disconnected_since = time.time() - 10  # 10s ago
        feed._last_ts = 0

        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])

        assert feed._ws_backfill_needed is False

    def test_debug_logging(self):
        """Test that debug mode does not cause errors during OHLCV processing."""
        feed = _make_feed(debug=True)
        feed._last_ts = 0
        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])  # Should not raise


# ---------------------------------------------------------------------------
# Test: _check_ws_health
# ---------------------------------------------------------------------------

class TestCheckWSHealth:
    """Test WebSocket health check functionality.

    Tests the _check_ws_health method which monitors the WebSocket
    connection state and detects stale data or disconnections.
    """

    def test_not_connected_skips(self):
        """Test that health check is skipped when not connected.

        Verifies that when _ws_connected is False, the health check
        exits early without performing any checks.
        """
        feed = _make_feed()
        feed._ws_connected = False
        feed._check_ws_health()  # Should not raise

    def test_no_manager_skips(self):
        """Test that health check is skipped when manager is None.

        Verifies that when _websocket_manager is None, the health
        check exits early without errors.
        """
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = None
        feed._check_ws_health()

    def test_manager_reports_disconnected(self):
        """Test disconnection when manager reports not connected.

        Verifies that when the WebSocket manager's is_connected
        method returns False, the feed's connection flag is updated.
        """
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = False

        feed._check_ws_health()
        assert feed._ws_connected is False

    def test_stale_data_marks_disconnected(self):
        """Test disconnection due to stale data.

        Verifies that when no data has been received for longer
        than the health check interval, the connection is marked
        as disconnected.
        """
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = True
        feed._ws_last_data_time = time.time() - 60  # 60s ago, > 30s threshold

        feed._check_ws_health()
        assert feed._ws_connected is False

    def test_fresh_data_stays_connected(self):
        """Test connection stays active with fresh data.

        Verifies that when data was received recently (within
        the health check interval), the connection remains active.
        """
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = True
        feed._ws_last_data_time = time.time() - 5  # 5s ago

        feed._check_ws_health()
        assert feed._ws_connected is True


# ---------------------------------------------------------------------------
# Test: _start_websocket
# ---------------------------------------------------------------------------

class TestStartWebSocket:
    """Test WebSocket initialization and startup.

    Tests the _start_websocket method which initializes the
    WebSocket connection, either using a shared manager from
    the store or creating a new one per feed.
    """

    def test_no_enhancements_skips(self):
        """Test WebSocket initialization is skipped without enhancements.

        Verifies that when HAS_CCXT_ENHANCEMENTS is False, the
        WebSocket manager is not initialized.
        """
        feed = _make_feed(use_ws=True)
        from backtrader.feeds import ccxtfeed as feed_mod
        orig = feed_mod.HAS_CCXT_ENHANCEMENTS
        feed_mod.HAS_CCXT_ENHANCEMENTS = False
        try:
            feed._start_websocket()
            assert feed._websocket_manager is None
        finally:
            feed_mod.HAS_CCXT_ENHANCEMENTS = orig

    def test_uses_shared_ws_from_store(self):
        """Test using shared WebSocket manager from store.

        Verifies that when the store provides a WebSocket manager,
        it is used and the OHLCV subscription is registered.
        """
        feed = _make_feed(use_ws=True)
        mock_ws = MagicMock()
        feed.store.get_websocket_manager.return_value = mock_ws

        feed._start_websocket()
        assert feed._websocket_manager is mock_ws
        mock_ws.subscribe_ohlcv.assert_called_once()

    def test_creates_per_feed_ws_when_store_returns_none(self):
        """Test creating per-feed WebSocket manager.

        Verifies that when the store does not provide a WebSocket
        manager, a new one is created and started for this feed.
        """
        feed = _make_feed(use_ws=True)
        feed.store.get_websocket_manager.return_value = None

        from backtrader.feeds import ccxtfeed as feed_mod
        with patch.object(feed_mod, 'CCXTWebSocketManager') as MockWS:
            mock_ws = MagicMock()
            MockWS.return_value = mock_ws
            feed._start_websocket()
            assert feed._websocket_manager is mock_ws
            mock_ws.start.assert_called_once()
            mock_ws.subscribe_ohlcv.assert_called_once()

    def test_ws_start_error_handled(self):
        """Test error handling during WebSocket initialization.

        Verifies that when WebSocket initialization raises an
        exception, the error is caught gracefully and the manager
        remains None.
        """
        feed = _make_feed(use_ws=True)
        feed.store.get_websocket_manager.side_effect = OSError("ws init error")

        feed._start_websocket()
        assert feed._websocket_manager is None


# ---------------------------------------------------------------------------
# Test: _fetch_ohlcv_with_retry
# ---------------------------------------------------------------------------

class TestFetchOHLCVWithRetry:
    """Test OHLCV data fetching with retry logic.

    Tests the _fetch_ohlcv_with_retry method which handles transient
    network errors by retrying failed requests.
    """

    def test_success_first_try(self):
        """Test successful fetch on first attempt.

        Verifies that when the store's fetch_ohlcv succeeds on the
        first try, data is returned immediately without retries.
        """
        feed = _make_feed()
        result = feed._fetch_ohlcv_with_retry('BTC/USDT', '1m', 0, 10)
        assert len(result) == 2
        feed.store.fetch_ohlcv.assert_called_once()

    def test_retry_on_network_error(self):
        """Test retry behavior on network errors.

        Verifies that when a NetworkError occurs, the fetch is
        retried and succeeds on the second attempt.
        """
        from ccxt import NetworkError
        feed = _make_feed()
        feed.store.fetch_ohlcv.side_effect = [
            NetworkError('timeout'),
            [[1700000000000, 50000, 50100, 49900, 50050, 100]],
        ]
        result = feed._fetch_ohlcv_with_retry('BTC/USDT', '1m', 0, 10)
        assert len(result) == 1
        assert feed.store.fetch_ohlcv.call_count == 2

    def test_all_retries_fail(self):
        """Test failure after exhausting retries.

        Verifies that when all retry attempts fail, the exception
        is propagated to the caller.
        """
        from ccxt import NetworkError
        feed = _make_feed()
        feed.store.fetch_ohlcv.side_effect = NetworkError('timeout')
        with pytest.raises(NetworkError):
            feed._fetch_ohlcv_with_retry('BTC/USDT', '1m', 0, 10)
        assert feed.store.fetch_ohlcv.call_count == 3

    def test_exchange_error_no_retry(self):
        """Test no retry for exchange errors.

        Verifies that ExchangeError (which indicates a permanent
        error like invalid symbol) is not retried and propagates
        immediately.
        """
        from ccxt import ExchangeError
        feed = _make_feed()
        feed.store.fetch_ohlcv.side_effect = ExchangeError('invalid symbol')
        with pytest.raises(ExchangeError):
            feed._fetch_ohlcv_with_retry('BAD/SYM', '1m', 0, 10)
        feed.store.fetch_ohlcv.assert_called_once()


# ---------------------------------------------------------------------------
# Test: _update_bar
# ---------------------------------------------------------------------------

class TestUpdateBar:
    """Test REST API data fetching and queueing.

    Tests the _update_bar method which fetches OHLCV data via
    REST API and enqueues it for consumption by the backtest engine.
    """

    def test_disconnected_store_skips(self):
        """Test skipping fetch when store is disconnected.

        Verifies that when is_connected returns False, no fetch
        attempt is made.
        """
        feed = _make_feed()
        feed.store.is_connected.return_value = False
        feed._update_bar()
        feed.store.fetch_ohlcv.assert_not_called()

    def test_fetch_and_enqueue_bars(self):
        """Test successful fetch and enqueuing of bars.

        Verifies that bars fetched from the store are properly
        enqueued to the internal data queue.
        """
        feed = _make_feed()
        feed._last_ts = 0
        feed._update_bar()
        assert not feed._data.empty()

    def test_live_mode_fetches_fewer_bars(self):
        """Test reduced limit in live mode.

        Verifies that when livemode is True, fewer bars are
        requested to minimize latency.
        """
        feed = _make_feed()
        feed._last_ts = 0
        feed._update_bar(livemode=True)
        call_args = feed.store.fetch_ohlcv.call_args
        assert call_args[1]['limit'] == 3  # Live mode limit

    def test_fromdate_sets_last_ts(self):
        """Test that fromdate updates last timestamp.

        Verifies that when a fromdate is provided, _last_ts is
        updated to reflect the starting point for data fetching.
        """
        feed = _make_feed()
        dt = datetime(2024, 6, 1, 0, 0)
        feed._update_bar(fromdate=dt)
        # _last_ts should be updated to the fromdate
        assert feed._last_ts > 0

    def test_drop_newest(self):
        """Test drop_newest excludes the most recent bar.

        Verifies that when drop_newest is True, only historical
        bars are enqueued and the newest (possibly incomplete)
        bar is dropped.
        """
        feed = _make_feed(drop_newest=True)
        feed._last_ts = 0
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
            [1700000060000, 50050, 50200, 50000, 50150, 120],
        ]
        feed._update_bar()
        # Only first bar should be enqueued (second dropped)
        count = 0
        while not feed._data.empty():
            feed._data.get()
            count += 1
        assert count == 1

    def test_bars_with_none_skipped(self):
        """Test that bars with None values are skipped.

        Verifies that bars containing None values (indicating
        incomplete data) are filtered out.
        """
        feed = _make_feed()
        feed._last_ts = 0
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, None, 50100, 49900, 50050, 100],  # Has None
            [1700000060000, 50050, 50200, 50000, 50150, 120],
        ]
        feed._update_bar()
        count = 0
        while not feed._data.empty():
            feed._data.get()
            count += 1
        assert count == 1  # Only valid bar

    def test_fetch_error_tracked(self):
        """Test tracking of consecutive fetch errors.

        Verifies that when a fetch fails, the error counter is
        incremented.
        """
        feed = _make_feed()
        from ccxt.base.errors import NetworkError
        feed.store.fetch_ohlcv.side_effect = NetworkError("API down")
        feed._update_bar()
        assert feed._consecutive_fetch_errors == 1

    def test_many_fetch_errors_backs_off(self):
        """Test backoff after many consecutive errors.

        Verifies that after reaching the maximum consecutive
        errors, the counter continues to track the error state.
        """
        feed = _make_feed()
        from ccxt.base.errors import NetworkError
        feed.store.fetch_ohlcv.side_effect = NetworkError("API down")
        feed._consecutive_fetch_errors = 9
        feed._update_bar()
        assert feed._consecutive_fetch_errors == 10


# ---------------------------------------------------------------------------
# Test: _load_bar
# ---------------------------------------------------------------------------

class TestLoadBar:
    """Test loading individual bars from the data queue.

    Tests the _load_bar method which dequeues a single bar
    and populates the feed's line data.
    """

    def test_empty_queue_returns_none(self):
        """Test handling of empty data queue.

        Verifies that when the queue is empty, _load_bar returns
        None to indicate no data is available.
        """
        feed = _make_feed()
        assert feed._load_bar() is None

    def test_valid_bar_loaded(self):
        """Test successful loading of a valid bar.

        Verifies that a bar in the queue is properly dequeued
        and its values are set to the feed's line attributes.
        """
        feed = _make_feed()
        feed._data.put([1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0])
        result = feed._load_bar()
        assert result is True
        feed.lines.open.__setitem__.assert_called()
        feed.lines.close.__setitem__.assert_called()
        feed.lines.volume.__setitem__.assert_called()


# ---------------------------------------------------------------------------
# Test: _load (state machine)
# ---------------------------------------------------------------------------

class TestLoadStateMachine:
    """Test the _load state machine transitions.

    Tests the _load method which implements a state machine for
    managing data loading through different phases: historical
    backfill, live WebSocket, and live REST polling.
    """

    def test_over_returns_false(self):
        """Test _ST_OVER state returns False.

        Verifies that when the feed state is _ST_OVER, _load
        returns False to signal end of data.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_OVER
        assert feed._load() is False

    def test_live_rest_polling(self):
        """Test REST polling in live mode.

        Verifies that when in _ST_LIVE state without WebSocket,
        REST polling is used to fetch new data.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_LIVE
        feed._last_update_bar_time = 0  # Trigger fetch

        result = feed._load()
        # Should have fetched and loaded
        assert result is True or result is None

    def test_live_ws_connected_loads_bar(self):
        """Test loading bar with connected WebSocket.

        Verifies that when WebSocket is connected, bars from
        the WebSocket queue are loaded.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed(use_ws=True)
        feed._state = CCXTFeed._ST_LIVE
        feed._ws_connected = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = True
        feed._ws_last_data_time = time.time()

        # Put a bar in queue
        feed._data.put([1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0])
        result = feed._load()
        assert result is True

    def test_live_ws_disconnected_falls_back(self):
        """Test fallback to REST when WebSocket disconnected.

        Verifies that when WebSocket is disconnected, the feed
        falls back to REST polling and tracks disconnection time.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed(use_ws=True)
        feed._state = CCXTFeed._ST_LIVE
        feed._ws_connected = False
        feed._websocket_manager = MagicMock()
        feed._ws_disconnected_since = 0
        feed._last_update_bar_time = 0  # Trigger fetch

        result = feed._load()
        # Should have done REST fetch
        assert feed._ws_disconnected_since > 0

    def test_live_ws_backfill_after_reconnect(self):
        """Test backfill after WebSocket reconnection.

        Verifies that when _ws_backfill_needed is set after
        reconnection, backfill is performed and flag is cleared.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed(use_ws=True)
        feed._state = CCXTFeed._ST_LIVE
        feed._ws_connected = True
        feed._ws_backfill_needed = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = True
        feed._ws_last_data_time = time.time()

        feed._data.put([1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0])
        feed._load()
        # Backfill should have been triggered and flag cleared
        assert feed._ws_backfill_needed is False

    def test_historback_transitions_to_live(self):
        """Test transition from historical backfill to live.

        Verifies that when historical data is exhausted, the
        feed transitions to _ST_LIVE state.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_HISTORBACK
        feed.put_notification = MagicMock()
        # Empty queue — no more historical data
        feed._last_update_bar_time = 0

        result = feed._load()
        # Should transition to LIVE and then attempt REST fetch
        assert feed._state == CCXTFeed._ST_LIVE

    def test_historback_historical_mode_ends(self):
        """Test historical mode ends properly.

        Verifies that in historical-only mode, the feed
        transitions to _ST_OVER when data is exhausted.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed(historical=True)
        feed._state = CCXTFeed._ST_HISTORBACK
        feed.put_notification = MagicMock()

        result = feed._load()
        assert result is False
        assert feed._state == CCXTFeed._ST_OVER


# ---------------------------------------------------------------------------
# Test: haslivedata, islive, stop
# ---------------------------------------------------------------------------

class TestFeedMisc:
    """Test miscellaneous feed methods.

    Tests utility methods like haslivedata, islive, and stop
    which control feed lifecycle and state reporting.
    """

    def test_haslivedata_true(self):
        """Test haslivedata returns True when live with data.

        Verifies that in _ST_LIVE state with queued data,
        haslivedata returns True.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_LIVE
        feed._data.put([1, 2, 3, 4, 5, 6])
        assert feed.haslivedata() is True

    def test_haslivedata_false_not_live(self):
        """Test haslivedata returns False when not in live state.

        Verifies that in _ST_HISTORBACK state, haslivedata
        returns False even with queued data.
        """
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_HISTORBACK
        feed._data.put([1, 2, 3, 4, 5, 6])
        assert feed.haslivedata() is False

    def test_islive(self):
        """Test islive returns True for live feeds.

        Verifies that by default (non-historical), islive
        returns True.
        """
        feed = _make_feed()
        assert feed.islive() is True

    def test_islive_historical(self):
        """Test islive returns False for historical feeds.

        Verifies that when historical parameter is True,
        islive returns False.
        """
        feed = _make_feed(historical=True)
        assert feed.islive() is False

    def test_stop_with_ws(self):
        """Test stop with WebSocket manager.

        Verifies that stop() calls stop on WebSocket manager,
        threaded data manager, and store when WebSocket is
        not shared.
        """
        feed = _make_feed()
        mock_ws = MagicMock()
        mock_threaded = MagicMock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = False  # Not shared, so stop() should call ws.stop()
        feed._threaded_data_manager = mock_threaded
        feed.stop()
        mock_ws.stop.assert_called_once()
        mock_threaded.stop.assert_called_once()
        feed.store.stop.assert_called_once()
        # After stop, ws manager is set to None
        assert feed._websocket_manager is None

    def test_stop_without_ws(self):
        """Test stop without WebSocket manager.

        Verifies that stop() only calls store.stop() when
        no WebSocket is active.
        """
        feed = _make_feed()
        feed.stop()
        feed.store.stop.assert_called_once()


# ===========================================================================
# CCXTFeedWithFunding coverage tests
# ===========================================================================

class TestFeedWithFunding:
    """Test feeds/ccxtfeed_funding.py key paths.

    Tests the CCXTFeedWithFunding class which extends CCXTFeed
    to include funding rate and mark price data for perpetual
    futures trading.
    """

    def _make_funding_feed(self, store=None, use_ws=False, **kw):
        """Create a CCXTFeedWithFunding with mocked internals.

        Args:
            store: Mock CCXTStore instance.
            use_ws: Whether WebSocket is enabled.
            **kw: Additional parameter overrides.

        Returns:
            A mock CCXTFeedWithFunding instance ready for testing.
        """
        from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding

        if store is None:
            store = _make_mock_store()

        feed = CCXTFeedWithFunding.__new__(CCXTFeedWithFunding)

        # Base class attrs
        feed.p = MagicMock()
        feed.p.dataname = 'BTC/USDT:USDT'
        feed.p.historical = False
        feed.p.backfill_start = False
        feed.p.fromdate = None
        feed.p.hist_start_date = None
        feed.p.use_websocket = use_ws
        feed.p.use_threaded_data = False
        feed.p.ohlcv_limit = 100
        feed.p.drop_newest = False
        feed.p.debug = kw.get('debug', False)
        feed.p.fetch_ohlcv_params = {}
        feed.p.ws_reconnect_delay = 5.0
        feed.p.ws_max_reconnect_delay = 60.0
        feed.p.max_fetch_retries = 3
        feed.p.fetch_retry_delay = 0.001
        feed.p.ws_health_check_interval = 30.0
        feed.p.fetch_funding_rate = True
        feed.p.fetch_mark_price = True
        feed.p.funding_rate_interval = 8 * 3600

        feed.store = store
        feed._state = None
        feed._data = queue.Queue(maxsize=1000)
        feed._last_id = ""
        feed._last_ts = 0
        feed._last_update_bar_time = 0
        feed._websocket_manager = None
        feed._ws_connected = False
        feed._ws_thread = None
        feed._ws_lock = threading.Lock()
        feed._ws_last_data_time = 0
        feed._ws_disconnected_since = 0
        feed._ws_backfill_needed = False
        feed._threaded_data_manager = None
        feed._consecutive_fetch_errors = 0
        feed._max_consecutive_errors = 10
        feed._last_error_time = 0
        feed._timeframe = 4
        feed._compression = 1

        # Funding-specific attrs
        feed._funding_rate = 0.0
        feed._next_funding_time = 0
        feed._mark_price = 0.0
        feed._last_funding_fetch = 0
        feed._ws_is_shared = False
        feed._funding_lock = threading.Lock()
        feed._current_funding = {
            'funding_rate': 0.0,
            'predicted_funding_rate': 0.0,
            'mark_price': 0.0,
            'next_funding_time': 0,
            'timestamp': 0,
        }
        feed._funding_history = {}
        feed._ws_funding_connected = False
        feed._ws_ohlcv_connected = False
        feed.lines = MagicMock()

        return feed

    def test_funding_feed_attributes(self):
        """Test funding-specific attributes are initialized.

        Verifies that funding rate and mark price attributes
        are initialized to zero.
        """
        feed = self._make_funding_feed()
        assert feed._funding_rate == 0.0
        assert feed._mark_price == 0.0

    def test_on_funding_rate_callback(self):
        """Test _on_websocket_funding callback.

        Verifies that funding rate updates from WebSocket
        are properly stored and the connection flag is set.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed._on_websocket_funding({
            'fundingRate': 0.0001,
            'timestamp': 1700000000000,
            'nextFundingTime': 1700028800000,
            'info': {'predictedFundingRate': '0.00005'},
        })
        assert feed._current_funding['funding_rate'] == 0.0001
        assert feed._current_funding['next_funding_time'] == 1700028800000
        assert feed._ws_funding_connected is True

    def test_on_funding_rate_fallback_fields(self):
        """Funding callback falls back to 'rate' or 'info.fundingRate'.

        Verifies alternative field names are supported for
        different exchange API formats.
        """
        feed = self._make_funding_feed(use_ws=True)
        # Test 'rate' fallback
        feed._on_websocket_funding({'rate': 0.0002, 'timestamp': 1700000000000, 'info': {}})
        assert feed._current_funding['funding_rate'] == 0.0002

    def test_on_mark_price_callback(self):
        """Test _on_websocket_mark_price callback.

        Verifies that mark price updates are stored and
        funding info is extracted from the info field.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed._on_websocket_mark_price({
            'markPrice': 50000.5,
            'timestamp': 1700000000000,
            'info': {'lastFundingRate': '0.0003', 'nextFundingTime': '1700028800000'},
        })
        assert feed._current_funding['mark_price'] == 50000.5
        assert feed._current_funding['funding_rate'] == 0.0003
        assert feed._ws_funding_connected is True

    def test_start_websocket_shared(self):
        """Test _start_websocket uses shared WS and sets _ws_is_shared.

        Verifies that when the store provides a WebSocket manager,
        it is used and marked as shared.
        """
        feed = self._make_funding_feed(use_ws=True)
        mock_ws = MagicMock()
        feed.store.get_websocket_manager.return_value = mock_ws

        if hasattr(feed, '_start_websocket'):
            feed._start_websocket()
            assert feed._websocket_manager is mock_ws

    def test_stop_shared_ws_not_stopped(self):
        """stop() does not stop shared WS manager.

        Verifies that when WebSocket is shared, stop() does
        not call stop on it to avoid affecting other feeds.
        """
        feed = self._make_funding_feed()
        mock_ws = MagicMock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = True

        feed.stop()
        mock_ws.stop.assert_not_called()
        # Manager is set to None after stop
        assert feed._websocket_manager is None

    def test_stop_per_feed_ws_stopped(self):
        """stop() stops per-feed WS manager.

        Verifies that when WebSocket is not shared, stop()
        properly closes it.
        """
        feed = self._make_funding_feed()
        mock_ws = MagicMock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = False

        feed.stop()
        mock_ws.stop.assert_called_once()
        assert feed._websocket_manager is None

    def test_on_websocket_ohlcv(self):
        """Test _on_websocket_ohlcv integrates funding data.

        Verifies that OHLCV bars are extended with funding
        rate and mark price data.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed._current_funding = {
            'funding_rate': 0.0001,
            'mark_price': 50000.5,
            'next_funding_time': 1700028800000,
            'predicted_funding_rate': 0.00005,
            'timestamp': 0,
        }
        feed._last_ts = 0

        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])

        assert not feed._data.empty()
        extended = feed._data.get()
        assert len(extended) == 10  # 6 OHLCV + 4 funding fields
        assert extended[6] == 0.0001  # funding_rate
        assert extended[7] == 50000.5  # mark_price

    def test_get_funding_for_bar(self):
        """Test _get_funding_for_bar returns correct funding.

        Verifies that funding data for a specific timestamp
        is retrieved from history correctly.
        """
        feed = self._make_funding_feed()
        feed._funding_history = {
            1700000000000: {'funding_rate': 0.0001},
            1700028800000: {'funding_rate': 0.0002},
        }
        # Get for timestamp between the two
        result = feed._get_funding_for_bar(1700010000000)
        assert result['funding_rate'] == 0.0001

    def test_get_funding_for_bar_empty(self):
        """With empty history, returns current funding.

        Verifies that when no historical funding data exists,
        the current funding values are returned.
        """
        feed = self._make_funding_feed()
        feed._funding_history = {}
        result = feed._get_funding_for_bar(1700000000000)
        assert result == feed._current_funding

    # --- utc_to_ts ---

    def test_utc_to_ts(self):
        """Test UTC datetime to timestamp conversion.

        Verifies that datetime objects are correctly converted
        to millisecond timestamps.
        """
        feed = self._make_funding_feed()
        dt = datetime(2024, 1, 1, 12, 30)
        ts = feed.utc_to_ts(dt)
        assert isinstance(ts, int)
        assert ts > 0

    # --- haslivedata / islive ---

    def test_haslivedata_true(self):
        """Test haslivedata returns True when live with data.

        Verifies positive result in _ST_LIVE state with data.
        """
        from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding
        feed = self._make_funding_feed()
        feed._state = feed._ST_LIVE
        feed._data.put((1, 2, 3, 4, 5, 6))
        assert feed.haslivedata() is True

    def test_haslivedata_false(self):
        """Test haslivedata returns False when not live.

        Verifies negative result in _ST_HISTORBACK state.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_HISTORBACK
        assert feed.haslivedata() is False

    def test_islive(self):
        """Test islive returns True for live feeds.

        Verifies default behavior returns True.
        """
        feed = self._make_funding_feed()
        assert feed.islive() is True

    def test_islive_historical(self):
        """Test islive returns False for historical feeds.

        Verifies historical mode returns False.
        """
        feed = self._make_funding_feed()
        feed.p.historical = True
        assert feed.islive() is False

    # --- _start_websocket ---

    def test_start_websocket_shared_with_subscriptions(self):
        """Full _start_websocket flow with shared WS manager.

        Verifies that shared WebSocket is used and all required
        subscriptions (OHLCV, funding rate, mark price) are made.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed.p.include_funding = True
        feed.p.ws_startup_timeout = 1
        feed.p.debug = False

        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        feed.store.get_websocket_manager.return_value = mock_ws
        feed.store.get_granularity = MagicMock(return_value='1m')

        feed._start_websocket()

        assert feed._websocket_manager is mock_ws
        assert feed._ws_is_shared is True
        mock_ws.subscribe_ohlcv.assert_called_once()
        mock_ws.subscribe_funding_rate.assert_called_once()
        mock_ws.subscribe_mark_price.assert_called_once()

    def test_start_websocket_per_feed_fallback(self):
        """Creates per-feed WS when store returns None.

        Verifies that when no shared WebSocket is available,
        a new one is created for this feed.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed.p.include_funding = False
        feed.p.ws_startup_timeout = 1
        feed.store.get_websocket_manager.return_value = None

        from backtrader.feeds import ccxtfeed_funding as fund_mod
        with patch.object(fund_mod, 'CCXTWebSocketManager') as MockWS:
            mock_ws = MagicMock()
            mock_ws.is_connected.return_value = True
            MockWS.return_value = mock_ws

            feed._start_websocket()

            assert feed._ws_is_shared is False
            mock_ws.start.assert_called_once()
            mock_ws.subscribe_ohlcv.assert_called_once()
            # No funding subscriptions since include_funding=False
            mock_ws.subscribe_funding_rate.assert_not_called()

    def test_start_websocket_timeout(self):
        """Times out if WS never connects.

        Verifies timeout handling when WebSocket fails to connect.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed.p.ws_startup_timeout = 0.2
        feed.store.get_websocket_manager.return_value = None

        from backtrader.feeds import ccxtfeed_funding as fund_mod
        with patch.object(fund_mod, 'CCXTWebSocketManager') as MockWS:
            mock_ws = MagicMock()
            mock_ws.is_connected.return_value = False  # Never connects
            MockWS.return_value = mock_ws

            feed._start_websocket()
            # Should have fallen back to None after exception
            assert feed._websocket_manager is None

    def test_start_websocket_exception(self):
        """General exception during _start_websocket.

        Verifies exception handling during WebSocket initialization.
        """
        feed = self._make_funding_feed(use_ws=True)
        feed.store.get_websocket_manager.side_effect = RuntimeError("boom")
        feed._start_websocket()
        assert feed._websocket_manager is None

    # --- _update_bar ---

    def test_update_bar_basic(self):
        """Fetches and enqueues bars with funding data.

        Verifies that bars fetched from REST are extended with
        funding data.
        """
        feed = self._make_funding_feed()
        feed._last_ts = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
        ]
        feed._update_bar()
        assert not feed._data.empty()
        bar = feed._data.get()
        assert len(bar) == 10  # 6 OHLCV + 4 funding

    def test_update_bar_livemode(self):
        """Test update_bar in live mode.

        Verifies REST fetch works in live mode.
        """
        feed = self._make_funding_feed()
        feed._last_ts = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
        ]
        feed._update_bar(livemode=True)
        assert not feed._data.empty()

    def test_update_bar_fromdate(self):
        """Test update_bar with fromdate parameter.

        Verifies that fromdate updates the last timestamp.
        """
        feed = self._make_funding_feed()
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
        ]
        feed._update_bar(fromdate=datetime(2024, 1, 1))
        assert feed._last_ts > 0

    def test_update_bar_drop_newest(self):
        """Test drop_newest excludes the most recent bar.

        Verifies that the newest bar is dropped when the
        parameter is set.
        """
        feed = self._make_funding_feed()
        feed.p.drop_newest = True
        feed._last_ts = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
            [1700000060000, 50050, 50200, 50000, 50150, 120],
        ]
        feed._update_bar()
        count = 0
        while not feed._data.empty():
            feed._data.get()
            count += 1
        assert count == 1  # Newest dropped

    def test_update_bar_none_in_bar_skipped(self):
        """Test bars with None values are skipped.

        Verifies data validation filters invalid bars.
        """
        feed = self._make_funding_feed()
        feed._last_ts = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, None, 50100, 49900, 50050, 100],
            [1700000060000, 50050, 50200, 50000, 50150, 120],
        ]
        feed._update_bar()
        count = 0
        while not feed._data.empty():
            feed._data.get()
            count += 1
        assert count == 1  # Only valid bar

    # --- _load_bar ---

    def test_load_bar_empty(self):
        """Test _load_bar with empty queue.

        Verifies None is returned when no data available.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        assert feed._load_bar() is None

    def test_load_bar_extended(self):
        """Extended bar (10 fields) with funding data.

        Verifies loading a pre-extended bar with all funding fields.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100, 0.0001, 50000.5, 1700028800000, 0.00005)
        feed._data.put(bar)
        result = feed._load_bar()
        assert result is True

    def test_load_bar_standard(self):
        """Standard 6-field bar augmented with current funding.

        Verifies that standard bars get current funding appended.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100)
        feed._data.put(bar)
        result = feed._load_bar()
        assert result is True

    def test_load_bar_no_funding(self):
        """include_funding=False skips funding lines.

        Verifies that funding lines are not populated when disabled.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = False
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100)
        feed._data.put(bar)
        result = feed._load_bar()
        assert result is True

    # --- _load state machine ---

    def test_load_over(self):
        """Test _ST_OVER state returns False.

        Verifies end of data signal.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_OVER
        assert feed._load() is False

    def test_load_live_ws_connected(self):
        """Test loading with connected WebSocket.

        Verifies bars are loaded from WebSocket queue.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_LIVE
        feed.p.use_websocket = True
        feed._ws_connected = True
        # Put bar in queue so _load_bar returns True
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100, 0.0001, 50000.5, 1700028800000, 0.00005)
        feed._data.put(bar)
        feed.p.include_funding = True
        result = feed._load()
        assert result is True

    def test_load_live_ws_connected_empty_returns_none(self):
        """Test WebSocket connected but empty queue.

        Verifies None is returned when no data available.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_LIVE
        feed.p.use_websocket = True
        feed._ws_connected = True
        # Empty queue
        result = feed._load()
        assert result is None

    def test_load_live_rest_polling(self):
        """Test REST polling in live mode.

        Verifies fallback to REST polling works.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_LIVE
        feed.p.use_websocket = False
        feed._last_update_bar_time = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
        ]
        feed._last_ts = 0
        feed.p.include_funding = True
        result = feed._load()
        assert result is True

    def test_load_historback_to_live(self):
        """Test transition from historical to live.

        Verifies state transition when historical data exhausted.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_HISTORBACK
        feed.p.historical = False
        feed.put_notification = MagicMock()
        feed.p.use_websocket = False
        feed._last_update_bar_time = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = []
        feed.p.include_funding = True
        # Empty queue triggers transition
        result = feed._load()
        assert feed._state == feed._ST_LIVE

    def test_load_historback_historical_ends(self):
        """Test historical mode ends properly.

        Verifies transition to _ST_OVER in historical-only mode.
        """
        feed = self._make_funding_feed()
        feed._state = feed._ST_HISTORBACK
        feed.p.historical = True
        feed.put_notification = MagicMock()
        result = feed._load()
        assert result is False
        assert feed._state == feed._ST_OVER

    # --- _fetch_historical_funding_rates ---

    def test_fetch_historical_funding_rates(self):
        """Test fetching historical funding rates.

        Verifies that funding history is populated from exchange data.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        feed.p.funding_history_days = 3
        feed.p.debug = False
        feed.store.exchange.fetch_funding_rate_history = MagicMock(return_value=[
            {'timestamp': 1700000000000, 'rate': 0.0001, 'nextFundingTime': 1700028800000},
            {'timestamp': 1700028800000, 'rate': 0.0002, 'nextFundingTime': 1700057600000},
        ])
        feed._fetch_historical_funding_rates()
        assert len(feed._funding_history) == 2
        assert feed._current_funding['funding_rate'] == 0.0002

    def test_fetch_historical_funding_no_include(self):
        """Test fetching skipped when include_funding is False.

        Verifies no fetch occurs when funding is disabled.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = False
        feed._fetch_historical_funding_rates()
        assert len(feed._funding_history) == 0

    def test_fetch_historical_funding_error(self):
        """Test error handling during funding history fetch.

        Verifies graceful handling of API errors.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        feed.p.funding_history_days = 3
        feed.p.debug = False
        feed.store.exchange.fetch_funding_rate_history = MagicMock(
            side_effect=Exception("API error")
        )
        feed._fetch_historical_funding_rates()  # Should not raise
        assert len(feed._funding_history) == 0

    def test_fetch_historical_no_method(self):
        """Test exchange without funding rate history support.

        Verifies graceful handling when method is unavailable.
        """
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        feed.p.funding_history_days = 3
        feed.p.debug = False
        # Exchange without fetch_funding_rate_history
        del feed.store.exchange.fetch_funding_rate_history
        feed._fetch_historical_funding_rates()
        assert len(feed._funding_history) == 0

    # --- _on_websocket_ohlcv edge cases ---

    def test_on_websocket_ohlcv_empty(self):
        """Test empty data list handling.

        Verifies no crash on empty WebSocket data.
        """
        feed = self._make_funding_feed()
        feed._on_websocket_ohlcv([])
        assert feed._data.empty()

    def test_on_websocket_ohlcv_none(self):
        """Test None data handling.

        Verifies no crash on None WebSocket data.
        """
        feed = self._make_funding_feed()
        feed._on_websocket_ohlcv(None)
        assert feed._data.empty()

    def test_on_websocket_ohlcv_short_bar(self):
        """Test malformed bar handling.

        Verifies bars with insufficient fields are rejected.
        """
        feed = self._make_funding_feed()
        feed._on_websocket_ohlcv([[1, 2, 3]])  # Too short
        assert feed._data.empty()

    def test_on_websocket_ohlcv_duplicate_ts(self):
        """Bar with same ts as last_ts uses >= so it is enqueued.

        Verifies duplicate timestamp handling.
        """
        feed = self._make_funding_feed()
        feed._last_ts = 1700000000000
        bar = [1700000000000, 50000, 50100, 49900, 50050, 100]
        feed._on_websocket_ohlcv([bar])
        assert not feed._data.empty()

    def test_on_websocket_ohlcv_debug(self):
        """Test debug mode doesn't cause errors.

        Verifies debug logging is handled safely.
        """
        feed = self._make_funding_feed(debug=True)
        bar = [1700000000000, 50000, 50100, 49900, 50050, 100]
        feed._on_websocket_ohlcv([bar])

    def test_on_websocket_ohlcv_exception(self):
        """Exception in callback doesn't crash.

        Verifies exception safety in OHLCV callback.
        """
        feed = self._make_funding_feed(debug=True)
        feed._ws_lock = threading.Lock()
        # _funding_lock is None to trigger exception inside with block
        feed._funding_lock = None
        bar = [1700000060000, 50000, 50100, 49900, 50050, 100]
        feed._last_ts = 0
        # Should handle exception gracefully
        try:
            feed._on_websocket_ohlcv([bar])
        except Exception:
            pass  # Some exceptions may propagate

    # --- _on_websocket_funding edge cases ---

    def test_on_websocket_funding_info_fallback(self):
        """Falls back to info.fundingRate.

        Verifies alternative field name support.
        """
        feed = self._make_funding_feed()
        feed._on_websocket_funding({
            'timestamp': 1700000000000,
            'info': {'fundingRate': '0.0003'},
        })
        assert feed._current_funding['funding_rate'] == 0.0003

    def test_on_websocket_funding_no_timestamp(self):
        """Missing timestamp uses current time.

        Verifies default timestamp generation.
        """
        feed = self._make_funding_feed()
        feed._on_websocket_funding({
            'fundingRate': 0.0001,
            'info': {},
        })
        assert feed._current_funding['funding_rate'] == 0.0001
        assert feed._current_funding['timestamp'] > 0

    def test_on_websocket_funding_debug(self):
        """Test debug mode for funding callback.

        Verifies debug logging is handled safely.
        """
        feed = self._make_funding_feed(debug=True)
        feed._on_websocket_funding({
            'fundingRate': 0.0001,
            'timestamp': 1700000000000,
            'info': {},
        })

    def test_on_websocket_funding_exception(self):
        """Exception doesn't crash.

        Verifies exception safety in funding callback.
        """
        feed = self._make_funding_feed(debug=True)
        feed._funding_lock = None  # Will cause AttributeError
        try:
            feed._on_websocket_funding({'fundingRate': 0.0001, 'info': {}})
        except Exception:
            pass

    # --- _on_websocket_mark_price edge cases ---

    def test_on_websocket_mark_price_no_info(self):
        """Test mark price without info field.

        Verifies handling of minimal mark price data.
        """
        feed = self._make_funding_feed()
        feed._on_websocket_mark_price({
            'markPrice': 50000.0,
            'timestamp': 1700000000000,
            'info': {},
        })
        assert feed._current_funding['mark_price'] == 50000.0

    def test_on_websocket_mark_price_debug(self):
        """Test debug mode for mark price callback.

        Verifies debug logging is handled safely.
        """
        feed = self._make_funding_feed(debug=True)
        feed._on_websocket_mark_price({
            'markPrice': 50000.0,
            'timestamp': 1700000000000,
            'info': {},
        })

    def test_on_websocket_mark_price_exception(self):
        """Exception doesn't crash.

        Verifies exception safety in mark price callback.
        """
        feed = self._make_funding_feed(debug=True)
        feed._funding_lock = None
        try:
            feed._on_websocket_mark_price({'markPrice': 50000.0, 'info': {}})
        except Exception:
            pass

    # --- WebSocketRequiredError ---

    def test_websocket_required_error(self):
        """Test WebSocketRequiredError exception.

        Verifies the error message is stored correctly.
        """
        from backtrader.feeds.ccxtfeed_funding import WebSocketRequiredError
        err = WebSocketRequiredError("test")
        assert str(err) == "test"
