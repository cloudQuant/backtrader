"""CCXT OKX SMA Trading Strategy Example.

This module demonstrates how to use Backtrader with the CCXT library to connect
to the OKX cryptocurrency exchange and implement a Simple Moving Average (SMA)
trading strategy.

The example shows:
- Setting up a CCXTStore for OKX exchange connection
- Creating a custom strategy with SMA indicator
- Managing live data feeds for multiple trading pairs
- Handling order execution and trade notifications
- Monitoring wallet balances and portfolio value

Note: This script requires API credentials for OKX exchange stored in a
.env file in the project root directory.
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

import backtrader as bt
from backtrader import Order
from backtrader.brokers.ccxtbroker import *
from backtrader.feeds.ccxtfeed import *
from backtrader.stores.ccxtstore import *


class TestStrategy(bt.Strategy):
    """A simple trading strategy using SMA indicator for cryptocurrency trading.

    This strategy demonstrates how to:
    - Calculate a Simple Moving Average (SMA) indicator
    - Monitor live data feed status
    - Check wallet balances across multiple cryptocurrencies
    - Log price and balance information
    - Handle order and trade notifications

    Attributes:
        sma: Simple Moving Average indicator with period of 21.
        bought: Boolean flag indicating if a buy order has been executed.
        live_data: Boolean flag indicating if the data feed is in live mode.
    """

    def __init__(self):
        """Initialize the TestStrategy.

        Sets up the SMA indicator and initializes the bought flag to False.
        The live_data attribute will be set dynamically based on data feed status.
        """
        self.sma = bt.indicators.SMA(self.data, period=21)
        self.bought = False

    def timestamp2datetime(timestamp):
        """Convert a Unix timestamp to a formatted datetime string.

        Args:
            timestamp (float): Unix timestamp to convert.

        Returns:
            str: Formatted datetime string in the format "YYYY-MM-DD HH:MM:SS.ffffff".
        """
        # Convert timestamp to datetime object
        dt_object = datetime.fromtimestamp(timestamp)
        # Format datetime object as string
        formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S.%f")
        return formatted_time

    def log(self, msg):
        """Log a message with a timestamp prefix.

        Args:
            msg (str): The message to log.
        """
        now_time = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S.%f")
        print(f"{now_time} === {msg}")

    def next(self):
        """Execute the main strategy logic for each bar.

        This method is called by Backtrader for each new data bar. It:
        1. Retrieves wallet balances for BTC, ETH, EOS, and USDT
        2. Logs current cash balance and price data
        3. Optionally executes a buy order (commented out in this example)

        Note:
            The buy order execution is currently disabled. When enabled,
            it would place a market buy order for a cryptocurrency pair.
        """
        # Get cash and balance
        # New broker method that will let you get the cash and balance for
        # any wallet. It also means we can disable the getcash() and getvalue()
        # rest calls before and after next which slows things down.

        # NOTE: If you try to get the wallet balance from a wallet you have
        # never funded, a KeyError will be raised! Change LTC below as approriate
        if self.live_data:
            balance = self.broker.get_wallet_balance(["BTC", "ETH", "EOS", "USDT"])
            cash = balance["USDT"]["cash"]
            if self.live_data and not self.bought:
                # Buy
                # size x price should be >10 USDT at a minimum at Binance
                # make sure you use a price that is below the market price if you don't want to actually buy
                # self.order = self.sell(size=0.002, exectype=Order.Limit, price=3200)
                # self.order = self.sell(size=0.002, exectype=Order.Market)
                # self.order = self.buy(size=0.001, exectype=Order.Limit, price=50000)

                # For exchanges like Huobi and OKEX, the size field for spot market buy orders is actually the `amount to spend`, not the quantity to buy
                # However, the ccxt library implemented a unified interface trick, still using size=quantity, price=price as parameters
                # Then internally calculates size*price=`amount to spend`, and passes the actual parameter `amount to spend` to the exchange
                # Remember, since it's a market order, the final executed quantity may not equal the input size!
                # In this case, order.executed.remsize within backtrader is not reliable, see backtrader code for details
                # self.order = self.buy(size=0.001, exectype=Order.Market, price=50000)
                # And immediately cancel the buy order
                # self.cancel(self.order)
                # self.cancel(self.order)
                self.bought = True
        else:
            # Avoid checking the balance during a backfill. Otherwise, it will
            # Slow things down.
            cash = "NA"

        self.log("---------------------------------------")
        for data in self.datas:
            self.log(
                "{} - {} | Cash {} | O: {}  C: {}, len:{}".format(
                    data.datetime.datetime(),
                    data._name,
                    cash,
                    data.open[0],
                    data.close[0],
                    len(data),
                )
            )

    def notify_data(self, data, status, *args, **kwargs):
        """Receive notifications about data feed status changes.

        Args:
            data: The data feed object that triggered the notification.
            status: The status code indicating the current state of the data feed.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        dn = data._name
        dt = datetime.now()
        msg = f"Data Status: {data._getstatusname(status)}"
        print(dt, dn, msg)
        if data._getstatusname(status) == "LIVE":
            self.live_data = True
        else:
            self.live_data = False

    def notify_order(self, order):
        """Receive notifications about order status changes.

        Args:
            order (Order): The order object that triggered the notification.
        """
        if order.status in [order.Completed, order.Cancelled, order.Rejected]:
            self.order = None
        print("-" * 50, "ORDER BEGIN", datetime.now())
        print(order)
        print("-" * 50, "ORDER END")

    def notify_trade(self, trade):
        """Receive notifications about trade execution.

        Args:
            trade: The trade object that triggered the notification.
        """
        print("-" * 50, "TRADE BEGIN", datetime.now())
        print(trade)
        print("-" * 50, "TRADE END")

    def notify_cashvalue(self, cash, value):
        """Receive notifications about cash and value changes.

        This method is called by the broker to update the strategy about
        the current cash and portfolio value.

        Args:
            cash (float): The current available cash.
            value (float): The current portfolio value.
        """
        pass

    def notify_fund(self, cash, value, fundvalue, shares):
        """Receive notifications about fund-related metrics.

        This method is called by the broker to update the strategy about
        fund-related metrics when using fund-like brokers.

        Args:
            cash (float): The current available cash.
            value (float): The current portfolio value.
            fundvalue (float): The current fund value.
            shares (float): The number of fund shares.
        """
        pass


