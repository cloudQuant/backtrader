"""Unit tests for CTP futures live trading modules (ctp-python based).

Tests cover:
- CTPTraderSpi: order/trade callbacks, auth/login flow
- CTPMdSpi: tick data callbacks, subscribe
- CTPStore: send_order, cancel_order, stop, get_balance, get_positions
- CTPBroker: buy, sell, cancel, next, order/trade event processing
- CTPData: tick-to-bar aggregation, backfill, no _bar_timeframe reference

All ctp dependencies are mocked to avoid live CTP connections.
"""

import collections
import sys
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Mock the `ctp` C extension module BEFORE any CTP imports
# ---------------------------------------------------------------------------

_mock_ctp = MagicMock()

# CThostFtdcTraderSpi / CThostFtdcMdSpi: base classes for SPI subclassing
_mock_ctp.CThostFtdcTraderSpi = object
_mock_ctp.CThostFtdcMdSpi = object

# Mock API factory classes
_mock_ctp.CThostFtdcTraderApi = MagicMock()
_mock_ctp.CThostFtdcMdApi = MagicMock()

# Mock all CTP field structs as simple MagicMock factories
for _field_name in [
    'CThostFtdcReqAuthenticateField',
    'CThostFtdcReqUserLoginField',
    'CThostFtdcSettlementInfoConfirmField',
    'CThostFtdcInputOrderField',
    'CThostFtdcInputOrderActionField',
    'CThostFtdcQryTradingAccountField',
    'CThostFtdcQryInvestorPositionField',
    'CThostFtdcRspInfoField',
    'CThostFtdcDepthMarketDataField',
    'CThostFtdcSpecificInstrumentField',
]:
    setattr(_mock_ctp, _field_name, MagicMock)

sys.modules['ctp'] = _mock_ctp

