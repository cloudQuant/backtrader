============
Installation
============

This guide covers how to install Backtrader and configure your environment
for optimal performance.

Requirements
------------

- **Python**: 3.9+ (3.11+ recommended for ~15% performance boost)
- **Operating System**: Windows / macOS / Linux
- **Memory**: 4GB+ recommended

Core Dependencies
~~~~~~~~~~~~~~~~~

- **NumPy** >= 1.20.0
- **python-dateutil**

Optional Dependencies
~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: 20 80
   :header-rows: 1

   * - Package
     - Purpose
   * - matplotlib
     - Static chart plotting
   * - plotly
     - Interactive HTML charts (recommended)
   * - bokeh
     - Real-time chart updates
   * - pandas
     - DataFrame data feeds
   * - scipy
     - Statistical functions
   * - ib_insync
     - Interactive Brokers integration
   * - ccxt
     - Cryptocurrency exchange integration

Installation Methods
--------------------

From GitHub (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~

This is the recommended method to get the latest optimized version:

.. code-block:: bash

   # Clone from GitHub
   git clone https://github.com/cloudQuant/backtrader.git
   cd backtrader
   
   # Install dependencies
   pip install -r requirements.txt
   
   # Install backtrader in development mode
   pip install -e .

From Gitee (China)
~~~~~~~~~~~~~~~~~~

For users in China, use the Gitee mirror for faster download:

.. code-block:: bash

   git clone https://gitee.com/yunjinqi/backtrader.git
   cd backtrader
   pip install -r requirements.txt
   pip install -e .

With Visualization Support
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Install with all plotting backends
   pip install matplotlib plotly bokeh

With Live Trading Support
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # For Interactive Brokers
   pip install ib_insync
   
   # For cryptocurrency exchanges
   pip install ccxt

Virtual Environment (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using a virtual environment prevents conflicts:

.. code-block:: bash

   # Create virtual environment
   python -m venv bt_env
   
   # Activate (Linux/Mac)
   source bt_env/bin/activate
   
   # Activate (Windows)
   bt_env\Scripts\activate
   
   # Install backtrader
   pip install -e .

Performance Optimization
------------------------

Python 3.11+
~~~~~~~~~~~~

Using Python 3.11+ provides approximately 15-20% speed improvement:

.. code-block:: bash

   # Check your Python version
   python --version
   
   # If needed, install Python 3.11+
   # Then run your strategy
   python3.11 your_strategy.py

Cython Acceleration
~~~~~~~~~~~~~~~~~~~

For maximum performance, compile Cython extensions:

.. code-block:: bash

   # Install Cython
   pip install cython
   
   # Compile extensions (if available)
   python setup.py build_ext --inplace

Verification
------------

Verify your installation:

.. code-block:: python

   import backtrader as bt
   print(f"Backtrader version: {bt.__version__}")

Quick Test
~~~~~~~~~~

.. code-block:: python

   import backtrader as bt
   
   # Create engine
   cerebro = bt.Cerebro()
   cerebro.broker.setcash(100000)
   
   print(f'Starting portfolio value: {cerebro.broker.getvalue():.2f}')
   cerebro.run()
   print(f'Final portfolio value: {cerebro.broker.getvalue():.2f}')
   print('Installation successful!')

Run Tests
~~~~~~~~~

To verify everything works correctly:

.. code-block:: bash

   # Run test suite
   pytest ./tests -n 4 -v

Troubleshooting
---------------

Common Issues
~~~~~~~~~~~~~

**Import Error: No module named 'backtrader'**

.. code-block:: bash

   # Ensure you're in the correct environment
   pip install -e .

**Matplotlib backend issues**

.. code-block:: python

   import matplotlib
   matplotlib.use('Agg')  # For headless environments

**Memory errors with large datasets**

.. code-block:: python

   cerebro = bt.Cerebro(
       exactbars=True,   # Minimize memory usage
       stdstats=False    # Disable observers
   )

TA-Lib Installation
-------------------

For TA-Lib indicator support:

**macOS:**

.. code-block:: bash

   brew install ta-lib
   pip install TA-Lib

**Linux (Ubuntu/Debian):**

.. code-block:: bash

   sudo apt-get install ta-lib
   pip install TA-Lib

**Windows:**

Download pre-built wheel from https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib

.. code-block:: bash

   pip install TA_Lib‑0.4.24‑cp311‑cp311‑win_amd64.whl

Next Steps
----------

- :doc:`quickstart` - Your first strategy
- :doc:`concepts` - Core concepts
- :doc:`data_feeds` - Loading data

See Also
--------

- `Blog: 安装方法 <https://yunjinqi.blog.csdn.net/article/details/107594251>`_
- `GitHub Repository <https://github.com/cloudQuant/backtrader>`_
- `Gitee Mirror (中国) <https://gitee.com/yunjinqi/backtrader>`_
