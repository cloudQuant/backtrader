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
        # 将时间戳转换为datetime对象
        dt_object = datetime.fromtimestamp(timestamp)
        # 将datetime对象格式化为字符串形式
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

                # 对于火币和OKEX这类的交易所,他们现货的市价买单size字段其实传入的是`要花费的金额`,而不是要购买的数量,
                # 但是ccxt库在实现的时候为了统一接口,玩了点小技巧,仍然是按size=购买数量,price=购买价格来传参数,
                # 然后在内部计算size*price=`要花费的金额`后,再把真正的参数`要花费的金额`传给交易所.
                # 记住,因为是市价成交所以最后实际成交数量不一定等于传入的size数量!
                # 所以在这种情况下,backtrader平台内部的order.executed.remsize不可信,详见backtrader代码
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
