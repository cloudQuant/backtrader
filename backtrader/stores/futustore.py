#!/usr/bin/env python
"""Futu Store Module - Futu OpenD trading integration.

This module provides the FutuStore for connecting to Futu OpenD
for Hong Kong/US/A-Share stock trading.

Classes:
    FutuStore: Singleton store for Futu OpenD connections.

Example:
    >>> store = bt.stores.FutuStore(
    ...     host='127.0.0.1',
    ...     port=11111
    ... )
    >>> cerebro.setbroker(store.getbroker())

Note:
    Requires futu-api package: pip install futu-api
    And FutuOpenD running locally or accessible via network.
"""

import collections
from datetime import datetime
from time import sleep

from backtrader.mixins import ParameterizedSingletonMixin
from backtrader.utils.py3 import queue

# Try to import futu API
try:
    from futu import (
        OpenQuoteContext,
        OpenSecTradeContext,
        TrdMarket,
        TrdEnv,
        RET_OK,
        RET_ERROR,
        KLType,
        SubType,
        StockQuoteHandlerBase,
        OrderBookHandlerBase,
    )
    HAS_FUTU = True
except ImportError:
    HAS_FUTU = False
    OpenQuoteContext = None
    OpenSecTradeContext = None


class FutuQuoteHandler(StockQuoteHandlerBase if HAS_FUTU else object):
    """Handler for real-time stock quotes from Futu.
    
    Attributes:
        md_queue: Market data queue for distributing quote data.
    """
    
    def __init__(self, md_queue=None):
        if HAS_FUTU:
            super().__init__()
        self.md_queue = md_queue or {}
    
    def on_recv_rsp(self, rsp_str):
        """Handle received quote response.
        
        Args:
            rsp_str: Response string from Futu API.
            
        Returns:
            tuple: (ret_code, data) from API response.
        """
        if not HAS_FUTU:
            return RET_ERROR, None
        ret_code, data = super().on_recv_rsp(rsp_str)
        if ret_code != RET_OK:
            return RET_ERROR, data
        
        # Distribute data to corresponding queues
        for _, row in data.iterrows():
            code = row['code']
            if code in self.md_queue:
                self.md_queue[code].put(row.to_dict())
        
        return RET_OK, data


