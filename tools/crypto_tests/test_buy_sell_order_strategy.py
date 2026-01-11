"""Tests for crypto exchange buy/sell order execution.

This module tests order placement and cancellation functionality with
various crypto exchanges (Binance, OKX) using live trading connections.
"""
import json
from datetime import UTC, datetime, timedelta

import pytz
from bt_api_py.containers.orders.order import OrderStatus
from bt_api_py.functions.utils import read_yaml_file
from tzlocal import get_localzone

import backtrader as bt
from backtrader import Order, Trade
from backtrader.brokers.cryptobroker import CryptoBroker
from backtrader.feeds.cryptofeed import CryptoFeed
from backtrader.stores.cryptostore import CryptoStore
from backtrader.utils.log_message import SpdLogManager


def get_from_time_and_end_time():
    """Get time range for data fetching.

    Returns a tuple of (start_time, end_time) where start_time is one hour
    before the current time in UTC.

    Returns:
        tuple: (start_time, end_time) as timezone-aware datetime objects.
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
    """Test strategy for order placement and cancellation.

    This strategy tests basic order execution by placing limit orders
    and immediately cancelling them upon acceptance.
    """
    params = (("period", 22), ("log_file_name", "buy_sell_cancel_order.log"))

    def __init__(self):
        """Initialize the test strategy."""
        super().__init__()
        self.ma_dict = {
            data.get_name(): bt.indicators.SMA(data, period=self.p.period) for data in self.datas
        }

        self.now_live_data = False
        self.live_bar_num = 0
        self.create_order_dict = {data.get_name(): False for data in self.datas}
        self.cancel_order_dict = {data.get_name(): False for data in self.datas}

    def next(self):
        """Execute strategy logic on each bar.

        Places limit orders based on moving average crossover when in live mode.
        """
        for data in self.datas:
            cash = self.broker.getcash(data)
            value = self.broker.getvalue(data)
            now_close = data.close[0]
            now_time = bt.num2date(data.datetime[0], tz=get_localzone())
            ma_indicator = self.ma_dict[data.get_name()]
            now_ma = ma_indicator[0]
            pre_ma = ma_indicator[-1]
            self.log(
                f"{data.get_name()}, {now_time}, cash = {round(cash)}, value = {round(value)}, {data.close[0]}, {round(now_ma, 2)}"
            )
            if not self.now_live_data:
                return
            if now_ma > pre_ma:
                self.log("begin to make a long order")
                self.buy(data, 6, round(now_close * 0.95, 4), exectype="limit")
                self.log("make order completely")
            else:
                self.log("begin to make a short order")
                self.sell(data, 6, round(now_close * 1.05, 4), exectype="limit")
                self.log("make order completely")

        if self.now_live_data:
            self.live_bar_num += 1

        # if self.create_order and self.cancel_order:
        #     # self.envs.stop()
        #     # self.close()
        #     self.env.runstop()  # Stop the backtest

    def notify_order(self, order):
        """Handle order status updates.

        Cancels orders immediately upon acceptance for testing purposes.

        Args:
            order: Order object with status information.
        """
        data = order.data
        data_name = data.get_name()
        new_order = order.bt_api_data
        new_order.init_data()
        order_status = new_order.get_order_status()
        print("notify_order", data_name, new_order)
        print("order_status", order_status, type(order_status))
        if order_status == OrderStatus.ACCEPTED:
            print("notify_order begin to cancel order")
            self.create_order_dict[data_name] = True
            self.broker.cancel(order)
        if order_status == OrderStatus.CANCELED:
            print("notify_order cancel order succeeded")
            self.cancel_order_dict[data_name] = True
            stop = True
            for key in self.cancel_order_dict:
                if not self.cancel_order_dict[key]:
                    stop = False
            if stop:
                self.env.runstop()

    def notify_trade(self, trade):
        """Handle trade updates.

        Args:
            trade: Trade object with position information.
        """
        # Output information when a trade ends
        data = trade.data
        data_name = data.get_name()
        new_trade = trade.bt_api_data
        print(data_name, new_trade)

    def notify_data(self, data, status, *args, **kwargs):
        """Handle data feed status updates.

        Args:
            data: Data feed object.
            status: Data status code.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.
        """
        dn = data.get_name()
        dt = datetime.now()
        new_status = data._getstatusname(status)
        msg = f"{dt}, {dn} Data Status: {new_status}"
        self.log(msg)
        if new_status == "LIVE":
            self.live_data = True
            self.now_live_data = True
        else:
            self.live_data = False


def get_account_config():
    """Load account configuration from YAML file.

    Returns:
        dict: Account configuration with API keys and credentials.
    """
    account_config_data = read_yaml_file("account_config.yaml")
    return account_config_data


def test_binance_buy_sell_order():
    """Test buy/sell order execution on Binance.

    Places and cancels orders on Binance exchange to verify order
    execution functionality.

    Raises:
        AssertionError: If orders are not created or cancelled properly.
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
        dataname="BINANCE___SWAP___OP-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="BINANCE___SWAP___OP-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    for cancel_order in strategy_instance.cancel_order_dict.values():
        assert cancel_order is True
    for create_order in strategy_instance.create_order_dict.values():
        assert create_order is True


def test_okx_buy_and_sell():
    """Test buy/sell order execution on OKX.

    Places and cancels orders on OKX exchange to verify order
    execution functionality.

    Raises:
        AssertionError: If orders are not created or cancelled properly.
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
    print(exchange_params)
    crypto_store = CryptoStore(exchange_params, debug=True)
    print(crypto_store.kwargs)
    fromdate, todate = get_from_time_and_end_time()
    data3 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___OP-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data3, name="OKX___SWAP___OP-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    for cancel_order in strategy_instance.cancel_order_dict.values():
        assert cancel_order is True
    for create_order in strategy_instance.create_order_dict.values():
        assert create_order is True


def test_okx_and_binance_buy_sell_order():
    """Test buy/sell order execution on both OKX and Binance simultaneously.

    Places and cancels orders on both exchanges to verify multi-exchange
    order execution functionality.

    Raises:
        AssertionError: If orders are not created or cancelled properly.
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
        dataname="BINANCE___SWAP___OP-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data1, name="BINANCE___SWAP___OP-USDT")

    data2 = crypto_store.getdata(
        store=crypto_store,
        debug=True,
        dataname="OKX___SWAP___OP-USDT",
        fromdate=fromdate,
        todate=todate,
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
    )
    cerebro.adddata(data2, name="OKX___SWAP___OP-USDT")

    broker = CryptoBroker(store=crypto_store)
    cerebro.setbroker(broker)

    # Enable live mode for realtime data
    strategies = cerebro.run(live=True)
    # Get first strategy instance
    strategy_instance = strategies[0]
    assert strategy_instance.now_live_data is True
    for cancel_order in strategy_instance.cancel_order_dict.values():
        assert cancel_order is True
    for create_order in strategy_instance.create_order_dict.values():
        assert create_order is True


if __name__ == "__main__":
    print("--------------First test-------------------")
    test_binance_buy_sell_order()
    print("--------------Second test-------------------")
    test_okx_buy_and_sell()
    print("--------------Third test-------------------")
    test_okx_and_binance_buy_sell_order()
