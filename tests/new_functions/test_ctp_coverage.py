"""Unit tests for CTP futures live trading modules.

Tests cover:
- CTPStore: initialization, send_order, cancel_order, stop, exchange detection
- CTPBroker: buy, sell, cancel, next, order/trade event processing
- MyCtpbeeApi: on_order, on_trade, on_contract callbacks
- CTPData: bug fix verification

All ctpbee dependencies are mocked to avoid live CTP connections.
"""

import collections
import enum
import sys
import threading
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Mock entire ctpbee module tree BEFORE any CTP imports
# ---------------------------------------------------------------------------


class _MockDirection(enum.Enum):
    LONG = "\u591a"
    SHORT = "\u7a7a"
    NET = "\u51c0"


class _MockOffset(enum.Enum):
    NONE = ""
    OPEN = "\u5f00"
    CLOSE = "\u5e73"
    CLOSETODAY = "\u5e73\u4eca"
    CLOSEYESTERDAY = "\u5e73\u6628"


class _MockStatus(enum.Enum):
    SUBMITTING = "\u63d0\u4ea4\u4e2d"
    NOTTRADED = "\u672a\u6210\u4ea4"
    PARTTRADED = "\u90e8\u5206\u6210\u4ea4"
    ALLTRADED = "\u5168\u90e8\u6210\u4ea4"
    CANCELLED = "\u5df2\u64a4\u9500"
    REJECTED = "\u62d2\u5355"


class _MockOrderType(enum.Enum):
    LIMIT = "\u9650\u4ef7"
    MARKET = "\u5e02\u4ef7"
    STOP = "STOP"
    FAK = "FAK"
    FOK = "FOK"


class _MockExchange(enum.Enum):
    CFFEX = "CFFEX"
    SHFE = "SHFE"
    CZCE = "CZCE"
    DCE = "DCE"
    INE = "INE"
    GFEX = "GFEX"
    CTP = "ctp"
    TTS = "tts"


class _MockOrderRequest:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockCancelRequest:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockCtpbeeApi:
    def __init__(self, name, *args, **kwargs):
        self.name = name
        self.action = MagicMock()
        self.center = MagicMock()


class _MockCtpBee:
    def __init__(self, *args, **kwargs):
        self.config = MagicMock()

    def add_extension(self, ext):
        pass

    def start(self, **kwargs):
        pass

    def release(self):
        pass


# Build mock module tree
_mock_ctpbee = MagicMock()
_mock_ctpbee.CtpBee = _MockCtpBee
_mock_ctpbee.CtpbeeApi = _MockCtpbeeApi

_mock_constant = MagicMock()
_mock_constant.Direction = _MockDirection
_mock_constant.Offset = _MockOffset
_mock_constant.Status = _MockStatus
_mock_constant.OrderType = _MockOrderType
_mock_constant.Exchange = _MockExchange
_mock_constant.OrderRequest = _MockOrderRequest
_mock_constant.CancelRequest = _MockCancelRequest
_mock_constant.AccountData = MagicMock
_mock_constant.BarData = MagicMock
_mock_constant.ContractData = MagicMock
_mock_constant.LogData = MagicMock
_mock_constant.OrderData = MagicMock
_mock_constant.PositionData = MagicMock
_mock_constant.TickData = MagicMock
_mock_constant.TradeData = MagicMock

_mock_func = MagicMock()
_mock_func.Helper = MagicMock()

_mock_helpers = MagicMock()
_mock_helpers.datetime2timestamp = MagicMock(return_value=0)
_mock_helpers.get_last_timeframe_timestamp = MagicMock(return_value=0)
_mock_helpers.timestamp2datetime = MagicMock(return_value=datetime.now())

# Inject into sys.modules
sys.modules['ctpbee'] = _mock_ctpbee
sys.modules['ctpbee.constant'] = _mock_constant
sys.modules['ctpbee.func'] = _mock_func
sys.modules['ctpbee.helpers'] = _mock_helpers

# NOW import backtrader CTP modules
from backtrader.utils.py3 import queue


# ---------------------------------------------------------------------------
# Helpers to mock ctpbee event objects
# ---------------------------------------------------------------------------

def _make_mock_ctp_order(order_id='1_2_3', status=None, symbol='rb2501',
                         direction=None, price=3500.0, volume=1):
    """Create a mock CTP OrderData."""
    o = MagicMock()
    o.order_id = order_id
    o.local_order_id = order_id
    o.status = status
    o.symbol = symbol
    o.direction = direction
    o.price = price
    o.volume = volume
    return o


