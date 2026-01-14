======
Broker
======

The ``Broker`` class handles order execution and portfolio management.

.. automodule:: backtrader.broker
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

Overview
--------

The broker simulates or executes orders in live trading. It manages:

- Cash and portfolio value
- Order execution
- Commissions and slippage
- Position tracking
- Margin requirements

Default Broker
--------------

The default ``BackBroker`` provides:

- Simulated order execution
- Commission modeling
- Slippage simulation
- Margin/leverage support

Configuration
-------------

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Set initial cash
   cerebro.broker.setcash(100000)
   
   # Set commission
   cerebro.broker.setcommission(
       commission=0.001,      # 0.1% commission
       margin=None,           # No margin
       mult=1.0,              # Multiplier
   )
   
   # Set slippage
   cerebro.broker.set_slippage_perc(0.001)  # 0.1% slippage

Commission Schemes
------------------

.. code-block:: python

   # Percentage commission
   cerebro.broker.setcommission(commission=0.001)
   
   # Fixed commission per trade
   cerebro.broker.setcommission(
       commission=10,
       commtype=bt.CommInfoBase.COMM_FIXED
   )
   
   # Futures commission
   cerebro.broker.addcommissioninfo(
       bt.CommissionInfo(
           commission=2.0,
           margin=2000,
           mult=50
       ),
       name='ES'
   )

Accessing Broker in Strategy
----------------------------

.. code-block:: python

   class MyStrategy(bt.Strategy):
       def next(self):
           # Get current cash
           cash = self.broker.getcash()
           
           # Get portfolio value
           value = self.broker.getvalue()
           
           # Get position
           position = self.broker.getposition(self.data)
           
           # Check if we can buy
           if cash > self.data.close[0] * 100:
               self.buy(size=100)
