
import backtrader as bt
from datetime import datetime, timedelta, UTC
import json
from backtrader.stores.cryptostore import CryptoStore
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.brokers.cryptobroker import CryptoBroker
from backtrader.utils.log_message import SpdLogManager
from bt_api_py.functions.utils import read_yaml_file

class TestStrategy(bt.Strategy):

    def __init__(self):
        self.logger = self.init_logger()
        self.sma = bt.indicators.SMA(self.data, period=21)
        self.update_ma = False
        self.init_cash = None
        self.init_value = None
        self.init_ma = None
        self.update_cash = False
        self.update_value = False
        self.now_live_data = False
        self.live_bar_num = 0

    def init_logger(self):
        logger = SpdLogManager(file_name=self.__class__.__name__,
                               logger_name="strategy",
                               print_info=True).create_logger()
        return logger

    def log(self, txt):
        self.logger.info(txt)

    def next(self):

        # Get cash and balance
        # New broker method that will let you get the cash and balance for
        # any wallet. It also means we can disable the getcash() and getvalue()
        # rest calls before and after next which slows things down.

        # NOTE: If you try to get the wallet balance from a wallet you have
        # never funded, a KeyError will be raised! Change LTC below as approriate
        cash = self.broker.getcash()
        value = self.broker.getvalue()
        # if self.live_data:
        #     cash, value = self.broker.get_wallet_balance('USDT')
        # else:
        #     # Avoid checking the balance during a backfill. Otherwise, it will
        #     # Slow things down.
        #     cash = 'NA'

        for data in self.datas:
            self.log('{} - {} | Cash {} | O: {} H: {} L: {} C: {} V:{} SMA:{}'.format(data.datetime.datetime(),
                                                                                   data._name, cash, data.open[0], data.high[0], data.low[0], data.close[0], data.volume[0],
                                                                                   self.sma[0]))

        # check cash whether update
        if self.init_cash is None:
            self.init_cash = cash
        else:
            if cash != self.init_cash:
                self.update_cash = True

        # check value whether update
        if self.init_value is None:
            self.init_value = value
        else:
            if value != self.init_value:
                self.update_value = True

        # check ma whether update
        if self.init_ma is None:
            self.init_ma = self.sma[0]
        else:
            if self.sma[0] != self.init_ma:
                self.update_ma = True

        if self.now_live_data:
            self.live_bar_num += 1

        if self.live_bar_num == 2:
            # self.envs.stop()
            self.env.runstop()  # Stop the backtest



    def notify_data(self, data, status, *args, **kwargs):
        dn = data._name
        dt = datetime.now()
        msg= '{}, {} Data Status: {}'.format(dt, dn, data._getstatusname(status))
        self.log(msg)
        if data._getstatusname(status) == 'LIVE':
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
    assert strategy_instance.now_live_data is True
    # assert strategy_instance.update_cash is True
    # assert strategy_instance.update_value is True
    assert strategy_instance.update_ma is True



if __name__ == '__main__':
    test_binance_ma()