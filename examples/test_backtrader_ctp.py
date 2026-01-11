"""Test script for backtrader CTP integration.

This module demonstrates backtrader integration with CTP (Commodity Futures
Trading Protocol) for live Chinese futures market trading.
"""

import json
from datetime import datetime, time

import backtrader as bt
from backtrader.brokers.ctpbroker import *
from backtrader.feeds.ctpdata import *
from backtrader.stores.ctpstore import *


# Do not delete Origin definition, ctpbee interface requires it
class Origin:
    """Origin class for CTP order identification.

    This class is required by the ctpbee interface to identify the
    symbol and exchange for order placement.

    Attributes:
        symbol: The futures contract symbol (e.g., 'rb2405').
        exchange: The exchange code (e.g., 'SHFE').
    """

    def __init__(self, data):
        """Initialize Origin with data feed information.

        Args:
            data: Backtrader data feed object.
        """
        self.symbol = data._dataname.split(".")[0]
        self.exchange = data._name.split(".")[1]


# Trading hours: 8:45 AM to 3:00 PM, and 8:45 PM to 2:45 AM for live simulation trading.
# Chinese futures trading hours (day session/night session), live simulation is only available during trading hours.
# Other times only support non-real-time simulation. Weekends do not support simulation.
DAY_START = time(8, 45)  # Day session starts at 8:45
DAY_END = time(15, 0)  # Day session ends at 3:00 PM
NIGHT_START = time(20, 45)  # Night session starts at 8:45 PM
NIGHT_END = time(2, 45)  # Night session ends at 2:45 AM


# Check if currently in trading period
def is_trading_period():
    """Check if current time is within trading hours.

    Returns:
        bool: True if current time is within day or night trading sessions.
    """
    current_time = datetime.now().time()
    trading = False
    if (
        (current_time >= DAY_START and current_time <= DAY_END)
        or (current_time >= NIGHT_START)
        or (current_time <= NIGHT_END)
    ):
        trading = True
    return trading


class SmaCross(bt.Strategy):
    """Simple moving average crossover strategy for CTP futures trading.

    This strategy demonstrates basic data access and order placement
    using the CTP store for live futures trading.

    Attributes:
        beeapi: CTP bee API interface for order management.
        buy_order: Reference to current buy order.
        live_data: Flag indicating if live data is being received.
    """

    lines = ("sma",)
    params = dict(
        smaperiod=5,
        store=None,
    )

    def __init__(self):
        """Initialize the strategy with CTP API reference."""
        self.beeapi = self.p.store.main_ctpbee_api
        self.buy_order = None
        self.live_data = False
        # self.move_average = bt.ind.MovingAverageSimple(self.data, period=self.params.smaperiod)

    def prenext(self):
        """Called before minimum period is reached."""
        print("in prenext")
        for d in self.datas:
            print(
                d._name,
                d.datetime.datetime(0),
                "o h l c ",
                d.open[0],
                d.high[0],
                d.low[0],
                d.close[0],
                " vol ",
                d.volume[0],
            )

    def next(self):
        """Called on each bar with data.

        Prints market data, position, trades, and account information.
        Only executes trading logic when live data is received.
        """
        print("------------------------------------------ next start")

        for d in self.datas:
            print(
                "d._name",
                d._name,
                "d._dataname",
                d._dataname,
                d.datetime.datetime(0),
                "o h l c ",
                d.open[0],
                d.high[0],
                d.low[0],
                d.close[0],
                " vol ",
                d.volume[0],
            )
            pos = self.beeapi.app.center.get_position(d._dataname)
            print("position", pos)
            # Can access position, trades, orders and other live trading information
            # Refer to http://docs.ctpbee.com/modules/rec.html for access methods
            trades = self.beeapi.app.center.trades
            print("trades", trades)
            account = self.beeapi.app.center.account
            print("account", account)

        if not self.live_data:  # Not live data (still in historical data backfilling), skip order logic
            return

        # Open long position
        print("live buy")
        # self.open_long(self.data0.close[0] + 3, 1, self.data0)
        print("---------------------------------------------------")

    def notify_order(self, order):
        """Called when order status changes.

        Args:
            order: Order object with updated status.
        """
        print("Order status %s" % order.getstatusname())

    def notify_data(self, data, status, *args, **kwargs):
        """Called when data feed status changes.

        Args:
            data: Data feed object.
            status: New status code.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        dn = data._name
        dt = datetime.now()
        msg = f"notify_data Data Status: {data._getstatusname(status)}"
        print(dt, dn, msg)
        if data._getstatusname(status) == "LIVE":
            self.live_data = True
        else:
            self.live_data = False

    # Following are order placement functions
    def open_long(self, price, size, data):
        """Open a long position.

        Args:
            price: Order price.
            size: Order size.
            data: Data feed object.
        """
        self.beeapi.action.buy(price, size, Origin(data))

    def open_short(self, price, size, data):
        """Open a short position.

        Args:
            price: Order price.
            size: Order size.
            data: Data feed object.
        """
        self.beeapi.action.short(price, size, Origin(data))

    def close_long(self, price, size, data):
        """Close a long position.

        Args:
            price: Order price.
            size: Order size.
            data: Data feed object.
        """
        self.beeapi.action.cover(price, size, Origin(data))

    def close_short(self, price, size, data):
        """Close a short position.

        Args:
            price: Order price.
            size: Order size.
            data: Data feed object.
        """
        self.beeapi.action.sell(price, size, Origin(data))


# Main program starts
if __name__ == "__main__":
    with open("./params_02.json") as f:
        ctp_setting = json.load(f)

    cerebro = bt.Cerebro(live=True)

    store = CTPStore(ctp_setting, debug=True)
    cerebro.addstrategy(SmaCross, store=store)

    # Since historical backfill data comes from akshare, finest granularity is 1-minute bar
    # So live trading also only receives 1-minute bars
    # https://www.akshare.xyz/zh_CN/latest/data/futures/futures.html#id106

    data0 = store.getdata(
        dataname="ag2312.SHFE",
        timeframe=bt.TimeFrame.Minutes,  # Note: symbol must include exchange code.
        num_init_backfill=100 if is_trading_period() else 0,
    )  # Initial backfill bar count, set to 0 when using TEST server for simulation

    data1 = store.getdata(
        dataname="rb2401.SHFE",
        timeframe=bt.TimeFrame.Minutes,  # Note: symbol must include exchange code.
        num_init_backfill=100 if is_trading_period() else 0,
    )  # Initial backfill bar count, set to 0 when using TEST server for simulation

    cerebro.adddata(data0)
    cerebro.adddata(data1)

    cerebro.run()
