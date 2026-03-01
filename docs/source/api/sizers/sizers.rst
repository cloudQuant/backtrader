======
Sizers
======

Sizers determine position sizes for orders.

.. automodule:: backtrader.sizers
   :members:
   :undoc-members:
   :show-inheritance:
   :no-index:

Overview
--------

Sizers calculate how many shares/contracts to trade based on portfolio value,
risk parameters, or custom logic.

Built-in Sizers
---------------

- ``FixedSize``: Fixed number of units
- ``FixedReverser``: Fixed size with position reversal
- ``PercentSizer``: Percentage of portfolio
- ``AllInSizer``: Use all available cash
- ``AllInSizerInt``: All-in with integer shares

Using Sizers
------------

.. code-block:: python

   cerebro = bt.Cerebro()
   
   # Fixed size sizer
   cerebro.addsizer(bt.sizers.FixedSize, stake=10)
   
   # Percentage sizer (10% of portfolio per trade)
   cerebro.addsizer(bt.sizers.PercentSizer, percents=10)
   
   # All-in sizer
   cerebro.addsizer(bt.sizers.AllInSizer)

Per-Strategy Sizer
------------------

.. code-block:: python

   cerebro.addstrategy(
       MyStrategy,
       sizer=bt.sizers.PercentSizer,
       sizer_percents=5
   )

Creating Custom Sizers
----------------------

.. code-block:: python

   class RiskSizer(bt.Sizer):
       params = (
           ('risk', 0.02),  # Risk 2% per trade
       )
       
       def _getsizing(self, comminfo, cash, data, isbuy):
           # Calculate position size based on risk
           risk_amount = cash * self.params.risk
           atr = self.strategy.atr[0]  # Assume ATR indicator exists
           
           if atr > 0:
               size = int(risk_amount / atr)
           else:
               size = 0
           
           return size
   
   # Use custom sizer
   cerebro.addsizer(RiskSizer, risk=0.01)
