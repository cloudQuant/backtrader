#!/usr/bin/env python
"""Futu Broker Module - Futu OpenD broker implementation.

This module provides the FutuBroker for trading through Futu OpenD
for Hong Kong/US/A-Share stock trading.

Classes:
    FutuOrder: Futu-specific order implementation.
    FutuBroker: Broker implementation for Futu trading.

Example:
    >>> store = bt.stores.FutuStore(host='127.0.0.1', port=11111)
    >>> cerebro.setbroker(store.getbroker())

Note:
    Requires futu-api package: pip install futu-api
"""

import collections
from datetime import datetime

from ..broker import BrokerBase
from ..order import Order
from ..position import Position
from ..stores.futustore import FutuStore
from ..utils.py3 import queue


class FutuOrder(Order):
    """Futu-specific order implementation.
    
    Attributes:
        futu_order: Raw Futu order dictionary from the API.
        executed_fills: List of processed fill IDs.
    """
    
    def __init__(self, owner, data, exectype, side, amount, price, futu_order):
        """Initialize a FutuOrder instance.
        
        Args:
            owner: Strategy that owns this order.
            data: Data feed associated with this order.
            exectype: Order execution type.
            side: Order side ('buy' or 'sell').
            amount: Order quantity.
            price: Order price.
            futu_order: Raw order dict from Futu API.
        """
        self.owner = owner
        self.data = data
        self.exectype = exectype
        self.ordtype = self.Buy if side == 'buy' else self.Sell
        self.size = float(amount)
        self.price = float(price) if price else None
        self.futu_order = futu_order
        self.executed_fills = []
        super().__init__()


# Registration mechanism
def _register_futu_broker_class(broker_cls):
    """Register broker class with the store when module is loaded."""
    FutuStore.BrokerCls = broker_cls
    return broker_cls


