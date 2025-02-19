import backtrader as bt
from datetime import datetime, timedelta, UTC
import json
import pytz
from tzlocal import get_localzone

from backtrader import Trade, Order
from backtrader.stores.cryptostore import CryptoStore
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.brokers.cryptobroker import CryptoBroker
from backtrader.utils.log_message import SpdLogManager
from bt_api_py.functions.utils import read_yaml_file


def get_from_time_and_end_time():
    # 获取当前的本地时间（带有时区信息）
    local_time = datetime.now().astimezone()

    # 设置微秒为 0，保留分钟和秒
    local_time_rounded = local_time.replace(microsecond=0)

    # 将本地时间转换为 UTC 时间
    utc_time = local_time_rounded.astimezone(pytz.UTC)

    # 返回从当前时间的前一小时到当前时间的范围
    return utc_time - timedelta(hours=1), utc_time

class TestStrategy(bt.BtApiStrategy):
    params = (("period", 22), ("log_file_name", "buy_sell_cancel_order.log"))

    def __init__(self):
        super().__init__()
        self.ma_dict = {data.get_name(): bt.indicators.SMA(data, period=self.p.period)
                        for data in self.datas}
        self.now_live_data = False
        self.live_bar_num = 0
        self.create_order = False
        self.cancel_order = False

    def next(self):
        for data in self.datas:
            cash = self.broker.getcash(data)
            value = self.broker.getvalue(data)
            now_close = data.close[0]
            now_time = bt.num2date(data.datetime[0], tz=get_localzone())
            ma_indicator = self.ma_dict[data.get_name()]
            now_ma = ma_indicator[0]
            pre_ma = ma_indicator[-1]
            self.log(
                f"{data.get_name()}, {now_time}, cash = {round(cash)}, value = {round(value)}, {data.close[0]}, {round(now_ma, 2)}")
            if not self.now_live_data:
                return
            if now_ma > pre_ma:
                self.log("begin to make a long order")
                self.buy(data, 5, round(now_close*0.95, 4),  exectype='limit')
            else:
                self.log("begin to make a short order")
                self.sell(data, 5, round(now_close*1.05, 4),  exectype='limit')

        if self.now_live_data:
            self.live_bar_num += 1

        if self.create_order and self.cancel_order:
            # self.envs.stop()
            # self.close()
            self.env.runstop()  # Stop the backtest

    def notify_order(self, order):
        data = order.data
        data_name = data.get_name()
        new_order = order.bt_api_data
        new_order.init_data()
        order_status = new_order.get_order_status()
        print(data_name, new_order)
        if order_status == "NEW":
            self.create_order = True
            self.broker.cancel(order)
        if order_status == "CANCELED":
            self.cancel_order = True


    def notify_trade(self, trade):
        # 一个trade结束的时候输出信息
        data = trade.data
        data_name = data.get_name()
        new_trade = trade.bt_api_data
        print(data_name, new_trade)

    def notify_data(self, data, status, *args, **kwargs):
        dn = data.get_name()
        dt = datetime.now()
        new_status = data._getstatusname(status)
        msg= '{}, {} Data Status: {}'.format(dt, dn, new_status)
        self.log(msg)
        if new_status == 'LIVE':
            self.live_data = True
            self.now_live_data = True
        else:
            self.live_data = False

def get_account_config():
    account_config_data = read_yaml_file('account_config.yaml')
    return account_config_data


def test_binance_ma():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "BINANCE___SWAP": {
            "public_key": account_config_data['binance']['public_key'],
            "private_key": account_config_data['binance']['private_key']
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()
    data3 = crypto_store.getdata(store=crypto_store,
                                 debug=True,
                                 dataname="BINANCE___SWAP___OP-USDT",
                                 fromdate=fromdate,
                                 todate=todate,
                                 timeframe=bt.TimeFrame.Minutes,
                                 compression=1)
    cerebro.adddata(data3, name="BINANCE___SWAP___OP-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    assert strategy_instance.create_order is True
    assert strategy_instance.cancel_order is True


def test_okx_ma():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "OKX___SWAP": {
            "public_key": account_config_data['okx']['public_key'],
            "private_key": account_config_data['okx']['private_key'],
            "passphrase": account_config_data['okx']["passphrase"],
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()
    data3 = crypto_store.getdata(store=crypto_store,
                                 debug=True,
                                 dataname="OKX___SWAP___BTC-USDT",
                                 fromdate=fromdate,
                                 todate=todate,
                                 timeframe=bt.TimeFrame.Minutes,
                                 compression=1)
    cerebro.adddata(data3, name="OKX___SWAP___BTC-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True



def test_okx_and_binance():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "OKX___SWAP": {
            "public_key": account_config_data['okx']['public_key'],
            "private_key": account_config_data['okx']['private_key'],
            "passphrase": account_config_data['okx']["passphrase"],
        },
        "BINANCE___SWAP": {
            "public_key": account_config_data['binance']['public_key'],
            "private_key": account_config_data['binance']['private_key']
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()
    data1 = crypto_store.getdata(store=crypto_store,
                                 debug=True,
                                 dataname="BINANCE___SWAP___BNB-USDT",
                                 fromdate=fromdate,
                                 todate=todate,
                                 timeframe=bt.TimeFrame.Minutes,
                                 compression=1)
    cerebro.adddata(data1, name="BINANCE___SWAP___BNB-USDT")

    data2 = crypto_store.getdata(store=crypto_store,
                                 debug=True,
                                 dataname="OKX___SWAP___BTC-USDT",
                                 fromdate=fromdate,
                                 todate=todate,
                                 timeframe=bt.TimeFrame.Minutes,
                                 compression=1)
    cerebro.adddata(data2, name="OKX___SWAP___BTC-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    assert strategy_instance.create_order is True
    assert strategy_instance.cancel_order is True


if __name__ == '__main__':
    test_binance_ma()
    # test_okx_ma()
    # test_okx_and_binance()