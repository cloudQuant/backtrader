import time
from datetime import datetime, timedelta

import pytz
from bt_api_py.functions.log_message import SpdLogManager
from bt_api_py.functions.utils import read_yaml_file

import backtrader as bt
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.stores.cryptostore import CryptoStore


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
    def __init__(self):
        super().__init__()
        self.next_runs = 0
        self.historical_data_loaded = False
        self.realtime_data_loaded = False
        self.debug = True
        self.now_live_data = False
        self.live_data = False
        self.live_bar_num = 0
        self.logger = self.init_logger()

    # def prenext(self):
    #     self.next()

    def next(self, dt=None):
        # Check if historical data is loaded
        for data in self.datas:
            now_time = bt.num2date(data.datetime[0], tz=pytz.timezone("Asia/Shanghai"))
            self.log(f"{data.get_name()}, {now_time}, {data.close[0]}")

        if not self.historical_data_loaded and not self.now_live_data:
            self.log("Historical data loaded successfully!")
            self.historical_data_loaded = True

        # Check if realtime data is loaded
        if self.now_live_data:
            self.log("Realtime data loaded successfully!")
            self.realtime_data_loaded = True

        if self.historical_data_loaded and self.realtime_data_loaded:
            self.live_bar_num += 1

        if self.live_bar_num == 3:
            self.env.runstop()  # Stop the backtest
        self.log(f"live bar number: {self.live_bar_num}")

    def notify_data(self, data, status, *args, **kwargs):
        dn = data.get_name()
        msg = f"{dn} Data Status: {data._getstatusname(status)}"
        self.log(msg)
        if data._getstatusname(status) == "LIVE":
            self.live_data = True
            self.now_live_data = True
        else:
            self.live_data = False


def get_account_config():
    account_config_data = read_yaml_file("account_config.yaml")
    return account_config_data


def test_binance_three_data_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "BINANCE___SWAP": {
            "public_key": account_config_data["binance"]["public_key"],
            "private_key": account_config_data["binance"]["private_key"],
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()

    data1 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="BINANCE___SWAP___BNB-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data1, name="BINANCE___SWAP___BNB-USDT")

    data2 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="BINANCE___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data2, name="BINANCE___SWAP___BTC-USDT")

    data3 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="BINANCE___SWAP___ETH-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="BINANCE___SWAP___ETH-USDT")

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_binance_one_data_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "BINANCE___SWAP": {
            "public_key": account_config_data["binance"]["public_key"],
            "private_key": account_config_data["binance"]["private_key"],
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()
    data3 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="BINANCE___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="BINANCE___SWAP___BTC-USDT")

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_okx_one_data_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "OKX___SWAP": {
            "public_key": account_config_data["okx"]["public_key"],
            "private_key": account_config_data["okx"]["private_key"],
            "passphrase": account_config_data["okx"]["passphrase"],
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()

    data2 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data2, name="OKX___SWAP___BTC-USDT")
    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_okx_two_data_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "OKX___SWAP": {
            "public_key": account_config_data["okx"]["public_key"],
            "private_key": account_config_data["okx"]["private_key"],
            "passphrase": account_config_data["okx"]["passphrase"],
        }
    }
    crypto_store = CryptoStore(exchange_params, debug=True)
    fromdate, todate = get_from_time_and_end_time()
    # data1 = crypto_store.getdata( store=crypto_store,
    #                               debug=True,
    #                               dataname="OKX___SWAP___BNB-USDT",
    #                               fromdate=nine_hours_ago,
    #                               timeframe=bt.TimeFrame.Minutes,
    #                               compression=1)
    # cerebro.adddata(data1, name="OKX___SWAP___BNB-USDT")

    data2 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data2, name="OKX___SWAP___BTC-USDT")

    data3 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___ETH-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="OKX___SWAP___ETH-USDT")

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_binance_one_okx_one_data_strategy():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TestStrategy)
    account_config_data = get_account_config()
    exchange_params = {
        "OKX___SWAP": {
            "public_key": account_config_data["okx"]["public_key"],
            "private_key": account_config_data["okx"]["private_key"],
            "passphrase": account_config_data["okx"]["passphrase"],
        },
        "BINANCE___SWAP": {
            "public_key": account_config_data["binance"]["public_key"],
            "private_key": account_config_data["binance"]["private_key"],
        },
    }
    crypto_store = CryptoStore(exchange_params, debug=True)

    fromdate, todate = get_from_time_and_end_time()

    data2 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data2, name="OKX___SWAP___BTC-USDT")
    data3 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="BINANCE___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="BINANCE___SWAP___BTC-USDT")

    # Enable live mode for realtime data
    # strategies = cerebro.run(live=True)
    strategies = cerebro.run(live=True)
    # 获取第一个策略实例
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


if __name__ == "__main__":
    print("-----------第一个进行测试---------------")
    test_binance_one_data_strategy()  # successfully
    print("-----------第二个进行测试---------------")
    test_okx_one_data_strategy()  # successfully
    print("-----------第三个进行测试---------------")
    test_binance_three_data_strategy()
    print("-----------第四个进行测试---------------")
    test_okx_two_data_strategy()
    print("-----------第五个进行测试---------------")
    test_binance_one_okx_one_data_strategy()
