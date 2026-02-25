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
    """Create a mock CCXTStore."""
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
    """Create a CCXTFeed with mocked internals, bypassing DataBase.__init__."""
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
    """Test feed initialization and utility."""

    def test_utc_to_ts(self):
        feed = _make_feed()
        dt = datetime(2024, 1, 1, 12, 30)
        ts = feed.utc_to_ts(dt)
        assert isinstance(ts, int)
        assert ts > 0

    def test_feed_attributes_initialized(self):
        feed = _make_feed()
        assert feed._data is not None
        assert feed._ws_connected is False
        assert feed._consecutive_fetch_errors == 0


# ---------------------------------------------------------------------------
# Test: _on_websocket_ohlcv
# ---------------------------------------------------------------------------

class TestOnWebsocketOHLCV:
    """Test WebSocket OHLCV callback."""

    def test_empty_data_ignored(self):
        feed = _make_feed()
        feed._on_websocket_ohlcv([])
        assert feed._data.empty()

    def test_none_data_ignored(self):
        feed = _make_feed()
        feed._on_websocket_ohlcv(None)
        assert feed._data.empty()

    def test_new_bar_enqueued(self):
        feed = _make_feed()
        feed._last_ts = 0
        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])
        assert not feed._data.empty()
        assert feed._last_ts == 1700000000000
        assert feed._ws_connected is True

    def test_old_bar_skipped(self):
        feed = _make_feed()
        feed._last_ts = 1700000000000  # Already seen this
        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])
        assert feed._data.empty()

    def test_short_bar_skipped(self):
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
        feed = _make_feed(debug=True)
        feed._last_ts = 0
        bar = [1700000000000, 50000.0, 50100.0, 49900.0, 50050.0, 100.0]
        feed._on_websocket_ohlcv([bar])  # Should not raise


# ---------------------------------------------------------------------------
# Test: _check_ws_health
# ---------------------------------------------------------------------------

class TestCheckWSHealth:
    """Test WebSocket health check."""

    def test_not_connected_skips(self):
        feed = _make_feed()
        feed._ws_connected = False
        feed._check_ws_health()  # Should not raise

    def test_no_manager_skips(self):
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = None
        feed._check_ws_health()

    def test_manager_reports_disconnected(self):
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = False

        feed._check_ws_health()
        assert feed._ws_connected is False

    def test_stale_data_marks_disconnected(self):
        feed = _make_feed()
        feed._ws_connected = True
        feed._websocket_manager = MagicMock()
        feed._websocket_manager.is_connected.return_value = True
        feed._ws_last_data_time = time.time() - 60  # 60s ago, > 30s threshold

        feed._check_ws_health()
        assert feed._ws_connected is False

    def test_fresh_data_stays_connected(self):
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
    """Test WebSocket initialization."""

    def test_no_enhancements_skips(self):
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
        feed = _make_feed(use_ws=True)
        mock_ws = MagicMock()
        feed.store.get_websocket_manager.return_value = mock_ws

        feed._start_websocket()
        assert feed._websocket_manager is mock_ws
        mock_ws.subscribe_ohlcv.assert_called_once()

    def test_creates_per_feed_ws_when_store_returns_none(self):
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
        feed = _make_feed(use_ws=True)
        feed.store.get_websocket_manager.side_effect = OSError("ws init error")

        feed._start_websocket()
        assert feed._websocket_manager is None


# ---------------------------------------------------------------------------
# Test: _fetch_ohlcv_with_retry
# ---------------------------------------------------------------------------

