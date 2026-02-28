============
Contributing
============

Thank you for your interest in contributing to Backtrader! This guide will help you get started.

Development Setup
-----------------

1. Fork and clone the repository:

.. code-block:: bash

   # Fork from https://github.com/cloudQuant/backtrader
   git clone https://github.com/YOUR_USERNAME/backtrader.git
   cd backtrader
   git remote add upstream https://github.com/cloudQuant/backtrader.git

2. Create virtual environment:

.. code-block:: bash

   # Create virtual environment
   python -m venv venv

   # Activate (Linux/Mac)
   source venv/bin/activate

   # Activate (Windows)
   venv\Scripts\activate

3. Install development dependencies:

.. code-block:: bash

   # Install package in development mode
   pip install -e .

   # Install development tools
   pip install pytest pytest-cov pytest-xdist
   pip install black ruff mypy
   pip install matplotlib plotly pandas

Code Style
----------

Following these style guidelines ensures code consistency and quality.

Line Length
~~~~~~~~~~~

Maximum line length: **124 characters**

.. code-block:: python

   # GOOD - Under 124 characters
   def calculate_indicator_value(self, period: int, data_series: pd.Series) -> float:
       return data_series.rolling(window=period).mean()

   # BAD - Too long
   def calculate_indicator_value(self, period: int, data_series: pd.Series, some_other_long_parameter_name: str) -> float:
       ...

Docstrings
~~~~~~~~~~

Use **Google-style** docstrings:

.. code-block:: python

   def calculate_sma(self, period: int) -> float:
       """Calculate Simple Moving Average.

       Args:
           period: Number of periods for the moving average.

       Returns:
           The SMA value.

       Raises:
           ValueError: If period is less than 1.
       """
       if period < 1:
           raise ValueError("Period must be at least 1")
       ...

Type Hints
~~~~~~~~~~

Use type hints for function signatures:

.. code-block:: python

   from typing import List, Optional, Dict, Any

   def process_data(data: List[float], threshold: Optional[float] = None) -> Dict[str, Any]:
       """Process data with optional threshold."""
       ...

Critical Rules
--------------

1. **NEVER introduce new metaclasses**
   Use the explicit ``donew()`` pattern instead.

.. code-block:: python

   # WRONG
   class MetaStrategy(type):
       pass

   class MyStrategy(bt.Strategy, metaclass=MetaStrategy):
       pass

   # CORRECT
   class MyStrategy(bt.Strategy):
       def __new__(cls, *args, **kwargs):
           _obj, args, kwargs = cls.donew(*args, **kwargs)
           return _obj

2. **ALWAYS call super().__init__() before accessing self.p**

.. code-block:: python

   # WRONG
   def __init__(self):
       period = self.p.period  # Error! self.p doesn't exist yet
       super().__init__()

   # CORRECT
   def __init__(self):
       super().__init__()
       period = self.p.period  # OK now

3. **Use specific exception handling**

.. code-block:: python

   # WRONG
   try:
       order = api.place_order(...)
   except Exception:
       pass  # Hides all errors

   # CORRECT
   try:
       order = api.place_order(...)
   except (NetworkError, ExchangeError) as e:
       logger.error(f"Order failed: {e}")
       raise

4. **Use SpdLogManager for logging**

.. code-block:: python

   # Import the logger
   from backtrader.utils.spdlog import SpdLogManager

   logger = SpdLogManager.get_logger(__name__)
   logger.info("Strategy started")

Running Tests
-------------

.. code-block:: bash

   # Run all tests
   pytest tests/ -n 4 -v

   # Run specific test module
   pytest tests/test_indicator.py -v

   # Run with coverage
   pytest tests/ --cov=backtrader --cov-report=term-missing

   # Run only fast tests (skip integration)
   pytest tests/ -m "not integration" -v

Test Organization
~~~~~~~~~~~~~~~~~

Tests are organized into:

* ``tests/original_tests/`` - Core functionality tests
* ``tests/add_tests/`` - Additional coverage tests
* ``tests/refactor_tests/`` - Post-metaclass removal tests
* ``tests/strategies/`` - Strategy-specific tests

Test Markers
~~~~~~~~~~~~

| Marker | Purpose |
|--------|---------|
| ``priority_p0`` | Core functionality |
| ``priority_p1`` | Core user journeys |
| ``priority_p2`` | Secondary features |
| ``priority_p3`` | Rarely used features |
| ``integration`` | Requires live connection |
| ``websocket`` | WebSocket-specific |
| ``trading`` | Sandbox order tests |

Submitting Changes
-----------------

1. Create a feature branch:

.. code-block:: bash

   git checkout -b feature/your-feature-name

2. Write tests:

.. code-block:: bash

   # Create test file
   touch tests/add_tests/test_your_feature.py

3. Make your changes:

.. code-block:: bash

   # Format code
   black backtrader/
   ruff check backtrader/

   # Run tests
   pytest tests/ -n 4 -v

4. Commit with conventional commit format:

.. code-block:: bash

   git commit -m "feat: add new indicator for volatility calculation"

   Commit types:
   * ``feat`` - New feature
   * ``fix`` - Bug fix
   * ``docs`` - Documentation
   * ``test`` - Tests
   * ``refactor`` - Code refactoring
   * ``perf`` - Performance improvement
   * ``style`` - Code style
   * ``chore`` - Maintenance

5. Push and create pull request:

.. code-block:: bash

   git push origin feature/your-feature-name

Documentation Updates
---------------------

When modifying code, update relevant documentation:

* New module → Update ``docs/project-structure.md``
* New parameters → Update relevant guide
* Architecture changes → Update ``docs/ARCHITECTURE.md``
* New features → Update user guide

Building Documentation
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # Build HTML documentation
   cd docs
   make html

   # Build Chinese documentation
   make html-zh

   # Serve locally for preview
   make live

Code Review Process
-------------------

All pull requests undergo review for:

1. **Functionality** - Does it work as intended?
2. **Code Quality** - Does it follow style guidelines?
3. **Test Coverage** - Are tests adequate?
4. **Documentation** - Is documentation updated?
5. **Performance** - Does it impact performance negatively?

Performance Guidelines
----------------------

* Minimize ``len()``, ``isinstance()``, ``hasattr()`` in hot paths
* Use vectorized operations where possible
* Profile before optimizing
* Document performance-critical sections

.. code-block:: python

   # GOOD - Cache length check
   def next(self):
       data_len = len(self.data)  # Cache
       if data_len > self.minperiod:
           # Your logic here

   # BAD - Repeated length checks
   def next(self):
       if len(self.data) > self.minperiod:
           if len(self.data) > 50:  # Redundant
               # Your logic here

Community Guidelines
--------------------

* Be respectful and constructive
* Focus on what is best for the community
* Show empathy towards other community members

Getting Help
------------

* `GitHub Issues <https://github.com/cloudQuant/backtrader/issues>`_ - Bug reports and feature requests
* `Author's Blog <https://yunjinqi.blog.csdn.net/>`_ - Tutorials and examples
* `Discussions <https://github.com/cloudQuant/backtrader/discussions>`_ - Questions and ideas

Thank you for contributing to Backtrader!
