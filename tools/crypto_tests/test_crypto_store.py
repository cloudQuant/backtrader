"""Crypto Store Module Tests.

This module tests the CryptoStore class which provides connectivity to
cryptocurrency exchanges for backtesting and live trading.

Test Coverage:
    - Multiple CryptoStore instances with different exchange configurations
    - OKX exchange connection setup
    - Binance exchange connection setup
    - Independent store instances (no shared state)

Dependencies:
    - bt_api_py: Exchange API wrapper library
    - backtrader.stores.cryptostore: Crypto store implementation
    - account_config.yaml: Exchange credentials configuration file

Configuration File Format (account_config.yaml):
    okx:
        public_key: <OKX API public key>
        private_key: <OKX API private key>
        passphrase: <OKX API passphrase>
    binance:
        public_key: <Binance API public key>
        private_key: <Binance API private key>

Note:
    Tests require valid exchange credentials in account_config.yaml.
    Ensure credentials file exists and contains valid API keys before running.
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


def test_init_two_time():
    """Test initializing two CryptoStore instances with different exchanges.

    Verifies that multiple CryptoStore instances can be created independently
    with different exchange configurations without shared state or conflicts.

    Test Setup:
        1. Load account credentials from account_config.yaml
        2. Configure OKX swap exchange parameters
        3. Configure Binance swap exchange parameters
        4. Create first CryptoStore with OKX configuration
        5. Create second CryptoStore with Binance configuration
        6. Verify each store maintains its own configuration

    Configuration Structure:
        exchange_params = {
            "EXCHANGE___MARKET_TYPE": {
                "public_key": API public key,
                "private_key": API private key,
                "passphrase": API passphrase (OKX only)
            }
        }

    Args:
        None (reads from account_config.yaml file)

    Returns:
        None (assertion-based test)

    Raises:
        AssertionError: If exchange configurations are not properly stored.
        FileNotFoundError: If account_config.yaml does not exist.
        KeyError: If required configuration keys are missing.

    Validated:
        - crypto_store_1 contains OKX___SWAP configuration
        - crypto_store_2 contains BINANCE___SWAP configuration
        - Each store's kwargs dictionary has correct exchange keys

    Example:
        >>> test_init_two_time()  # Runs assertion checks
        # If credentials file exists and is valid, test passes silently
        # If assertions fail, AssertionError is raised
    """
    # Load exchange credentials from configuration file
    account_config_data = read_yaml_file("account_config.yaml")

    # Configure OKX swap exchange parameters
    exchange_params_1 = {
        "OKX___SWAP": {
            "public_key": account_config_data["okx"]["public_key"],
            "private_key": account_config_data["okx"]["private_key"],
            "passphrase": account_config_data["okx"]["passphrase"],
        }
    }

    # Configure Binance swap exchange parameters
    exchange_params_2 = {
        "BINANCE___SWAP": {
            "public_key": account_config_data["binance"]["public_key"],
            "private_key": account_config_data["binance"]["private_key"],
        }
    }

    # First initialization: Create OKX store with debug enabled
    crypto_store_1 = CryptoStore(exchange_params_1, debug=True)

    # Second initialization: Create Binance store with debug enabled
    crypto_store_2 = CryptoStore(exchange_params_2, debug=True)

    # Verify each store maintains its own configuration independently
    assert "OKX___SWAP" in crypto_store_1.kwargs
    assert "BINANCE___SWAP" in crypto_store_2.kwargs
