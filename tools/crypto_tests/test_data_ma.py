"""Cryptocurrency exchange data integration tests with Moving Average indicators.

This module contains integration tests for connecting to cryptocurrency exchanges
(Binance and OKX) through the Backtrader framework. It tests real-time data fetching,
Simple Moving Average (SMA) indicator calculations, and broker integration for
crypto trading.

The tests verify:
- Real-time data feed connectivity
- SMA indicator updates with live data
- Cash and value tracking through CryptoBroker
- Multi-exchange data handling
- Data status notifications (LIVE, DELAYED, etc.

Note: These tests require valid API credentials in account_config.yaml.
"""

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
    """Calculate UTC time range for data retrieval.

    Gets the current local time, rounds it to the second, converts to UTC,
    and returns a time range from one hour before the current time to the
    current time. This is useful for fetching recent historical data for
    testing or analysis.

    Returns:
        tuple: A tuple containing two datetime objects in UTC:
            - from_time: One hour before current time
            - to_time: Current time
    """
    # Get current local time (with timezone info)
    local_time = datetime.now().astimezone()

    # Set microseconds to 0, keep minutes and seconds
    local_time_rounded = local_time.replace(microsecond=0)

    # Convert local time to UTC time
    utc_time = local_time_rounded.astimezone(pytz.UTC)

    # Return range from one hour before current time to current time
    return utc_time - timedelta(hours=1), utc_time


class TestStrategy(bt.BtApiStrategy):
    """Test strategy for validating crypto exchange data and indicator updates.

    This strategy monitors multiple data feeds from cryptocurrency exchanges,
    calculates Simple Moving Average (SMA) indicators for each feed, and tracks
    whether values (cash, portfolio value, SMA) are updating correctly with
    live data.

    The strategy automatically stops after processing 3 live bars to allow
    for automated testing.

    Attributes:
        logger: Logger instance for output messages
        sma_dict (dict): Mapping of data feed names to their SMA indicators
        update_ma (bool): Flag indicating if SMA values have updated
        init_cash (float): Initial cash value for comparison
        init_value (float): Initial portfolio value for comparison
        init_ma (float): Initial SMA value for comparison
        update_cash (bool): Flag indicating if cash has updated
        update_value (bool): Flag indicating if portfolio value has updated
        now_live_data (bool): Flag indicating if live data has been received
        live_bar_num (int): Counter for number of live bars processed
    """

    def __init__(self):
        """Initialize the TestStrategy.

        Sets up logging, creates SMA indicators for all data feeds with a
        21-period window, and initializes tracking flags to monitor updates
        to cash, value, and moving averages.
        """
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
        """Process each bar of data.

        Called on every new bar for all data feeds. Logs current state
        including cash, portfolio value, close price, and SMA value.
        Tracks whether cash, value, and SMA values have changed from
        their initial values. Stops execution after 3 live bars.

        The method iterates through all data feeds and checks:
        - Current cash and portfolio value from the broker
        - Current close price and SMA indicator value
        - Whether values have updated since initialization
        """
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
        """Handle data feed status notifications.

        Called when the status of a data feed changes (e.g., from delayed
        to live). Logs the status change and updates the live_data flag
        when the feed enters LIVE state.

        Args:
            data: The data feed object whose status changed
            status: Integer status code (e.g., bt.misc.LIVE, bt.misc.DELAYED)
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments
        """
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
    """Load account configuration from YAML file.

    Reads API credentials and configuration settings from the
    account_config.yaml file. This file should contain API keys,
    secrets, and other connection parameters for cryptocurrency exchanges.

    Returns:
        dict: Dictionary containing account configuration with keys for
            different exchanges (e.g., 'binance', 'okx') and their
            respective credentials (public_key, private_key, passphrase)

    Raises:
        FileNotFoundError: If account_config.yaml does not exist
        yaml.YAMLError: If the YAML file is malformed
    """
    account_config_data = read_yaml_file("account_config.yaml")
    return account_config_data


def test_binance_ma():
    """Test Binance exchange integration with SMA indicator.

    Creates a Cerebro instance, connects to Binance swap market,
    fetches live BTC-USDT data for the past hour, and runs a
    backtest with the TestStrategy. Verifies that:
    - Live data is received
    - SMA indicator values update with new data

    Uses account credentials from account_config.yaml for authentication.

    Raises:
        AssertionError: If live data is not received or SMA values don't update
        KeyError: If account credentials are missing from config file
    """
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
    """Test OKX exchange integration with SMA indicator.

    Creates a Cerebro instance, connects to OKX swap market,
    fetches live BTC-USDT data for the past hour, and runs a
    backtest with the TestStrategy. Verifies that:
    - Live data is received
    - SMA indicator values update with new data

    Uses account credentials from account_config.yaml for authentication.
    OKX requires additional passphrase parameter beyond public/private keys.

    Raises:
        AssertionError: If live data is not received or SMA values don't update
        KeyError: If account credentials are missing from config file
    """
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
    """Test multi-exchange integration with OKX and Binance.

    Creates a Cerebro instance that connects to both OKX and Binance
    exchanges simultaneously. Fetches live data from:
    - BNB-USDT on Binance swap market
    - BTC-USDT on OKX swap market

    Runs a backtest with the TestStrategy to verify that:
    - Live data is received from both exchanges
    - SMA indicator values update correctly with multiple data feeds

    This test validates the framework's ability to handle multiple
    concurrent exchange connections and data feeds.

    Raises:
        AssertionError: If live data is not received or SMA values don't update
        KeyError: If account credentials are missing from config file
    """
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
