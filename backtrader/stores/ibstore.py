#!/usr/bin/env python
"""Interactive Brokers Store Module - IB API connection.

This module provides the IBStore for connecting to Interactive Brokers
TWS or IB Gateway for trading and data.

Classes:
    IBStore: Singleton store for IB connections.
    IBMessage: IB message handling.

Functions:
    _ts2dt: Converts IB timestamp to datetime.

Example:
    >>> store = bt.stores.IBStore(port=7497, clientId=1)
    >>> cerebro.setbroker(store.getbroker())
"""
import bisect
import collections
import inspect
import itertools
import random
import threading
import time
from copy import copy
from datetime import datetime, timedelta

import ib.opt as ibopt
from ib.ext.Contract import Contract

from ..dataseries import TimeFrame
from ..position import Position
from ..utils import UTC, AutoDict
from ..utils.py3 import bstr, long, queue

# Remove MetaParams import since we'll eliminate metaclass usage
# from backtrader.metabase import MetaParams
from .mixins import ParameterizedSingletonMixin

bytes = bstr  # py2/3 need for ibpy


def _ts2dt(tstamp=None):
    # Transforms a RTVolume timestamp to a datetime object
    # Convert timestamp to datetime object, if no timestamp specified, return current UTC time
    # If timestamp is not None, empty, False, process timestamp and return datetime object
    if not tstamp:
        return datetime.now(UTC)
    # todo backtrader built-in code, 1000 caused error, changed to 1, this makes calculated UTC time 8 hours behind Beijing time
    # If using 1000, the time obtained would be from 1970
    # sec, msec = divmod(long(tstamp), 1000)
    sec, msec = divmod(long(tstamp), 1)
    usec = msec * 1000
    return datetime.fromtimestamp(sec, UTC).replace(microsecond=usec)


class RTVolume:
    """Parses a tickString tickType 48 (RTVolume) event from the IB API into its
    constituent fields
    Supports using a "price" to simulate an RTVolume from a tickPrice event
    """

    _fields = [
        ("price", float),
        ("size", int),
        ("datetime", _ts2dt),
        ("volume", int),
        ("vwap", float),
        ("single", bool),
    ]

    def __init__(self, rtvol="", price=None, tmoffset=None):
        # Use a provided string or simulate a list of empty tokens
        # Split received tick data
        tokens = iter(rtvol.split(";"))

        # Put the tokens as attributes using the corresponding func
        # Convert split tick data and assign values, these two code sections are quite concise
        for name, func in self._fields:
            setattr(self, name, func(next(tokens)) if rtvol else func())

        # If price was provided use it
        # If price is provided separately, use price, will override price received from tick
        if price is not None:
            self.price = price
        # If time offset is not None, add time offset to existing time
        if tmoffset is not None:
            self.datetime += tmoffset


# Decorator to mark methods to register with ib.opt
def ibregister(f):
    f._ibregister = True
    return f


