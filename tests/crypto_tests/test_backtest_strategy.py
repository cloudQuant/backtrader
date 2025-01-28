import time
from datetime import datetime, timedelta
import backtrader as bt
from backtrader.feeds.cryptofeed import CryptoFeed
from bt_api_py.functions.utils import read_yaml_file

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.next_runs = 0
        self.historical_data_loaded = False
        self.realtime_data_loaded = False

    def next(self, dt=None):
        dt = dt or self.datas[0].datetime.datetime(0)
        print('%s closing price: %s' % (dt.isoformat(), self.datas[0].close[0]))
        self.next_runs += 1

        # Check if historical data is loaded
        if not self.historical_data_loaded and len(self.datas[0]) > 0:
            print("Historical data loaded successfully!")
            self.historical_data_loaded = True

        # Check if realtime data is loaded
        if not self.realtime_data_loaded and self.datas[0].islive:
            print("Realtime data loaded successfully!")
            self.realtime_data_loaded = True

        # If both historical and realtime data are loaded, mark test as successful
        if self.historical_data_loaded and self.realtime_data_loaded:
            print("Test succeeded: Both historical and realtime data loaded successfully!")
            # self.stop()  # Stop the backtest
            self.env.runstop()  # Stop the backtest

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
    # 获取当前时间
    now = datetime.now()
    # 计算当前时间之前的 2 个小时
    two_hours_ago = now - timedelta(hours=9)
    now_datetime = datetime(2025,1,27, 8,0,0)
    data = CryptoFeed(dataname="BNB-USDT",
                      fromdate=two_hours_ago,
                      timeframe=bt.TimeFrame.Minutes,
                      compression=1,
                      **kwargs)
    cerebro.adddata(data)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True

if __name__ == '__main__':
    test_backtest_strategy()