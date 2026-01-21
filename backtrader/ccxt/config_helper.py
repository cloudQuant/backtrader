#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CCXT Configuration Helper Module.

This module provides helper functions for loading CCXT exchange configurations
from environment variables and .env files.

Example:
    >>> from backtrader.ccxt.config_helper import load_ccxt_config_from_env
    >>> config = load_ccxt_config_from_env('binance')
    >>> store = bt.stores.CCXTStore(exchange='binance', config=config)
"""

import os
from typing import Dict, Optional
from pathlib import Path

try:
    from dotenv import load_dotenv
    HAS_DOTENV = True
except ImportError:
    HAS_DOTENV = False


# Exchange-specific credential mappings
EXCHANGE_CREDENTIALS = {
    'okx': {
        'apiKey': 'OKX_API_KEY',
        'secret': 'OKX_SECRET',
        'password': 'OKX_PASSWORD',
    },
    'binance': {
        'apiKey': 'BINANCE_API_KEY',
        'secret': 'BINANCE_SECRET',
    },
    'bybit': {
        'apiKey': 'BYBIT_API_KEY',
        'secret': 'BYBIT_SECRET',
    },
    'kraken': {
        'apiKey': 'KRAKEN_API_KEY',
        'secret': 'KRAKEN_SECRET',
    },
    'kucoin': {
        'apiKey': 'KUCOIN_API_KEY',
        'secret': 'KUCOIN_SECRET',
        'password': 'KUCOIN_PASSWORD',
    },
    'coinbase': {
        'apiKey': 'COINBASE_API_KEY',
        'secret': 'COINBASE_SECRET',
    },
    'coinbaseex': {
        'apiKey': 'COINBASEEX_API_KEY',
        'secret': 'COINBASEEX_SECRET',
    },
    'gate': {
        'apiKey': 'GATE_API_KEY',
        'secret': 'GATE_SECRET',
    },
    'huobi': {
        'apiKey': 'HUOBI_API_KEY',
        'secret': 'HUOBI_SECRET',
    },
    'kucoinfutures': {
        'apiKey': 'KUCOIN_API_KEY',
        'secret': 'KUCOIN_SECRET',
        'password': 'KUCOIN_PASSWORD',
    },
    'bitget': {
        'apiKey': 'BITGET_API_KEY',
        'secret': 'BITGET_SECRET',
        'password': 'BITGET_PASSWORD',
    },
}


def load_dotenv_file(env_path: Optional[str] = None) -> bool:
    """Load .env file from the specified path or default locations.

    Args:
        env_path: Optional path to .env file. If not provided, searches in
            default locations (project root, current directory).

    Returns:
        bool: True if .env was loaded successfully, False otherwise.
    """
    if not HAS_DOTENV:
        print("Warning: python-dotenv not installed. Install with: pip install python-dotenv")
        return False

    if env_path:
        load_dotenv(dotenv_path=env_path)
        return True

    # Try default locations
    default_paths = [
        Path.cwd() / '.env',
        Path(__file__).resolve().parent.parent.parent / '.env',
    ]

    for path in default_paths:
        if path.exists():
            load_dotenv(dotenv_path=path)
            return True

    return False


def load_ccxt_config_from_env(
    exchange: str,
    env_path: Optional[str] = None,
    enable_rate_limit: bool = True,
    sandbox: bool = False,
) -> Dict:
    """Load CCXT exchange configuration from environment variables.

    This function loads API credentials for the specified exchange from
    environment variables. It automatically loads the .env file if present.

    Supported exchanges: okx, binance, bybit, kraken, kucoin, coinbase,
    gate, huobi, kucoinfutures, bitget

    Args:
        exchange: Exchange ID (e.g., 'binance', 'okx', 'bybit').
        env_path: Optional path to .env file. If not provided, searches in
            default locations.
        enable_rate_limit: Enable CCXT's built-in rate limiting (default: True).
        sandbox: Use exchange sandbox/testnet mode (default: False).

    Returns:
        dict: Configuration dictionary compatible with CCXTStore.

    Raises:
        ValueError: If required credentials are not found in environment.

    Example:
        >>> config = load_ccxt_config_from_env('binance')
        >>> store = bt.stores.CCXTStore(
        ...     exchange='binance',
        ...     currency='USDT',
        ...     config=config,
        ...     retries=5
        ... )
    """
    # Load .env file if available
    load_dotenv_file(env_path)

    # Get credential mapping for this exchange
    exchange_lower = exchange.lower()
    credentials = EXCHANGE_CREDENTIALS.get(exchange_lower, {})

    if not credentials:
        raise ValueError(
            f"Exchange '{exchange}' is not in the credentials mapping. "
            f"Supported exchanges: {list(EXCHANGE_CREDENTIALS.keys())}"
        )

    # Build config from environment variables
    config = {
        'enableRateLimit': enable_rate_limit,
    }

    for key, env_var in credentials.items():
        value = os.getenv(env_var)
        if value:
            config[key] = value
        elif key in ['apiKey', 'secret']:
            # These are required
            raise ValueError(
                f"Missing required credential '{env_var}' for exchange '{exchange}'. "
                f"Please set it in your .env file or environment variables."
            )

    # Set sandbox mode if requested
    if sandbox:
        config['options'] = {'defaultType': 'swap'}

    return config


def get_exchange_credentials(exchange: str) -> Dict[str, str]:
    """Get API credentials for an exchange from environment variables.

    Returns only the credential fields (apiKey, secret, password) without
    additional CCXT settings.

    Args:
        exchange: Exchange ID (e.g., 'binance', 'okx').

    Returns:
        dict: Dictionary containing apiKey, secret, and optionally password.

    Raises:
        ValueError: If required credentials are not found.

    Example:
        >>> creds = get_exchange_credentials('okx')
        >>> print(creds['apiKey'])
    """
    exchange_lower = exchange.lower()
    credentials = EXCHANGE_CREDENTIALS.get(exchange_lower, {})

    if not credentials:
        raise ValueError(
            f"Exchange '{exchange}' is not in the credentials mapping. "
            f"Supported exchanges: {list(EXCHANGE_CREDENTIALS.keys())}"
        )

    result = {}
    for key, env_var in credentials.items():
        value = os.getenv(env_var)
        if not value and key in ['apiKey', 'secret']:
            raise ValueError(
                f"Missing required credential '{env_var}' for exchange '{exchange}'."
            )
        if value:
            result[key] = value

    return result


def list_supported_exchanges() -> list:
    """Return list of supported exchanges for credential loading.

    Returns:
        list: List of exchange IDs that have credential mappings.

    Example:
        >>> exchanges = list_supported_exchanges()
        >>> print(exchanges)
        ['okx', 'binance', 'bybit', 'kraken', ...]
    """
    return list(EXCHANGE_CREDENTIALS.keys())
