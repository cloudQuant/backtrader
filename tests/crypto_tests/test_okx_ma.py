from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.stores.cryptostore import CryptoStore
from backtrader import Order
import backtrader as bt
from datetime import datetime, timedelta
import json
from bt_api_py.functions.utils import read_yaml_file


class TestStrategy(bt.Strategy):

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data, period=21)
        self.bought = False

    def next(self):
        # Get cash and balance
        # New broker method that will let you get the cash and balance for
        # any wallet. It also means we can disable the getcash() and getvalue()
        # rest calls before and after next which slows things down.

        # NOTE: If you try to get the wallet balance from a wallet you have
        # never funded, a KeyError will be raised! Change LTC below as approriate
        if self.live_data:
            balance = self.broker.get_wallet_balance(['BTC','ETH','EOS','USDT'])
            cash = balance['USDT']['cash']
            if self.live_data and not self.bought:
                # Buy
                # size x price should be >10 USDT at a minimum at Binance
                # make sure you use a price that is below the market price if you don't want to actually buy
                #self.order = self.sell(size=0.002, exectype=Order.Limit, price=3200)
                #self.order = self.sell(size=0.002, exectype=Order.Market)
                #self.order = self.buy(size=0.001, exectype=Order.Limit, price=50000)

                #对于火币和OKEX这类的交易所,他们现货的市价买单size字段其实传入的是`要花费的金额`,而不是要购买的数量,
                #但是ccxt库在实现的时候为了统一接口,玩了点小技巧,仍然是按size=购买数量,price=购买价格来传参数,
                #然后在内部计算size*price=`要花费的金额`后,再把真正的参数`要花费的金额`传给交易所.
                #记住,因为是市价成交所以最后实际成交数量不一定等于传入的size数量!
                #所以在这种情况下,backtrader平台内部的order.executed.remsize不可信,详见backtrader代码
                self.order = self.buy(size=0.001, exectype=Order.Market, price=50000)
                # And immediately cancel the buy order
                #self.cancel(self.order)
                #self.cancel(self.order)
                self.bought = True
        else:
            # Avoid checking the balance during a backfill. Otherwise, it will
            # Slow things down.
            cash = 'NA'

        print('---------------------------------------')
        for data in self.datas:
            print('{} - {} | Cash {} | O: {} H: {} L: {} C: {} V:{} SMA:{}'.format(data.datetime.datetime(),
                                                                                   data._name, cash, data.open[0], data.high[0], data.low[0], data.close[0], data.volume[0],
                                                                                   self.sma[0]))

    def notify_data(self, data, status, *args, **kwargs):
        dn = data._name
        dt = datetime.now()
        msg= 'Data Status: {}'.format(data._getstatusname(status))
        print(dt, dn, msg)
        if data._getstatusname(status) == 'LIVE':
            self.live_data = True
        else:
            self.live_data = False

    def notify_order(self, order):
        if order.status in [order.Completed, order.Cancelled, order.Rejected]:
            self.order = None
        print('-' * 50, 'ORDER BEGIN', datetime.now())
        print(order)
        print('-' * 50, 'ORDER END')

    def notify_trade(self, trade):
        print('-' * 50, 'TRADE BEGIN', datetime.now())
        print(trade)
        print('-' * 50, 'TRADE END')

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


def get_account_config():
    account_config_data = read_yaml_file('account_config.yaml')
    return account_config_data


def test_okx_ma():
    cerebro = bt.Cerebro(quicknotify=True, live=True)
    # Add the strategy
    cerebro.addstrategy(TestStrategy)

    account_config_data = get_account_config()
    kwargs = {
        "public_key": account_config_data['binance']['public_key'],
        "private_key": account_config_data['binance']['private_key'],
        "exchange": 'binance',
        "symbol": "BNB-USDT",
        "asset_type": "swap",
        "debug": True
    }
    # 获取当前时间
    now = datetime.now()
    # 计算当前时间之前的 2 个小时
    nine_hours_ago = now - timedelta(hours=9)
    data = CryptoFeed(dataname="BNB-USDT",
                      fromdate=nine_hours_ago,
                      timeframe=bt.TimeFrame.Minutes,
                      compression=1,
                      **kwargs)
    cerebro.adddata(data)
    broker = CryptoBroker(store=data.store)
    cerebro.setbroker(broker)

    # Run the strategy
    strategies = cerebro.run()
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    for sym in ['BTC/USDT','ETH/USDT','EOS/USDT']:
        data = store.getdata(dataname=sym, name=sym,
                             timeframe=bt.TimeFrame.Minutes, fromdate=hist_start_date,
                             compression=1, ohlcv_limit=1000, drop_newest=True)
        # Add the feed
        cerebro.adddata(data)

    # Run the strategy
    cerebro.run()