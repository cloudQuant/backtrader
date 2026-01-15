#!/usr/bin/env python
"""OANDA Store Module - OANDA broker connection.

This module provides the OandaStore for connecting to OANDA
brokerage for trading and market data.

Classes:
    OandaStore: Singleton store for OANDA connections.
    OandaRequestError: Custom exception for request errors.
    OandaStreamError: Custom exception for stream errors.

Example:
    >>> store = bt.stores.OandaStore(
    ...     account='your_account',
    ...     token='your_token'
    ... )
    >>> cerebro.setbroker(store.getbroker())
"""

import collections
import json
import threading
import time as _time
import traceback
from datetime import datetime, timedelta, timezone

import oandapy
import requests  # oandapy depdendency

from ..dataseries import TimeFrame
from ..order import Order
from ..utils.py3 import queue

# Remove MetaParams import since we'll eliminate metaclass usage
# from backtrader.metabase import MetaParams
from .mixins import ParameterizedSingletonMixin

# Python 3.11+ has datetime.UTC, earlier versions use timezone.utc
UTC = timezone.utc

# Extend the exceptions to support extra cases


class OandaRequestError(oandapy.OandaError):
    """Exception raised when an OANDA API request fails.

    This exception is used to wrap request failures, such as network errors
    or malformed requests, into a standardized error format compatible with
    the OANDA API error handling system.
    """

    def __init__(self):
        """Initialize the OandaRequestError with default error details.

        Creates an error dictionary with code 599, message "Request Error",
        and an empty description, then passes it to the parent OandaError class.
        """
        er = dict(code=599, message="Request Error", description="")
        super(self.__class__, self).__init__(er)


class OandaStreamError(oandapy.OandaError):
    """Exception raised when an OANDA streaming operation fails.

    This exception is used to wrap streaming failures, such as connection drops
    or malformed streaming data, into a standardized error format compatible with
    the OANDA API error handling system.

    Attributes:
        content: Optional description of the streaming failure.
    """

    def __init__(self, content=""):
        """Initialize the OandaStreamError with error details.

        Args:
            content: Description of the streaming error (default: "").
        """
        er = dict(code=598, message="Failed Streaming", description=content)
        super(self.__class__, self).__init__(er)


class OandaTimeFrameError(oandapy.OandaError):
    """Exception raised when an unsupported timeframe is requested.

    This exception is raised when attempting to use a timeframe/granularity
    combination that is not supported by the OANDA API.
    """

    def __init__(self, content):
        """Initialize the OandaTimeFrameError with error details.

        Args:
            content: The unsupported timeframe or content that triggered the error.
        """
        er = dict(code=597, message="Not supported TimeFrame", description="")
        super(self.__class__, self).__init__(er)


class OandaNetworkError(oandapy.OandaError):
    """Exception raised when a network error occurs during OANDA API communication.

    This exception is used to wrap network-related failures, such as connection
    timeouts or DNS resolution failures, into a standardized error format.
    """

    def __init__(self):
        """Initialize the OandaNetworkError with default error details.

        Creates an error dictionary with code 596, message "Network Error",
        and an empty description, then passes it to the parent OandaError class.
        """
        er = dict(code=596, message="Network Error", description="")
        super(self.__class__, self).__init__(er)


# OANDA has suspended domestic business and this API is no longer available, ignore this source code
class API(oandapy.API):
    """Custom OANDA API wrapper with enhanced error handling.

    This class extends the standard oandapy.API to provide better exception
    handling for network requests. Instead of simply printing exceptions,
    it catches RequestException and returns standardized error responses.

    Note:
        OANDA has suspended domestic business and this API is no longer
        available. This code is kept for reference purposes.
    """

    def request(self, endpoint, method="GET", params=None):
        """Make an HTTP request to the OANDA API with enhanced error handling.

        This method overrides the parent class to catch RequestException
        and return standardized error responses instead of raising exceptions.

        Args:
            endpoint: The API endpoint to call (e.g., "v1/accounts").
            method: HTTP method to use (default: "GET").
            params: Dictionary of query parameters or request body data.

        Returns:
            dict: JSON response parsed as a dictionary, or an error response
                dictionary if the request fails.

        Raises:
            No exceptions are raised; errors are returned as error response dicts.
        """
        url = f"{self.api_url}/{endpoint}"

        method = method.lower()
        params = params or {}

        func = getattr(self.client, method)

        request_args = {}
        if method == "get":
            request_args["params"] = params
        else:
            request_args["data"] = params

        # Added the try block
        try:
            response = func(url, **request_args)
        except requests.RequestException as e:
            traceback.format_exception(e)
            return OandaRequestError().error_response

        content = response.content.decode("utf-8")
        content = json.loads(content)

        # error message
        if response.status_code >= 400:
            # changed from raise to return
            return oandapy.OandaError(content).error_response

        return content