def _make_mock_ctp_trade(order_id='1_2_3', symbol='rb2501',
                         direction=None, price=3500.0, volume=1):
    """Create a mock CTP TradeData."""
    t = MagicMock()
    t.order_id = order_id
    t.local_order_id = order_id
    t.symbol = symbol
    t.direction = direction
    t.price = price
    t.volume = volume
    return t


# ---------------------------------------------------------------------------
# Test MyCtpbeeApi callbacks
# ---------------------------------------------------------------------------

class TestMyCtpbeeApi:
    """Tests for MyCtpbeeApi event callbacks."""

    def _make_api(self):
        """Create a MyCtpbeeApi with mocked queues."""
        # Force reimport with mocked ctpbee
        from backtrader.stores.ctpstore import MyCtpbeeApi

        api = object.__new__(MyCtpbeeApi)
        # Manually set attributes that __init__ would set
        api.md_queue = {}
        api.order_queue = queue.Queue()
        api.trade_queue = queue.Queue()
        api.is_position_ok = False
        api.is_account_ok = False
        api.contracts = {}
        api._bar_timeframe = None
        api._bar_compression = None
        api._bar_begin_time = None
        api._bar_end_time = None
        api._bar_interval = None
        api._data_name = None
        api.time_diff = None
        api.bar_datetime = None
        api.bar_open_price = 0.0
        api.bar_high_price = float('-inf')
        api.bar_low_price = float('inf')
        api.bar_close_price = 0.0
        api.bar_volume = 0.0
        api.action = MagicMock()
        return api

    def test_on_order_pushes_to_queue(self):
        api = self._make_api()
        mock_order = _make_mock_ctp_order()
        api.on_order(mock_order)
        assert not api.order_queue.empty()
        result = api.order_queue.get_nowait()
        assert result.order_id == '1_2_3'

    def test_on_order_no_queue(self):
        api = self._make_api()
        api.order_queue = None
        # Should not raise
        api.on_order(_make_mock_ctp_order())

    def test_on_trade_pushes_to_queue(self):
        api = self._make_api()
        mock_trade = _make_mock_ctp_trade(price=3600.0, volume=2)
        api.on_trade(mock_trade)
        assert not api.trade_queue.empty()
        result = api.trade_queue.get_nowait()
        assert result.price == 3600.0
        assert result.volume == 2

    def test_on_trade_no_queue(self):
        api = self._make_api()
        api.trade_queue = None
        api.on_trade(_make_mock_ctp_trade())

    def test_on_contract_caches(self):
        api = self._make_api()
        contract = MagicMock()
        contract.local_symbol = 'rb2501.SHFE'
        contract.symbol = 'rb2501'
        api.on_contract(contract)
        assert api.contracts['rb2501.SHFE'] is contract
        assert api.contracts['rb2501'] is contract

    def test_on_position_sets_flag(self):
        api = self._make_api()
        assert not api.is_position_ok
        api.on_position(MagicMock())
        assert api.is_position_ok

    def test_on_account_sets_flag(self):
        api = self._make_api()
        assert not api.is_account_ok
        api.on_account(MagicMock())
        assert api.is_account_ok

    def test_subscribe_minutes(self):
        api = self._make_api()
        api.subscribe('rb2501', 4, 5)
        assert api._data_name == 'rb2501'
        assert api._bar_timeframe == 4
        assert api._bar_compression == 5
        assert api.time_diff == 300  # 60 * 5
        assert api._bar_interval == '5m'

    def test_subscribe_daily(self):
        api = self._make_api()
        api.subscribe('rb2501', 5, 1)
        assert api.time_diff == 86400
        assert api._bar_interval == '1d'

    def test_subscribe_default(self):
        api = self._make_api()
        api.subscribe('rb2501', 99, 1)
        assert api.time_diff == 60
        assert api._bar_interval == '1m'


# ---------------------------------------------------------------------------
# Test CTPStore
# ---------------------------------------------------------------------------

