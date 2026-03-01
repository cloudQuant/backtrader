#!/usr/bin/env python
"""CTP Store Module - CTP futures trading via ctp-python.

This module provides the CTPStore for connecting to CTP (China Futures)
using the ctp-python package (native SWIG wrapper around official CTP C++ API).

Classes:
    CTPTraderSpi: Trader callback handler.
    CTPMdSpi: Market data callback handler.
    CTPStore: Singleton store managing both trader and market data connections.

Example:
    >>> store = bt.stores.CTPStore(
    ...     td_front='tcp://180.168.146.187:10130',
    ...     md_front='tcp://180.168.146.187:10131',
    ...     broker_id='9999',
    ...     user_id='your_id',
    ...     password='your_password',
    ...     app_id='simnow_client_test',
    ...     auth_code='0000000000000000',
    )
    >>> cerebro.setbroker(store.getbroker())
"""

import hashlib
import logging
import os
import tempfile
import threading
from time import sleep, time

import ctp

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.utils.py3 import queue

logger = logging.getLogger(__name__)

# CTP uses DBL_MAX (1.7976931348623157e+308) for invalid prices
_CTP_INVALID_PRICE = 1e300

# ---------------------------------------------------------------------------
# CTP constants for order direction / offset / order price type
# ---------------------------------------------------------------------------
# Direction
THOST_FTDC_D_Buy = "0"
THOST_FTDC_D_Sell = "1"
# Offset
THOST_FTDC_OF_Open = "0"
THOST_FTDC_OF_Close = "1"
THOST_FTDC_OF_CloseToday = "3"
THOST_FTDC_OF_CloseYesterday = "4"
# Order price type
THOST_FTDC_OPT_LimitPrice = "2"
THOST_FTDC_OPT_AnyPrice = "1"
# Hedge flag
THOST_FTDC_HF_Speculation = "1"
# Time condition
THOST_FTDC_TC_GFD = "3"  # Good for day
THOST_FTDC_TC_IOC = "1"  # Immediate or cancel
# Volume condition
THOST_FTDC_VC_AV = "1"  # Any volume
THOST_FTDC_VC_CV = "3"  # Complete volume
# Contingent condition
THOST_FTDC_CC_Immediately = "1"
# Force close reason
THOST_FTDC_FCC_NotForceClose = "0"
# Action flag
THOST_FTDC_AF_Delete = "0"
# Order status
THOST_FTDC_OST_AllTraded = "0"
THOST_FTDC_OST_PartTradedQueueing = "1"
THOST_FTDC_OST_PartTradedNotQueueing = "2"
THOST_FTDC_OST_NoTradeQueueing = "3"
THOST_FTDC_OST_NoTradeNotQueueing = "4"
THOST_FTDC_OST_Canceled = "5"
THOST_FTDC_OST_Unknown = "a"


# ---------------------------------------------------------------------------
# CTPTraderSpi: Trader callback handler
# ---------------------------------------------------------------------------


