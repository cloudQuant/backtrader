import time
from datetime import datetime, timedelta
import backtrader as bt
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.stores.cryptostore import CryptoStore
from bt_api_py.functions.utils import read_yaml_file
from bt_api_py.functions.log_message import SpdLogManager


class TestStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()
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
        # if self.historical_data_loaded and self.realtime_data_loaded:
        #     print("Test succeeded: Both historical and realtime data loaded successfully!")
        #     # self.stop()  # Stop the backtest
        #     self.env.runstop()  # Stop the backtest
        for data in self.datas:
            self.log(f"{data._name}, {bt.num2date(data.datetime[0])}, {data.close[0]}")

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
    exchange_params = {
        "BINANCE___SWAP": {
        "public_key": account_config_data['binance']['public_key'],
        "private_key": account_config_data['binance']['private_key']
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    nine_hours_ago = datetime.now() - timedelta(hours=9)
    data1 = crypto_store.getdata( exchange_params,
                                  debug=True,
                                  dataname="BNB-USDT",
                                  symbol="BNB-USDT",
                                  fromdate=nine_hours_ago,
                                  timeframe=bt.TimeFrame.Minutes,
                                  compression=1)
    cerebro.adddata(data1, name="BNB-USDT")

    data2 = crypto_store.getdata(exchange_params,
                                 debug=True,
                                 dataname="BTC-USDT",
                                 symbol="BTC-USDT",
                                 fromdate=nine_hours_ago,
                                 timeframe=bt.TimeFrame.Minutes,
                                 compression=1)
    cerebro.adddata(data2, name="BTC-USDT")

    # data3 = crypto_store.getdata(exchange_params,
    #                              debug=True,
    #                              dataname="ETH-USDT",
    #                              symbol="ETH-USDT",
    #                              fromdate=nine_hours_ago,
    #                              timeframe=bt.TimeFrame.Minutes,
    #                              compression=1)
    # cerebro.adddata(data3, name="ETH-USDT")

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True

if __name__ == '__main__':
    test_backtest_strategy()