class TestCTPStore:
    """Tests for CTPStore (mocked ctpbee)."""

    def _make_store(self):
        """Create a CTPStore with fully mocked ctpbee."""
        from backtrader.stores.ctpstore import CTPStore

        store = CTPStore.__new__(CTPStore)
        store.ctp_setting = {}
        store._is_connected = True
        store._stopped = False
        store._cash = 100000.0
        store._value = 150000.0
        store.order_queue = queue.Queue()
        store.trade_queue = queue.Queue()
        store.q_feed_qlive = {}
        store._order_id_map = {}
        store._lock = threading.Lock()

        # Mock the main_ctpbee_api
        store.main_ctpbee_api = MagicMock()
        store.main_ctpbee_api.contracts = {}
        store.main_ctpbee_api.center.positions = []
        store.main_ctpbee_api.center.account.available = 100000.0
        store.main_ctpbee_api.center.account.balance = 150000.0

        # Mock the app
        store.app = MagicMock()

        return store

    def test_is_connected(self):
        store = self._make_store()
        assert store.is_connected is True

    def test_is_connected_after_stop(self):
        store = self._make_store()
        store.stop()
        assert store.is_connected is False

    def test_stop_idempotent(self):
        store = self._make_store()
        store.stop()
        store.stop()  # second call should be no-op
        assert store._stopped is True

    def test_stop_release_error(self):
        store = self._make_store()
        store.app.release.side_effect = RuntimeError("release failed")
        store.stop()  # should not raise
        assert store._stopped is True

    def test_get_cash(self):
        store = self._make_store()
        assert store.get_cash() == 100000.0

    def test_get_value(self):
        store = self._make_store()
        assert store.get_value() == 150000.0

    def test_get_balance(self):
        store = self._make_store()
        store.main_ctpbee_api.center.account.available = 88000.0
        store.main_ctpbee_api.center.account.balance = 99000.0
        store.get_balance()
        assert store.get_cash() == 88000.0
        assert store.get_value() == 99000.0

    def test_get_balance_error(self):
        store = self._make_store()
        store.main_ctpbee_api.center.account = None
        store.get_balance()  # should not raise
        # Cash/value unchanged
        assert store.get_cash() == 100000.0

    def test_get_positions(self):
        store = self._make_store()
        store.main_ctpbee_api.center.positions = [{'local_symbol': 'rb2501.SHFE'}]
        pos = store.get_positions()
        assert len(pos) == 1

    def test_get_positions_error(self):
        store = self._make_store()
        type(store.main_ctpbee_api.center).positions = PropertyMock(side_effect=Exception("err"))
        pos = store.get_positions()
        assert pos == []

    def test_register_feed(self):
        store = self._make_store()
        feed = MagicMock()
        feed.p.dataname = 'rb2501.SHFE'
        q = store.register(feed)
        assert isinstance(q, queue.Queue)
        assert 'rb2501.SHFE' in store.q_feed_qlive

    def test_detect_exchange_with_suffix(self):
        store = self._make_store()
        assert store._detect_exchange('rb2501.SHFE') == _MockExchange.SHFE
        assert store._detect_exchange('IF2501.CFFEX') == _MockExchange.CFFEX
        assert store._detect_exchange('m2501.DCE') == _MockExchange.DCE

    def test_detect_exchange_from_contract_cache(self):
        store = self._make_store()
        contract = MagicMock()
        contract.exchange = _MockExchange.CZCE
        store.main_ctpbee_api.contracts = {'SR501': contract}
        assert store._detect_exchange('SR501') == _MockExchange.CZCE

    def test_detect_exchange_default(self):
        store = self._make_store()
        # No suffix, no cache -> default SHFE
        assert store._detect_exchange('unknown') == _MockExchange.SHFE

    def test_send_order_success(self):
        store = self._make_store()
        store.main_ctpbee_api.action.send_order.return_value = '1_2_3'

        result = store.send_order(
            symbol='rb2501.SHFE',
            direction=_MockDirection.LONG,
            offset=_MockOffset.OPEN,
            order_type=_MockOrderType.LIMIT,
            volume=1,
            price=3500.0,
        )
        assert result == '1_2_3'
        store.main_ctpbee_api.action.send_order.assert_called_once()

    def test_send_order_failure(self):
        store = self._make_store()
        store.main_ctpbee_api.action.send_order.side_effect = Exception("fail")

        result = store.send_order(
            symbol='rb2501.SHFE',
            direction=_MockDirection.LONG,
            offset=_MockOffset.OPEN,
            order_type=_MockOrderType.LIMIT,
            volume=1,
            price=3500.0,
        )
        assert result is None

    def test_cancel_order_success(self):
        store = self._make_store()
        store.main_ctpbee_api.action.cancel_order.return_value = None
        result = store.cancel_order('rb2501.SHFE', '1_2_3')
        assert result is True

    def test_cancel_order_failure(self):
        store = self._make_store()
        store.main_ctpbee_api.action.cancel_order.side_effect = Exception("fail")
        result = store.cancel_order('rb2501.SHFE', '1_2_3')
        assert result is False


# ---------------------------------------------------------------------------
# Test CTPBroker
# ---------------------------------------------------------------------------