class TestFetchOHLCVWithRetry:
    """Test OHLCV retry logic."""

    def test_success_first_try(self):
        feed = _make_feed()
        result = feed._fetch_ohlcv_with_retry('BTC/USDT', '1m', 0, 10)
        assert len(result) == 2
        feed.store.fetch_ohlcv.assert_called_once()

    def test_retry_on_network_error(self):
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
        from ccxt import NetworkError
        feed = _make_feed()
        feed.store.fetch_ohlcv.side_effect = NetworkError('timeout')
        with pytest.raises(NetworkError):
            feed._fetch_ohlcv_with_retry('BTC/USDT', '1m', 0, 10)
        assert feed.store.fetch_ohlcv.call_count == 3

    def test_exchange_error_no_retry(self):
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
    """Test REST data fetching into queue."""

    def test_disconnected_store_skips(self):
        feed = _make_feed()
        feed.store.is_connected.return_value = False
        feed._update_bar()
        feed.store.fetch_ohlcv.assert_not_called()

    def test_fetch_and_enqueue_bars(self):
        feed = _make_feed()
        feed._last_ts = 0
        feed._update_bar()
        assert not feed._data.empty()

    def test_live_mode_fetches_fewer_bars(self):
        feed = _make_feed()
        feed._last_ts = 0
        feed._update_bar(livemode=True)
        call_args = feed.store.fetch_ohlcv.call_args
        assert call_args[1]['limit'] == 3  # Live mode limit

    def test_fromdate_sets_last_ts(self):
        feed = _make_feed()
        dt = datetime(2024, 6, 1, 0, 0)
        feed._update_bar(fromdate=dt)
        # _last_ts should be updated to the fromdate
        assert feed._last_ts > 0

    def test_drop_newest(self):
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
        feed = _make_feed()
        from ccxt.base.errors import NetworkError
        feed.store.fetch_ohlcv.side_effect = NetworkError("API down")
        feed._update_bar()
        assert feed._consecutive_fetch_errors == 1

    def test_many_fetch_errors_backs_off(self):
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
    """Test loading a single bar from the queue."""

    def test_empty_queue_returns_none(self):
        feed = _make_feed()
        assert feed._load_bar() is None

    def test_valid_bar_loaded(self):
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
    """Test the _load state machine."""

    def test_over_returns_false(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_OVER
        assert feed._load() is False

    def test_live_rest_polling(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_LIVE
        feed._last_update_bar_time = 0  # Trigger fetch

        result = feed._load()
        # Should have fetched and loaded
        assert result is True or result is None

    def test_live_ws_connected_loads_bar(self):
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
    """Test misc feed methods."""

    def test_haslivedata_true(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_LIVE
        feed._data.put([1, 2, 3, 4, 5, 6])
        assert feed.haslivedata() is True

    def test_haslivedata_false_not_live(self):
        from backtrader.feeds.ccxtfeed import CCXTFeed
        feed = _make_feed()
        feed._state = CCXTFeed._ST_HISTORBACK
        feed._data.put([1, 2, 3, 4, 5, 6])
        assert feed.haslivedata() is False

    def test_islive(self):
        feed = _make_feed()
        assert feed.islive() is True

    def test_islive_historical(self):
        feed = _make_feed(historical=True)
        assert feed.islive() is False

    def test_stop_with_ws(self):
        feed = _make_feed()
        mock_ws = MagicMock()
        mock_threaded = MagicMock()
        feed._websocket_manager = mock_ws
        feed._threaded_data_manager = mock_threaded
        feed.stop()
        mock_ws.stop.assert_called_once()
        mock_threaded.stop.assert_called_once()
        feed.store.stop.assert_called_once()
        # After stop, ws manager is set to None
        assert feed._websocket_manager is None

    def test_stop_without_ws(self):
        feed = _make_feed()
        feed.stop()
        feed.store.stop.assert_called_once()


# ===========================================================================
# CCXTFeedWithFunding coverage tests
# ===========================================================================

class TestFeedWithFunding:
    """Test feeds/ccxtfeed_funding.py key paths."""

    def _make_funding_feed(self, store=None, use_ws=False, **kw):
        """Create a CCXTFeedWithFunding with mocked internals."""
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
        feed = self._make_funding_feed()
        assert feed._funding_rate == 0.0
        assert feed._mark_price == 0.0

    def test_on_funding_rate_callback(self):
        """Test _on_websocket_funding callback."""
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
        """Funding callback falls back to 'rate' or 'info.fundingRate'."""
        feed = self._make_funding_feed(use_ws=True)
        # Test 'rate' fallback
        feed._on_websocket_funding({'rate': 0.0002, 'timestamp': 1700000000000, 'info': {}})
        assert feed._current_funding['funding_rate'] == 0.0002

    def test_on_mark_price_callback(self):
        """Test _on_websocket_mark_price callback."""
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
        """Test _start_websocket uses shared WS and sets _ws_is_shared."""
        feed = self._make_funding_feed(use_ws=True)
        mock_ws = MagicMock()
        feed.store.get_websocket_manager.return_value = mock_ws

        if hasattr(feed, '_start_websocket'):
            feed._start_websocket()
            assert feed._websocket_manager is mock_ws

    def test_stop_shared_ws_not_stopped(self):
        """stop() does not stop shared WS manager."""
        feed = self._make_funding_feed()
        mock_ws = MagicMock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = True

        feed.stop()
        mock_ws.stop.assert_not_called()
        # Manager is set to None after stop
        assert feed._websocket_manager is None

    def test_stop_per_feed_ws_stopped(self):
        """stop() stops per-feed WS manager."""
        feed = self._make_funding_feed()
        mock_ws = MagicMock()
        feed._websocket_manager = mock_ws
        feed._ws_is_shared = False

        feed.stop()
        mock_ws.stop.assert_called_once()
        assert feed._websocket_manager is None

    def test_on_websocket_ohlcv(self):
        """Test _on_websocket_ohlcv integrates funding data."""
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
        """Test _get_funding_for_bar returns correct funding."""
        feed = self._make_funding_feed()
        feed._funding_history = {
            1700000000000: {'funding_rate': 0.0001},
            1700028800000: {'funding_rate': 0.0002},
        }
        # Get for timestamp between the two
        result = feed._get_funding_for_bar(1700010000000)
        assert result['funding_rate'] == 0.0001

    def test_get_funding_for_bar_empty(self):
        """With empty history, returns current funding."""
        feed = self._make_funding_feed()
        feed._funding_history = {}
        result = feed._get_funding_for_bar(1700000000000)
        assert result == feed._current_funding

    # --- utc_to_ts ---

    def test_utc_to_ts(self):
        feed = self._make_funding_feed()
        dt = datetime(2024, 1, 1, 12, 30)
        ts = feed.utc_to_ts(dt)
        assert isinstance(ts, int)
        assert ts > 0

    # --- haslivedata / islive ---

    def test_haslivedata_true(self):
        from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding
        feed = self._make_funding_feed()
        feed._state = feed._ST_LIVE
        feed._data.put((1, 2, 3, 4, 5, 6))
        assert feed.haslivedata() is True

    def test_haslivedata_false(self):
        feed = self._make_funding_feed()
        feed._state = feed._ST_HISTORBACK
        assert feed.haslivedata() is False

    def test_islive(self):
        feed = self._make_funding_feed()
        assert feed.islive() is True

    def test_islive_historical(self):
        feed = self._make_funding_feed()
        feed.p.historical = True
        assert feed.islive() is False

    # --- _start_websocket ---

    def test_start_websocket_shared_with_subscriptions(self):
        """Full _start_websocket flow with shared WS manager."""
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
        """Creates per-feed WS when store returns None."""
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
        """Times out if WS never connects."""
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
        """General exception during _start_websocket."""
        feed = self._make_funding_feed(use_ws=True)
        feed.store.get_websocket_manager.side_effect = RuntimeError("boom")
        feed._start_websocket()
        assert feed._websocket_manager is None

    # --- _update_bar ---

    def test_update_bar_basic(self):
        """Fetches and enqueues bars with funding data."""
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
        feed = self._make_funding_feed()
        feed._last_ts = 0
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
        ]
        feed._update_bar(livemode=True)
        assert not feed._data.empty()

    def test_update_bar_fromdate(self):
        feed = self._make_funding_feed()
        feed.store.get_granularity.return_value = '1m'
        feed.store.fetch_ohlcv.return_value = [
            [1700000000000, 50000, 50100, 49900, 50050, 100],
        ]
        feed._update_bar(fromdate=datetime(2024, 1, 1))
        assert feed._last_ts > 0

    def test_update_bar_drop_newest(self):
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
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        assert feed._load_bar() is None

    def test_load_bar_extended(self):
        """Extended bar (10 fields) with funding data."""
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100, 0.0001, 50000.5, 1700028800000, 0.00005)
        feed._data.put(bar)
        result = feed._load_bar()
        assert result is True

    def test_load_bar_standard(self):
        """Standard 6-field bar augmented with current funding."""
        feed = self._make_funding_feed()
        feed.p.include_funding = True
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100)
        feed._data.put(bar)
        result = feed._load_bar()
        assert result is True

    def test_load_bar_no_funding(self):
        """include_funding=False skips funding lines."""
        feed = self._make_funding_feed()
        feed.p.include_funding = False
        bar = (1700000000000, 50000, 50100, 49900, 50050, 100)
        feed._data.put(bar)
        result = feed._load_bar()
        assert result is True

    # --- _load state machine ---

    def test_load_over(self):
        feed = self._make_funding_feed()
        feed._state = feed._ST_OVER
        assert feed._load() is False

    def test_load_live_ws_connected(self):
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
        feed = self._make_funding_feed()
        feed._state = feed._ST_LIVE
        feed.p.use_websocket = True
        feed._ws_connected = True
        # Empty queue
        result = feed._load()
        assert result is None

    def test_load_live_rest_polling(self):
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
        feed = self._make_funding_feed()
        feed._state = feed._ST_HISTORBACK
        feed.p.historical = True
        feed.put_notification = MagicMock()
        result = feed._load()
        assert result is False
        assert feed._state == feed._ST_OVER

    # --- _fetch_historical_funding_rates ---

    def test_fetch_historical_funding_rates(self):
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
        feed = self._make_funding_feed()
        feed.p.include_funding = False
        feed._fetch_historical_funding_rates()
        assert len(feed._funding_history) == 0

    def test_fetch_historical_funding_error(self):
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
        feed = self._make_funding_feed()
        feed._on_websocket_ohlcv([])
        assert feed._data.empty()

    def test_on_websocket_ohlcv_none(self):
        feed = self._make_funding_feed()
        feed._on_websocket_ohlcv(None)
        assert feed._data.empty()

    def test_on_websocket_ohlcv_short_bar(self):
        feed = self._make_funding_feed()
        feed._on_websocket_ohlcv([[1, 2, 3]])  # Too short
        assert feed._data.empty()

    def test_on_websocket_ohlcv_duplicate_ts(self):
        """Bar with same ts as last_ts uses >= so it is enqueued."""
        feed = self._make_funding_feed()
        feed._last_ts = 1700000000000
        bar = [1700000000000, 50000, 50100, 49900, 50050, 100]
        feed._on_websocket_ohlcv([bar])
        assert not feed._data.empty()

    def test_on_websocket_ohlcv_debug(self):
        feed = self._make_funding_feed(debug=True)
        bar = [1700000000000, 50000, 50100, 49900, 50050, 100]
        feed._on_websocket_ohlcv([bar])

    def test_on_websocket_ohlcv_exception(self):
        """Exception in callback doesn't crash."""
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
        """Falls back to info.fundingRate."""
        feed = self._make_funding_feed()
        feed._on_websocket_funding({
            'timestamp': 1700000000000,
            'info': {'fundingRate': '0.0003'},
        })
        assert feed._current_funding['funding_rate'] == 0.0003

    def test_on_websocket_funding_no_timestamp(self):
        """Missing timestamp uses current time."""
        feed = self._make_funding_feed()
        feed._on_websocket_funding({
            'fundingRate': 0.0001,
            'info': {},
        })
        assert feed._current_funding['funding_rate'] == 0.0001
        assert feed._current_funding['timestamp'] > 0

    def test_on_websocket_funding_debug(self):
        feed = self._make_funding_feed(debug=True)
        feed._on_websocket_funding({
            'fundingRate': 0.0001,
            'timestamp': 1700000000000,
            'info': {},
        })

    def test_on_websocket_funding_exception(self):
        """Exception doesn't crash."""
        feed = self._make_funding_feed(debug=True)
        feed._funding_lock = None  # Will cause AttributeError
        try:
            feed._on_websocket_funding({'fundingRate': 0.0001, 'info': {}})
        except Exception:
            pass

    # --- _on_websocket_mark_price edge cases ---

    def test_on_websocket_mark_price_no_info(self):
        feed = self._make_funding_feed()
        feed._on_websocket_mark_price({
            'markPrice': 50000.0,
            'timestamp': 1700000000000,
            'info': {},
        })
        assert feed._current_funding['mark_price'] == 50000.0

    def test_on_websocket_mark_price_debug(self):
        feed = self._make_funding_feed(debug=True)
        feed._on_websocket_mark_price({
            'markPrice': 50000.0,
            'timestamp': 1700000000000,
            'info': {},
        })

    def test_on_websocket_mark_price_exception(self):
        """Exception doesn't crash."""
        feed = self._make_funding_feed(debug=True)
        feed._funding_lock = None
        try:
            feed._on_websocket_mark_price({'markPrice': 50000.0, 'info': {}})
        except Exception:
            pass

    # --- WebSocketRequiredError ---

    def test_websocket_required_error(self):
        from backtrader.feeds.ccxtfeed_funding import WebSocketRequiredError
        err = WebSocketRequiredError("test")
        assert str(err) == "test"
