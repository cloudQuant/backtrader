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


def test_init_two_time():
    account_config_data = read_yaml_file("account_config.yaml")
    exchange_params_1 = {
        "OKX___SWAP": {
            "public_key": account_config_data["okx"]["public_key"],
            "private_key": account_config_data["okx"]["private_key"],
            "passphrase": account_config_data["okx"]["passphrase"],
        }
    }

    exchange_params_2 = {
        "BINANCE___SWAP": {
            "public_key": account_config_data["binance"]["public_key"],
            "private_key": account_config_data["binance"]["private_key"],
        }
    }
    # First initialization
    crypto_store_1 = CryptoStore(exchange_params_1, debug=True)
    # Second initialization
    crypto_store_2 = CryptoStore(exchange_params_2, debug=True)
    assert "OKX___SWAP" in crypto_store_1.kwargs
    assert "BINANCE___SWAP" in crypto_store_2.kwargs