# NOW import backtrader CTP modules (they will pick up the mocked ctp)
from backtrader.utils.py3 import queue
from backtrader.stores.ctpstore import (
    CTPTraderSpi, CTPMdSpi, CTPStore,
    THOST_FTDC_D_Buy, THOST_FTDC_D_Sell,
    THOST_FTDC_OF_Open, THOST_FTDC_OF_Close,
    THOST_FTDC_OPT_LimitPrice, THOST_FTDC_OPT_AnyPrice,
    THOST_FTDC_OST_AllTraded, THOST_FTDC_OST_Canceled,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order_event(order_ref='1', status='3', rejected=False, **kwargs):
    """Create a dict mimicking CTPTraderSpi.OnRtnOrder output."""
    evt = {
        'order_ref': order_ref,
        'order_sys_id': '',
        'front_id': 0,
        'session_id': 0,
        'instrument': 'rb2501',
        'direction': THOST_FTDC_D_Buy,
        'offset': THOST_FTDC_OF_Open,
        'price': 3500.0,
        'volume': 1,
        'volume_traded': 0,
        'volume_remaining': 1,
        'status': status,
        'status_msg': '',
    }
    if rejected:
        evt['rejected'] = True
    evt.update(kwargs)
    return evt


def _make_trade_event(order_ref='1', price=3500.0, volume=1, **kwargs):
    """Create a dict mimicking CTPTraderSpi.OnRtnTrade output."""
    evt = {
        'order_ref': order_ref,
        'order_sys_id': '',
        'instrument': 'rb2501',
        'direction': THOST_FTDC_D_Buy,
        'offset': THOST_FTDC_OF_Open,
        'price': price,
        'volume': volume,
        'trade_id': '001',
        'trade_time': '10:00:00',
    }
    evt.update(kwargs)
    return evt


def _make_mock_data(dataname='rb2501.SHFE'):
    """Create a mock data feed that Order constructor can use."""
    import datetime as dt
    from backtrader.utils import date2num

    data = MagicMock()
    data.p.dataname = dataname
    data._dataname = dataname
    data.p.sessionend = dt.time(15, 0, 0)
    data.p.simulated = False

    now_num = date2num(dt.datetime(2025, 3, 1, 10, 0, 0))
    mock_dt_line = MagicMock()
    mock_dt_line.__getitem__ = MagicMock(return_value=now_num)
    mock_dt_line.datetime = MagicMock(return_value=dt.datetime(2025, 3, 1, 10, 0, 0))
    mock_dt_line.date = MagicMock(return_value=dt.date(2025, 3, 1))
    data.datetime = mock_dt_line
    data.date2num = date2num

    mock_close = MagicMock()
    mock_close.__getitem__ = MagicMock(return_value=3500.0)
    data.close = mock_close
    return data


# ---------------------------------------------------------------------------
# Test CTPTraderSpi
# ---------------------------------------------------------------------------

class TestCTPTraderSpi:
    """Tests for CTPTraderSpi callbacks."""

    def _make_spi(self):
        spi = CTPTraderSpi(
            front='tcp://127.0.0.1:10130',
            broker_id='9999',
            user_id='test',
            password='test',
            app_id='test_app',
            auth_code='0000000000000000',
        )
        return spi

    def test_initial_state(self):
        spi = self._make_spi()
        assert spi.connected is False
        assert spi.authed is False
        assert spi.loggedin is False
        assert spi.order_ref == 0

    def test_on_front_connected(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.OnFrontConnected()
        assert spi.connected is True
        spi.api.ReqAuthenticate.assert_called_once()

    def test_on_rsp_authenticate_success(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        rsp_info = MagicMock()
        rsp_info.ErrorID = 0
        spi.OnRspAuthenticate(None, rsp_info, 1, True)
        assert spi.authed is True
        spi.api.ReqUserLogin.assert_called_once()

    def test_on_rsp_authenticate_failure(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        rsp_info = MagicMock()
        rsp_info.ErrorID = 1
        rsp_info.ErrorMsg = 'auth error'
        spi.OnRspAuthenticate(None, rsp_info, 1, True)
        assert spi.authed is False

    def test_on_rsp_user_login_success(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        login = MagicMock()
        login.FrontID = 1
        login.SessionID = 2
        rsp_info = MagicMock()
        rsp_info.ErrorID = 0
        spi.OnRspUserLogin(login, rsp_info, 1, True)
        assert spi.loggedin is True
        assert spi.front_id == 1
        assert spi.session_id == 2
        spi.api.ReqSettlementInfoConfirm.assert_called_once()

    def test_on_rtn_order_pushes_to_queue(self):
        spi = self._make_spi()
        pOrder = MagicMock()
        pOrder.OrderRef = '1'
        pOrder.OrderSysID = '  SYS001  '
        pOrder.FrontID = 1
        pOrder.SessionID = 2
        pOrder.InstrumentID = 'rb2501'
        pOrder.Direction = THOST_FTDC_D_Buy
        pOrder.CombOffsetFlag = THOST_FTDC_OF_Open
        pOrder.LimitPrice = 3500.0
        pOrder.VolumeTotalOriginal = 1
        pOrder.VolumeTraded = 0
        pOrder.VolumeTotal = 1
        pOrder.OrderStatus = THOST_FTDC_OST_Canceled
        pOrder.StatusMsg = 'cancelled'
        spi.OnRtnOrder(pOrder)
        assert not spi.order_queue.empty()
        evt = spi.order_queue.get_nowait()
        assert evt['order_ref'] == '1'
        assert evt['status'] == THOST_FTDC_OST_Canceled

    def test_on_rtn_order_none(self):
        spi = self._make_spi()
        spi.OnRtnOrder(None)  # should not raise
        assert spi.order_queue.empty()

    def test_on_rtn_trade_pushes_to_queue(self):
        spi = self._make_spi()
        pTrade = MagicMock()
        pTrade.OrderRef = '1'
        pTrade.OrderSysID = ' SYS001 '
        pTrade.InstrumentID = 'rb2501'
        pTrade.Direction = THOST_FTDC_D_Buy
        pTrade.OffsetFlag = THOST_FTDC_OF_Open
        pTrade.Price = 3500.0
        pTrade.Volume = 1
        pTrade.TradeID = ' T001 '
        pTrade.TradeTime = '10:00:00'
        spi.OnRtnTrade(pTrade)
        assert not spi.trade_queue.empty()
        evt = spi.trade_queue.get_nowait()
        assert evt['price'] == 3500.0
        assert evt['volume'] == 1

    def test_on_rsp_order_insert_error(self):
        spi = self._make_spi()
        pInputOrder = MagicMock()
        pInputOrder.OrderRef = '1'
        pInputOrder.InstrumentID = 'rb2501'
        pInputOrder.Direction = THOST_FTDC_D_Buy
        pInputOrder.CombOffsetFlag = THOST_FTDC_OF_Open
        pInputOrder.LimitPrice = 3500.0
        pInputOrder.VolumeTotalOriginal = 1
        rsp_info = MagicMock()
        rsp_info.ErrorID = 42
        rsp_info.ErrorMsg = 'order rejected'
        spi.OnRspOrderInsert(pInputOrder, rsp_info, 1, True)
        assert not spi.order_queue.empty()
        evt = spi.order_queue.get_nowait()
        assert evt['rejected'] is True

    def test_next_order_ref(self):
        spi = self._make_spi()
        ref1 = spi._next_order_ref()
        ref2 = spi._next_order_ref()
        assert ref1 == '1'
        assert ref2 == '2'

    def test_send_order_success(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.api.ReqOrderInsert.return_value = 0
        ref = spi.send_order('rb2501', THOST_FTDC_D_Buy, THOST_FTDC_OF_Open, 3500.0, 1)
        assert ref is not None
        spi.api.ReqOrderInsert.assert_called_once()

    def test_send_order_failure(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.api.ReqOrderInsert.return_value = -1
        ref = spi.send_order('rb2501', THOST_FTDC_D_Buy, THOST_FTDC_OF_Open, 3500.0, 1)
        assert ref is None

    def test_cancel_order_by_ref(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.api.ReqOrderAction.return_value = 0
        spi.front_id = 1
        spi.session_id = 2
        result = spi.cancel_order_by_ref('rb2501', '1')
        assert result is True

    def test_query_account(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.query_account()
        spi.api.ReqQryTradingAccount.assert_called_once()

    def test_on_rsp_qry_trading_account(self):
        spi = self._make_spi()
        acc = MagicMock()
        acc.Available = 100000.0
        acc.Balance = 150000.0
        acc.CurrMargin = 5000.0
        acc.Commission = 10.0
        acc.FrozenMargin = 0.0
        acc.FrozenCash = 0.0
        spi.OnRspQryTradingAccount(acc, None, 1, True)
        assert spi._account['available'] == 100000.0
        assert spi._account['balance'] == 150000.0
        assert spi._account_query_done.is_set()

    def test_on_rsp_qry_position(self):
        spi = self._make_spi()
        pos = MagicMock()
        pos.InstrumentID = 'rb2501'
        pos.PosiDirection = '2'  # Long
        pos.Position = 5
        pos.YdPosition = 3
        pos.TodayPosition = 2
        pos.OpenCost = 17500.0
        pos.PositionProfit = 100.0
        spi.OnRspQryInvestorPosition(pos, None, 1, True)
        assert len(spi._positions) == 1
        assert spi._positions[0]['instrument'] == 'rb2501'
        assert spi._position_query_done.is_set()

    def test_on_front_disconnected(self):
        spi = self._make_spi()
        spi.connected = True
        spi.loggedin = True
        spi.OnFrontDisconnected(1001)
        assert spi.connected is False
        assert spi.loggedin is False


# ---------------------------------------------------------------------------
# Test CTPMdSpi
# ---------------------------------------------------------------------------

class TestCTPMdSpi:
    """Tests for CTPMdSpi callbacks."""

    def _make_spi(self):
        spi = CTPMdSpi(
            front='tcp://127.0.0.1:10131',
            broker_id='9999',
            user_id='test',
            password='test',
        )
        return spi

    def test_initial_state(self):
        spi = self._make_spi()
        assert spi.connected is False
        assert spi.loggedin is False
        assert len(spi.tick_queues) == 0

    def test_on_front_connected(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.OnFrontConnected()
        assert spi.connected is True
        spi.api.ReqUserLogin.assert_called_once()

    def test_on_rsp_user_login_success(self):
        spi = self._make_spi()
        rsp = MagicMock()
        rsp.ErrorID = 0
        spi.OnRspUserLogin(None, rsp, 1, True)
        assert spi.loggedin is True

    def test_register_instrument(self):
        spi = self._make_spi()
        q = spi.register_instrument('rb2501')
        assert isinstance(q, queue.Queue)
        assert 'rb2501' in spi.tick_queues
        # Registering same instrument returns same queue
        q2 = spi.register_instrument('rb2501')
        assert q is q2

    def test_on_rtn_depth_market_data(self):
        spi = self._make_spi()
        spi.register_instrument('rb2501')
        md = MagicMock()
        md.InstrumentID = 'rb2501'
        md.LastPrice = 3500.0
        md.OpenPrice = 3480.0
        md.HighestPrice = 3510.0
        md.LowestPrice = 3470.0
        md.Volume = 1000
        md.OpenInterest = 50000.0
        md.BidPrice1 = 3499.0
        md.AskPrice1 = 3501.0
        md.BidVolume1 = 10
        md.AskVolume1 = 12
        md.UpdateTime = '10:00:00'
        md.UpdateMillisec = 500
        md.TradingDay = '20250301'
        md.ActionDay = '20250301'
        spi.OnRtnDepthMarketData(md)
        assert not spi.tick_queues['rb2501'].empty()
        tick = spi.tick_queues['rb2501'].get_nowait()
        assert tick['last_price'] == 3500.0
        assert tick['instrument'] == 'rb2501'

    def test_on_rtn_depth_market_data_unregistered(self):
        spi = self._make_spi()
        md = MagicMock()
        md.InstrumentID = 'unknown'
        md.LastPrice = 100.0
        spi.OnRtnDepthMarketData(md)  # should not raise

    def test_on_rtn_depth_market_data_none(self):
        spi = self._make_spi()
        spi.OnRtnDepthMarketData(None)  # should not raise

    def test_subscribe(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.subscribe(['rb2501', 'IF2506'])
        spi.api.SubscribeMarketData.assert_called_once_with(['rb2501', 'IF2506'])

    def test_subscribe_string(self):
        spi = self._make_spi()
        spi.api = MagicMock()
        spi.subscribe('rb2501')
        spi.api.SubscribeMarketData.assert_called_once_with(['rb2501'])

    def test_on_front_disconnected(self):
        spi = self._make_spi()
        spi.connected = True
        spi.loggedin = True
        spi.OnFrontDisconnected(2001)
        assert spi.connected is False
        assert spi.loggedin is False


# ---------------------------------------------------------------------------
# Test CTPStore
# ---------------------------------------------------------------------------

class TestCTPStore:
    """Tests for CTPStore."""

    def _make_store(self):
        """Create a CTPStore with fully mocked internals."""
        store = CTPStore.__new__(CTPStore)
        store.ctp_setting = {}
        store._is_connected = True
        store._stopped = False
        store._cash = 100000.0
        store._value = 150000.0
        store.order_queue = queue.Queue()
        store.trade_queue = queue.Queue()

        # Mock SPIs
        store.trader_spi = MagicMock()
        store.trader_spi.loggedin = True
        store.trader_spi._account = {'available': 100000.0, 'balance': 150000.0}
        store.trader_spi._account_query_done = threading.Event()
        store.trader_spi._account_query_done.set()
        store.trader_spi._positions = []
        store.trader_spi._position_query_done = threading.Event()
        store.trader_spi._position_query_done.set()

        store.md_spi = MagicMock()
        store.md_spi.loggedin = True
        store.md_spi.tick_queues = {}

        # Rate limiting and feed tracking (added in bug fix round)
        store._last_balance_query = 0.0
        store._balance_query_interval = 2.0
        store._feed_count = 0

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
        store.stop()
        assert store._stopped is True

    def test_get_cash(self):
        store = self._make_store()
        assert store.get_cash() == 100000.0

    def test_get_value(self):
        store = self._make_store()
        assert store.get_value() == 150000.0

    def test_get_balance(self):
        store = self._make_store()
        store.trader_spi._account = {'available': 88000.0, 'balance': 99000.0}
        store.get_balance()
        assert store.get_cash() == 88000.0
        assert store.get_value() == 99000.0

    def test_get_balance_error(self):
        store = self._make_store()
        store.trader_spi.query_account.side_effect = Exception('err')
        store.get_balance()  # should not raise
        assert store.get_cash() == 100000.0

    def test_get_positions(self):
        store = self._make_store()
        store.trader_spi._positions = [
            {'instrument': 'rb2501', 'direction': '2', 'volume': 5}
        ]
        pos = store.get_positions()
        assert len(pos) == 1
        assert pos[0]['instrument'] == 'rb2501'

    def test_get_positions_error(self):
        store = self._make_store()
        store.trader_spi.query_positions.side_effect = Exception('err')
        pos = store.get_positions()
        assert pos == []

    def test_send_order_success(self):
        store = self._make_store()
        store.trader_spi.send_order.return_value = '1'
        ref = store.send_order(
            symbol='rb2501.SHFE',
            direction=THOST_FTDC_D_Buy,
            offset=THOST_FTDC_OF_Open,
            price=3500.0,
            volume=1,
        )
        assert ref == '1'
        store.trader_spi.send_order.assert_called_once()

    def test_send_order_extracts_instrument(self):
        store = self._make_store()
        store.trader_spi.send_order.return_value = '1'
        store.send_order('rb2501.SHFE', THOST_FTDC_D_Buy, THOST_FTDC_OF_Open, 3500.0, 1)
        call_kwargs = store.trader_spi.send_order.call_args
        assert call_kwargs[1]['instrument'] == 'rb2501'

    def test_cancel_order(self):
        store = self._make_store()
        store.trader_spi.cancel_order_by_ref.return_value = True
        result = store.cancel_order('rb2501.SHFE', '1')
        assert result is True

    def test_register_feed(self):
        store = self._make_store()
        feed = MagicMock()
        feed.p.dataname = 'rb2501.SHFE'
        store.register(feed)
        store.md_spi.register_instrument.assert_called_once_with('rb2501')

    def test_subscribe(self):
        store = self._make_store()
        store.subscribe('rb2501.SHFE')
        store.md_spi.subscribe.assert_called_once_with(['rb2501'])


# ---------------------------------------------------------------------------
# Test CTPBroker
# ---------------------------------------------------------------------------

class TestCTPBroker:
    """Tests for CTPBroker order lifecycle."""

    def _make_broker(self):
        from backtrader.brokers.ctpbroker import CTPBroker

        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}  # dict for O(1) removal
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 150000.0
        broker.positions = collections.defaultdict(lambda: MagicMock(size=0, price=0.0))
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker._pending_stops = []  # C1: pending stop orders
        broker._params = {'use_positions': True, 'commission': 0.0}
        broker.get_param = lambda k: broker._params.get(k)

        # Mock the store
        broker.o = MagicMock()
        broker.o.order_queue = queue.Queue()
        broker.o.trade_queue = queue.Queue()
        broker.o.send_order.return_value = '1'
        broker.o.cancel_order.return_value = True
        broker.o.get_balance.return_value = None
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_buy_creates_order(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        assert order is not None
        assert order.ref in broker.orders
        assert order._ctp_order_ref == '1'
        assert len(broker.open_orders) == 1

    def test_sell_creates_order(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.sell(owner, data, size=1, price=3500.0,
                            exectype=None, parent=None, transmit=True)
        assert order is not None
        assert order.issell()
        assert order._ctp_order_ref == '1'

    def test_buy_rejected_on_send_failure(self):
        broker = self._make_broker()
        from backtrader.position import Position
        from backtrader.order import Order
        broker.positions = collections.defaultdict(Position)
        broker.o.send_order.return_value = None
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        assert order.status == Order.Rejected
        assert len(broker.open_orders) == 0

    def test_cancel_order(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)
        result = broker.cancel(order)
        assert result is order
        broker.o.cancel_order.assert_called_once()

    def test_cancel_no_ctp_ref(self):
        broker = self._make_broker()
        order = MagicMock()
        order.ref = 999
        order._ctp_order_ref = None
        result = broker.cancel(order)
        assert result is order

    def test_next_processes_events(self):
        broker = self._make_broker()
        broker.next()
        broker.o.get_balance.assert_called_once()

    def test_process_order_cancel_event(self):
        broker = self._make_broker()
        from backtrader.position import Position
        from backtrader.order import Order
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)

        evt = _make_order_event(order_ref='1', status=THOST_FTDC_OST_Canceled)
        broker.o.order_queue.put(evt)
        broker._process_order_events()

        assert order.status == Order.Canceled
        assert order.ref not in broker.open_orders

    def test_process_order_reject_event(self):
        broker = self._make_broker()
        from backtrader.position import Position
        from backtrader.order import Order
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)

        evt = _make_order_event(order_ref='1', rejected=True)
        broker.o.order_queue.put(evt)
        broker._process_order_events()

        assert order.status == Order.Rejected
        assert order.ref not in broker.open_orders

    def test_process_trade_fill(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0,
                           exectype=None, parent=None, transmit=True)

        evt = _make_trade_event(order_ref='1', price=3500.0, volume=1)
        broker.o.trade_queue.put(evt)
        broker._process_trade_events()

        pos = broker.positions['rb2501.SHFE']
        assert pos.size == 1

    def test_process_unknown_order_event(self):
        broker = self._make_broker()
        evt = _make_order_event(order_ref='unknown')
        broker.o.order_queue.put(evt)
        broker._process_order_events()  # should not raise

    def test_process_unknown_trade_event(self):
        broker = self._make_broker()
        evt = _make_trade_event(order_ref='unknown')
        broker.o.trade_queue.put(evt)
        broker._process_trade_events()  # should not raise

    def test_get_notification(self):
        broker = self._make_broker()
        assert broker.get_notification() is None
        mock_order = MagicMock()
        broker.notifs.append(mock_order)
        assert broker.get_notification() is mock_order

    def test_orderstatus(self):
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

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
        data = _make_mock_data()
        pos = broker.getposition(data, clone=True)
        assert pos.size == 5

    def test_buy_close_short(self):
        """Buy when short position exists should use CLOSE offset."""
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        broker.positions['rb2501.SHFE'] = Position(-3, 3400.0)
        owner = MagicMock()
        data = _make_mock_data()

        broker.buy(owner, data, size=1, price=3500.0,
                   exectype=None, parent=None, transmit=True)
        call_kwargs = broker.o.send_order.call_args
        assert call_kwargs[1].get('offset') == THOST_FTDC_OF_Close

    def test_sell_close_long(self):
        """Sell when long position exists should use CLOSE offset."""
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        broker.positions['rb2501.SHFE'] = Position(5, 3400.0)
        owner = MagicMock()
        data = _make_mock_data()

        broker.sell(owner, data, size=1, price=3500.0,
                    exectype=None, parent=None, transmit=True)
        call_kwargs = broker.o.send_order.call_args
        assert call_kwargs[1].get('offset') == THOST_FTDC_OF_Close

    def test_buy_open_long(self):
        """Buy with no position should use OPEN offset."""
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        owner = MagicMock()
        data = _make_mock_data()

        broker.buy(owner, data, size=1, price=3500.0,
                   exectype=None, parent=None, transmit=True)
        call_kwargs = broker.o.send_order.call_args
        assert call_kwargs[1].get('offset') == THOST_FTDC_OF_Open
        assert call_kwargs[1].get('direction') == THOST_FTDC_D_Buy


# ---------------------------------------------------------------------------
# Test CTPBroker start() position loading
# ---------------------------------------------------------------------------

class TestCTPBrokerStart:
    """Tests for CTPBroker.start() position loading."""

    def _make_broker_for_start(self):
        from backtrader.brokers.ctpbroker import CTPBroker
        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}  # dict for O(1) removal
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 0.0
        broker.startingvalue = broker.value = 0.0
        broker.positions = collections.defaultdict(
            lambda: MagicMock(size=0, price=0.0)
        )
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker.o = MagicMock()
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_start_with_positions(self):
        broker = self._make_broker_for_start()
        from backtrader.position import Position
        broker.positions = collections.defaultdict(Position)
        broker._params = {'use_positions': True}
        broker.get_param = lambda k: broker._params.get(k)

        broker.o.get_positions.return_value = [
            {'instrument': 'rb2501', 'direction': '2', 'volume': 5, 'avg_price': 3500.0,
             'yd_volume': 5, 'today_volume': 0},
        ]
        with patch.object(type(broker).__bases__[0], 'start', return_value=None):
            broker.start()
        assert broker.positions['rb2501'].size == 5

    def test_start_with_empty_positions(self):
        broker = self._make_broker_for_start()
        broker._params = {'use_positions': True}
        broker.get_param = lambda k: broker._params.get(k)
        broker.o.get_positions.return_value = []
        with patch.object(type(broker).__bases__[0], 'start', return_value=None):
            broker.start()


# ---------------------------------------------------------------------------
# Test CTPData source code verification
# ---------------------------------------------------------------------------

class TestCTPDataSource:
    """Verify CTPData source code correctness."""

    def test_no_bar_timeframe_in_backfill(self):
        """_get_backfill_data should use _timeframe not _bar_timeframe."""
        import ast
        with open('backtrader/feeds/ctpdata.py') as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if isinstance(node.attr, str) and node.attr == '_bar_timeframe':
                    pytest.fail("Found _bar_timeframe reference in ctpdata.py")

    def test_no_ctpbee_imports(self):
        """CTPData should not import ctpbee."""
        with open('backtrader/feeds/ctpdata.py') as f:
            source = f.read()
        assert 'ctpbee' not in source, "ctpdata.py still references ctpbee"

    def test_no_ctpbee_in_store(self):
        """CTPStore should not import ctpbee."""
        with open('backtrader/stores/ctpstore.py') as f:
            source = f.read()
        assert 'ctpbee' not in source, "ctpstore.py still references ctpbee"

    def test_no_ctpbee_in_broker(self):
        """CTPBroker should not import ctpbee."""
        with open('backtrader/brokers/ctpbroker.py') as f:
            source = f.read()
        assert 'ctpbee' not in source, "ctpbroker.py still references ctpbee"


# ---------------------------------------------------------------------------
# Tests for A1: SHFE/INE CloseToday/CloseYesterday
# ---------------------------------------------------------------------------

class TestSHFECloseOffset:
    """Tests for SHFE/INE CloseToday/CloseYesterday offset determination."""

    def _make_broker(self):
        from backtrader.brokers.ctpbroker import CTPBroker
        from backtrader.position import Position

        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 150000.0
        broker.positions = collections.defaultdict(Position)
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker._pending_stops = []
        broker._params = {'use_positions': True, 'commission': 0.0}
        broker.get_param = lambda k: broker._params.get(k)

        broker.o = MagicMock()
        broker.o.order_queue = queue.Queue()
        broker.o.trade_queue = queue.Queue()
        broker.o.send_order.return_value = '1'
        broker.o.get_balance.return_value = None
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_close_today_shfe(self):
        """SHFE sell close with today position should use CloseToday."""
        from backtrader.brokers.ctpbroker import THOST_FTDC_OF_CloseToday
        from backtrader.position import Position
        broker = self._make_broker()
        broker.positions['rb2501.SHFE'] = Position(5, 3500.0)
        broker._pos_detail['rb2501'] = {
            'today_long': 5, 'today_short': 0, 'yd_long': 0, 'yd_short': 0
        }
        owner = MagicMock()
        data = _make_mock_data('rb2501.SHFE')

        broker.sell(owner, data, size=3, price=3500.0, exectype=None)
        call_kwargs = broker.o.send_order.call_args
        assert call_kwargs[1].get('offset') == THOST_FTDC_OF_CloseToday

    def test_close_yesterday_shfe(self):
        """SHFE sell close with yd position should use CloseYesterday."""
        from backtrader.brokers.ctpbroker import THOST_FTDC_OF_CloseYesterday
        from backtrader.position import Position
        broker = self._make_broker()
        broker.positions['rb2501.SHFE'] = Position(5, 3500.0)
        broker._pos_detail['rb2501'] = {
            'today_long': 0, 'today_short': 0, 'yd_long': 5, 'yd_short': 0
        }
        owner = MagicMock()
        data = _make_mock_data('rb2501.SHFE')

        broker.sell(owner, data, size=3, price=3500.0, exectype=None)
        call_kwargs = broker.o.send_order.call_args
        assert call_kwargs[1].get('offset') == THOST_FTDC_OF_CloseYesterday

    def test_non_shfe_uses_close(self):
        """Non-SHFE exchange should use plain Close offset."""
        broker = self._make_broker()
        from backtrader.position import Position
        broker.positions['IF2506.CFFEX'] = Position(5, 4000.0)
        owner = MagicMock()
        data = _make_mock_data('IF2506.CFFEX')

        broker.sell(owner, data, size=3, price=4000.0, exectype=None)
        call_kwargs = broker.o.send_order.call_args
        assert call_kwargs[1].get('offset') == THOST_FTDC_OF_Close

    def test_extract_exchange(self):
        from backtrader.brokers.ctpbroker import _extract_exchange, _extract_instrument
        assert _extract_exchange('rb2501.SHFE') == 'SHFE'
        assert _extract_exchange('IF2506.CFFEX') == 'CFFEX'
        assert _extract_exchange('rb2501') == ''
        assert _extract_instrument('rb2501.SHFE') == 'rb2501'
        assert _extract_instrument('rb2501') == 'rb2501'


# ---------------------------------------------------------------------------
# Tests for A2: Commission calculation
# ---------------------------------------------------------------------------

class TestCommissionCalc:
    """Tests for commission calculation in trade processing."""

    def _make_broker_with_commission(self, comm=1.5):
        from backtrader.brokers.ctpbroker import CTPBroker
        from backtrader.position import Position

        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 150000.0
        broker.positions = collections.defaultdict(Position)
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker._pending_stops = []
        broker._params = {'use_positions': True, 'commission': comm}
        broker.get_param = lambda k: broker._params.get(k)

        broker.o = MagicMock()
        broker.o.order_queue = queue.Queue()
        broker.o.trade_queue = queue.Queue()
        broker.o.send_order.return_value = '1'
        broker.o.get_balance.return_value = None
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_commission_applied_on_fill(self):
        """Commission should be applied when processing trade fills."""
        broker = self._make_broker_with_commission(comm=2.0)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=3, price=3500.0, exectype=None)
        evt = _make_trade_event(order_ref='1', price=3500.0, volume=3)
        broker.o.trade_queue.put(evt)
        broker._process_trade_events()

        # Commission = 2.0 * 3 = 6.0
        assert order.executed.comm == 6.0

    def test_zero_commission(self):
        """Zero commission rate should produce zero commission."""
        broker = self._make_broker_with_commission(comm=0.0)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3500.0, exectype=None)
        evt = _make_trade_event(order_ref='1', price=3500.0, volume=1)
        broker.o.trade_queue.put(evt)
        broker._process_trade_events()

        assert order.executed.comm == 0.0


# ---------------------------------------------------------------------------
# Tests for B3: Invalid tick data filtering
# ---------------------------------------------------------------------------

class TestInvalidTickFiltering:
    """Tests for invalid tick data filtering in CTPMdSpi."""

    def _make_spi(self):
        spi = CTPMdSpi.__new__(CTPMdSpi)
        spi.front = 'tcp://127.0.0.1:0'
        spi.broker_id = '9999'
        spi.user_id = 'test'
        spi.password = 'test'
        spi.request_id = 0
        spi._id_lock = threading.Lock()
        spi.connected = False
        spi.loggedin = False
        spi._subscribed = set()
        spi.tick_queues = {}
        spi._lock = threading.Lock()
        return spi

    def test_dbl_max_price_filtered(self):
        """Tick with DBL_MAX price should be filtered out."""
        spi = self._make_spi()
        spi.register_instrument('rb2501')
        md = MagicMock()
        md.InstrumentID = 'rb2501'
        md.LastPrice = 1.7976931348623157e+308  # DBL_MAX
        spi.OnRtnDepthMarketData(md)
        assert spi.tick_queues['rb2501'].empty()

    def test_zero_price_filtered(self):
        """Tick with zero price should be filtered out."""
        spi = self._make_spi()
        spi.register_instrument('rb2501')
        md = MagicMock()
        md.InstrumentID = 'rb2501'
        md.LastPrice = 0.0
        spi.OnRtnDepthMarketData(md)
        assert spi.tick_queues['rb2501'].empty()

    def test_negative_price_filtered(self):
        """Tick with negative price should be filtered out."""
        spi = self._make_spi()
        spi.register_instrument('rb2501')
        md = MagicMock()
        md.InstrumentID = 'rb2501'
        md.LastPrice = -100.0
        spi.OnRtnDepthMarketData(md)
        assert spi.tick_queues['rb2501'].empty()

    def test_valid_price_with_invalid_secondary(self):
        """Valid last_price but invalid secondary price should still produce tick with 0.0."""
        spi = self._make_spi()
        spi.register_instrument('rb2501')
        md = MagicMock()
        md.InstrumentID = 'rb2501'
        md.LastPrice = 3500.0
        md.OpenPrice = 1.7976931348623157e+308  # invalid
        md.HighestPrice = 3510.0
        md.LowestPrice = 3470.0
        md.Volume = 100
        md.OpenInterest = 5000.0
        md.BidPrice1 = 3499.0
        md.AskPrice1 = 3501.0
        md.BidVolume1 = 10
        md.AskVolume1 = 12
        md.UpdateTime = '10:00:00'
        md.UpdateMillisec = 0
        md.TradingDay = '20250301'
        md.ActionDay = '20250301'
        spi.OnRtnDepthMarketData(md)
        assert not spi.tick_queues['rb2501'].empty()
        tick = spi.tick_queues['rb2501'].get_nowait()
        assert tick['open_price'] == 0.0  # sanitized to 0.0
        assert tick['high_price'] == 3510.0  # valid


# ---------------------------------------------------------------------------
# Tests for B4: Bounded queue protection
# ---------------------------------------------------------------------------

class TestBoundedQueues:
    """Tests for bounded queue protection."""

    def test_md_tick_queue_has_maxsize(self):
        """Registered tick queues should have maxsize."""
        spi = CTPMdSpi.__new__(CTPMdSpi)
        spi.tick_queues = {}
        spi._lock = threading.Lock()
        spi._subscribed = set()
        q = spi.register_instrument('rb2501')
        assert q.maxsize == 10000

    def test_subscribe_tracks_instruments(self):
        """Subscribe should track instruments for reconnect."""
        spi = CTPMdSpi.__new__(CTPMdSpi)
        spi._subscribed = set()
        spi.api = MagicMock()
        spi._id_lock = threading.Lock()
        spi.request_id = 0
        spi.subscribe(['rb2501', 'IF2506'])
        assert 'rb2501' in spi._subscribed
        assert 'IF2506' in spi._subscribed


# ---------------------------------------------------------------------------
# Tests for C1: Stop/StopLimit order support
# ---------------------------------------------------------------------------

class TestStopOrders:
    """Tests for local stop order triggering."""

    def _make_broker(self):
        from backtrader.brokers.ctpbroker import CTPBroker
        from backtrader.position import Position

        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 150000.0
        broker.positions = collections.defaultdict(Position)
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker._pending_stops = []
        broker._params = {'use_positions': True, 'commission': 0.0}
        broker.get_param = lambda k: broker._params.get(k)

        broker.o = MagicMock()
        broker.o.order_queue = queue.Queue()
        broker.o.trade_queue = queue.Queue()
        broker.o.send_order.return_value = '1'
        broker.o.get_balance.return_value = None
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_stop_order_held_locally(self):
        """Stop order should be held locally, not sent to CTP immediately."""
        from backtrader.order import Order
        broker = self._make_broker()
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3600.0,
                           exectype=Order.Stop)
        assert len(broker._pending_stops) == 1
        broker.o.send_order.assert_not_called()
        assert order.ref in broker.open_orders

    def test_stop_buy_triggered(self):
        """Stop buy should trigger when price >= stop_price."""
        from backtrader.order import Order
        broker = self._make_broker()
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3600.0,
                           exectype=Order.Stop)
        # Simulate price reaching stop
        data.close.__getitem__ = MagicMock(return_value=3600.0)
        broker._check_stop_triggers()

        assert len(broker._pending_stops) == 0
        broker.o.send_order.assert_called_once()
        assert order.triggered is True

    def test_stop_sell_triggered(self):
        """Stop sell should trigger when price <= stop_price."""
        from backtrader.order import Order
        broker = self._make_broker()
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.sell(owner, data, size=1, price=3400.0,
                            exectype=Order.Stop)
        data.close.__getitem__ = MagicMock(return_value=3400.0)
        broker._check_stop_triggers()

        assert len(broker._pending_stops) == 0
        broker.o.send_order.assert_called_once()

    def test_stop_not_triggered_yet(self):
        """Stop should NOT trigger if price hasn't reached stop level."""
        from backtrader.order import Order
        broker = self._make_broker()
        owner = MagicMock()
        data = _make_mock_data()

        broker.buy(owner, data, size=1, price=3600.0, exectype=Order.Stop)
        data.close.__getitem__ = MagicMock(return_value=3500.0)  # below stop
        broker._check_stop_triggers()

        assert len(broker._pending_stops) == 1
        broker.o.send_order.assert_not_called()

    def test_stoplimit_uses_limit_price(self):
        """StopLimit should send limit order when triggered."""
        from backtrader.order import Order
        broker = self._make_broker()
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=1, price=3600.0,
                           plimit=3610.0, exectype=Order.StopLimit)
        data.close.__getitem__ = MagicMock(return_value=3600.0)
        broker._check_stop_triggers()

        call_kwargs = broker.o.send_order.call_args[1]
        from backtrader.stores.ctpstore import THOST_FTDC_OPT_LimitPrice
        assert call_kwargs['order_price_type'] == THOST_FTDC_OPT_LimitPrice
        assert call_kwargs['price'] == 3610.0


# ---------------------------------------------------------------------------
# Tests for C3: Trading session-aware bar alignment
# ---------------------------------------------------------------------------

class TestSessionBarAlignment:
    """Tests for trading session-aware bar time alignment."""

    def test_align_bar_time_basic(self):
        """Basic alignment should return reasonable bar start/end."""
        from backtrader.feeds.ctpdata import CTPData, CHINA_TZ
        data = CTPData.__new__(CTPData)
        data._bar_compression_secs = 300  # 5 minutes
        dt = CHINA_TZ.localize(datetime(2025, 3, 1, 10, 3, 0))
        bar_start, bar_end = data._align_bar_time(dt)
        assert bar_start <= dt
        assert bar_end > bar_start

    def test_align_clips_at_session_break(self):
        """Bar crossing 10:15 session break should be clipped."""
        from backtrader.feeds.ctpdata import CTPData, CHINA_TZ
        data = CTPData.__new__(CTPData)
        data._bar_compression_secs = 300  # 5 minutes
        # Tick at 10:12 — 5-min bar would be 10:10-10:15
        dt = CHINA_TZ.localize(datetime(2025, 3, 1, 10, 12, 0))
        bar_start, bar_end = data._align_bar_time(dt)
        # bar_end should be clipped to 10:15 session break
        assert bar_end.hour == 10
        assert bar_end.minute == 15

    def test_align_no_clip_in_middle(self):
        """Bar fully within a session should not be clipped."""
        from backtrader.feeds.ctpdata import CTPData, CHINA_TZ
        data = CTPData.__new__(CTPData)
        data._bar_compression_secs = 300  # 5 minutes
        # Tick at 10:02 — 5-min bar would be 10:00-10:05
        dt = CHINA_TZ.localize(datetime(2025, 3, 1, 10, 2, 0))
        bar_start, bar_end = data._align_bar_time(dt)
        assert bar_end.hour == 10
        assert bar_end.minute == 5


# ---------------------------------------------------------------------------
# Tests for position detail tracking in trade events
# ---------------------------------------------------------------------------

class TestPositionDetailTracking:
    """Tests for today/yd position detail updates on trade fills."""

    def _make_broker(self):
        from backtrader.brokers.ctpbroker import CTPBroker
        from backtrader.position import Position

        broker = CTPBroker.__new__(CTPBroker)
        broker.orders = collections.OrderedDict()
        broker.open_orders = {}
        broker.notifs = collections.deque()
        broker._ref_to_bt = {}
        broker.startingcash = broker.cash = 100000.0
        broker.startingvalue = broker.value = 150000.0
        broker.positions = collections.defaultdict(Position)
        broker._pos_detail = collections.defaultdict(
            lambda: {'today_long': 0, 'today_short': 0, 'yd_long': 0, 'yd_short': 0}
        )
        broker._pending_stops = []
        broker._params = {'use_positions': True, 'commission': 0.0}
        broker.get_param = lambda k: broker._params.get(k)

        broker.o = MagicMock()
        broker.o.order_queue = queue.Queue()
        broker.o.trade_queue = queue.Queue()
        broker.o.send_order.return_value = '1'
        broker.o.get_balance.return_value = None
        broker.o.get_cash.return_value = 100000.0
        broker.o.get_value.return_value = 150000.0
        return broker

    def test_open_buy_updates_today_long(self):
        """Opening a buy should increase today_long."""
        broker = self._make_broker()
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.buy(owner, data, size=3, price=3500.0, exectype=None)
        evt = _make_trade_event(order_ref='1', price=3500.0, volume=3,
                                offset=THOST_FTDC_OF_Open)
        broker.o.trade_queue.put(evt)
        broker._process_trade_events()

        # _extract_instrument('rb2501.SHFE') -> 'rb2501'
        assert broker._pos_detail['rb2501']['today_long'] == 3

    def test_close_today_updates_detail(self):
        """Closing today position should decrease today_long."""
        from backtrader.stores.ctpstore import THOST_FTDC_OF_CloseToday
        from backtrader.position import Position
        broker = self._make_broker()
        # _extract_instrument('rb2501.SHFE') -> 'rb2501'
        broker._pos_detail['rb2501'] = {
            'today_long': 5, 'today_short': 0, 'yd_long': 0, 'yd_short': 0
        }
        broker.positions['rb2501.SHFE'] = Position(5, 3500.0)
        owner = MagicMock()
        data = _make_mock_data()

        order = broker.sell(owner, data, size=2, price=3500.0, exectype=None)
        evt = _make_trade_event(order_ref='1', price=3500.0, volume=2,
                                offset=THOST_FTDC_OF_CloseToday)
        broker.o.trade_queue.put(evt)
        broker._process_trade_events()

        assert broker._pos_detail['rb2501']['today_long'] == 3
