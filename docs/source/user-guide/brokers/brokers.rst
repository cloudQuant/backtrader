===================
Brokers and Orders
===================

Backtrader provides a comprehensive broker simulation system that models real trading
conditions including commissions, slippage, margin, and various order types.

Broker Basics
-------------

The broker manages:

- **Cash**: Available trading capital
- **Value**: Total portfolio value (cash + positions)
- **Positions**: Current holdings
- **Orders**: Order management and execution

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Set initial cash
   cerebro.broker.setcash(100000)
   
   # Get current values
   cash = cerebro.broker.getcash()
   value = cerebro.broker.getvalue()

Commission Models
-----------------

Percentage Commission
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Simple percentage commission (0.1%)
   cerebro.broker.setcommission(commission=0.001)
   
   # Per-trade commission with percentage
   cerebro.broker.setcommission(
       commission=0.001,     # 0.1% per trade
       margin=None,          # No margin requirement
       mult=1.0              # Contract multiplier
   )

Fixed Commission
^^^^^^^^^^^^^^^^

.. code-block:: python

   # Fixed commission per trade
   class FixedCommission(bt.CommInfoBase):
       params = (
           ('commission', 5.0),      # $5 per trade
           ('stocklike', True),
           ('commtype', bt.CommInfoBase.COMM_FIXED),
       )
       
       def _getcommission(self, size, price, pseudoexec):
           return self.p.commission
   
   cerebro.broker.addcommissioninfo(FixedCommission())

Futures Commission
^^^^^^^^^^^^^^^^^^

.. code-block:: python

   # Futures with margin and multiplier
   cerebro.broker.setcommission(
       commission=2.0,       # $2 per contract
       margin=5000,          # Margin per contract
       mult=10,              # Contract multiplier
       commtype=bt.CommInfoBase.COMM_FIXED
   )

Slippage
--------

Slippage simulates the difference between expected and actual execution prices.

.. code-block:: python

   # Fixed slippage (price points)
   cerebro.broker.set_slippage_fixed(fixed=0.01)
   
   # Percentage slippage
   cerebro.broker.set_slippage_perc(perc=0.001)  # 0.1%
   
   # Volume-based slippage
   cerebro.broker.set_slippage_perc(
       perc=0.001,
       slip_open=True,       # Apply to open orders
       slip_limit=False,     # Don't apply to limit orders
       slip_match=True,      # Apply to matched orders
       slip_out=False        # Don't slip out of high/low range
   )

Order Types
-----------

Market Orders
^^^^^^^^^^^^^

Execute immediately at current market price.

.. code-block:: python

   # Buy at market
   self.buy()
   
   # Sell at market with size
   self.sell(size=100)

Limit Orders
^^^^^^^^^^^^

Execute at specified price or better.

.. code-block:: python

   # Buy limit order
   self.buy(exectype=bt.Order.Limit, price=100.0)
   
   # Sell limit order
   self.sell(exectype=bt.Order.Limit, price=110.0, size=50)

Stop Orders
^^^^^^^^^^^

Trigger when price reaches stop level.

.. code-block:: python

   # Stop buy (for short covering)
   self.buy(exectype=bt.Order.Stop, price=105.0)
   
   # Stop sell (stop loss)
   self.sell(exectype=bt.Order.Stop, price=95.0)

Stop-Limit Orders
^^^^^^^^^^^^^^^^^

Combination of stop and limit orders.

.. code-block:: python

   # Stop-limit order
   self.buy(
       exectype=bt.Order.StopLimit,
       price=105.0,      # Stop trigger price
       plimit=106.0      # Limit price after trigger
   )

Bracket Orders
^^^^^^^^^^^^^^

Entry with take-profit and stop-loss.

.. code-block:: python

   # Bracket order (entry + stop loss + take profit)
   orders = self.buy_bracket(
       price=100.0,          # Entry price (limit)
       stopprice=95.0,       # Stop loss price
       limitprice=110.0,     # Take profit price
       size=100
   )
   
   # Returns tuple: (main_order, stop_order, limit_order)

Target Orders
^^^^^^^^^^^^^

Automatically calculate order size to reach target.

.. code-block:: python

   # Target percent of portfolio value
   self.order_target_percent(target=0.5)  # 50% of portfolio
   
   # Target size
   self.order_target_size(target=100)     # Target 100 shares
   
   # Target value
   self.order_target_value(target=10000)  # Target $10,000 position

Order Management
----------------

Order Status
^^^^^^^^^^^^

