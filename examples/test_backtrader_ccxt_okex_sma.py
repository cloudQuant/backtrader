import json
from datetime import datetime, timedelta

import backtrader as bt
from backtrader import Order
from backtrader.brokers.ccxtbroker import *
from backtrader.feeds.ccxtfeed import *
from backtrader.stores.ccxtstore import *


class TestStrategy(bt.Strategy):

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=21)
        self.bought = False

    def timestamp2datetime(timestamp):
        # Convert timestamp to datetime object
        dt_object = datetime.fromtimestamp(timestamp)
        # Format datetime object as string
        formatted_time = dt_object.strftime("%Y-%m-%d %H:%M:%S.%f")
        return formatted_time

    def log(self, msg):
        now_time = datetime.fromtimestamp(time.time()).strftime("%Y-%m-%d %H:%M:%S.%f")
        print(f"{now_time} === {msg}")

    def next(self):
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
        dn = data._name
        dt = datetime.now()
        msg = f"Data Status: {data._getstatusname(status)}"
        print(dt, dn, msg)
        if data._getstatusname(status) == "LIVE":
            self.live_data = True
        else:
            self.live_data = False

    def notify_order(self, order):
        if order.status in [order.Completed, order.Cancelled, order.Rejected]:
            self.order = None
        print("-" * 50, "ORDER BEGIN", datetime.now())
        print(order)
        print("-" * 50, "ORDER END")

    def notify_trade(self, trade):
        print("-" * 50, "TRADE BEGIN", datetime.now())
        print(trade)
        print("-" * 50, "TRADE END")

    def notify_cashvalue(self, cash, value):
        """
        Receives the current fund value, value status of the strategy's broker
        """
        pass

    def notify_fund(self, cash, value, fundvalue, shares):
        """
        Receives the current cash, value, fundvalue and fund shares
        """
        pass


with open(r"D:\key_info\params-crypto.json") as f:
    params = json.load(f)

cerebro = bt.Cerebro(quicknotify=True, live=True)

# Add the strategy
cerebro.addstrategy(TestStrategy)

# Create our store
config = {
    "apiKey": params["okex"]["apikey"],
    "secret": params["okex"]["secret"],
    "password": params["okex"]["password"],
    "enableRateLimit": True,
}

# IMPORTANT NOTE - Kraken (and some other exchanges) will not return any values
# for get cash or value if You have never held any BNB coins in your account.
# So switch BNB to a coin you have funded previously if you get errors
store = CCXTStore(exchange="okex5", currency="USDT", config=config, retries=5, debug=False)

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
        compression=3,
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