class Streamer(oandapy.Streamer):
    """Enhanced streamer for OANDA API with custom header support.

    This class extends oandapy.Streamer to support custom headers and
    improved exception handling. It puts received data into a queue
    for asynchronous processing.

    Attributes:
        connected: Boolean indicating if the stream is active.
        q: Queue object for receiving streaming data.
        client: HTTP client for making requests.
    """

    def __init__(self, q, headers=None, *args, **kwargs):
        """Initialize the Streamer with a queue and optional headers.

        Args:
            q: Queue object to put received streaming data into.
            headers: Optional dictionary of HTTP headers to include in requests.
            *args: Additional positional arguments passed to parent class.
            **kwargs: Additional keyword arguments passed to parent class.
        """
        # Override to provide headers, which is in the standard API interface
        super().__init__(*args, **kwargs)

        self.connected = None
        if headers:
            self.client.headers.update(headers)

        self.q = q

    def run(self, endpoint, params=None):
        """Run the streaming connection with enhanced exception handling.

        This method maintains a persistent connection to the OANDA streaming
        endpoint, processing incoming data and putting it into the queue.
        It handles network errors gracefully and supports heartbeat filtering.

        Args:
            endpoint: The streaming endpoint to connect to.
            params: Optional dictionary of query parameters, including:
                - ignore_heartbeat: If True, heartbeat messages are filtered out.
        """
        self.connected = True

        params = params or {}

        ignore_heartbeat = None
        if "ignore_heartbeat" in params:
            ignore_heartbeat = params["ignore_heartbeat"]

        request_args = {"params": params}

        url = f"{self.api_url}/{endpoint}"

        while self.connected:
            # Added exception control here
            try:
                response = self.client.get(url, **request_args)
            except requests.RequestException as e:
                traceback.format_exception(e)
                self.q.put(OandaRequestError().error_response)
                break

            if response.status_code != 200:
                self.on_error(response.content)
                break  # added break here

            # Changed chunk_size 90 -> None
            try:
                for line in response.iter_lines(chunk_size=None):
                    if not self.connected:
                        break

                    if line:
                        data = json.loads(line.decode("utf-8"))
                        if not (ignore_heartbeat and "heartbeat" in data):
                            self.on_success(data)

            except Exception as e:  # socket.error has been seen
                traceback.format_exception(e)
                self.q.put(OandaStreamError().error_response)
                break

    def on_success(self, data):
        """Process successfully received streaming data.

        This method is called for each valid message received from the
        streaming endpoint. It extracts tick or transaction data and
        puts it into the queue for processing.

        Args:
            data: Dictionary containing the streaming data, which may contain
                either a 'tick' key with price data or a 'transaction' key
                with order/trade information.
        """
        if "tick" in data:
            self.q.put(data["tick"])
        elif "transaction" in data:
            self.q.put(data["transaction"])

    def on_error(self, data):
        """Handle streaming errors.

        This method is called when an error occurs during streaming,
        such as a non-200 status code. It disconnects the stream
        and puts the error into the queue for handling.

        Args:
            data: Raw error response content from the failed request.
        """
        self.disconnect()
        self.q.put(OandaStreamError(data).error_response)