class CTPTraderSpi(ctp.CThostFtdcTraderSpi):
    """CTP Trader SPI — handles order/trade/account/position callbacks."""

    def __init__(self, front, broker_id, user_id, password, app_id, auth_code):
        """Initialize the CTP Trader SPI.

        Args:
            front: CTP trader front address (e.g., 'tcp://180.168.146.187:10130').
            broker_id: Broker ID assigned by CTP.
            user_id: User ID for trading.
            password: Password for the trading account.
            app_id: Application ID for authentication.
            auth_code: Authentication code for the application.
        """
        super().__init__()
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self.password = password
        self.app_id = app_id
        self.auth_code = auth_code

        self.request_id = 0
        self.order_ref = 0
        self.front_id = 0
        self.session_id = 0
        self._id_lock = threading.Lock()

        # State flags
        self.connected = False
        self.authed = False
        self.loggedin = False
        self.login_error = None  # (error_id, error_msg) tuple on failure
        # T6: Disconnect/reconnect callbacks
        self._disconnect_callbacks = []
        self._reconnect_callbacks = []

        # Event queues (set by CTPStore)
        self.order_queue = queue.Queue()
        self.trade_queue = queue.Queue()

        # Account / position query results
        self._account = None
        self._positions = []
        self._position_query_done = threading.Event()
        self._account_query_done = threading.Event()

        # Create API
        dir_name = "".join(("ctp", broker_id, user_id)).encode("UTF-8")
        dir_name = hashlib.md5(dir_name).hexdigest()
        dir_path = os.path.join(tempfile.gettempdir(), dir_name, "Trader") + os.sep
        if not os.path.isdir(dir_path):
            os.makedirs(dir_path)
        self.api = ctp.CThostFtdcTraderApi.CreateFtdcTraderApi(dir_path)

    def run(self):
        """Start the trader API in current thread (blocking)."""
        self.api.RegisterSpi(self)
        self.api.RegisterFront(self.front)
        self.api.Init()
        self.api.Join()

    def _next_request_id(self):
        """Generate the next unique request ID.

        Returns:
            int: The next request ID.
        """
        with self._id_lock:
            self.request_id += 1
            return self.request_id

    def _next_order_ref(self):
        """Generate the next unique order reference.

        Returns:
            str: The next order reference as a string.
        """
        with self._id_lock:
            self.order_ref += 1
            return str(self.order_ref)

    # --- Connection callbacks ---
    def OnFrontConnected(self):
        """Handle front connection established event.

        Initiates authentication when connection is established.
        """
        logger.info("[CTPTrader] OnFrontConnected")
        self.connected = True
        self._do_auth()

    def OnFrontDisconnected(self, nReason):
        """Handle front disconnection event.

        Args:
            nReason: Reason code for disconnection.

        Note:
            CTP API will auto-reconnect and fire OnFrontConnected again.
        """
        logger.warning(f"[CTPTrader] OnFrontDisconnected reason={nReason}")
        self.connected = False
        self.loggedin = False
        self.authed = False
        # T6: Notify registered disconnect callbacks
        for cb in getattr(self, "_disconnect_callbacks", []):
            try:
                cb(nReason)
            except Exception as e:
                logger.error(f"[CTPTrader] disconnect callback error: {e}")
        # B1: CTP API will auto-reconnect and fire OnFrontConnected again.
        # Our OnFrontConnected -> _do_auth -> _do_login chain handles re-login.
        logger.info("[CTPTrader] Waiting for auto-reconnect...")

    # --- Auth / Login ---
    def _do_auth(self):
        """Send authentication request to CTP server."""
        field = ctp.CThostFtdcReqAuthenticateField()
        field.BrokerID = self.broker_id
        field.UserID = self.user_id
        field.AppID = self.app_id
        field.AuthCode = self.auth_code
        self.api.ReqAuthenticate(field, self._next_request_id())

    def OnRspAuthenticate(self, pRspAuthenticateField, pRspInfo, nRequestID, bIsLast):
        """Handle authentication response.

        Args:
            pRspAuthenticateField: Authentication response field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo and pRspInfo.ErrorID == 0:
            logger.info("[CTPTrader] Auth OK")
            self.authed = True
            self._do_login()
        else:
            err = pRspInfo.ErrorMsg if pRspInfo else "unknown"
            logger.error(f"[CTPTrader] Auth failed: {err}")

    def _do_login(self):
        """Send login request to CTP server."""
        field = ctp.CThostFtdcReqUserLoginField()
        field.BrokerID = self.broker_id
        field.UserID = self.user_id
        field.Password = self.password
        self.api.ReqUserLogin(field, self._next_request_id())

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        """Handle user login response.

        Args:
            pRspUserLogin: User login response field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo and pRspInfo.ErrorID == 0:
            self.loggedin = True
            self.login_error = None
            self.front_id = pRspUserLogin.FrontID
            self.session_id = pRspUserLogin.SessionID
            logger.info(f"[CTPTrader] Login OK front={self.front_id} session={self.session_id}")
            # T6: Notify reconnect callbacks
            for cb in self._reconnect_callbacks:
                try:
                    cb()
                except Exception as e:
                    logger.error(f"[CTPTrader] reconnect callback error: {e}")
            # Confirm settlement
            field = ctp.CThostFtdcSettlementInfoConfirmField()
            field.BrokerID = self.broker_id
            field.InvestorID = self.user_id
            self.api.ReqSettlementInfoConfirm(field, self._next_request_id())
        else:
            err_id = pRspInfo.ErrorID if pRspInfo else -1
            err_msg = pRspInfo.ErrorMsg if pRspInfo else "unknown"
            self.login_error = (err_id, err_msg)
            logger.error(f"[CTPTrader] Login failed: ErrorID={err_id} {err_msg}")

    def OnRspSettlementInfoConfirm(self, pSettlementInfoConfirm, pRspInfo, nRequestID, bIsLast):
        """Handle settlement info confirmation response.

        Args:
            pSettlementInfoConfirm: Settlement confirmation field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        logger.info("[CTPTrader] Settlement confirmed")

    # --- Order callbacks ---
    def OnRtnOrder(self, pOrder):
        """Order status update from exchange.

        Args:
            pOrder: Order object from CTP.
        """
        if pOrder is None:
            return
        info = {
            "order_ref": pOrder.OrderRef,
            "order_sys_id": pOrder.OrderSysID.strip() if pOrder.OrderSysID else "",
            "front_id": pOrder.FrontID,
            "session_id": pOrder.SessionID,
            "instrument": pOrder.InstrumentID,
            "direction": pOrder.Direction,
            "offset": pOrder.CombOffsetFlag,
            "price": pOrder.LimitPrice,
            "volume": pOrder.VolumeTotalOriginal,
            "volume_traded": pOrder.VolumeTraded,
            "volume_remaining": pOrder.VolumeTotal,
            "status": pOrder.OrderStatus,
            "status_msg": pOrder.StatusMsg if hasattr(pOrder, "StatusMsg") else "",
        }
        logger.debug(f"[CTPTrader] OnRtnOrder: {info}")
        self.order_queue.put(info)

    def OnRtnTrade(self, pTrade):
        """Trade fill notification from exchange.

        Args:
            pTrade: Trade object from CTP.
        """
        if pTrade is None:
            return
        info = {
            "order_ref": pTrade.OrderRef,
            "order_sys_id": pTrade.OrderSysID.strip() if pTrade.OrderSysID else "",
            "instrument": pTrade.InstrumentID,
            "direction": pTrade.Direction,
            "offset": pTrade.OffsetFlag,
            "price": pTrade.Price,
            "volume": pTrade.Volume,
            "trade_id": pTrade.TradeID.strip() if pTrade.TradeID else "",
            "trade_time": pTrade.TradeTime if hasattr(pTrade, "TradeTime") else "",
        }
        logger.debug(f"[CTPTrader] OnRtnTrade: {info}")
        self.trade_queue.put(info)

    def OnRspOrderInsert(self, pInputOrder, pRspInfo, nRequestID, bIsLast):
        """Order insert error response.

        Args:
            pInputOrder: Input order field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"[CTPTrader] OrderInsert error: {pRspInfo.ErrorMsg}")
            if pInputOrder:
                info = {
                    "order_ref": pInputOrder.OrderRef,
                    "instrument": pInputOrder.InstrumentID,
                    "status": THOST_FTDC_OST_Canceled,
                    "status_msg": pRspInfo.ErrorMsg,
                    "direction": pInputOrder.Direction,
                    "offset": pInputOrder.CombOffsetFlag,
                    "price": pInputOrder.LimitPrice,
                    "volume": pInputOrder.VolumeTotalOriginal,
                    "volume_traded": 0,
                    "volume_remaining": pInputOrder.VolumeTotalOriginal,
                    "front_id": 0,
                    "session_id": 0,
                    "order_sys_id": "",
                    "rejected": True,
                }
                self.order_queue.put(info)

    def OnRspOrderAction(self, pInputOrderAction, pRspInfo, nRequestID, bIsLast):
        """Cancel order error response.

        Args:
            pInputOrderAction: Order action field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo and pRspInfo.ErrorID != 0:
            logger.error(f"[CTPTrader] OrderAction error: {pRspInfo.ErrorMsg}")

    def OnRspError(self, pRspInfo, nRequestID, bIsLast):
        """Handle general error response.

        Args:
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo:
            logger.error(f"[CTPTrader] RspError: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}")

    # --- Account query ---
    _last_query_time = 0.0  # T14: throttle all CTP queries (1s rate limit)

    def _throttle_query(self):
        """T14: Ensure at least 1.1s between consecutive CTP queries."""
        now = time()
        elapsed = now - CTPTraderSpi._last_query_time
        if elapsed < 1.1:
            sleep(1.1 - elapsed)
        CTPTraderSpi._last_query_time = time()

    def query_account(self):
        """Send account query request."""
        self._throttle_query()
        self._account_query_done.clear()
        field = ctp.CThostFtdcQryTradingAccountField()
        field.BrokerID = self.broker_id
        field.InvestorID = self.user_id
        self.api.ReqQryTradingAccount(field, self._next_request_id())

    def OnRspQryTradingAccount(self, pTradingAccount, pRspInfo, nRequestID, bIsLast):
        """Handle trading account query response.

        Args:
            pTradingAccount: Trading account field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pTradingAccount:
            self._account = {
                "available": pTradingAccount.Available,
                "balance": pTradingAccount.Balance,
                "margin": pTradingAccount.CurrMargin,
                "commission": pTradingAccount.Commission,
                "frozen_margin": pTradingAccount.FrozenMargin,
                "frozen_cash": pTradingAccount.FrozenCash,
                "trading_day": getattr(pTradingAccount, "TradingDay", None),
            }
        if bIsLast:
            self._account_query_done.set()

    # --- Position query ---
    def query_positions(self):
        """Send position query request."""
        self._throttle_query()
        self._positions = []
        self._position_query_done.clear()
        field = ctp.CThostFtdcQryInvestorPositionField()
        field.BrokerID = self.broker_id
        field.InvestorID = self.user_id
        self.api.ReqQryInvestorPosition(field, self._next_request_id())

    def OnRspQryInvestorPosition(self, pInvestorPosition, pRspInfo, nRequestID, bIsLast):
        """Handle investor position query response.

        Args:
            pInvestorPosition: Investor position field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pInvestorPosition and pInvestorPosition.InstrumentID:
            self._positions.append(
                {
                    "instrument": pInvestorPosition.InstrumentID,
                    "direction": pInvestorPosition.PosiDirection,  # '2'=Long, '3'=Short
                    "volume": pInvestorPosition.Position,
                    "yd_volume": pInvestorPosition.YdPosition,
                    "today_volume": pInvestorPosition.TodayPosition,
                    "avg_price": pInvestorPosition.OpenCost / max(pInvestorPosition.Position, 1),
                    "position_profit": pInvestorPosition.PositionProfit,
                }
            )
        if bIsLast:
            self._position_query_done.set()

    # --- Order submission ---
    def send_order(
        self,
        instrument,
        direction,
        offset,
        price,
        volume,
        order_price_type=THOST_FTDC_OPT_LimitPrice,
    ):
        """Submit an order to CTP.

        Args:
            instrument: Instrument ID (e.g. 'rb2501').
            direction: '0'=Buy, '1'=Sell.
            offset: '0'=Open, '1'=Close, '3'=CloseToday, '4'=CloseYesterday.
            price: Order price.
            volume: Number of contracts.
            order_price_type: '2'=Limit (default), '1'=Market.

        Returns:
            str: order_ref string, or None on failure.
        """
        order_ref = self._next_order_ref()
        field = ctp.CThostFtdcInputOrderField()
        field.BrokerID = self.broker_id
        field.InvestorID = self.user_id
        field.InstrumentID = instrument
        field.OrderRef = order_ref
        field.Direction = direction
        field.CombOffsetFlag = offset
        field.CombHedgeFlag = THOST_FTDC_HF_Speculation
        field.OrderPriceType = order_price_type
        field.LimitPrice = float(price)
        field.VolumeTotalOriginal = int(volume)
        if order_price_type == THOST_FTDC_OPT_AnyPrice:
            field.TimeCondition = THOST_FTDC_TC_IOC
            field.VolumeCondition = THOST_FTDC_VC_CV
            field.LimitPrice = 0.0
        else:
            field.TimeCondition = THOST_FTDC_TC_GFD
            field.VolumeCondition = THOST_FTDC_VC_AV
        field.MinVolume = 1
        field.ContingentCondition = THOST_FTDC_CC_Immediately
        field.ForceCloseReason = THOST_FTDC_FCC_NotForceClose
        field.IsAutoSuspend = 0

        try:
            ret = self.api.ReqOrderInsert(field, self._next_request_id())
            if ret == 0:
                logger.info(
                    f"[CTPTrader] send_order: {instrument} dir={direction} "
                    f"offset={offset} price={price} vol={volume} ref={order_ref}"
                )
                return order_ref
            else:
                logger.error(f"[CTPTrader] send_order failed ret={ret}")
                return None
        except Exception as e:
            logger.error(f"[CTPTrader] send_order exception: {e}")
            return None

    def cancel_order_by_ref(
        self, instrument, order_ref, front_id=None, session_id=None, exchange_id=""
    ):
        """Cancel an order by order_ref.

        Args:
            instrument: Instrument ID.
            order_ref: Order reference.
            front_id: Front ID (defaults to current session).
            session_id: Session ID (defaults to current session).
            exchange_id: Exchange ID (optional).

        Returns:
            bool: True if cancellation request succeeded, False otherwise.
        """
        field = ctp.CThostFtdcInputOrderActionField()
        field.BrokerID = self.broker_id
        field.InvestorID = self.user_id
        field.InstrumentID = instrument
        field.OrderRef = str(order_ref)
        field.FrontID = front_id or self.front_id
        field.SessionID = session_id or self.session_id
        field.ActionFlag = THOST_FTDC_AF_Delete
        if exchange_id:
            field.ExchangeID = exchange_id

        try:
            ret = self.api.ReqOrderAction(field, self._next_request_id())
            logger.info(f"[CTPTrader] cancel_order ref={order_ref} ret={ret}")
            return ret == 0
        except Exception as e:
            logger.error(f"[CTPTrader] cancel_order exception: {e}")
            return False

    def release(self):
        """Release the trader API resources.

        Unregisters the SPI callback and releases the CTP trader API.
        This should be called when shutting down the connection to
        properly clean up native resources.
        """
        try:
            self.api.RegisterSpi(None)
            self.api.Release()
        except Exception as e:
            logger.warning(f"[CTPTrader] release error: {e}")


