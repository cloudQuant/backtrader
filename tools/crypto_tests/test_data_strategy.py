"""Tests for crypto data feed functionality.

This module contains tests for validating data loading from various cryptocurrency
exchanges including Binance and OKX. Tests cover both historical data retrieval
and live data streaming capabilities.

The tests use the CryptoStore and CryptoFeed classes to connect to exchange
APIs and verify that data can be loaded correctly in both historical and
real-time modes.
"""
import time
from datetime import datetime, timedelta

import pytz
from bt_api_py.functions.log_message import SpdLogManager
from bt_api_py.functions.utils import read_yaml_file

import backtrader as bt
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.stores.cryptostore import CryptoStore


def get_from_time_and_end_time():
    """Calculate time range for data fetching.

    Computes a time range starting from one hour before the current time
    up to the current time. All times are in UTC to ensure consistency
    with exchange APIs.

    Returns:
        tuple: A tuple containing two timezone-aware datetime objects:
            - start_time: datetime object one hour before current time
            - end_time: datetime object representing current time
            Both times are in UTC timezone.
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
    """Test strategy for validating crypto data feed functionality.

    This strategy is used to verify that both historical and live data
    are loaded correctly from cryptocurrency exchange data feeds. It tracks
    the loading process and validates that data transitions from historical
    to live mode as expected.

    Attributes:
        next_runs (int): Counter for number of times next() has been called.
        historical_data_loaded (bool): Flag indicating historical data loaded.
        realtime_data_loaded (bool): Flag indicating realtime data loaded.
        debug (bool): Enable debug logging.
        now_live_data (bool): Flag indicating currently receiving live data.
        live_data (bool): Flag indicating live data status.
        live_bar_num (int): Counter for live bars received.
        logger: Logger instance for outputting messages.
    """

    def __init__(self):
        """Initialize the TestStrategy instance.

        Sets up all tracking attributes for monitoring data feed status
        and initializes the logger for outputting test messages.
        """
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
        """Execute strategy logic on each bar.

        This method is called on each new bar of data. It logs the current
        price and time for all data feeds, tracks the transition from
        historical to live data, and stops the backtest after receiving
        a specified number of live bars.

        Args:
            dt (datetime, optional): Datetime parameter for backtesting mode.
                Not used in this implementation.

        Behavior:
            - Logs current bar data for all data feeds
            - Sets historical_data_loaded flag on first bar
            - Sets realtime_data_loaded flag when live data arrives
            - Stops backtest after 3 live bars
        """
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
        """Handle data feed status updates.

        Called when the status of a data feed changes. This method tracks
        when data feeds transition from historical to live mode.

        Args:
            data: Data feed object that triggered the notification.
            status: Integer status code indicating the data feed state.
            *args: Additional positional arguments (unused).
            **kwargs: Additional keyword arguments (unused).

        Status Codes:
            Status codes are defined by backtrader and indicate states such as:
            - DELAYED: Data is delayed
            - LIVE: Realtime live data
            - NOTSUBSCRIBED: Not subscribed to data
            - OVERSAMPLED: Data is being oversampled
            - CONCURRENT: Concurrent data reception
        """
        dn = data.get_name()
        msg = f"{dn} Data Status: {data._getstatusname(status)}"
        self.log(msg)
        if data._getstatusname(status) == "LIVE":
            self.live_data = True
            self.now_live_data = True
        else:
            self.live_data = False


def get_account_config():
    """Load account configuration from YAML file.

    Reads the account configuration file which contains API credentials
    for various cryptocurrency exchanges (Binance, OKX, etc.).

    Returns:
        dict: Dictionary containing account configuration with keys for
            each exchange including public_key, private_key, and passphrase
            (for exchanges that require it).

    Raises:
        FileNotFoundError: If account_config.yaml file does not exist.
        KeyError: If required configuration keys are missing.
    """
    account_config_data = read_yaml_file("account_config.yaml")
    return account_config_data


def test_binance_three_data_strategy():
    """Test Binance data feed with three trading pairs.

    This test validates loading both historical and live data from Binance
    exchange for three different perpetual swap trading pairs:
    BNB-USDT, BTC-USDT, and ETH-USDT.

    The test:
    1. Creates a Cerebro engine with TestStrategy
    2. Loads account credentials from configuration
    3. Creates CryptoStore with Binance API credentials
    4. Adds three data feeds for different trading pairs
    5. Runs the backtest in live mode
    6. Asserts that both historical and live data were loaded

    Raises:
        AssertionError: If historical or realtime data loading fails.
        ConnectionError: If connection to Binance API fails.
    """
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
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_binance_one_data_strategy():
    """Test Binance data feed with single trading pair.

    This test validates loading both historical and live data from Binance
    exchange for the BTC-USDT perpetual swap trading pair.

    The test:
    1. Creates a Cerebro engine with TestStrategy
    2. Loads account credentials from configuration
    3. Creates CryptoStore with Binance API credentials
    4. Adds one data feed for BTC-USDT
    5. Runs the backtest in live mode
    6. Asserts that both historical and live data were loaded

    Raises:
        AssertionError: If historical or realtime data loading fails.
        ConnectionError: If connection to Binance API fails.
    """
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
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_okx_one_data_strategy():
    """Test OKX data feed with single trading pair.

    This test validates loading both historical and live data from OKX
    exchange for the BTC-USDT perpetual swap trading pair.

    The test:
    1. Creates a Cerebro engine with TestStrategy
    2. Loads account credentials from configuration (includes passphrase)
    3. Creates CryptoStore with OKX API credentials
    4. Adds one data feed for BTC-USDT
    5. Runs the backtest in live mode
    6. Asserts that both historical and live data were loaded

    Raises:
        AssertionError: If historical or realtime data loading fails.
        ConnectionError: If connection to OKX API fails.
    """
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
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_okx_two_data_strategy():
    """Test OKX data feed with two trading pairs.

    This test validates loading both historical and live data from OKX
    exchange for two different perpetual swap trading pairs:
    BTC-USDT and ETH-USDT.

    The test:
    1. Creates a Cerebro engine with TestStrategy
    2. Loads account credentials from configuration (includes passphrase)
    3. Creates CryptoStore with OKX API credentials
    4. Adds two data feeds for BTC-USDT and ETH-USDT
    5. Runs the backtest in live mode
    6. Asserts that both historical and live data were loaded

    Raises:
        AssertionError: If historical or realtime data loading fails.
        ConnectionError: If connection to OKX API fails.
    """
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
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


def test_binance_one_okx_one_data_strategy():
    """Test mixed exchange data feeds with Binance and OKX.

    This test validates loading both historical and live data from two
    different cryptocurrency exchanges simultaneously: Binance and OKX.
    Each exchange provides data for the BTC-USDT perpetual swap pair.

    The test:
    1. Creates a Cerebro engine with TestStrategy
    2. Loads account credentials for both exchanges from configuration
    3. Creates CryptoStore with credentials for both Binance and OKX
    4. Adds one data feed from OKX for BTC-USDT
    5. Adds one data feed from Binance for BTC-USDT
    6. Runs the backtest in live mode
    7. Asserts that both historical and live data were loaded

    Raises:
        AssertionError: If historical or realtime data loading fails.
        ConnectionError: If connection to either exchange API fails.
    """
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
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.historical_data_loaded is True
    assert strategy_instance.realtime_data_loaded is True


if __name__ == "__main__":
    print("-----------First test---------------")
    test_binance_one_data_strategy()  # successfully
    print("-----------Second test---------------")
    test_okx_one_data_strategy()  # successfully
    print("-----------Third test---------------")
    test_binance_three_data_strategy()
    print("-----------Fourth test---------------")
    test_okx_two_data_strategy()
    print("-----------Fifth test---------------")
    test_binance_one_okx_one_data_strategy()
