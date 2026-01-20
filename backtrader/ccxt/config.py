#!/usr/bin/env python
"""Exchange Configuration Module - Exchange-specific settings.

This module provides centralized configuration for different cryptocurrency
exchanges including order types, timeframes, and exchange-specific parameters.

Classes:
    ExchangeConfig: Configuration manager for exchange-specific settings.

Example:
    >>> order_type = ExchangeConfig.get_order_type('binance', Order.StopLimit)
    >>> timeframe = ExchangeConfig.get_timeframe('binance', (4, 60))
"""

from typing import Dict, Any, Optional

# Use integer constants to avoid circular import with backtrader
# These match the values defined in backtrader.order.OrderBase
_ORDER_MARKET = 0
_ORDER_LIMIT = 2
_ORDER_STOP = 3
_ORDER_STOPLIMIT = 4
_ORDER_STOPTRAIL = 5

# TimeFrame constants from backtrader.dataseries
_TF_MINUTES = 4
_TF_DAYS = 5
_TF_WEEKS = 6
_TF_MONTHS = 7


class ExchangeConfig:
    """Centralized exchange configuration manager.
    
    Provides unified access to exchange-specific configurations including
    order type mappings, timeframe mappings, and custom parameters.
    """
    
    # Order type mappings per exchange
    # Key: exchange_id, Value: {bt_order_type: exchange_order_type}
    ORDER_TYPES: Dict[str, Dict[int, str]] = {
        'binance': {
            _ORDER_MARKET: 'market',
            _ORDER_LIMIT: 'limit',
            _ORDER_STOP: 'stop_market',
            _ORDER_STOPLIMIT: 'stop_limit',
            _ORDER_STOPTRAIL: 'trailing_stop_market',
        },
        'okx': {
            _ORDER_MARKET: 'market',
            _ORDER_LIMIT: 'limit',
            _ORDER_STOP: 'trigger',
            _ORDER_STOPLIMIT: 'oco',
        },
        'bybit': {
            _ORDER_MARKET: 'Market',
            _ORDER_LIMIT: 'Limit',
            _ORDER_STOP: 'Stop',
            _ORDER_STOPLIMIT: 'StopLimit',
        },
        'kraken': {
            _ORDER_MARKET: 'market',
            _ORDER_LIMIT: 'limit',
            _ORDER_STOP: 'stop-loss',
            _ORDER_STOPLIMIT: 'stop-loss-limit',
        },
        'coinbase': {
            _ORDER_MARKET: 'market',
            _ORDER_LIMIT: 'limit',
            _ORDER_STOP: 'stop',
            _ORDER_STOPLIMIT: 'stop_limit',
        },
        # Default fallback
        'default': {
            _ORDER_MARKET: 'market',
            _ORDER_LIMIT: 'limit',
            _ORDER_STOP: 'stop',
            _ORDER_STOPLIMIT: 'stop_limit',
        },
    }
    
    # Timeframe mappings per exchange
    # Key: exchange_id, Value: {(bt_timeframe, compression): exchange_timeframe}
    TIMEFRAMES: Dict[str, Dict[tuple, str]] = {
        'binance': {
            (_TF_MINUTES, 1): '1m',
            (_TF_MINUTES, 3): '3m',
            (_TF_MINUTES, 5): '5m',
            (_TF_MINUTES, 15): '15m',
            (_TF_MINUTES, 30): '30m',
            (_TF_MINUTES, 60): '1h',
            (_TF_MINUTES, 120): '2h',
            (_TF_MINUTES, 240): '4h',
            (_TF_MINUTES, 360): '6h',
            (_TF_MINUTES, 480): '8h',
            (_TF_MINUTES, 720): '12h',
            (_TF_DAYS, 1): '1d',
            (_TF_DAYS, 3): '3d',
            (_TF_WEEKS, 1): '1w',
            (_TF_MONTHS, 1): '1M',
        },
        'okx': {
            (_TF_MINUTES, 1): '1m',
            (_TF_MINUTES, 3): '3m',
            (_TF_MINUTES, 5): '5m',
            (_TF_MINUTES, 15): '15m',
            (_TF_MINUTES, 30): '30m',
            (_TF_MINUTES, 60): '1H',
            (_TF_MINUTES, 120): '2H',
            (_TF_MINUTES, 240): '4H',
            (_TF_MINUTES, 360): '6H',
            (_TF_MINUTES, 720): '12H',
            (_TF_DAYS, 1): '1D',
            (_TF_WEEKS, 1): '1W',
            (_TF_MONTHS, 1): '1M',
        },
        'bybit': {
            (_TF_MINUTES, 1): '1',
            (_TF_MINUTES, 3): '3',
            (_TF_MINUTES, 5): '5',
            (_TF_MINUTES, 15): '15',
            (_TF_MINUTES, 30): '30',
            (_TF_MINUTES, 60): '60',
            (_TF_MINUTES, 120): '120',
            (_TF_MINUTES, 240): '240',
            (_TF_MINUTES, 360): '360',
            (_TF_MINUTES, 720): '720',
            (_TF_DAYS, 1): 'D',
            (_TF_WEEKS, 1): 'W',
            (_TF_MONTHS, 1): 'M',
        },
        # Default fallback (CCXT standard)
        'default': {
            (_TF_MINUTES, 1): '1m',
            (_TF_MINUTES, 5): '5m',
            (_TF_MINUTES, 15): '15m',
            (_TF_MINUTES, 30): '30m',
            (_TF_MINUTES, 60): '1h',
            (_TF_MINUTES, 240): '4h',
            (_TF_DAYS, 1): '1d',
            (_TF_WEEKS, 1): '1w',
            (_TF_MONTHS, 1): '1M',
        },
    }
    
    # Exchange-specific parameters
    EXCHANGE_PARAMS: Dict[str, Dict[str, Any]] = {
        'binance': {
            'rateLimit': 1200,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',  # 'spot', 'future', 'margin'
                'adjustForTimeDifference': True,
                'recvWindow': 5000,
            },
        },
        'binanceusdm': {
            'rateLimit': 1200,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'future',
                'adjustForTimeDifference': True,
            },
        },
        'okx': {
            'rateLimit': 100,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            },
        },
        'bybit': {
            'rateLimit': 100,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'linear',  # 'spot', 'linear', 'inverse'
            },
        },
        'kraken': {
            'rateLimit': 3000,
            'enableRateLimit': True,
        },
        'coinbase': {
            'rateLimit': 100,
            'enableRateLimit': True,
        },
        'default': {
            'rateLimit': 1000,
            'enableRateLimit': True,
        },
    }
    
    # Fee structures (maker/taker in percentage)
    FEES: Dict[str, Dict[str, float]] = {
        'binance': {'maker': 0.1, 'taker': 0.1},
        'okx': {'maker': 0.08, 'taker': 0.1},
        'bybit': {'maker': 0.01, 'taker': 0.06},
        'kraken': {'maker': 0.16, 'taker': 0.26},
        'coinbase': {'maker': 0.4, 'taker': 0.6},
        'default': {'maker': 0.1, 'taker': 0.1},
    }
    
    @classmethod
    def get_order_type(cls, exchange: str, bt_type: int) -> str:
        """Get exchange-specific order type string.
        
        Args:
            exchange: Exchange ID.
            bt_type: Backtrader order type constant.
            
        Returns:
            Exchange-specific order type string.
        """
        exchange_types = cls.ORDER_TYPES.get(exchange, cls.ORDER_TYPES['default'])
        return exchange_types.get(bt_type, 'limit')
    
    @classmethod
    def get_timeframe(cls, exchange: str, bt_tf: tuple) -> str:
        """Get exchange-specific timeframe string.
        
        Args:
            exchange: Exchange ID.
            bt_tf: Tuple of (TimeFrame constant, compression).
            
        Returns:
            Exchange-specific timeframe string.
        """
        exchange_tfs = cls.TIMEFRAMES.get(exchange, cls.TIMEFRAMES['default'])
        return exchange_tfs.get(bt_tf, '1h')
    
    @classmethod
    def get_params(cls, exchange: str) -> dict:
        """Get exchange-specific configuration parameters.
        
        Args:
            exchange: Exchange ID.
            
        Returns:
            Configuration dictionary for the exchange.
        """
        return cls.EXCHANGE_PARAMS.get(exchange, cls.EXCHANGE_PARAMS['default']).copy()
    
    @classmethod
    def get_fees(cls, exchange: str) -> dict:
        """Get fee structure for an exchange.
        
        Args:
            exchange: Exchange ID.
            
        Returns:
            Dictionary with 'maker' and 'taker' fees.
        """
        return cls.FEES.get(exchange, cls.FEES['default']).copy()
    
    @classmethod
    def get_rate_limit(cls, exchange: str) -> int:
        """Get rate limit for an exchange.
        
        Args:
            exchange: Exchange ID.
            
        Returns:
            Requests per minute limit.
        """
        params = cls.get_params(exchange)
        return params.get('rateLimit', 1000)
    
    @classmethod
    def supports_order_type(cls, exchange: str, bt_type: int) -> bool:
        """Check if an exchange supports a specific order type.
        
        Args:
            exchange: Exchange ID.
            bt_type: Backtrader order type constant.
            
        Returns:
            True if the order type is supported.
        """
        exchange_types = cls.ORDER_TYPES.get(exchange, cls.ORDER_TYPES['default'])
        return bt_type in exchange_types
    
    @classmethod
    def get_supported_timeframes(cls, exchange: str) -> list:
        """Get list of supported timeframes for an exchange.
        
        Args:
            exchange: Exchange ID.
            
        Returns:
            List of (TimeFrame, compression) tuples.
        """
        exchange_tfs = cls.TIMEFRAMES.get(exchange, cls.TIMEFRAMES['default'])
        return list(exchange_tfs.keys())
    
    @classmethod
    def merge_config(cls, exchange: str, user_config: dict) -> dict:
        """Merge user config with exchange defaults.
        
        Args:
            exchange: Exchange ID.
            user_config: User-provided configuration.
            
        Returns:
            Merged configuration dictionary.
        """
        default_params = cls.get_params(exchange)
        
        # Deep merge for 'options' key
        if 'options' in default_params and 'options' in user_config:
            merged_options = {**default_params['options'], **user_config['options']}
            result = {**default_params, **user_config}
            result['options'] = merged_options
        else:
            result = {**default_params, **user_config}
        
        return result
