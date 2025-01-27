import time
from datetime import datetime, timedelta
import backtrader as bt
from backtrader.feeds.cryptofeed import CryptoFeed
from bt_api_py.functions.utils import read_yaml_file

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.next_runs = 0

    def next(self, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print('%s closing price: %s' % (dt.isoformat(), self.datas[0].close[0]))
        self.next_runs += 1

def get_account_config():
    account_config_data = read_yaml_file('account_config.yaml')
    return account_config_data

def test_backtest_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    kwargs = {
        "public_key": account_config_data['binance']['public_key'],
        "private_key": account_config_data['binance']['private_key'],
        "exchange": 'binance',
        "symbol": "BNB-USDT",
        "asset_type": "swap"
    }
    data = CryptoFeed(dataname="BNB-USDT",
                      fromdate=datetime(2025, 1, 27, 8, 0),
                      timeframe=bt.TimeFrame.Minutes,
                      compression=1,
                      **kwargs)
    cerebro.adddata(data)

    # Run the strategy
    cerebro.run()


if __name__ == '__main__':
    test_backtest_strategy()