class FutuStore(ParameterizedSingletonMixin):
    """Singleton store for Futu OpenD connections.
    
    This class provides connection management and API access for Futu OpenD,
    supporting Hong Kong, US, and China A-Share markets.
    
    Attributes:
        host: Futu OpenD host address.
        port: Futu OpenD port number.
        trd_env: Trading environment (REAL or SIMULATE).
        market: Trading market (HK, US, CN, etc.).
        quote_ctx: Quote context for market data.
        trade_ctx: Trade context for order execution.
    """
    
    # Supported timeframes mapping
    _GRANULARITIES = {
        (4, 1): KLType.K_1M if HAS_FUTU else '1m',      # 1 minute
        (4, 5): KLType.K_5M if HAS_FUTU else '5m',      # 5 minutes
        (4, 15): KLType.K_15M if HAS_FUTU else '15m',   # 15 minutes
        (4, 30): KLType.K_30M if HAS_FUTU else '30m',   # 30 minutes
        (4, 60): KLType.K_60M if HAS_FUTU else '1h',    # 1 hour
        (5, 1): KLType.K_DAY if HAS_FUTU else '1d',     # 1 day
        (6, 1): KLType.K_WEEK if HAS_FUTU else '1w',    # 1 week
        (7, 1): KLType.K_MON if HAS_FUTU else '1M',     # 1 month
    }
    
    BrokerCls = None  # broker class will auto register
    DataCls = None    # data class will auto register
    
    @classmethod
    def getdata(cls, *args, **kwargs):
        """Returns `DataCls` with args, kwargs"""
        return cls.DataCls(*args, **kwargs)
    
    @classmethod
    def getbroker(cls, *args, **kwargs):
        """Returns broker with *args, **kwargs from registered `BrokerCls`"""
        return cls.BrokerCls(*args, **kwargs)
    
    def __init__(self, host='127.0.0.1', port=11111, trd_env=None, market=None,
                 password=None, debug=False, **kwargs):
        """Initialize the FutuStore instance.
        
        Args:
            host: Futu OpenD host address. Defaults to '127.0.0.1'.
            port: Futu OpenD port number. Defaults to 11111.
            trd_env: Trading environment. TrdEnv.REAL or TrdEnv.SIMULATE.
            market: Trading market. TrdMarket.HK, TrdMarket.US, etc.
            password: Trading password for unlocking trades.
            debug: Enable debug output.
            **kwargs: Additional keyword arguments.
        """
        super().__init__()
        
        if not HAS_FUTU:
            raise ImportError(
                "futu-api package is required for FutuStore. "
                "Install it with: pip install futu-api"
            )
        
        self.host = host
        self.port = port
        self.trd_env = trd_env or TrdEnv.SIMULATE
        self.market = market or TrdMarket.HK
        self.password = password
        self.debug = debug
        
        # Initialize values
        self._cash = 0.0
        self._value = 0.0
        
        # Market data queues for each feed
        self.q_feed_qlive = {}
        
        # Create contexts
        self.quote_ctx = OpenQuoteContext(host=host, port=port)
        self.trade_ctx = OpenSecTradeContext(host=host, port=port)
        
        # Set trading environment
        self.trade_ctx.set_trd_env(self.trd_env)
        
        # Unlock trade if password provided
        if password and self.trd_env == TrdEnv.REAL:
            ret, data = self.trade_ctx.unlock_trade(password)
            if ret != RET_OK:
                print(f"Warning: Failed to unlock trade: {data}")
        
        # Set up quote handler
        self.quote_handler = FutuQuoteHandler(md_queue=self.q_feed_qlive)
        self.quote_ctx.set_handler(self.quote_handler)
        
        # Get initial balance
        self.get_balance()
        
        if debug:
            print(f"FutuStore initialized: {host}:{port}, market={market}")
    
    def register(self, feed):
        """Register feed market data queue.
        
        Args:
            feed: Data feed to register.
            
        Returns:
            queue.Queue: Queue for the feed's market data.
        """
        self.q_feed_qlive[feed.p.dataname] = queue.Queue()
        return self.q_feed_qlive[feed.p.dataname]
    
    def subscribe(self, dataname, subtype=None):
        """Subscribe to market data for a symbol.
        
        Args:
            dataname: Symbol to subscribe to (e.g., 'HK.00700').
            subtype: Subscription type. Defaults to SubType.QUOTE.
            
        Returns:
            bool: True if subscription successful, False otherwise.
        """
        if subtype is None:
            subtype = [SubType.QUOTE, SubType.K_1M]
        
        ret, data = self.quote_ctx.subscribe([dataname], subtype)
        if ret != RET_OK:
            print(f"Failed to subscribe to {dataname}: {data}")
            return False
        
        if self.debug:
            print(f"Subscribed to {dataname}")
        return True
    
    def get_granularity(self, timeframe, compression):
        """Get Futu KLType for a timeframe/compression combination.
        
        Args:
            timeframe: Backtrader timeframe code.
            compression: Compression multiplier.
            
        Returns:
            KLType: Futu K-line type.
            
        Raises:
            ValueError: If timeframe/compression not supported.
        """
        kl_type = self._GRANULARITIES.get((timeframe, compression))
        if kl_type is None:
            raise ValueError(
                f"Unsupported timeframe/compression: {timeframe}/{compression}"
            )
        return kl_type
    
    def fetch_ohlcv(self, symbol, kl_type, start=None, end=None, limit=100):
        """Fetch OHLCV data from Futu.
        
        Args:
            symbol: Symbol to fetch (e.g., 'HK.00700').
            kl_type: K-line type (KLType.K_1M, KLType.K_DAY, etc.).
            start: Start date string (YYYY-MM-DD).
            end: End date string (YYYY-MM-DD).
            limit: Maximum number of bars to fetch.
            
        Returns:
            list: List of OHLCV data or empty list on error.
        """
        ret, data, _ = self.quote_ctx.request_history_kline(
            symbol,
            ktype=kl_type,
            start=start,
            end=end,
            max_count=limit
        )
        
        if ret != RET_OK:
            print(f"Failed to fetch OHLCV for {symbol}: {data}")
            return []
        
        # Convert to list of [timestamp, open, high, low, close, volume]
        result = []
        for _, row in data.iterrows():
            dt = datetime.strptime(row['time_key'], '%Y-%m-%d %H:%M:%S')
            timestamp = int(dt.timestamp() * 1000)
            result.append([
                timestamp,
                row['open'],
                row['high'],
                row['low'],
                row['close'],
                row['volume']
            ])
        
        return result
    
    def get_balance(self):
        """Get account balance from Futu.
        
        Updates internal _cash and _value attributes.
        """
        ret, data = self.trade_ctx.accinfo_query(trd_env=self.trd_env, market=self.market)
        if ret != RET_OK:
            print(f"Failed to get balance: {data}")
            return
        
        if len(data) > 0:
            self._cash = float(data['cash'][0]) if 'cash' in data.columns else 0.0
            self._value = float(data['total_assets'][0]) if 'total_assets' in data.columns else 0.0
        
        if self.debug:
            print(f"Balance: cash={self._cash}, value={self._value}")
    
    def get_positions(self):
        """Get current positions from Futu.
        
        Returns:
            list: List of position dictionaries.
        """
        ret, data = self.trade_ctx.position_list_query(
            trd_env=self.trd_env,
            market=self.market
        )
        
        if ret != RET_OK:
            print(f"Failed to get positions: {data}")
            return []
        
        positions = []
        for _, row in data.iterrows():
            positions.append({
                'symbol': row['code'],
                'size': row['qty'],
                'price': row['cost_price'],
                'market_value': row['market_val'],
                'pl': row['pl_val']
            })
        
        return positions
    
    def get_cash(self):
        """Get available cash.
        
        Returns:
            float: Available cash balance.
        """
        return self._cash
    
    def get_value(self):
        """Get total account value.
        
        Returns:
            float: Total account value.
        """
        return self._value
    
    def create_order(self, symbol, order_type, side, amount, price=None, **kwargs):
        """Create an order on Futu.
        
        Args:
            symbol: Symbol to trade.
            order_type: Order type string.
            side: 'buy' or 'sell'.
            amount: Order quantity.
            price: Order price (for limit orders).
            **kwargs: Additional order parameters.
            
        Returns:
            dict: Order information or None on error.
        """
        from futu import TrdSide, OrderType as FutuOrderType
        
        trd_side = TrdSide.BUY if side.lower() == 'buy' else TrdSide.SELL
        
        # Map order type
        if order_type == 'market':
            futu_order_type = FutuOrderType.MARKET
        else:
            futu_order_type = FutuOrderType.NORMAL
        
        ret, data = self.trade_ctx.place_order(
            price=price or 0,
            qty=amount,
            code=symbol,
            trd_side=trd_side,
            order_type=futu_order_type,
            trd_env=self.trd_env,
            **kwargs
        )
        
        if ret != RET_OK:
            print(f"Failed to create order: {data}")
            return None
        
        return data.to_dict('records')[0] if len(data) > 0 else None
    
    def cancel_order(self, order_id, **kwargs):
        """Cancel an order.
        
        Args:
            order_id: Order ID to cancel.
            **kwargs: Additional parameters.
            
        Returns:
            dict: Cancellation result or None on error.
        """
        ret, data = self.trade_ctx.modify_order(
            modify_order_op=2,  # Cancel
            order_id=order_id,
            qty=0,
            price=0,
            trd_env=self.trd_env
        )
        
        if ret != RET_OK:
            print(f"Failed to cancel order: {data}")
            return None
        
        return data.to_dict('records')[0] if len(data) > 0 else None
    
    def fetch_order(self, order_id):
        """Fetch order information.
        
        Args:
            order_id: Order ID to fetch.
            
        Returns:
            dict: Order information or None on error.
        """
        ret, data = self.trade_ctx.order_list_query(
            order_id=order_id,
            trd_env=self.trd_env
        )
        
        if ret != RET_OK:
            print(f"Failed to fetch order: {data}")
            return None
        
        return data.to_dict('records')[0] if len(data) > 0 else None
    
    def stop(self):
        """Stop and close all connections."""
        if self.quote_ctx:
            self.quote_ctx.close()
        if self.trade_ctx:
            self.trade_ctx.close()