class OandaStore(ParameterizedSingletonMixin):
    """Singleton class wrapping to control the connections to Oanda.

    This class now uses ParameterizedSingletonMixin instead of MetaSingleton metaclass
    to implement the singleton pattern. This provides the same functionality without
    metaclasses while maintaining full backward compatibility.

    Params:

      - ``token`` (default:``None``): API access token

      - ``account`` (default: ``None``): account id

      - ``practice`` (default: ``False``): use the test environment

      - ``account_tmout`` (default: ``10.0``): refresh period for account
        value/cash refresh
    """

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    params = (
        ("token", ""),
        ("account", ""),
        ("practice", False),
        ("account_tmout", 10.0),  # account balance refresh timeout
    )

    _DTEPOCH = datetime(1970, 1, 1)
    _ENVPRACTICE = "practice"
    _ENVLIVE = "live"

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self):
        """Initialize the OandaStore with default attributes and API connection.

        Sets up queues for order management, account data, and notifications.
        Also initializes the OANDA API client with the configured environment
        and access token.
        """
        super().__init__()

        self.q_orderclose = None
        self.q_ordercreate = None
        self.q_account = None
        self.cash = None
        self.notifs = collections.deque()  # store notifications for cerebro

        self._env = None  # reference to cerebro for general notifications
        self.broker = None  # broker instance
        self.datas = list()  # datas that have registered over start

        self._orders = collections.OrderedDict()  # map order.ref to oid
        self._ordersrev = collections.OrderedDict()  # map oid to order.ref
        self._transpend = collections.defaultdict(collections.deque)

        self._oenv = self._ENVPRACTICE if self.p.practice else self._ENVLIVE
        self.oapi = API(
            environment=self._oenv,
            access_token=self.p.token,
            headers={"X-Accept-Datetime-Format": "UNIX"},
        )

        self._cash = 0.0
        self._value = 0.0
        self._evt_acct = threading.Event()

    def start(self, data=None, broker=None):
        """Start the store for data or broker operation.

        This method initializes the store for either data feeds or broker
        operations. For data feeds, it registers the data and notifies
        the broker. For broker operations, it starts the event streaming
        and broker management threads.

        Args:
            data: Optional data feed instance to register.
            broker: Optional broker instance to start managing.
        """
        if data is None and broker is None:
            self.cash = None
            return

        if data is not None:
            self._env = data._env
            # For datas simulate a queue with None to kickstart co
            self.datas.append(data)

            if self.broker is not None:
                self.broker.data_started(data)

        elif broker is not None:
            self.broker = broker
            self.streaming_events()
            self.broker_threads()

    def stop(self):
        """Stop the store and signal all threads to terminate.

        Sends None to all broker-related queues to signal threads to
        gracefully shut down.
        """
        # signal end of thread
        if self.broker is not None:
            self.q_ordercreate.put(None)
            self.q_orderclose.put(None)
            self.q_account.put(None)

    def put_notification(self, msg, *args, **kwargs):
        """Add a notification to the store's notification queue.

        Args:
            msg: The notification message.
            *args: Additional positional arguments to store with the notification.
            **kwargs: Additional keyword arguments to store with the notification.
        """
        self.notifs.append((msg, args, kwargs))

    def get_notifications(self):
        """Return the pending "store" notifications"""
        self.notifs.append(None)  # put a mark / threads could still append
        return [x for x in iter(self.notifs.popleft, None)]

    # Oanda supported granularities
    _GRANULARITIES = {
        (TimeFrame.Seconds, 5): "S5",
        (TimeFrame.Seconds, 10): "S10",
        (TimeFrame.Seconds, 15): "S15",
        (TimeFrame.Seconds, 30): "S30",
        (TimeFrame.Minutes, 1): "M1",
        (TimeFrame.Minutes, 2): "M3",
        (TimeFrame.Minutes, 3): "M3",
        (TimeFrame.Minutes, 4): "M4",
        (TimeFrame.Minutes, 5): "M5",
        (TimeFrame.Minutes, 10): "M5",
        (TimeFrame.Minutes, 15): "M5",
        (TimeFrame.Minutes, 30): "M5",
        (TimeFrame.Minutes, 60): "H1",
        (TimeFrame.Minutes, 120): "H2",
        (TimeFrame.Minutes, 180): "H3",
        (TimeFrame.Minutes, 240): "H4",
        (TimeFrame.Minutes, 360): "H6",
        (TimeFrame.Minutes, 480): "H8",
        (TimeFrame.Days, 1): "D",
        (TimeFrame.Weeks, 1): "W",
        (TimeFrame.Months, 1): "M",
    }

    def get_positions(self):
        """Get current open positions from OANDA.

        Returns:
            list or None: List of position dictionaries if successful,
                None if an error occurs. Each dictionary contains
                position details including instrument, units, and side.
        """
        try:
            positions = self.oapi.get_positions(self.p.account)
        except (
            oandapy.OandaError,
            OandaRequestError,
        ):
            return None

        poslist = positions.get("positions", [])
        return poslist

    def get_granularity(self, timeframe, compression):
        """Get the OANDA API granularity string for a timeframe/compression pair.

        Args:
            timeframe: The TimeFrame constant (e.g., TimeFrame.Minutes).
            compression: The compression value (e.g., 5 for 5-minute bars).

        Returns:
            str or None: The OANDA API granularity string (e.g., "M5"), or None
                if the timeframe/combination is not supported.
        """
        return self._GRANULARITIES.get((timeframe, compression), None)

    def get_instrument(self, dataname):
        """Get instrument information from OANDA.

        Args:
            dataname: The instrument name to query (e.g., "EUR_USD").

        Returns:
            dict or None: Dictionary containing instrument details if found,
                None if the instrument doesn't exist or an error occurs.
        """
        try:
            insts = self.oapi.get_instruments(self.p.account, instruments=dataname)
        except (
            oandapy.OandaError,
            OandaRequestError,
        ):
            return None

        i = insts.get("instruments", [{}])
        return i[0] or None

    def streaming_events(self, tmout=None):
        """Start streaming events for the account.

        Creates and starts threads to listen for streaming events from
        the OANDA API, including transaction updates and order status changes.

        Args:
            tmout: Optional timeout in seconds before starting the stream.

        Returns:
            Queue: Queue object that will receive streaming event data.
        """
        q = queue.Queue()
        kwargs = {"q": q, "tmout": tmout}

        t = threading.Thread(target=self._t_streaming_listener, kwargs=kwargs)
        t.daemon = True
        t.start()

        t = threading.Thread(target=self._t_streaming_events, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    def _t_streaming_listener(self, q, tmout=None):
        while True:
            trans = q.get()
            self._transaction(trans)

    def _t_streaming_events(self, q, tmout=None):
        if tmout is not None:
            _time.sleep(tmout)

        streamer = Streamer(
            q,
            environment=self._oenv,
            access_token=self.p.token,
            headers={"X-Accept-Datetime-Format": "UNIX"},
        )

        streamer.events(ignore_heartbeat=False)

    def candles(self, dataname, dtbegin, dtend, timeframe, compression, candleFormat, includeFirst):
        """Get historical candle data for an instrument.

        Creates a thread to fetch historical OHLCV data from OANDA
        for the specified instrument and time range.

        Args:
            dataname: The instrument name to fetch data for.
            dtbegin: Start datetime for the data fetch (can be None).
            dtend: End datetime for the data fetch (can be None).
            timeframe: TimeFrame constant for the bars.
            compression: Compression value for the timeframe.
            candleFormat: Format for candle data (e.g., "bidask", "midpoint").
            includeFirst: Whether to include the first candle.

        Returns:
            Queue: Queue object that will receive candle data dictionaries,
                terminated by an empty dictionary to signal completion.
        """
        kwargs = locals().copy()
        kwargs.pop("self")
        kwargs["q"] = q = queue.Queue()
        t = threading.Thread(target=self._t_candles, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    def _t_candles(
        self, dataname, dtbegin, dtend, timeframe, compression, candleFormat, includeFirst, q
    ):
        granularity = self.get_granularity(timeframe, compression)
        if granularity is None:
            e = OandaTimeFrameError()
            q.put(e.error_response)
            return

        dtkwargs = {}
        if dtbegin is not None:
            dtkwargs["start"] = int((dtbegin - self._DTEPOCH).total_seconds())

        if dtend is not None:
            dtkwargs["end"] = int((dtend - self._DTEPOCH).total_seconds())

        try:
            response = self.oapi.get_history(
                instrument=dataname, granularity=granularity, candleFormat=candleFormat, **dtkwargs
            )

        except oandapy.OandaError as e:
            q.put(e.error_response)
            q.put(None)
            return

        for candle in response.get("candles", []):
            q.put(candle)

        q.put({})  # end of transmission

    def streaming_prices(self, dataname, tmout=None):
        """Start streaming prices for a specific instrument.

        Creates and starts a thread to stream real-time price data
        for the specified instrument from the OANDA API.

        Args:
            dataname: The instrument name to stream prices for.
            tmout: Optional timeout in seconds before starting the stream.

        Returns:
            Queue: Queue object that will receive streaming price data.
        """
        q = queue.Queue()
        kwargs = {"q": q, "dataname": dataname, "tmout": tmout}
        t = threading.Thread(target=self._t_streaming_prices, kwargs=kwargs)
        t.daemon = True
        t.start()
        return q

    def _t_streaming_prices(self, dataname, q, tmout):
        if tmout is not None:
            _time.sleep(tmout)

        streamer = Streamer(
            q,
            environment=self._oenv,
            access_token=self.p.token,
            headers={"X-Accept-Datetime-Format": "UNIX"},
        )

        streamer.rates(self.p.account, instruments=dataname)

    def get_cash(self):
        """Get the current available cash (margin) from the account.

        Returns:
            float: The current available cash/margin for trading.
                This is updated periodically by the account polling thread.
        """
        return self._cash

    def get_value(self):
        """Get the current account value (balance) from the account.

        Returns:
            float: The current account balance.
                This is updated periodically by the account polling thread.
        """
        return self._value

    _ORDEREXECS = {
        Order.Market: "market",
        Order.Limit: "limit",
        Order.Stop: "stop",
        Order.StopLimit: "stop",
    }

    def broker_threads(self):
        """Start and manage all broker-related threads.

        Creates and starts daemon threads for:
        - Account data updates (cash and value refresh)
        - Order creation processing
        - Order cancellation processing

        Also waits for initial account data to be loaded.
        """
        self.q_account = queue.Queue()
        self.q_account.put(True)  # force an immediate update
        t = threading.Thread(target=self._t_account)
        t.daemon = True
        t.start()

        self.q_ordercreate = queue.Queue()
        t = threading.Thread(target=self._t_order_create)
        t.daemon = True
        t.start()

        self.q_orderclose = queue.Queue()
        t = threading.Thread(target=self._t_order_cancel)
        t.daemon = True
        t.start()

        # Wait once for the values to be set
        self._evt_acct.wait(self.p.account_tmout)

    def _t_account(self):
        while True:
            try:
                msg = self.q_account.get(timeout=self.p.account_tmout)
                if msg is None:
                    break  # end of thread
            except queue.Empty:  # tmout -> time to refresh
                pass

            try:
                accinfo = self.oapi.get_account(self.p.account)
            except Exception as e:
                self.put_notification(e)
                continue

            try:
                self._cash = accinfo["marginAvail"]
                self._value = accinfo["balance"]
            except KeyError:
                pass

            self._evt_acct.set()

    def order_create(self, order, stopside=None, takeside=None, **kwargs):
        """Create and submit an order to OANDA.

        Args:
            order: The backtrader Order object to create.
            stopside: Optional stop-loss order side with price information.
            takeside: Optional take-profit order side with price information.
            **kwargs: Additional parameters to pass to the OANDA API.

        Returns:
            Order: The same order object passed in, for chaining.
        """
        okwargs = dict()
        okwargs["instrument"] = order.data._dataname
        okwargs["units"] = abs(order.created.size)
        okwargs["side"] = "buy" if order.isbuy() else "sell"
        okwargs["type"] = self._ORDEREXECS[order.exectype]
        if order.exectype != Order.Market:
            okwargs["price"] = order.created.price
            if order.valid is None:
                # 1 year and datetime.max fail ... 1-month works
                valid = datetime.now(UTC) + timedelta(days=30)
            else:
                valid = order.data.num2date(order.valid)
                # To timestamp with seconds precision
            okwargs["expiry"] = int((valid - self._DTEPOCH).total_seconds())

        if order.exectype == Order.StopLimit:
            okwargs["lowerBound"] = order.created.pricelimit
            okwargs["upperBound"] = order.created.pricelimit

        if order.exectype == Order.StopTrail:
            okwargs["trailingStop"] = order.trailamount

        if stopside is not None:
            okwargs["stopLoss"] = stopside.price

        if takeside is not None:
            okwargs["takeProfit"] = takeside.price

        okwargs.update(**kwargs)  # anything from the user

        self.q_ordercreate.put(
            (
                order.ref,
                okwargs,
            )
        )
        return order

    _OIDSINGLE = ["orderOpened", "tradeOpened", "tradeReduced"]
    _OIDMULTIPLE = ["tradesClosed"]

    def _t_order_create(self):
        while True:
            msg = self.q_ordercreate.get()
            if msg is None:
                break

            oref, okwargs = msg
            try:
                o = self.oapi.create_order(self.p.account, **okwargs)
            except Exception as e:
                self.put_notification(e)
                self.broker._reject(oref)
                return

            # Ids are delivered in different fields, and all must be fetched to
            # match them (as executions) to the order generated here
            oids = list()
            for oidfield in self._OIDSINGLE:
                if oidfield in o and "id" in o[oidfield]:
                    oids.append(o[oidfield]["id"])

            for oidfield in self._OIDMULTIPLE:
                if oidfield in o:
                    for suboidfield in o[oidfield]:
                        oids.append(suboidfield["id"])

            if not oids:
                self.broker._reject(oref)
                return

            self._orders[oref] = oids[0]
            self.broker._submit(oref)
            if okwargs["type"] == "market":
                self.broker._accept(oref)  # taken immediately

            for oid in oids:
                self._ordersrev[oid] = oref  # maps ids to backtrader order

                # A transaction may have happened and was stored
                tpending = self._transpend[oid]
                tpending.append(None)  # eom marker
                while True:
                    trans = tpending.popleft()
                    if trans is None:
                        break
                    self._process_transaction(oid, trans)

    def order_cancel(self, order):
        """Request cancellation of an existing order.

        Args:
            order: The backtrader Order object to cancel.

        Returns:
            Order: The same order object passed in, for chaining.
        """
        self.q_orderclose.put(order.ref)
        return order

    def _t_order_cancel(self):
        while True:
            oref = self.q_orderclose.get()
            if oref is None:
                break

            oid = self._orders.get(oref, None)
            if oid is None:
                continue  # the order is no longer there
            try:
                self.oapi.close_order(self.p.account, oid)
            except Exception as e:
                traceback.format_exception(e)
                continue  # not cancelled - FIXME: notify

            self.broker._cancel(oref)

    _X_ORDER_CREATE = (
        "STOP_ORDER_CREATE",
        "LIMIT_ORDER_CREATE",
        "MARKET_IF_TOUCHED_ORDER_CREATE",
    )

    def _transaction(self, trans):
        # Invoked from Streaming Events. May actually receive an event for an
        # oid which has not yet been returned after creating an order. Hence,
        # store if not yet seen, else forward to processer
        ttype = trans["type"]
        if ttype == "MARKET_ORDER_CREATE":
            try:
                oid = trans["tradeReduced"]["id"]
            except KeyError:
                try:
                    oid = trans["tradeOpened"]["id"]
                except KeyError:
                    return  # cannot do anything else

        elif ttype in self._X_ORDER_CREATE:
            oid = trans["id"]
        elif ttype == "ORDER_FILLED":
            oid = trans["orderId"]

        elif ttype == "ORDER_CANCEL":
            oid = trans["orderId"]

        elif ttype == "TRADE_CLOSE":
            oid = trans["id"]
            pid = trans["tradeId"]
            if pid in self._orders and False:  # Know nothing about trade
                return  # can do nothing

            # Skip above - at the moment do nothing
            # Received directly from an event in the WebGUI, for example, which
            # closes an existing position related to order with id -> pid
            # COULD BE DONE: Generate a fake counter-order to gracefully
            # close the existing position
            msg = (
                "Received TRADE_CLOSE for unknown order, possibly generated"
                " over a different client or GUI"
            )
            self.put_notification(msg, trans)
            return

        else:  # Go always gracefully
            try:
                oid = trans["id"]
            except KeyError:
                oid = "None"

            msg = "Received {} with oid {}. Unknown situation"
            msg = msg.format(ttype, oid)
            self.put_notification(msg, trans)
            return

        try:
            self._ordersrev[oid]
            self._process_transaction(oid, trans)
        except KeyError:  # not yet seen, keep as pending
            self._transpend[oid].append(trans)

    _X_ORDER_FILLED = (
        "MARKET_ORDER_CREATE",
        "ORDER_FILLED",
        "TAKE_PROFIT_FILLED",
        "STOP_LOSS_FILLED",
        "TRAILING_STOP_FILLED",
    )

    def _process_transaction(self, oid, trans):
        try:
            oref = self._ordersrev.pop(oid)
        except KeyError:
            return

        ttype = trans["type"]

        if ttype in self._X_ORDER_FILLED:
            size = trans["units"]
            if trans["side"] == "sell":
                size = -size
            price = trans["price"]
            self.broker._fill(oref, size, price, ttype=ttype)

        elif ttype in self._X_ORDER_CREATE:
            self.broker._accept(oref)
            self._ordersrev[oid] = oref

        elif ttype in "ORDER_CANCEL":
            reason = trans["reason"]
            if reason == "ORDER_FILLED":
                pass  # individual execs have done the job
            elif reason == "TIME_IN_FORCE_EXPIRED":
                self.broker._expire(oref)
            elif reason == "CLIENT_REQUEST":
                self.broker._cancel(oref)
            else:  # default action ... if nothing else
                self.broker._reject(oref)
