import time
from datetime import datetime, timedelta
import backtrader as bt
from backtrader.feeds.cryptofeed import CryptoFeed
from bt_api_py.functions.utils import read_yaml_file
from bt_api_py.functions.log_message import SpdLogManager


class TestStrategy(bt.Strategy):
    def __init__(self):
        self.next_runs = 0
        self.historical_data_loaded = False
        self.realtime_data_loaded = False
        self.debug = True
        self.now_live_data = False
        self.logger = self.init_logger()

    def init_logger(self):
        if self.debug:
            print_info = True
        else:
            print_info = False
        logger = SpdLogManager(file_name='crypto_strategy.log',
                               logger_name="strategy",
                               print_info=print_info).create_logger()
        return logger

    def log(self, txt, level="info"):
        if level == "info":
            self.logger.info(txt)
        elif level == "warning":
            self.logger.warning(txt)
        elif level == "error":
            self.logger.error(txt)
        elif level == "debug":
            self.logger.debug(txt)
        else:
            pass

    def next(self, dt=None):
        # If both historical and realtime data are loaded, mark test as successful
        if self.historical_data_loaded and self.realtime_data_loaded:
            print("Test succeeded: Both historical and realtime data loaded successfully!")
            # self.stop()  # Stop the backtest
            self.env.runstop()  # Stop the backtest

        dt = dt or self.datas[0].datetime.datetime(0)
        self.log('%s closing price: %s' % (dt.isoformat(), self.datas[0].close[0]))
        self.next_runs += 1

        # Check if historical data is loaded
        if not self.historical_data_loaded and not self.now_live_data:
            self.log("Historical data loaded successfully!")
            self.historical_data_loaded = True

        # Check if realtime data is loaded
        if self.now_live_data:
            self.log("Realtime data loaded successfully!")
            self.realtime_data_loaded = True


    def notify_data(self, data, status, *args, **kwargs):
        dn = data._name
        dt = datetime.now()
        msg= '{}, {} Data Status: {}'.format(dt, dn, data._getstatusname(status))
        self.log(msg)
        if data._getstatusname(status) == 'LIVE':
            self.log(f"now data status = {data._getstatusname(status)}")
            self.live_data = True
            self.now_live_data = True
        else:
            self.live_data = False

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
        "asset_type": "swap",
        'debug':True
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