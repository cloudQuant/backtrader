============
Installation
============

Requirements
------------

- Python 3.7 or higher
- NumPy >= 1.20.0

Optional Dependencies
~~~~~~~~~~~~~~~~~~~~~

- **matplotlib**: For plotting charts
- **pandas**: For DataFrame data feeds
- **pyfolio**: For advanced analytics
- **scipy**: For some statistical functions

Installation Methods
--------------------

From PyPI (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   pip install backtrader

From Source
~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/mementum/backtrader.git
   cd backtrader
   pip install -e .

With All Dependencies
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   pip install backtrader[plotting]

Development Installation
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/mementum/backtrader.git
   cd backtrader
   pip install -e ".[dev]"

Verification
------------

Verify your installation:

.. code-block:: python

   import backtrader as bt
   print(bt.__version__)

Quick Test
~~~~~~~~~~

.. code-block:: python

   import backtrader as bt
   
   cerebro = bt.Cerebro()
   print('Cerebro created successfully!')