.. code-block:: python

   def notify_order(self, order):
       if order.status in [order.Submitted, order.Accepted]:
           return  # Order pending
       
       if order.status == order.Completed:
           if order.isbuy():
               print(f'BUY executed at {order.executed.price:.2f}')
           else:
               print(f'SELL executed at {order.executed.price:.2f}')
       
       elif order.status == order.Canceled:
           print('Order canceled')
       elif order.status == order.Margin:
           print('Insufficient margin')
       elif order.status == order.Rejected:
           print('Order rejected')

Cancel Orders
^^^^^^^^^^^^^

.. code-block:: python

   # Cancel specific order
   self.cancel(order)
   
   # Cancel all pending orders
   for order in self.broker.get_orders_open():
       self.cancel(order)

Order Validity
^^^^^^^^^^^^^^

.. code-block:: python

   from datetime import datetime, timedelta
   
   # Good Till Date
   self.buy(
       exectype=bt.Order.Limit,
       price=100.0,
       valid=datetime.now() + timedelta(days=5)
   )
   
   # Good Till Canceled (default)
   self.buy(exectype=bt.Order.Limit, price=100.0, valid=None)
   
   # Day order
   self.buy(exectype=bt.Order.Limit, price=100.0, valid=bt.Order.DAY)

Position Management
-------------------

.. code-block:: python

   def next(self):
       # Check current position
       if self.position:
           print(f'Position size: {self.position.size}')
           print(f'Average price: {self.position.price}')
           print(f'Current P&L: {self.position.size * (self.data.close[0] - self.position.price)}')
       
       # Get position for specific data
       pos = self.getposition(self.datas[0])
       
       # Close all positions
       if self.position:
           self.close()

Margin and Leverage
-------------------

.. code-block:: python

   # Set leverage for futures
   cerebro.broker.setcommission(
       commission=0.0,
       margin=10000,         # Margin per contract
       mult=50,              # Contract multiplier (e.g., E-mini S&P)
       leverage=10.0         # Maximum leverage
   )
   
   # Check available margin
   def next(self):
       available_margin = self.broker.getcash()
       required_margin = self.broker.get_margin_info(self.data)

Cheat-On-Open / Cheat-On-Close
------------------------------

Special execution modes for backtesting convenience:

.. code-block:: python

   # Cheat-On-Open: Order placed at bar close, executed at next bar's open
   cerebro.broker.set_coo(True)
   
   # Cheat-On-Close: Order placed and executed at current bar's close
   # WARNING: Not realistic - used only for specific testing scenarios
   cerebro.broker.set_coc(True)

.. warning::
   Cheat-On-Close is not realistic and should only be used for testing specific
   scenarios where you need to simulate executing at the closing price.

Broker Methods Reference
------------------------

.. list-table::
   :widths: 35 65
   :header-rows: 1

   * - Method
     - Description
   * - ``set_cash(cash)``
     - Set initial capital
   * - ``get_cash()``
     - Get available cash
   * - ``get_value()``
     - Get total portfolio value
   * - ``getposition(data)``
     - Get position for a data feed
   * - ``get_orders_open()``
     - Get list of pending orders
   * - ``set_slippage_perc(perc)``
     - Set percentage slippage
   * - ``set_slippage_fixed(fixed)``
     - Set fixed slippage (points)
   * - ``setcommission(...)``
     - Set commission parameters
   * - ``set_coo(coo)``
     - Enable Cheat-On-Open
   * - ``set_coc(coc)``
     - Enable Cheat-On-Close
   * - ``add_cash(cash)``
     - Add or remove cash (negative value)

Best Practices
--------------

1. **Realistic Simulation**

   .. code-block:: python
   
      # Include all trading costs
      cerebro.broker.setcommission(commission=0.001)
      cerebro.broker.set_slippage_perc(perc=0.0005)

2. **Order Tracking**

   .. code-block:: python
   
      def __init__(self):
          self.order = None
      
      def next(self):
          if self.order:  # Check if order pending
              return
          # Trading logic here

3. **Risk Management**

   .. code-block:: python
   
      def next(self):
          # Check if we have enough cash
          if self.broker.getcash() < 1000:
              return
          
          # Position sizing
          size = int(self.broker.getvalue() * 0.02 / self.data.close[0])
          if size > 0:
              self.buy(size=size)

See Also
--------

- :doc:`strategies` - Strategy development
- :doc:`analyzers` - Performance analysis
- :doc:`live_trading` - Live trading setup
- `Blog: Broker使用方法 <https://yunjinqi.blog.csdn.net/article/details/113442367>`_
- `Blog: 滑点设置 <https://yunjinqi.blog.csdn.net/article/details/113446335>`_
- `Blog: 佣金设置 <https://yunjinqi.blog.csdn.net/article/details/113730323>`_