# Load environment variables from .env file
# Look for .env in the project root (two levels up from examples/)
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Get OKX credentials from environment variables
api_key = os.getenv("OKX_API_KEY")
api_secret = os.getenv("OKX_SECRET")
api_password = os.getenv("OKX_PASSWORD")

if not all([api_key, api_secret, api_password]):
    raise ValueError(
        "Missing OKX API credentials. Please set OKX_API_KEY, OKX_SECRET, "
        "and OKX_PASSWORD in your .env file. See .env.example for reference."
    )

cerebro = bt.Cerebro(quicknotify=True, live=True)

# Add the strategy
cerebro.addstrategy(TestStrategy)

# Create our store with OKX exchange
config = {
    "apiKey": api_key,
    "secret": api_secret,
    "password": api_password,
    "enableRateLimit": True,
}

# IMPORTANT NOTE - Kraken (and some other exchanges) will not return any values
# for get cash or value if You have never held any BNB coins in your account.
# So switch BNB to a coin you have funded previously if you get errors
store = CCXTStore(exchange="okx", currency="USDT", config=config, retries=5, debug=False)

# Get the broker and pass any kwargs if needed.
broker = store.getbroker()
cerebro.setbroker(broker)

# Get our data
# Drop newest will prevent us from loading partial data from incomplete candles
hist_start_date = datetime.utcnow() - timedelta(minutes=100)
for symbol in ["BTC/USDT", "LPT/USDT", "EOS/USDT"]:
    # for symbol in ["BTC/USDT"]:
    data = store.getdata(
        dataname=symbol,
        name=symbol,
        timeframe=bt.TimeFrame.Minutes,
        fromdate=hist_start_date,
        compression=1,
        ohlcv_limit=100,
        drop_newest=False,
    )
    # data = store.getdata(dataname=symbol, name=symbol,
    #                      timeframe=bt.TimeFrame.Days, fromdate=hist_start_date,
    #                      compression=1, ohlcv_limit=100, drop_newest=True)
    # Add the feed
    cerebro.adddata(data)

# Run the strategy
cerebro.run()