@_register_futu_broker_class
class FutuBroker(BrokerBase):
    """Broker implementation for Futu OpenD.
    
    This class maps orders/positions from Futu to the internal API of backtrader.
    
    Attributes:
        store: FutuStore instance for API access.
        positions: Dictionary of positions by symbol.
        open_orders: List of open orders.
        notifs: Queue of order notifications.
    """
    
    order_types = {
        Order.Market: 'market',
        Order.Limit: 'limit',
        Order.Stop: 'stop',
        Order.StopLimit: 'stop_limit',
    }
    
    def __init__(self, debug=False, **kwargs):
        """Initialize FutuBroker.
        
        Args:
            debug: Enable debug output.
            **kwargs: Arguments passed to FutuStore.
        """
        super().__init__()
        
        self.store = FutuStore(**kwargs)
        self.debug = debug
        
        self.positions = collections.defaultdict(Position)
        self.notifs = queue.Queue()
        self.open_orders = []
        
        self.startingcash = self.store._cash
        self.startingvalue = self.store._value
        
        self._last_op_time = 0
    
    def start(self):
        """Start the broker and load existing positions."""
        super().start()
        
        # Load existing positions
        positions = self.store.get_positions()
        for p in positions:
            symbol = p['symbol']
            size = p['size']
            price = p['price']
            self.positions[symbol] = Position(size, price)
        
        if self.debug:
            print(f"FutuBroker started with {len(positions)} positions")
    
    def stop(self):
        """Stop the broker and close connections."""
        super().stop()
        self.store.stop()
    
    def get_balance(self):
        """Get and update account balance.
        
        Returns:
            tuple: (cash, value)
        """
        self.store.get_balance()
        self.cash = self.store._cash
        self.value = self.store._value
        return self.cash, self.value
    
    def getcash(self):
        """Get available cash.
        
        Returns:
            float: Available cash balance.
        """
        self.cash = self.store._cash
        return self.cash
    
    def getvalue(self, datas=None):
        """Get portfolio value.
        
        Args:
            datas: Unused, for API compatibility.
            
        Returns:
            float: Total portfolio value.
        """
        self.value = self.store._value
        return self.value
    
    def get_notification(self):
        """Get next order notification.
        
        Returns:
            Order or None: Next notification or None if empty.
        """
        try:
            return self.notifs.get(False)
        except queue.Empty:
            return None
    
    def notify(self, order):
        """Add order to notification queue.
        
        Args:
            order: Order to notify.
        """
        self.notifs.put(order)
    
    def getposition(self, data, clone=True):
        """Get position for a data feed.
        
        Args:
            data: Data feed.
            clone: If True, return a clone.
            
        Returns:
            Position: Position for the data feed.
        """
        pos = self.positions[data._dataname]
        if clone:
            pos = pos.clone()
        return pos
    
    def next(self):
        """Called each iteration to check order status."""
        if self.debug:
            pass
        
        # Rate limit: check every 3 seconds
        nts = datetime.now().timestamp()
        if nts - self._last_op_time < 3:
            return
        self._last_op_time = nts
        
        self._next()
    
    def _next(self):
        """Process open orders and check for fills."""
        for order in list(self.open_orders):
            if order.futu_order is None:
                continue
            
            order_id = order.futu_order.get('order_id')
            if not order_id:
                continue
            
            # Fetch order status
            futu_order = self.store.fetch_order(order_id)
            if futu_order is None:
                continue
            
            status = futu_order.get('order_status', '')
            filled_qty = float(futu_order.get('dealt_qty', 0))
            avg_price = float(futu_order.get('dealt_avg_price', 0))
            
            # Check for fills
            if filled_qty > abs(order.executed.size):
                new_fill_size = filled_qty - abs(order.executed.size)
                fill_size = new_fill_size if order.isbuy() else -new_fill_size
                fill_price = avg_price
                
                order.execute(
                    datetime.now(),
                    fill_size,
                    fill_price,
                    0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0.0, 0, 0.0
                )
                
                # Update position
                pos = self.getposition(order.data, clone=False)
                pos.update(fill_size, fill_price)
                
                # Mark order status
                if status in ['FILLED_ALL', 'FILLED_PART']:
                    if filled_qty >= order.size:
                        order.completed()
                    else:
                        order.partial()
                
                self.notify(order.clone())
            
            # Check if order is closed
            if status == 'FILLED_ALL':
                self.open_orders.remove(order)
            elif status in ['CANCELLED_ALL', 'CANCELLED_PART', 'FAILED']:
                order.cancel()
                self.notify(order.clone())
                self.open_orders.remove(order)
    
    def _submit(self, owner, data, exectype, side, amount, price, params):
        """Submit an order to Futu.
        
        Args:
            owner: Strategy submitting the order.
            data: Data feed for the order.
            exectype: Execution type.
            side: 'buy' or 'sell'.
            amount: Order quantity.
            price: Order price.
            params: Additional parameters.
            
        Returns:
            FutuOrder: Created order.
        """
        order_type = self.order_types.get(exectype, 'limit')
        
        # Create order on Futu
        ret_ord = self.store.create_order(
            symbol=data.p.dataname,
            order_type=order_type,
            side=side,
            amount=amount,
            price=price
        )
        
        order = FutuOrder(owner, data, exectype, side, amount, price, ret_ord)
        self.open_orders.append(order)
        self.notify(order.clone())
        self._next()
        
        return order
    
    def buy(self, owner, data, size, price=None, plimit=None,
            exectype=None, valid=None, tradeid=0, oco=None,
            trailamount=None, trailpercent=None, **kwargs):
        """Create a buy order.
        
        Args:
            owner: Strategy creating the order.
            data: Data feed.
            size: Order size.
            price: Order price.
            plimit: Price limit for stop-limit orders.
            exectype: Execution type.
            valid: Order validity.
            tradeid: Trade ID.
            oco: OCO order reference.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional parameters.
            
        Returns:
            FutuOrder: Created order.
        """
        kwargs.pop('parent', None)
        kwargs.pop('transmit', None)
        return self._submit(owner, data, exectype, 'buy', size, price, kwargs)
    
    def sell(self, owner, data, size, price=None, plimit=None,
             exectype=None, valid=None, tradeid=0, oco=None,
             trailamount=None, trailpercent=None, **kwargs):
        """Create a sell order.
        
        Args:
            owner: Strategy creating the order.
            data: Data feed.
            size: Order size.
            price: Order price.
            plimit: Price limit for stop-limit orders.
            exectype: Execution type.
            valid: Order validity.
            tradeid: Trade ID.
            oco: OCO order reference.
            trailamount: Trailing stop amount.
            trailpercent: Trailing stop percentage.
            **kwargs: Additional parameters.
            
        Returns:
            FutuOrder: Created order.
        """
        kwargs.pop('parent', None)
        kwargs.pop('transmit', None)
        return self._submit(owner, data, exectype, 'sell', size, price, kwargs)
    
    def cancel(self, order):
        """Cancel an order.
        
        Args:
            order: Order to cancel.
            
        Returns:
            FutuOrder: The order (potentially updated).
        """
        if order.futu_order is None:
            return order
        
        order_id = order.futu_order.get('order_id')
        if not order_id:
            return order
        
        # Check if already filled or cancelled
        futu_order = self.store.fetch_order(order_id)
        if futu_order:
            status = futu_order.get('order_status', '')
            if status in ['FILLED_ALL', 'CANCELLED_ALL', 'FAILED']:
                return order
        
        # Cancel the order
        self.store.cancel_order(order_id)
        self._next()
        
        return order
    
    def get_orders_open(self, safe=False):
        """Get all open orders.
        
        Args:
            safe: Unused, for API compatibility.
            
        Returns:
            list: List of open orders.
        """
        return self.open_orders