class TestCTPBroker:
    """Tests for CTPBroker order lifecycle."""

    def _make_broker(self):
        """Create a CTPBroker with mocked store."""
        from backtrader.brokers.ctpbroker import CTPBroker

        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = []
        broker.notifs = collections.deque()
        broker._ctp_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 150000.0
        broker.positions = collections.defaultdict(lambda: MagicMock(size=0, price=0.0))

        # Mock the store
        broker.o = MagicMock()
        broker.o.order_queue = queue.Queue()
        broker.o.trade_queue = queue.Queue()
        broker.o.send_order.return_value = '1_2_3'
        broker.o.cancel_order.return_value = True
        broker.o.get_balance.return_value = None
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0

        return broker

    def _make_data(self, dataname='rb2501.SHFE'):
        """Create a mock data feed that Order constructor can use."""
        import datetime as dt
        from backtrader.utils import date2num

        data = MagicMock()
        data.p.dataname = dataname
        data._dataname = dataname
        data.p.sessionend = dt.time(15, 0, 0)
        data.p.simulated = False

        # datetime line must support [0] returning a float (date2num format)
        now_num = date2num(dt.datetime(2025, 3, 1, 10, 0, 0))
        mock_dt_line = MagicMock()
        mock_dt_line.__getitem__ = MagicMock(return_value=now_num)
        mock_dt_line.datetime = MagicMock(return_value=dt.datetime(2025, 3, 1, 10, 0, 0))
        mock_dt_line.date = MagicMock(return_value=dt.date(2025, 3, 1))
        data.datetime = mock_dt_line
        data.date2num = date2num

        # close line
        mock_close = MagicMock()
        mock_close.__getitem__ = MagicMock(return_value=3500.0)
        data.close = mock_close

        return data

    def test_buy_creates_order(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        assert order is not None
        assert order.ref in broker.orders
        assert order._ctp_order_id == '1_2_3'
        assert len(broker.open_orders) == 1

    def test_sell_creates_order(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        order = broker.sell(owner, data, size=1, price=3500.0,
                            exectype=None, parent=None, transmit=True)
        assert order is not None
        assert order.issell()
        assert order._ctp_order_id == '1_2_3'

    def test_buy_rejected_on_send_failure(self):
        broker = self._make_broker()
        from backtrader.position import Position
        from backtrader.order import Order
        broker.positions = collections.defaultdict(Position)
        broker.o.send_order.return_value = None  # Simulate failure
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        assert order.status == Order.Rejected
        assert len(broker.open_orders) == 0

    def test_cancel_order(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        result = broker.cancel(order)
        assert result is order
        broker.o.cancel_order.assert_called_once()

    def test_cancel_no_ctp_id(self):
        broker = self._make_broker()
        order = MagicMock()
        order.ref = 999
        # No _ctp_order_id attribute
        del order._ctp_order_id
        result = broker.cancel(order)
        assert result is order

    def test_next_processes_events(self):
        broker = self._make_broker()
        # next() should not raise even with empty queues
        broker.next()
        broker.o.get_balance.assert_called_once()

    def test_process_order_cancel_event(self):
        broker = self._make_broker()
        from backtrader.position import Position
        from backtrader.order import Order
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        # Create an order first
        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)

        # Simulate CTP cancel event
        ctp_order = _make_mock_ctp_order(
            order_id='1_2_3', status=_MockStatus.CANCELLED
        )
        broker.o.order_queue.put(ctp_order)
        broker._process_order_events()

        assert order.status == Order.Canceled
        assert order not in broker.open_orders

    def test_process_order_reject_event(self):
        broker = self._make_broker()
        from backtrader.position import Position
        from backtrader.order import Order
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)

        ctp_order = _make_mock_ctp_order(
            order_id='1_2_3', status=_MockStatus.REJECTED
        )
        broker.o.order_queue.put(ctp_order)
        broker._process_order_events()

        assert order.status == Order.Rejected
        assert order not in broker.open_orders

    def test_process_trade_fill(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)

        # Simulate trade fill
        ctp_trade = _make_mock_ctp_trade(
            order_id='1_2_3', price=3500.0, volume=1
        )
        broker.o.trade_queue.put(ctp_trade)
        broker._process_trade_events()

        # Position should be updated
        pos = broker.positions['rb2501.SHFE']
        assert pos.size == 1

    def test_process_unknown_order_event(self):
        broker = self._make_broker()
        # Put an event with unknown order_id
        ctp_order = _make_mock_ctp_order(order_id='unknown_999')
        broker.o.order_queue.put(ctp_order)
        broker._process_order_events()  # should not raise

    def test_process_unknown_trade_event(self):
        broker = self._make_broker()
        ctp_trade = _make_mock_ctp_trade(order_id='unknown_999')
        broker.o.trade_queue.put(ctp_trade)
        broker._process_trade_events()  # should not raise

    def test_get_notification(self):
        broker = self._make_broker()
        assert broker.get_notification() is None
        from backtrader.order import Order
        mock_order = MagicMock()
        broker.notifs.append(mock_order)
        assert broker.get_notification() is mock_order

    def test_orderstatus(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        status = broker.orderstatus(order)
        assert status is not None

    def test_getcash(self):
        broker = self._make_broker()
        broker.o.get_cash.return_value = 88000.0
        assert broker.getcash() == 88000.0

    def test_getvalue(self):
        broker = self._make_broker()
        broker.o.get_value.return_value = 99000.0
        assert broker.getvalue() == 99000.0

    def test_getposition(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        broker.positions['rb2501.SHFE'] = Position(5, 3500.0)
        data = self._make_data()
        pos = broker.getposition(data, clone=True)
        assert pos.size == 5

    def test_buy_close_short(self):
        """Buy when short position exists should use CLOSE offset."""
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        broker.positions['rb2501.SHFE'] = Position(-3, 3400.0)  # Short 3
        owner = MagicMock()
        data = self._make_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        # Verify send_order was called with CLOSE offset
        call_kwargs = broker.o.send_order.call_args
        from ctpbee.constant import Offset as CTPOffset
        assert call_kwargs.kwargs.get('offset') == CTPOffset.CLOSE or \
               call_kwargs[1].get('offset') == CTPOffset.CLOSE

    def test_sell_close_long(self):
        """Sell when long position exists should use CLOSE offset."""
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        broker.positions['rb2501.SHFE'] = Position(5, 3400.0)  # Long 5
        owner = MagicMock()
        data = self._make_data()

        order = broker.sell(owner, data, size=1, price=3500.0,
                            exectype=None, parent=None, transmit=True)
        call_kwargs = broker.o.send_order.call_args
        from ctpbee.constant import Offset as CTPOffset
        assert call_kwargs.kwargs.get('offset') == CTPOffset.CLOSE or \
               call_kwargs[1].get('offset') == CTPOffset.CLOSE


# ---------------------------------------------------------------------------
# Test CTPBroker start() position loading
# ---------------------------------------------------------------------------

class TestCTPBrokerStart:
    """Tests for CTPBroker.start() position loading."""

    def _make_broker_for_start(self):
        from backtrader.brokers.ctpbroker import CTPBroker
        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = []
        broker.notifs = collections.deque()
        broker._ctp_to_bt = {}
        broker.startingcash = broker.cash = 0.0
        broker.startingvalue = broker.value = 0.0
        broker.positions = collections.defaultdict(
            lambda: MagicMock(size=0, price=0.0)
        )

        broker.o = MagicMock()
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_start_with_dict_positions(self):
        broker = self._make_broker_for_start()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)

        # Set param
        broker._params = {'use_positions': True}
        broker.get_param = lambda k: broker._params.get(k)

        broker.o.get_positions.return_value = [
            {'direction': 'long', 'volume': 5, 'price': 3500.0,
             'local_symbol': 'rb2501.SHFE'},
        ]

        # Call start (skip super().start())
        with patch.object(type(broker).__bases__[0], 'start', return_value=None):
            broker.start()

        assert broker.positions['rb2501.SHFE'].size == 5
        assert broker.positions['rb2501.SHFE'].price == 3500.0

    def test_start_with_empty_positions(self):
        broker = self._make_broker_for_start()
        broker._params = {'use_positions': True}
        broker.get_param = lambda k: broker._params.get(k)
        broker.o.get_positions.return_value = []

        with patch.object(type(broker).__bases__[0], 'start', return_value=None):
            broker.start()
        # Should not error


# ---------------------------------------------------------------------------
# Test CTPData bug fix
# ---------------------------------------------------------------------------

class TestCTPDataBugFix:
    """Verify the _bar_timeframe → _timeframe bug fix in ctpdata.py."""

    def test_no_bar_timeframe_attribute_in_get_backfill(self):
        """The code should reference self._timeframe, not self._bar_timeframe."""
        import ast
        with open('backtrader/feeds/ctpdata.py') as f:
            source = f.read()

        tree = ast.parse(source)
        # Find _get_backfill_data method and check it doesn't use _bar_timeframe
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.attr, str) and node.attr == '_bar_timeframe':
                    # Check if it's inside _get_backfill_data
                    pytest.fail("Found _bar_timeframe reference in ctpdata.py - bug not fixed!")