# ---------------------------------------------------------------------------
# CTPMdSpi: Market data callback handler
# ---------------------------------------------------------------------------


class CTPMdSpi(ctp.CThostFtdcMdSpi):
    """CTP Market Data SPI — handles tick data callbacks."""

    def __init__(self, front, broker_id, user_id, password):
        """Initialize the CTP Market Data SPI.

        Args:
            front: CTP market data front address (e.g., 'tcp://180.168.146.187:10131').
            broker_id: Broker ID assigned by CTP.
            user_id: User ID for market data.
            password: Password for the market data account.
        """
        super().__init__()
        self.front = front
        self.broker_id = broker_id
        self.user_id = user_id
        self.password = password

        self.request_id = 0
        self._id_lock = threading.Lock()  # B2: thread-safe request_id
        self.connected = False
        self.loggedin = False

        # Subscribed instruments for re-subscribe on reconnect
        self._subscribed = set()

        # Tick data queues: instrument -> queue.Queue
        self.tick_queues = {}
        self._lock = threading.Lock()

        # Create API
        dir_name = "".join(("ctp", broker_id, user_id)).encode("UTF-8")
        dir_name = hashlib.md5(dir_name).hexdigest()
        dir_path = os.path.join(tempfile.gettempdir(), dir_name, "Md") + os.sep
        if not os.path.isdir(dir_path):
            os.makedirs(dir_path)
        self.api = ctp.CThostFtdcMdApi.CreateFtdcMdApi(dir_path)

    def run(self):
        """Start the MD API in current thread (blocking)."""
        self.api.RegisterSpi(self)
        self.api.RegisterFront(self.front)
        self.api.Init()
        self.api.Join()

    def _next_request_id(self):
        """Generate the next unique request ID.

        Returns:
            int: The next request ID.
        """
        with self._id_lock:  # B2: thread-safe
            self.request_id += 1
            return self.request_id

    def OnFrontConnected(self):
        """Handle front connection established event.

        Initiates login when connection is established.
        """
        logger.info("[CTPMd] OnFrontConnected")
        self.connected = True
        field = ctp.CThostFtdcReqUserLoginField()
        field.BrokerID = self.broker_id
        field.UserID = self.user_id
        field.Password = self.password
        self.api.ReqUserLogin(field, self._next_request_id())

    def OnFrontDisconnected(self, nReason):
        """Handle front disconnection event.

        Args:
            nReason: Reason code for disconnection.

        Note:
            CTP API auto-reconnects; OnFrontConnected fires again.
        """
        logger.warning(f"[CTPMd] OnFrontDisconnected reason={nReason}")
        self.connected = False
        self.loggedin = False
        # B1: CTP API auto-reconnects; OnFrontConnected fires again
        logger.info("[CTPMd] Waiting for auto-reconnect...")

    def OnRspUserLogin(self, pRspUserLogin, pRspInfo, nRequestID, bIsLast):
        """Handle user login response.

        Args:
            pRspUserLogin: User login response field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.

        Note:
            Re-subscribes instruments after reconnect.
        """
        if pRspInfo and pRspInfo.ErrorID == 0:
            self.loggedin = True
            logger.info("[CTPMd] Login OK")
            # B1: Re-subscribe instruments after reconnect
            if self._subscribed:
                instruments = list(self._subscribed)
                logger.info(f"[CTPMd] Re-subscribing {len(instruments)} instruments")
                self.api.SubscribeMarketData(instruments)
        else:
            err = pRspInfo.ErrorMsg if pRspInfo else "unknown"
            logger.error(f"[CTPMd] Login failed: {err}")

    def OnRspSubMarketData(self, pSpecificInstrument, pRspInfo, nRequestID, bIsLast):
        """Handle market data subscription response.

        Args:
            pSpecificInstrument: Specific instrument field.
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo and pRspInfo.ErrorID == 0:
            inst = pSpecificInstrument.InstrumentID if pSpecificInstrument else "?"
            logger.info(f"[CTPMd] Subscribed: {inst}")
        else:
            err = pRspInfo.ErrorMsg if pRspInfo else "unknown"
            logger.error(f"[CTPMd] Subscribe failed: {err}")

    def OnRtnDepthMarketData(self, pDepthMarketData):
        """Tick data callback — put into instrument-specific queue.

        Args:
            pDepthMarketData: Depth market data field from CTP.
        """
        if pDepthMarketData is None:
            return
        inst = pDepthMarketData.InstrumentID

        # B3: Filter invalid prices (CTP uses DBL_MAX for missing data)
        last_price = pDepthMarketData.LastPrice
        try:
            if last_price <= 0 or last_price >= _CTP_INVALID_PRICE:
                return
        except TypeError:
            return

        def _safe_price(p):
            try:
                return p if 0 < p < _CTP_INVALID_PRICE else 0.0
            except TypeError:
                return 0.0

        # Build a plain dict to avoid CTP memory management issues
        tick = {
            "instrument": inst,
            "last_price": last_price,
            "open_price": _safe_price(pDepthMarketData.OpenPrice),
            "high_price": _safe_price(pDepthMarketData.HighestPrice),
            "low_price": _safe_price(pDepthMarketData.LowestPrice),
            "volume": pDepthMarketData.Volume,
            "open_interest": pDepthMarketData.OpenInterest,
            "bid_price1": _safe_price(pDepthMarketData.BidPrice1),
            "ask_price1": _safe_price(pDepthMarketData.AskPrice1),
            "bid_volume1": pDepthMarketData.BidVolume1,
            "ask_volume1": pDepthMarketData.AskVolume1,
            "update_time": pDepthMarketData.UpdateTime,
            "update_millisec": pDepthMarketData.UpdateMillisec,
            "trading_day": pDepthMarketData.TradingDay,
            "action_day": (
                pDepthMarketData.ActionDay if hasattr(pDepthMarketData, "ActionDay") else ""
            ),
        }
        with self._lock:
            q = self.tick_queues.get(inst)
        if q is not None:
            # B4: Discard oldest tick if queue is full to prevent memory overflow
            if q.full():
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
            q.put(tick)

    def subscribe(self, instruments):
        """Subscribe to market data for instruments.

        Args:
            instruments: list of instrument IDs, e.g. ['rb2501', 'IF2506'].
        """
        if isinstance(instruments, str):
            instruments = [instruments]
        self._subscribed.update(instruments)  # B1: track for re-subscribe
        self.api.SubscribeMarketData(instruments)

    def register_instrument(self, instrument):
        """Register a tick queue for an instrument.

        Args:
            instrument: Instrument ID to register.

        Returns:
            queue.Queue: The tick queue for the instrument.
        """
        with self._lock:
            if instrument not in self.tick_queues:
                # B4: Bounded queue (10000 ticks max per instrument)
                self.tick_queues[instrument] = queue.Queue(maxsize=10000)
        return self.tick_queues[instrument]

    def OnRspError(self, pRspInfo, nRequestID, bIsLast):
        """Handle general error response.

        Args:
            pRspInfo: Response info containing error ID and message.
            nRequestID: Request ID.
            bIsLast: Whether this is the last response.
        """
        if pRspInfo:
            logger.error(f"[CTPMd] RspError: {pRspInfo.ErrorID} {pRspInfo.ErrorMsg}")

    def release(self):
        """Release the market data API resources.

        Unregisters the SPI callback and releases the CTP market data API.
        This should be called when shutting down the connection to
        properly clean up native resources.
        """
        try:
            self.api.RegisterSpi(None)
            self.api.Release()
        except Exception as e:
            logger.warning(f"[CTPMd] release error: {e}")


# ---------------------------------------------------------------------------
# CTPStore: Singleton store managing both connections
# ---------------------------------------------------------------------------


class CTPStore(ParameterizedSingletonMixin):
    """Singleton store for CTP futures trading via ctp-python.

    Manages both Trader and MarketData connections, provides order
    submission/cancellation, account/position queries, and tick data
    distribution to data feeds.
    """

    BrokerCls = None  # broker class will auto register
    DataCls = None  # data class will auto register

    params = (("debug", False),)

    # SimNow defaults (Group 1, penetrating front, using monitoring center production key)
    DEFAULT_TD_FRONT = "tcp://182.254.243.31:30001"
    DEFAULT_MD_FRONT = "tcp://182.254.243.31:30011"
    DEFAULT_BROKER_ID = "9999"
    DEFAULT_APP_ID = "simnow_client_test"
    DEFAULT_AUTH_CODE = "0000000000000000"

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns `DataCls` with args, kwargs.

        Args:
            *args: Positional arguments to pass to DataCls.
            **kwargs: Keyword arguments to pass to DataCls.

        Returns:
            DataCls: Instance of the data class.
        """
        if cls.DataCls is None:
            from backtrader.feeds.ctpdata import CTPData

            cls.DataCls = CTPData
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered `BrokerCls`.

        Args:
            *args: Positional arguments to pass to BrokerCls.
            **kwargs: Keyword arguments to pass to BrokerCls.

        Returns:
            BrokerCls: Instance of the broker class.
        """
        if cls.BrokerCls is None:
            from backtrader.brokers.ctpbroker import CTPBroker

            cls.BrokerCls = CTPBroker
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self, ctp_setting=None, *args, **kwargs):
        """Initialize the CTPStore instance.

        Args:
            ctp_setting: Dict with keys: td_front, md_front, broker_id,
                user_id, password, app_id, auth_code.
                Can also pass these as **kwargs directly.
        """
        super().__init__()
        if getattr(self, "_ctp_initialized", False):
            return
        self._ctp_initialized = True

        if ctp_setting is None:
            ctp_setting = kwargs
        self.ctp_setting = ctp_setting
        self._is_connected = False
        self._stopped = False

        # Extract config
        self._td_front = ctp_setting.get("td_front", self.DEFAULT_TD_FRONT)
        self._md_front = ctp_setting.get("md_front", self.DEFAULT_MD_FRONT)
        self._broker_id = ctp_setting.get("broker_id", self.DEFAULT_BROKER_ID)
        self._user_id = ctp_setting.get("user_id", "")
        self._password = ctp_setting.get("password", "")
        self._app_id = ctp_setting.get("app_id", self.DEFAULT_APP_ID)
        self._auth_code = ctp_setting.get("auth_code", self.DEFAULT_AUTH_CODE)

        # Initial values
        self._cash = 0.0
        self._value = 0.0
        self._last_balance_query = 0.0
        self._balance_query_interval = 2.0  # CTP has 1s rate limit
        self._feed_count = 0  # track active data feeds

        # B4: Bounded event queues to prevent memory overflow
        self.order_queue = queue.Queue(maxsize=10000)
        self.trade_queue = queue.Queue(maxsize=10000)

        # Create SPIs
        self.trader_spi = CTPTraderSpi(
            front=self._td_front,
            broker_id=self._broker_id,
            user_id=self._user_id,
            password=self._password,
            app_id=self._app_id,
            auth_code=self._auth_code,
        )
        self.trader_spi.order_queue = self.order_queue
        self.trader_spi.trade_queue = self.trade_queue

        self.md_spi = CTPMdSpi(
            front=self._md_front,
            broker_id=self._broker_id,
            user_id=self._user_id,
            password=self._password,
        )

        # Start in daemon threads
        self._td_thread = threading.Thread(target=self.trader_spi.run, daemon=True)
        self._md_thread = threading.Thread(target=self.md_spi.run, daemon=True)
        self._td_thread.start()
        self._md_thread.start()

        # Wait for login (break early on error to avoid CTP login ban)
        timeout = 15
        waited = 0
        while waited < timeout:
            sleep(1)
            waited += 1
            if self.trader_spi.loggedin and self.md_spi.loggedin:
                break
            # Break early if login failed with an error (avoid accumulating
            # failed attempts that trigger CTP error 75 login ban)
            trader_err = getattr(self.trader_spi, "login_error", None)
            if trader_err is not None:
                logger.error(f"[CTPStore] Trader login error: {trader_err}")
                break
        if not self.trader_spi.loggedin:
            trader_err = getattr(self.trader_spi, "login_error", None)
            if trader_err:
                logger.warning(f"[CTPStore] Trader login failed: {trader_err}")
            else:
                logger.warning("[CTPStore] Trader login timeout")
        if not self.md_spi.loggedin:
            logger.warning("[CTPStore] MD login timeout")

        self._is_connected = self.trader_spi.loggedin
        if self._is_connected:
            logger.info("[CTPStore] Connected and logged in")
            # Query initial balance
            self.get_balance()

    def register(self, feed):
        """Register a data feed — creates a tick queue for its instrument.

        Args:
            feed: Data feed instance to register.

        Returns:
            queue.Queue: The tick queue for the feed's instrument.
        """
        self._feed_count += 1
        dataname = feed.p.dataname
        instrument = dataname.split(".")[0] if "." in dataname else dataname
        return self.md_spi.register_instrument(instrument)

    def subscribe(self, dataname):
        """Subscribe to market data for an instrument.

        Args:
            dataname: Instrument name, optionally with exchange suffix (e.g. 'rb2501.SHFE').
        """
        instrument = dataname.split(".")[0] if "." in dataname else dataname
        self.md_spi.subscribe([instrument])

    def stop(self):
        """Stop the CTP store and release all APIs.

        Only actually releases when last feed/broker disconnects.
        """
        self._feed_count = max(0, self._feed_count - 1)
        if self._feed_count > 0:
            return
        if self._stopped:
            return
        self._stopped = True
        self._is_connected = False
        self.trader_spi.release()
        self.md_spi.release()
        logger.info("[CTPStore] Stopped")

    def on_disconnect(self, callback):
        """Register a callback for CTP trader disconnect events.

        Args:
            callback: Function(reason) called when trader front disconnects.
        """
        self.trader_spi._disconnect_callbacks.append(callback)

    def on_reconnect(self, callback):
        """Register a callback for CTP trader reconnect events.

        Args:
            callback: Function() called after successful re-login.
        """
        self.trader_spi._reconnect_callbacks.append(callback)

    @property
    def is_connected(self):
        """Check if the store is connected.

        Returns:
            bool: True if connected and not stopped, False otherwise.
        """
        return self._is_connected and not self._stopped

    # --- Order submission ---
    def send_order(
        self, symbol, direction, offset, price, volume, order_price_type=THOST_FTDC_OPT_LimitPrice
    ):
        """Send an order to CTP.

        Args:
            symbol: e.g. 'rb2501.SHFE' or 'rb2501'.
            direction: THOST_FTDC_D_Buy ('0') or THOST_FTDC_D_Sell ('1').
            offset: THOST_FTDC_OF_Open ('0'), _Close ('1'), etc.
            price: Order price.
            volume: Number of contracts.
            order_price_type: Limit or Market.

        Returns:
            str: order_ref, or None on failure.
        """
        instrument = symbol.split(".")[0] if "." in symbol else symbol
        return self.trader_spi.send_order(
            instrument=instrument,
            direction=direction,
            offset=offset,
            price=price,
            volume=volume,
            order_price_type=order_price_type,
        )

    def cancel_order(self, symbol, order_ref, front_id=None, session_id=None):
        """Cancel an order.

        Args:
            symbol: e.g. 'rb2501.SHFE' or 'rb2501'.
            order_ref: Order reference.
            front_id: Front ID (optional).
            session_id: Session ID (optional).

        Returns:
            bool: True if cancellation request succeeded, False otherwise.
        """
        instrument = symbol.split(".")[0] if "." in symbol else symbol
        exchange_id = symbol.split(".")[1] if "." in symbol else ""
        return self.trader_spi.cancel_order_by_ref(
            instrument=instrument,
            order_ref=order_ref,
            front_id=front_id,
            session_id=session_id,
            exchange_id=exchange_id,
        )

    # --- Account / Position ---
    def get_balance(self):
        """Query and update account balance with rate limiting."""
        now = time()
        if now - self._last_balance_query < self._balance_query_interval:
            return
        try:
            self.trader_spi.query_account()
            if self.trader_spi._account_query_done.wait(timeout=5):
                acc = self.trader_spi._account
                if acc:
                    self._cash = acc["available"]
                    self._value = acc["balance"]
        except Exception as e:
            logger.error(f"[CTPStore] get_balance failed: {e}")
        finally:
            self._last_balance_query = time()

    def get_positions(self):
        """Query and return current positions.

        Returns:
            list: List of position dictionaries, or empty list on failure.
        """
        try:
            self.trader_spi.query_positions()
            if self.trader_spi._position_query_done.wait(timeout=5):
                return self.trader_spi._positions
        except Exception as e:
            logger.error(f"[CTPStore] get_positions failed: {e}")
        return []

    def get_cash(self):
        """Get the current available cash.

        Returns:
            float: Available cash balance.
        """
        return self._cash

    def get_value(self):
        """Get the current account value (total balance).

        Returns:
            float: Total account balance.
        """
        return self._value