class IBStore(ParameterizedSingletonMixin):
    """Singleton class wrapping an ibpy ibConnection instance.

    This class now uses ParameterizedSingletonMixin instead of MetaSingleton metaclass
    to implement the singleton pattern. This provides the same functionality without
    metaclasses while maintaining full backward compatibility.

    The parameters can also be specified in the classes which use this store,
    like ``IBData`` and ``IBBroker``
    # Parameters can also be specified in classes using this store, such as ``IBData`` and ``IBBroker``
    Params:

      - ``host`` (default:``127.0.0.1``): where IB TWS or IB Gateway are
        actually running. And although this will usually be the localhost, it
        must not be
        # Host address, usually the default host in IB TWS or IB Gateway is localhost, i.e., 127.0.0.1
        # But this address is not necessarily this default value

      - ``port`` (default: ``7496``): port to connect to. The demo system uses
        ``7497``
        # Port number, usually real account is 7496, demo account is 7497
      - ``clientId`` (default: ``None``): which clientId to use to connect to
        TWS.
        ``None``: generates a random id between 1 and 65535
        An ``integer``: will be passed as the value to use.
        # Set a clientid to connect to TWS, needed for multi-account management to know which id sent signal
        # Can get each id's status through masterid, if set to None, will generate random number between 1 and 65535

      - ``notifyall`` (default: ``False``)

        If ``False`` only ``error`` messages will be sent to the
        ``notify_store`` methods of ``Cerebro`` and ``Strategy``.
        If ``True``, each and every message received from TWS will be notified
        # When this parameter is set to False, only error message types will be passed to notify_store
        # If this parameter is set to True, all messages will be passed to notify_store

      - ``_debug`` (default: ``False``)
        Print all messages received from TWS to standard output
        # Print all messages received from TWS to standard output. Default is not to do this, when set to True, will print all messages
      - ``reconnect`` (default: ``3``)
        Number of attempts to try to reconnect after the 1st connection attempt
        fails
        Set it to a ``-1`` value to keep on reconnecting forever
        # Number of reconnection attempts after first connection attempt fails; default is 3 times, if set to -1, will keep trying to reconnect after connection fails

      - ``timeout`` (default: ``3.0``)

        Time in seconds between reconnection attemps
        # Seconds between each reconnection attempt, default is 3 seconds

      - ``timeoffset`` (default: ``True``)

        If True, the time obtained from ``reqCurrentTime`` (IB Server time)
        will be used to calculate the offset to localtime and this offset will
        be used for the price notifications (tickPrice events, for example for
        CASH markets) to modify the locally calculated timestamp.

        The time offset will propagate to other parts of the ``backtrader``
        ecosystem like the **resampling** to align resampling timestamps using
        the calculated offset.

        # If set to True, use time requested from IB server via reqCurrentTime method to calculate time difference with local time,
        # use this time difference to correct local timestamp when doing price notifications, and this time difference will be
        # propagated to backtrader ecosystem, such as resample function

      - ``timerefresh`` (default: ``60.0``)

        Time in seconds: how often the time offset has to be refreshed

        # How often to calculate the time difference between IB server and local time. Default is every 60 seconds

      - ``indcash`` (default: ``True``)

        Manage IND codes as if they were cash for price retrieval
        # For price retrieval of cash, used to manage IND codes
        # todo Haven't fully understood the meaning of this parameter
    """

    # Set a base for the data requests (historical/realtime) to distinguish the
    # id in the error notifications from orders, where the basis (usually
    # starting at 1) is set by TWS

    REQIDBASE = 0x01000000

    BrokerCls = None  # broker class will autoregister
    DataCls = None  # data class will auto register

    # todo Moved class attributes added after code init to before init

    # The _durations are meant to calculate the necessary historical data to
    # perform backfilling at the start of a connetion or a connection is lost.
    # Using a timedelta as a key allows quickly finding out which
    # bar size (values in the tuples int the dict) can be used.
    # This attribute is mainly used to quickly calculate how many bars need to be filled when backfilling historical data

    _durations = dict(
        [
            # 60 seconds - 1 min
            ("60 S", ("1 secs", "5 secs", "10 secs", "15 secs", "30 secs", "1 min")),
            # 120 seconds - 2 mins
            ("120 S", ("1 secs", "5 secs", "10 secs", "15 secs", "30 secs", "1 min", "2 mins")),
            # 180 seconds - 3 mins
            (
                "180 S",
                ("1 secs", "5 secs", "10 secs", "15 secs", "30 secs", "1 min", "2 mins", "3 mins"),
            ),
            # 300 seconds - 5 mins
            (
                "300 S",
                (
                    "1 secs",
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                ),
            ),
            # 600 seconds - 10 mins
            (
                "600 S",
                (
                    "1 secs",
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                ),
            ),
            # 900 seconds - 15 mins
            (
                "900 S",
                (
                    "1 secs",
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                ),
            ),
            # 1200 seconds - 20 mins
            (
                "1200 S",
                (
                    "1 secs",
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                ),
            ),
            # 1800 seconds - 30 mins
            (
                "1800 S",
                (
                    "1 secs",
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                ),
            ),
            # 3600 seconds - 1 hour
            (
                "3600 S",
                (
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                ),
            ),
            # 7200 seconds - 2 hours
            (
                "7200 S",
                (
                    "5 secs",
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                ),
            ),
            # 10,800 seconds - 3 hours
            (
                "10800 S",
                (
                    "10 secs",
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                ),
            ),
            # 14,400 seconds - 4 hours
            (
                "14400 S",
                (
                    "15 secs",
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                ),
            ),
            # 28,800 seconds - 8 hours
            (
                "28800 S",
                (
                    "30 secs",
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                    "8 hours",
                ),
            ),
            # 1 day
            (
                "1 D",
                (
                    "1 min",
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                    "8 hours",
                    "1 day",
                ),
            ),
            # 2 days
            (
                "2 D",
                (
                    "2 mins",
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                    "8 hours",
                    "1 day",
                ),
            ),
            # 1 week
            (
                "1 W",
                (
                    "3 mins",
                    "5 mins",
                    "10 mins",
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                    "8 hours",
                    "1 day",
                    "1 W",
                ),
            ),
            # 2 weeks
            (
                "2 W",
                (
                    "15 mins",
                    "20 mins",
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                    "8 hours",
                    "1 day",
                    "1 W",
                ),
            ),
            # 1 month
            (
                "1 M",
                (
                    "30 mins",
                    "1 hour",
                    "2 hours",
                    "3 hours",
                    "4 hours",
                    "8 hours",
                    "1 day",
                    "1 W",
                    "1 M",
                ),
            ),
            # 2+ months
            ("2 M", ("1 day", "1 W", "1 M")),
            ("3 M", ("1 day", "1 W", "1 M")),
            ("4 M", ("1 day", "1 W", "1 M")),
            ("5 M", ("1 day", "1 W", "1 M")),
            ("6 M", ("1 day", "1 W", "1 M")),
            ("7 M", ("1 day", "1 W", "1 M")),
            ("8 M", ("1 day", "1 W", "1 M")),
            ("9 M", ("1 day", "1 W", "1 M")),
            ("10 M", ("1 day", "1 W", "1 M")),
            ("11 M", ("1 day", "1 W", "1 M")),
            # 1+ years
            ("1 Y", ("1 day", "1 W", "1 M")),
        ]
    )

    # Sizes allow for quick translation from bar sizes above to actual
    # timeframes to make a comparison with the actual data
    _sizes = {
        "secs": (TimeFrame.Seconds, 1),
        "min": (TimeFrame.Minutes, 1),
        "mins": (TimeFrame.Minutes, 1),
        "hour": (TimeFrame.Minutes, 60),
        "hours": (TimeFrame.Minutes, 60),
        "day": (TimeFrame.Days, 1),
        "W": (TimeFrame.Weeks, 1),
        "M": (TimeFrame.Months, 1),
    }

    _dur2tf = {
        "S": TimeFrame.Seconds,
        "D": TimeFrame.Days,
        "W": TimeFrame.Weeks,
        "M": TimeFrame.Months,
        "Y": TimeFrame.Years,
    }

    params = (
        ("host", "127.0.0.1"),
        ("port", 7496),
        ("clientId", None),  # None generates a random clientid 1 -> 2^16
        ("notifyall", False),
        ("_debug", False),
        ("reconnect", 3),  # -1 forever, 0 No, > 0 number of retries
        ("timeout", 3.0),  # timeout between reconnections
        ("timeoffset", True),  # Use offset to server for timestamps if needed
        ("timerefresh", 60.0),  # How often to refresh the timeoffset
        ("indcash", True),  # Treat IND codes as CASH elements
    )

    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns ``DataCls`` with args, kwargs"""
        # Class method, get data
        return cls.DataCls(*args, **kwargs)

    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered ``BrokerCls``"""
        # Class method, get broker
        return cls.BrokerCls(*args, **kwargs)

    def __init__(self):
        # Initialize IBStore
        super().__init__()
        # Create 4 threads and add locks
        self._lock_q = threading.Lock()  # sync access to _tickerId/Queues
        self._lock_accupd = threading.Lock()  # sync account updates
        self._lock_pos = threading.Lock()  # sync position updates
        self._lock_notif = threading.Lock()  # sync access to notif queue

        # Account list received
        # Create two event management flags for account
        self._event_managed_accounts = threading.Event()
        self._event_accdownload = threading.Event()
        # Not reconnecting, default is False
        self.dontreconnect = False  # for non-recoverable connect errors
        # cerebro pointer, used to generate notifications
        self._env = None  # reference to cerebro for general notifications
        # broker instance, default is None
        self.broker = None  # broker instance
        # data, default is an empty list
        self.datas = list()  # datas that have registered over start
        # Request start from data or cerebro
        self.ccount = 0  # requests to start (from cerebro or datas)
        # Create a thread and lock, used for time difference or time compensation
        self._lock_tmoffset = threading.Lock()
        # Time difference or time compensation, default is a time difference value
        self.tmoffset = timedelta()  # to control time difference with server

        # Structures to hold datas requests
        # Data structure to save data requests
        self.qs = collections.OrderedDict()  # key: tickerId -> queues
        self.ts = collections.OrderedDict()  # key: queue -> tickerId
        self.iscash = dict()  # tickerIds from cash products (for ex: EUR.JPY)
        self.histexreq = dict()  # holds segmented historical requests
        self.histfmt = dict()  # holds datetimeformat for request
        self.histsend = dict()  # holds sessionend (data time) for request
        self.histtz = dict()  # holds sessionend (data time) for request

        # Data structure to save account information
        self.acc_cash = AutoDict()  # current total cash per account
        self.acc_value = AutoDict()  # current total value per account
        self.acc_upds = AutoDict()  # current account valueinfos per account

        self.port_update = False  # indicate whether to signal to broker

        self.positions = collections.defaultdict(Position)  # actual positions
        # todo Haven't understood why count can use self.REQIDBASE as parameter, using it directly causes error
        self._tickerId = itertools.count(self.REQIDBASE)  # unique tickerIds
        self.orderid = None  # next possible orderid (will be itertools.count)
        # Save cdetails request information
        self.cdetails = collections.defaultdict(list)  # hold cdetails requests
        # Manage accounts
        self.managed_accounts = list()  # received via managedAccounts
        # Notification information, saved using a queue
        self.notifs = queue.Queue()  # store notifications for cerebro

        # Use the provided clientId or a random one
        # Generate clientId
        if self.p.clientId is None:
            self.clientId = random.randint(1, pow(2, 16) - 1)
        else:
            self.clientId = self.p.clientId

        # ibpy connection object
        # Use ibpy to connect to IB
        self.conn = ibopt.ibConnection(host=self.p.host, port=self.p.port, clientId=self.clientId)

        # register a printall method if requested
        # If in debug mode or notify all information mode, register self.watcher to the connection
        if self.p._debug or self.p.notifyall:
            self.conn.registerAll(self.watcher)

        # Register decorated methods with conn
        # Get all methods on the connection
        methods = inspect.getmembers(self, inspect.ismethod)
        for name, method in methods:
            # If this method is not registerable, ignore
            if not getattr(method, "_ibregister", False):
                continue
            # If this method is registerable
            message = getattr(ibopt.message, name)
            # Then register this method
            self.conn.register(method, message)

        # These two functions are mainly used to quickly calculate how many bars are needed when backfilling data

        # This utility key function transforms a barsize into a:
        #   (Timeframe, Compression) tuple which can be sorted
        # Split bar size, for example "3 mins", returns result (TimeFrame.Minutes, 3)
        def keyfn(x):
            n, t = x.split()
            tf, comp = self._sizes[t]
            return (tf, int(n) * comp)

        # This utility key function transforms a duration into a:
        #   (Timeframe, Compression) tuple which can be sorted
        # Split and convert time interval, for example 1 D, returns result (TimeFrame.Days, 1)
        def key2fn(x):
            n, d = x.split()
            tf = self._dur2tf[d]
            return (tf, int(n))

        # Generate a table of reverse durations
        self.revdur = collections.defaultdict(list)
        # The table (dict) is a ONE-to-MANY relation of
        #   duration -> barsizes
        # Here it is reversed to get a ONE-to-MANY relation of
        #   barsize -> durations
        for duration, barsizes in self._durations.items():
            for barsize in barsizes:
                self.revdur[keyfn(barsize)].append(duration)

        # Once managed, sort the durations according to real duration and not
        # to the text form using the utility key above
        for barsize in self.revdur:
            self.revdur[barsize].sort(key=key2fn)

    # Start
    def start(self, data=None, broker=None):
        self.reconnect(fromstart=True)  # reconnect should be an invariant

        # Datas require some processing to kickstart data reception
        if data is not None:
            self._env = data._env
            # For datas simulate a queue with None to kickstart co
            self.datas.append(data)

            # if the connection fails, get a fake registration that will force the
            # datas to try to reconnect or else bail out
            return self.getTickerQueue(start=True)

        elif broker is not None:
            self.broker = broker

    # Stop
    def stop(self):
        try:
            self.conn.disconnect()  # disconnect should be an invariant
        except AttributeError:
            pass  # conn may have never been connected and lack "disconnect".

        # Unblock any calls set on these events
        self._event_managed_accounts.set()
        self._event_accdownload.set()

    # Print information to standard output
    def logmsg(self, *args):
        # for logging purposes
        if self.p._debug:
            print(*args)

    # After registration, if in debug mode, will print all messages,
    # if in notify all information mode, will pass all messages to notification
    def watcher(self, msg):
        # will be registered to see all messages if debug is requested
        self.logmsg(str(msg))
        if self.p.notifyall:
            self.notifs.put((msg, tuple(msg.values()), dict(msg.items())))

    # Used to determine if already connected to TWS or IB
    def connected(self):
        # The isConnected method is available through __getattr__ indirections
        # and may not be present, which indicates that no connection has been
        # made because the subattribute sender has not yet been created, hence
        # the check for the AttributeError exception
        try:
            return self.conn.isConnected()
        except AttributeError:
            pass

        return False  # non-connected (including non-initialized)

    # Reconnection method, this method must be an invariant, convenient to call many times
    def reconnect(self, fromstart=False, resub=False):
        # This method must be an invariant in which it can be called several
        # times from the same source and must be consistent.
        # An example would
        # be five data that are being received simultaneously, and all request a
        # reconnecting

        # Policy:
        #  - if dontreconnect has been set, no option to connect is possible
        #  - check connection and use the absence of isConnected as signal of
        #    first ever connection (add 1 to retries too)
        #  - Calculate the retries (forever or not)
        #  - Try to connect
        #  - If achieved and fromstart is false, the datas will be
        #    re-kickstarted to recreate the subscription

        # Set first connection to False, if currently connected and resub is True,
        # will call self.startdatas() and return True
        # If cannot get connection status, directly set firstconnect to True
        firstconnect = False
        try:
            if self.conn.isConnected():
                if resub:
                    self.startdatas()
                return True  # nothing to do
        except AttributeError:
            # Not connected, several __getattr__ indirections to
            # self.conn.sender.client.isConnected
            firstconnect = True
        # If not allowing reconnection, when reconnect is called, directly return False
        if self.dontreconnect:
            return False

        # This is only invoked from the main thread by datas, and therefore no
        # lock is needed to control synchronicity to it
        # Get number of retry attempts, if attempts >= 0, add 1 to attempts (True=1)
        retries = self.p.reconnect
        if retries >= 0:
            retries += firstconnect
        # If attempts < 0 or attempts > 0, will stay in while loop until attempts equals 0
        while retries < 0 or retries:
            # If not first connection attempt, rest timeout seconds then retry connection
            if not firstconnect:
                time.sleep(self.p.timeout)
            # Set firstconnect to False, for continuing to rest on next connection
            firstconnect = False
            # If connection successful, if fromstart is False or resub is True,
            # will call self.startdatas(), then return True
            if self.conn.connect():
                if not fromstart or resub:
                    self.startdatas()
                return True  # connection successful
            # If retries > 0, subtract 1 until equal to 0 to exit loop, or return
            if retries > 0:
                retries -= 1
        # If reconnection fails in the end, set dontreconnect to True and return False, indicating reconnection was not successful
        self.dontreconnect = True
        return False  # connection/reconnection failed

    # Request subscription data
    def startdatas(self):
        # kickstrat datas, not returning until all of them have been done
        ts = list()
        for data in self.datas:
            t = threading.Thread(target=data.reqdata)
            t.start()
            ts.append(t)

        for t in ts:
            t.join()

    # Stop subscription data, and pop data in LIFO order
    def stopdatas(self):
        # stop subs and force datas out of the loop (in LIFO order)
        qs = list(self.qs.values())
        ts = list()
        for data in self.datas:
            t = threading.Thread(target=data.canceldata)
            t.start()
            ts.append(t)

        for t in ts:
            t.join()

        for q in reversed(qs):  # datamaster the last one to get a None
            q.put(None)

    # Get notification information in queue
    def get_notifications(self):
        """Return the pending "store" notifications"""
        # The background thread could keep on adding notifications. The None
        # mark allows to identify which is the last notification to deliver
        self.notifs.put(None)  # put a mark
        notifs = list()
        while True:
            notif = self.notifs.get()
            if notif is None:  # mark is reached
                break
            notifs.append(notif)

        return notifs

    # Register related error information
    @ibregister
    def error(self, msg):
        # 100-199 Order/Data/Historical related
        # 200-203 tickerId and Order Related
        # 300-399 A mix of things: orders, connectivity, tickers, misc errors
        # 400-449 Seem order related again
        # 500-531 Connectivity/Communication Errors
        # 10000-100027 Mix of special orders/routing
        # 1100-1102 TWS connectivy to the outside
        # 1300- Socket dropped in client-TWS communication
        # 2100-2110 Informative about Data Farm status (id=-1)

        # All errors are logged to the environment (cerebro), because many
        # errors in Interactive Brokers are actually informational and many may
        # actually be of interest to the user
        # This place seems to complement the original function, causing all messages to be put in self.notifs
        # regardless of notifyall parameter
        # todo Come back to confirm whether there is an error here
        if not self.p.notifyall:
            self.notifs.put((msg, tuple(msg.values()), dict(msg.items())))

        # Manage those events which have to do with connection
        if msg.errorCode is None:
            # Usually received as an error in connection of just before disconn
            pass
        elif msg.errorCode in [200, 203, 162, 320, 321, 322]:
            # cdetails 200 security isn't found, notify over right queue
            # cdetails 203 security not allowed for acct
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                self.cancelQueue(q, True)

        elif msg.errorCode in [354, 420]:
            # 354 no subscription, 420 no real-time bar for contract
            # the calling data to let the data know ... it cannot resub
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                q.put(-msg.errorCode)
                self.cancelQueue(q)

        elif msg.errorCode == 10225:
            # 10225-Bust event occurred, current subscription is deactivated.
            # Please resubscribe real-time bars immediately.
            try:
                q = self.qs[msg.id]
            except KeyError:
                pass  # should not happend but it can
            else:
                q.put(-msg.errorCode)

        elif msg.errorCode == 326:  # not recoverable, clientId in use
            self.dontreconnect = True
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 502:
            # Cannot connect to TWS: port, config not open, tws off (504 then)
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 504:  # Not Connected for data op
            # Once for each data
            pass  # don't need to manage it

        elif msg.errorCode == 1300:
            # TWS has been closed. The port for a new connection is there
            # newport = int(msg.errorMsg.split('-')[-1])  # bla bla bla -7496
            self.conn.disconnect()
            self.stopdatas()

        elif msg.errorCode == 1100:
            # Connection lost - Notify ... datas will wait on the queue
            # with no messages arriving
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode == 1101:
            # Connection restored and tickerIds are gone
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode == 1102:
            # Connection restored and tickerIds maintained
            for q in self.ts:  # key: queue -> ticker
                q.put(-msg.errorCode)

        elif msg.errorCode < 500:
            # Given the myriad of errorCodes, start by assuming is an order
            # error and if not, the checks there will let it go
            if msg.id < self.REQIDBASE:
                if self.broker is not None:
                    self.broker.push_ordererror(msg)
            else:
                # Cancel the queue if a "data" reqId error is given: sanity
                q = self.qs[msg.id]
                self.cancelQueue(q, True)

    # Close connection
    @ibregister
    def connectionClosed(self, msg):
        # Sometimes this comes without 1300/502 or any other and will not be
        # seen in error, hence the need to manage the situation independently
        self.conn.disconnect()
        self.stopdatas()

    # Manage accounts
    @ibregister
    def managedAccounts(self, msg):
        # 1st message in the stream
        self.managed_accounts = msg.accountsList.split(",")
        self._event_managed_accounts.set()

        # Request time to avoid synchronization issues
        self.reqCurrentTime()

    # Request current time
    def reqCurrentTime(self):
        self.conn.reqCurrentTime()

    # Current time considering time difference
    @ibregister
    def currentTime(self, msg):
        if not self.p.timeoffset:  # only if requested ... apply timeoffset
            return
        curtime = datetime.fromtimestamp(float(msg.time))
        with self._lock_tmoffset:
            self.tmoffset = curtime - datetime.now()

        threading.Timer(self.p.timerefresh, self.reqCurrentTime).start()

    # Get current time difference or time compensation
    def timeoffset(self):
        with self._lock_tmoffset:
            return self.tmoffset

    # Next ticker id
    def nextTickerId(self):
        # Get the next ticker using next on the itertools.count
        return next(self._tickerId)

    # Next valid order id
    @ibregister
    def nextValidId(self, msg):
        # Create a counter from the TWS notified value to apply to orders
        self.orderid = itertools.count(msg.orderId)

    # Next order id
    def nextOrderId(self):
        # Get the next ticker using next on the itertools.count made with the
        # notified value from TWS
        return next(self.orderid)

    # Reuse queue
    def reuseQueue(self, tickerId):
        """Reuses queue for tickerId, returning the new tickerId and q"""
        with self._lock_q:
            # Invalidate tickerId in qs (where it is a key)
            q = self.qs.pop(tickerId, None)  # invalidate old
            iscash = self.iscash.pop(tickerId, None)

            # Update ts: q -> ticker
            tickerId = self.nextTickerId()  # get new tickerId
            self.ts[q] = tickerId  # Update ts: q -> tickerId
            self.qs[tickerId] = q  # Update qs: tickerId -> q
            self.iscash[tickerId] = iscash

        return tickerId, q

    # Get ticker queue
    def getTickerQueue(self, start=False):
        """Creates ticker/Queue for data delivery to a data feed"""
        q = queue.Queue()
        if start:
            q.put(None)
            return q

        with self._lock_q:
            tickerId = self.nextTickerId()
            self.qs[tickerId] = q  # can be managed from another thread
            self.ts[q] = tickerId
            self.iscash[tickerId] = False

        return tickerId, q

    # Cancel queue
    def cancelQueue(self, q, sendnone=False):
        """Cancels a Queue for data delivery"""
        # pop ts (tickers) and with the result qs (queues)
        tickerId = self.ts.pop(q, None)
        self.qs.pop(tickerId, None)

        self.iscash.pop(tickerId, None)

        if sendnone:
            q.put(None)

    # Check if queue is valid, return True if queue is in self.ts
    def validQueue(self, q):
        """Returns (bool) if a queue is still valid"""
        return q in self.ts  # queue -> ticker

    # Get detailed contract information
    def getContractDetails(self, contract, maxcount=None):
        cds = list()
        q = self.reqContractDetails(contract)
        while True:
            msg = q.get()
            if msg is None:
                break
            cds.append(msg)

        if not cds or (maxcount and len(cds) > maxcount):
            err = "Ambiguous contract: none/multiple answers received"
            self.notifs.put((err, cds, {}))
            return None

        return cds

    # Request contract information
    def reqContractDetails(self, contract):
        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()
        self.conn.reqContractDetails(tickerId, contract)
        return q

    # End of getting contract information
    @ibregister
    def contractDetailsEnd(self, msg):
        """Signal end of contractdetails"""
        self.cancelQueue(self.qs[msg.reqId], True)

    # Detailed contract information received from TWS
    @ibregister
    def contractDetails(self, msg):
        """Receive an answer and pass it to the queue"""
        self.qs[msg.reqId].put(msg)

    # Get historical data, method parameters differ from IB's request historical data method
    def reqHistoricalDataEx(
        self,
        contract,
        enddate,
        begindate,
        timeframe,
        compression,
        what=None,
        useRTH=False,
        tz="",
        sessionend=None,
        tickerId=None,
    ):
        """
        Extension of the raw reqHistoricalData proxy, which takes two dates
        rather than a duration, barsize and date

        It uses the IB published valid duration/barsizes to make a mapping and
        spread a historical request over several historical requests if needed
        """
        # Keep a copy for error reporting purposes
        # Get local variables, if contains self, remove it
        kwargs = locals().copy()
        kwargs.pop("self", None)  # remove self, no need to report it

        # If timeframe is less than seconds, not supported by this function, directly request tick data
        if timeframe < TimeFrame.Seconds:
            # Ticks are not supported
            return self.getTickerQueue(start=True)

        # If enddate is None, use current time as end time
        if enddate is None:
            enddate = datetime.now()
        # If begindate is None, request maximum available time length,
        # If this time length is None, consider no time length for this period, then call function to get tick data
        # If this time length is not None, calculate barsize
        # If calculated barsize is None, consider no barsize for this period, then call function to get tick data
        # If both are not None, call data request function to get specific historical data
        if begindate is None:
            duration = self.getmaxduration(timeframe, compression)
            if duration is None:
                err = "No duration for historical data request for timeframe/compresison"
                self.notifs.put((err, (), kwargs))
                return self.getTickerQueue(start=True)

            barsize = self.tfcomp_to_size(timeframe, compression)
            if barsize is None:
                err = "No supported barsize for historical data request for timeframe/compresison"
                self.notifs.put((err, (), kwargs))
                return self.getTickerQueue(start=True)

            return self.reqHistoricalData(
                contract=contract,
                enddate=enddate,
                duration=duration,
                barsize=barsize,
                what=what,
                useRTH=useRTH,
                tz=tz,
                sessionend=sessionend,
            )
        # Check if IB supports the requested timeframe/compression
        # Get available data length based on trading period, if time length is None, directly call tick data
        durations = self.getdurations(timeframe, compression)
        if not durations:  # return a queue and put a None in it
            return self.getTickerQueue(start=True)

        # Get or reuse a queue
        # If time period is not None,
        # If tickerId is None, directly call function to get tickerId and q
        # If tickerId is not None, call different function to get tickerId and q
        if tickerId is None:
            tickerId, q = self.getTickerQueue()
        else:
            tickerId, q = self.reuseQueue(tickerId)  # reuse q for old tickerId

        # Get the best possible duration to reduce the number of requests
        duration = None
        for dur in durations:
            intdate = self.dt_plus_duration(begindate, dur)
            if intdate >= enddate:
                intdate = enddate
                duration = dur  # begin -> end fits in single request
                break

        if duration is None:  # no duration large enough to fit the request
            duration = durations[-1]

            # Store the calculated data
            self.histexreq[tickerId] = dict(
                contract=contract,
                enddate=enddate,
                begindate=intdate,
                timeframe=timeframe,
                compression=compression,
                what=what,
                useRTH=useRTH,
                tz=tz,
                sessionend=sessionend,
            )

        barsize = self.tfcomp_to_size(timeframe, compression)
        self.histfmt[tickerId] = timeframe >= TimeFrame.Days
        self.histsend[tickerId] = sessionend
        self.histtz[tickerId] = tz

        if contract.m_secType in ["CASH", "CFD"]:
            self.iscash[tickerId] = 1  # msg.field code
            if not what:
                what = "BID"  # default for cash unless otherwise specified

        elif contract.m_secType in ["IND"] and self.p.indcash:
            self.iscash[tickerId] = 4  # msg.field code

        what = what or "TRADES"

        self.conn.reqHistoricalData(
            tickerId,
            contract,
            bytes(intdate.strftime("%Y%m%d %H:%M:%S") + " GMT"),
            bytes(duration),
            bytes(barsize),
            bytes(what),
            int(useRTH),
            2,
        )  # dateformat 1 for string, 2 for unix time in seconds

        return q

    # Request historical data from IB
    def reqHistoricalData(
        self, contract, enddate, duration, barsize, what=None, useRTH=False, tz="", sessionend=None
    ):
        """Proxy to reqHistorical Data"""

        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()

        if contract.m_secType in ["CASH", "CFD"]:
            self.iscash[tickerId] = True
            if not what:
                what = "BID"  # TRADES doesn't work
            elif what == "ASK":
                self.iscash[tickerId] = 2
        else:
            what = what or "TRADES"

        # split barsize "x time", look in sizes for (tf, comp) get tf
        tframe = self._sizes[barsize.split()[1]][0]
        self.histfmt[tickerId] = tframe >= TimeFrame.Days
        self.histsend[tickerId] = sessionend
        self.histtz[tickerId] = tz

        self.conn.reqHistoricalData(
            tickerId,
            contract,
            bytes(enddate.strftime("%Y%m%d %H:%M:%S") + " GMT"),
            bytes(duration),
            bytes(barsize),
            bytes(what),
            int(useRTH),
            2,
        )

        return q

    # Cancel data request
    def cancelHistoricalData(self, q):
        """Cancels an existing HistoricalData request

        Params:
          - q: the Queue returned by reqMktData
        """
        with self._lock_q:
            self.conn.cancelHistoricalData(self.ts[q])
            self.cancelQueue(q, True)

    # Request real-time bar data, default request is 5 seconds historical data
    def reqRealTimeBars(self, contract, useRTH=False, duration=5):
        """Creates a request for (5 seconds) Real Time Bars

        Params:
          - contract: a ib.ext.Contract.Contract intance
          - useRTH: (default: False) passed to TWS
          - duration: (default: 5) passed to TWS, no other value works in 2016)

        Returns:
          - a Queue the client can wait on to receive a RTVolume instance
        """
        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()

        # 20150929 - Only 5 secs supported for duration
        self.conn.reqRealTimeBars(tickerId, contract, duration, bytes("TRADES"), int(useRTH))

        return q

    # Cancel request for historical data
    def cancelRealTimeBars(self, q):
        """Cancels an existing MarketData subscription

        Params:
          - q: the Queue returned by reqMktData
        """
        with self._lock_q:
            tickerId = self.ts.get(q, None)
            if tickerId is not None:
                self.conn.cancelRealTimeBars(tickerId)

            self.cancelQueue(q, True)

    # Request market data
    def reqMktData(self, contract, what=None):
        """Creates a MarketData subscription

        Params:
          - contract: a ib.ext.Contract.Contract intance

        Returns:
          - a Queue the client can wait on to receive a RTVolume instance
        """
        # get a ticker/queue for identification/data delivery
        tickerId, q = self.getTickerQueue()
        ticks = "233"  # request RTVOLUME tick delivered over tickString

        if contract.m_secType in ["CASH", "CFD"]:
            self.iscash[tickerId] = True
            ticks = ""  # cash markets do not get RTVOLUME
            if what == "ASK":
                self.iscash[tickerId] = 2

        # q.put(None)  # to kickstart backfilling
        # Can request 233 also for cash ... nothing will arrive
        self.conn.reqMktData(tickerId, contract, bytes(ticks), False)
        return q

    # Cancel request for market data
    def cancelMktData(self, q):
        """Cancels an existing MarketData subscription

        Params:
          - q: the Queue returned by reqMktData
        """
        with self._lock_q:
            tickerId = self.ts.get(q, None)
            if tickerId is not None:
                self.conn.cancelMktData(tickerId)

            self.cancelQueue(q, True)

    # Functions related to processing tick data
    @ibregister
    def tickString(self, msg):
        # Receive and process a tickString message
        # If try executes normally, else will also execute; if try doesn't execute normally, else won't execute
        if msg.tickType == 48:  # RTVolume
            try:
                rtvol = RTVolume(msg.value)
            except ValueError:  # price doesn't in message ...
                pass
            else:
                # Don't need to adjust the time, because it is in "timestamp"
                # form in the message
                self.qs[msg.tickerId].put(rtvol)

    # Process tick data for cash market
    @ibregister
    def tickPrice(self, msg):
        """Cash Markets have no notion of "last_price"/"last_size" and the
        tracking of the price is done (industry de-facto standard at least with
        the IB API) following the BID price

        A RTVolume which will only contain a price is put into the client's
        queue to have a consistent cross-market interface
        """
        # Used for "CASH" markets,
        # The price field has been seen to be missing in some instances even if
        # "field" is 1
        tickerId = msg.tickerId
        fieldcode = self.iscash[tickerId]
        if fieldcode:
            if msg.field == fieldcode:  # Expected cash field code
                try:
                    if msg.price == -1.0:
                        # seems to indicate the stream is halted, for example, in
                        # between 23:00 - 23:15 CET for FOREX
                        return
                except AttributeError:
                    pass

                try:
                    rtvol = RTVolume(price=msg.price, tmoffset=self.tmoffset)
                    # print('rtvol with datetime:', rtvol.datetime)
                except ValueError:  # price doesn't in message ...
                    pass
                else:
                    self.qs[tickerId].put(rtvol)

    # Get real-time bar information
    @ibregister
    def realtimeBar(self, msg):
        """Receives x seconds Real Time Bars (at the time of writing only 5
        seconds are supported)

        Not valid for cash markets
        """
        # Get a naive localtime object
        msg.time = datetime.fromtimestamp(float(msg.time), UTC)
        self.qs[msg.reqId].put(msg)

    # Get historical data information
    @ibregister
    def historicalData(self, msg):
        """Receives the events of a historical data request"""
        # For multi-tiered downloads, we'd need to rebind the queue to a new
        # tickerId (in case tickerIds are not reusable) and instead of putting
        # None, issue a new reqHistData with the new data and move formward
        tickerId = msg.reqId
        q = self.qs[tickerId]
        if msg.date.startswith("finished-"):
            self.histfmt.pop(tickerId, None)
            self.histsend.pop(tickerId, None)
            self.histtz.pop(tickerId, None)
            kargs = self.histexreq.pop(tickerId, None)
            if kargs is not None:
                self.reqHistoricalDataEx(tickerId=tickerId, **kargs)
                return

            msg.date = None
            self.cancelQueue(q)
        else:
            dtstr = msg.date  # Format when string req: YYYYMMDD[ HH:MM:SS]
            if self.histfmt[tickerId]:
                sessionend = self.histsend[tickerId]
                dt = datetime.strptime(dtstr, "%Y%m%d")
                dteos = datetime.combine(dt, sessionend)
                tz = self.histtz[tickerId]
                if tz:
                    dteostz = tz.localize(dteos)
                    dteosutc = dteostz.astimezone(UTC).replace(tzinfo=None)
                    # When requesting, for example, daily bars, the current day
                    # will be returned with the already happened data. If the
                    # session end were added, the new ticks wouldn't make it
                    # through because they happen before the end of time
                else:
                    dteosutc = dteos

                if dteosutc <= datetime.now(UTC):
                    dt = dteosutc

                msg.date = dt
            else:
                msg.date = datetime.fromtimestamp(long(dtstr), UTC)

        q.put(msg)

    # Get time length for trading period
    def getdurations(self, timeframe, compression):
        key = (timeframe, compression)
        if key not in self.revdur:
            return []

        return self.revdur[key]

    # Get maximum time length for trading period
    def getmaxduration(self, timeframe, compression):
        key = (timeframe, compression)
        try:
            return self.revdur[key][-1]
        except (KeyError, IndexError):
            pass

        return None

    # Convert timeframe and compression to barsize
    def tfcomp_to_size(self, timeframe, compression):
        if timeframe == TimeFrame.Months:
            return f"{compression} M"

        if timeframe == TimeFrame.Weeks:
            return f"{compression} W"

        if timeframe == TimeFrame.Days:
            if not compression % 7:
                return f"{compression // 7} W"

            return f"{compression} day"

        if timeframe == TimeFrame.Minutes:
            if not compression % 60:
                hours = compression // 60
                return (f"{hours} hour") + ("s" * (hours > 1))

            return (f"{compression} min") + ("s" * (compression > 1))

        if timeframe == TimeFrame.Seconds:
            return f"{compression} secs"

        # Microseconds or ticks
        return None

    #
    def dt_plus_duration(self, dt, duration):
        size, dim = duration.split()
        size = int(size)
        if dim == "S":
            return dt + timedelta(seconds=size)

        if dim == "D":
            return dt + timedelta(days=size)

        if dim == "W":
            return dt + timedelta(days=size * 7)

        if dim == "M":
            month = dt.month - 1 + size  # -1 to make it 0 based, readd below
            years, month = divmod(month, 12)
            return dt.replace(year=dt.year + years, month=month + 1)

        if dim == "Y":
            return dt.replace(year=dt.year + size)

        return dt  # could do nothing with it ... return it intact

    def calcdurations(self, dtbegin, dtend):
        """Calculate a duration in between 2 datetimes"""
        duration = self.histduration(dtbegin, dtend)

        if duration[-1] == "M":
            m = int(duration.split()[0])
            m1 = min(2, m)  # (2, 1) -> 1, (2, 7) -> 2. Bottomline: 1 or 2
            m2 = max(1, m1)  # m1 can only be 1 or 2
            checkdur = f"{m2} M"
        elif duration[-1] == "Y":
            checkdur = "1 Y"
        else:
            checkdur = duration
        # todo There is a bug in the code here, changed to the following
        # sizes = self._durations[checkduration]
        sizes = self._durations[checkdur]
        return duration, sizes

    # Calculate time length and barsize between two times
    def calcduration(self, dtbegin, dtend):
        """Calculate a duration in between 2 datetimes. Returns single size"""
        duration, sizes = self._calcdurations(dtbegin, dtend)
        return duration, sizes[0]

    # Based on IB historical data API limitations, return smallest possible time length between two dates
    def histduration(self, dt1, dt2):
        # Given two dates calculates the smallest possible duration according
        # to the table from the Historical Data API limitations provided by IB
        #
        # Seconds: 'x S' (x: [60, 120, 180, 300, 600, 900, 1200, 1800, 3600,
        #                     7200, 10800, 14400, 28800])
        # Days: 'x D' (x: [1, 2]
        # Weeks: 'x W' (x: [1, 2])
        # Months: 'x M' (x: [1, 11])
        # Years: 'x Y' (x: [1])

        td = dt2 - dt1  # get a timedelta for calculations

        # First: array of secs
        tsecs = td.total_seconds()
        secs = [60, 120, 180, 300, 600, 900, 1200, 1800, 3600, 7200, 10800, 14400, 28800]

        idxsec = bisect.bisect_left(secs, tsecs)
        if idxsec < len(secs):
            return f"{secs[idxsec]} S"

        tdextra = bool(td.seconds or td.microseconds)  # over days/weeks

        # Next: 1 or 2 days
        days = td.days + tdextra
        if td.days <= 2:
            return f"{days} D"

        # Next: 1 or 2 weeks
        weeks, d = divmod(td.days, 7)
        weeks += bool(d or tdextra)
        if weeks <= 2:
            return f"{weeks} W"

        # Get references to dt components
        y2, m2, d2 = dt2.year, dt2.month, dt2.day
        y1, m1, d1 = dt1.year, dt1.month, dt2.day

        H2, M2, S2, US2 = dt2.hour, dt2.minute, dt2.second, dt2.microsecond
        H1, M1, S1, US1 = dt1.hour, dt1.minute, dt1.second, dt1.microsecond

        # Next: 1 -> 11 months (11 incl)
        months = (y2 * 12 + m2) - (y1 * 12 + m1) + ((d2, H2, M2, S2, US2) > (d1, H1, M1, S1, US1))
        if months <= 1:  # months <= 11
            return "1 M"  # return '{} M'.format(months)
        elif months <= 11:
            return "2 M"  # cap at 2 months to keep the table clean

        # Next: years
        # y = y2 - y1 + (m2, d2, H2, M2, S2, US2) > (m1, d1, H1, M1, S1, US1)
        # return '{} Y'.format(y)

        return "1 Y"  # to keep the table clean

    # Create contract as needed
    def makecontract(self, symbol, sectype, exch, curr, expiry="", strike=0.0, right="", mult=1):
        """returns a contract from the parameters without check"""

        contract = Contract()
        contract.m_symbol = bytes(symbol)
        contract.m_secType = bytes(sectype)
        contract.m_exchange = bytes(exch)
        if curr:
            contract.m_currency = bytes(curr)
        if sectype in ["FUT", "OPT", "FOP"]:
            contract.m_expiry = bytes(expiry)
        if sectype in ["OPT", "FOP"]:
            contract.m_strike = strike
            contract.m_right = bytes(right)
        if mult:
            contract.m_multiplier = bytes(mult)
        return contract

    # Cancel order
    def cancelOrder(self, orderid):
        """Proxy to cancelOrder"""
        self.conn.cancelOrder(orderid)

    # Place order
    def placeOrder(self, orderid, contract, order):
        """Proxy to placeOrder"""
        self.conn.placeOrder(orderid, contract, order)

    # Receive openOrder status
    @ibregister
    def openOrder(self, msg):
        """Receive the event ``openOrder`` events"""
        self.broker.push_orderstate(msg)

    # Receive execution details
    @ibregister
    def execDetails(self, msg):
        """Receive execDetails"""
        self.broker.push_execution(msg.execution)

    # Receive orderStatus event
    @ibregister
    def orderStatus(self, msg):
        """Receive the event ``orderStatus``"""
        self.broker.push_orderstatus(msg)

    # Receive commission report event
    @ibregister
    def commissionReport(self, msg):
        """Receive the event commissionReport"""
        self.broker.push_commissionreport(msg.commissionReport)

    # Request current positions
    def reqPositions(self):
        """Proxy to reqPositions"""
        self.conn.reqPositions()

    # Position, not yet implemented
    @ibregister
    def position(self, msg):
        """Receive event positions"""
        pass  # Not implemented yet

    # Request account updates
    def reqAccountUpdates(self, subscribe=True, account=None):
        """Proxy to reqAccountUpdates

        If ``account`` is ``None``, wait for the ``managedAccounts`` message to
        set the account codes
        """
        if account is None:
            self._event_managed_accounts.wait()
            account = self.managed_accounts[0]

        self.conn.reqAccountUpdates(subscribe, bytes(account))

    # Account information update complete
    @ibregister
    def accountDownloadEnd(self, msg):
        # Signals the end of an account update
        # the event indicates it's over. It's only false once, and can be used
        # to find out if it has at least been downloaded once
        self._event_accdownload.set()
        if False:
            if self.port_update:
                self.broker.push_portupdate()

                self.port_update = False

    # Update portfolio
    @ibregister
    def updatePortfolio(self, msg):
        # Lock access to the position dicts. This is called in sub-thread and
        # can kick in at any time
        with self._lock_pos:
            if not self._event_accdownload.is_set():  # 1st event seen
                position = Position(msg.position, msg.averageCost)
                self.positions[msg.contract.m_conId] = position
            else:
                position = self.positions[msg.contract.m_conId]
                if not position.fix(msg.position, msg.averageCost):
                    err = (
                        "The current calculated position and "
                        "the position reported by the broker do not match. "
                        "Operation can continue, but the trades "
                        "calculated in the strategy may be wrong"
                    )

                    self.notifs.put((err, (), {}))

                # Flag signal to broker at the end of account download
                # self.port_update = True
                self.broker.push_portupdate()

    # Get account position
    def getposition(self, contract, clone=False):
        # Lock access to the position dicts.
        # This is called from the main thread,
        # and updates could be happening in the background
        with self._lock_pos:
            position = self.positions[contract.m_conId]
            if clone:
                return copy(position)

            return position

    # Update account value
    @ibregister
    def updateAccountValue(self, msg):
        # Lock access to the dicts where values are updated. This happens in a
        # sub-thread and could kick it at anytime
        with self._lock_accupd:
            try:
                value = float(msg.value)
            except ValueError:
                value = msg.value

            self.acc_upds[msg.accountName][msg.key][msg.currency] = value

            if msg.key == "NetLiquidation":
                # NetLiquidationByCurrency and currency == 'BASE' is the same
                self.acc_value[msg.accountName] = value
            elif msg.key == "TotalCashBalance" and msg.currency == "BASE":
                self.acc_cash[msg.accountName] = value

    # Get all account value information
    def get_acc_values(self, account=None):
        """Returns all account value infos sent by TWS during regular updates
        Waits for at least one successful download

        If ``account`` is `None`, then a dictionary with accounts as keys will
        be returned containing all accounts

        If the account is specified or the system has only one account, the dictionary
        corresponding to that account is returned
        """
        # Wait for at least 1 account update download to have been finished
        # before the account infos can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._updacclock:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return self.acc_upds.copy()

                elif len(self.managed_accounts) > 1:
                    return self.acc_upds.copy()

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_upds[account].copy()
            except KeyError:
                pass

            return self.acc_upds.copy()

    # Get account net liquidation value
    def get_acc_value(self, account=None):
        """Returns the net liquidation value sent by TWS during regular updates
        Waits for at least one successful download

        If ``account`` is `None`, then a dictionary with accounts as keys will
        be returned containing all accounts

        If the account is specified or the system has only one account, the dictionary
        corresponding to that account is returned
        """
        # Wait for at least 1 account update download to have been finished
        # before the value can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._lock_accupd:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return float()

                elif len(self.managed_accounts) > 1:
                    return sum(self.acc_value.values())

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_value[account]
            except KeyError:
                pass

            return float()

    # Get account total cash value
    def get_acc_cash(self, account=None):
        """Returns the total cash value sent by TWS during regular updates
        Waits for at least one successful download

        If ``account`` is `None`, then a dictionary with accounts as keys will
        be returned containing all accounts

        If an account is specified or the system has only one account, the dictionary
        corresponding to that account is returned
        """
        # Wait for at least 1 account update download to have been finished
        # before the cash can be returned to the calling client
        if self.connected():
            self._event_accdownload.wait()
        # Lock access to acc_cash to avoid an event intefering
        with self._lock_accupd:
            if account is None:
                # wait for the managedAccount Messages
                if self.connected():
                    self._event_managed_accounts.wait()

                if not self.managed_accounts:
                    return float()

                elif len(self.managed_accounts) > 1:
                    return sum(self.acc_cash.values())

                # Only 1 account, fall through to return only 1
                account = self.managed_accounts[0]

            try:
                return self.acc_cash[account]
            except KeyError:
                pass
