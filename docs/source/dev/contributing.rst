============
Contributing
============

Development Setup
-----------------

1. Clone the repository:

.. code-block:: bash

   git clone https://github.com/mementum/backtrader.git
   cd backtrader

2. Create virtual environment:

.. code-block:: bash

   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   # or
   venv\Scripts\activate  # Windows

3. Install development dependencies:

.. code-block:: bash

   pip install -e ".[dev]"

Code Style
----------

- Follow PEP 8 guidelines
- Use Google-style docstrings
- Maximum line length: 100 characters
- Use type hints where possible

Running Tests
-------------

.. code-block:: bash

   # Run all tests
   pytest
   
   # Run specific test
   pytest tests/test_strategy.py
   
   # Run with coverage
   pytest --cov=backtrader

Documentation
-------------

Build documentation:

.. code-block:: bash

   cd docs
   make html      # English
   make html-zh   # Chinese

Pull Request Guidelines
-----------------------

1. Fork the repository
2. Create a feature branch
3. Write tests for new features
4. Update documentation
5. Submit pull request

Commit Messages
~~~~~~~~~~~~~~~

Use conventional commit format:

- ``feat: Add new feature``
- ``fix: Fix bug``
- ``docs: Update documentation``
- ``test: Add tests``
- ``refactor: Code refactoring``
