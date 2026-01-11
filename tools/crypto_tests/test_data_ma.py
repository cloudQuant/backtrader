import json
from datetime import UTC, datetime, timedelta

import pytz
from bt_api_py.functions.utils import read_yaml_file
from tzlocal import get_localzone

import backtrader as bt
from backtrader.brokers.cryptobroker import CryptoBroker
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.stores.cryptostore import CryptoStore
from backtrader.utils.log_message import SpdLogManager


def get_from_time_and_end_time():
    # Get current local time (with timezone info)
    local_time = datetime.now().astimezone()

    # Set microseconds to 0, keep minutes and seconds
    local_time_rounded = local_time.replace(microsecond=0)

    # Convert local time to UTC time
    utc_time = local_time_rounded.astimezone(pytz.UTC)

    # Return range from one hour before current time to current time
    return utc_time - timedelta(hours=1), utc_time


class TestStrategy(bt.BtApiStrategy):

    def __init__(self):
        super().__init__()
        self.logger = self.init_logger()
        self.sma_dict = {data.get_name(): bt.indicators.SMA(data, period=21) for data in self.datas}
        self.update_ma = False
        self.init_cash = None
        self.init_value = None
        self.init_ma = None
        self.update_cash = False
        self.update_value = False
        self.now_live_data = False
        self.live_bar_num = 0

    def next(self):

        # Get cash and balance
        # New broker method that will let you get the cash and balance for
        # any wallet. It also means we can disable the getcash() and getvalue()
        # rest calls before and after next which slows things down.

        # NOTE: If you try to get the wallet balance from a wallet you have
        # never funded, a KeyError will be raised! Change LTC below as approriate
        # if self.live_data:
        #     cash, value = self.broker.get_wallet_balance('USDT')
        # else:
        #     # Avoid checking the balance during a backfill. Otherwise, it will
        #     # Slow things down.
        #     cash = 'NA'

        for data in self.datas:
            cash = self.broker.getcash(data)
            value = self.broker.getvalue(data)
            # now_time = bt.num2date(data.datetime[0]).astimezone()   # First convert numeric time to timezone-naive datetime object
            now_time = bt.num2date(data.datetime[0], tz=get_localzone())
            now_ma = self.sma_dict[data.get_name()][0]
            self.log(
                f"{data.get_name()}, {now_time}, cash = {round(cash)}, value = {round(value)}, {data.close[0]}, {round(now_ma,2)}"
            )

            if self.init_ma is None:
                self.init_ma = now_ma
            else:
                if now_ma != self.init_ma:
                    self.update_ma = True
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

        if self.now_live_data:
            self.live_bar_num += 1

        if self.live_bar_num == 3:
            # self.envs.stop()
            self.env.runstop()  # Stop the backtest

    def notify_data(self, data, status, *args, **kwargs):
        dn = data.get_name()
        dt = datetime.now()
        msg = f"{dt}, {dn} Data Status: {data._getstatusname(status)}"
        self.log(msg)
        if data._getstatusname(status) == "LIVE":
            self.live_data = True
            self.now_live_data = True
        else:
            self.live_data = False


def get_account_config():
    account_config_data = read_yaml_file("account_config.yaml")
    return account_config_data


def test_binance_ma():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
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

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    # assert strategy_instance.update_cash is True
    # assert strategy_instance.update_value is True
    assert strategy_instance.update_ma is True


def test_okx_ma():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
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
    data3 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="OKX___SWAP___BTC-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    # assert strategy_instance.update_cash is True
    # assert strategy_instance.update_value is True
    assert strategy_instance.update_ma is True


def test_okx_and_binance():
    cerebro = bt.Cerebro(quicknotify=True)
    # Add the strategy
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
        dataname="OKX___SWAP___BTC-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data2, name="OKX___SWAP___BTC-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    # assert strategy_instance.update_cash is True
    # assert strategy_instance.update_value is True
    assert strategy_instance.update_ma is True


if __name__ == "__main__":
    print("-----------First test---------------")
    test_binance_ma()
    print("-----------Second test---------------")
    test_okx_ma()
    print("-----------Third test---------------")
    test_okx_and_binance()
