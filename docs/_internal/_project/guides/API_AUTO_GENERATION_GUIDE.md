# API Auto-Generation Guide

This guide explains how to automatically generate API documentation from Backtrader source code using Sphinx and related tools. It covers docstring conventions, type hints integration, cross-reference generation, and automated build pipelines.

## Table of Contents

1. [Overview](#overview)
2. [Tools and Frameworks](#tools-and-frameworks)
3. [Docstring Conventions](#docstring-conventions)
4. [Type Hints Integration](#type-hints-integration)
5. [Sphinx Configuration](#sphinx-configuration)
6. [AutoDoc Settings](#autodoc-settings)
7. [Generating API Docs](#generating-api-docs)
8. [Cross-Reference Generation](#cross-reference-generation)
9. [Automated Build Pipeline](#automated-build-pipeline)
10. [GitHub Actions Integration](#github-actions-integration)
11. [Example Configurations](#example-configurations)

- --

## Overview

API documentation for Backtrader is automatically generated from source code docstrings using Sphinx extensions. This approach ensures that documentation stays synchronized with the codebase and reduces manual maintenance overhead.

### Benefits

- **Single Source of Truth**: Documentation lives with the code
- **Type Safety**: Type hints are automatically extracted and displayed
- **Cross-References**: Automatic linking between related classes and methods
- **Multi-Language Support**: Support for both English and Chinese documentation
- **CI/CD Integration**: Automated builds on every commit

### Architecture

```mermaid
graph LR
    A[Source Code] --> B[Docstrings]
    B --> C[sphinx-apidoc]
    C --> D[RST Files]
    D --> E[sphinx-build]
    E --> F[HTML/PDF Docs]
    F --> G[GitHub Pages/RTD]

```bash

- --

## Tools and Frameworks

### Core Tools

| Tool | Version | Purpose |

|------|---------|---------|

| Sphinx | >= 5.0.0 | Documentation generator |

| sphinx-autodoc | bundled | Extract docstrings from Python modules |

| sphinx-autosummary | bundled | Generate summary tables |

| sphinx-napoleon | bundled | Parse Google/NumPy style docstrings |

| sphinx-ext-viewcode | bundled | Add source code links |

| sphinx-ext-intersphinx | bundled | Cross-project references |

| myst-parser | >= 2.0.0 | Markdown support |

| sphinx-copybutton | >= 0.5.0 | Copy button for code blocks |

| furo | >= 2023.1.1 | Modern HTML theme |

### Optional Tools

| Tool | Purpose |

|------|---------|

| sphinx-autobuild | Live reload during development |

| sphinx-intl | Internationalization support |

| sphinx-autodoc-typehints | Enhanced type hints display |

| sphinxcontrib-bibtex | Bibliography support |

### Installation

```bash

# Install documentation dependencies

pip install -r docs/requirements.txt

# Or install individually

pip install sphinx>=5.0.0
pip install sphinx-copybutton>=0.5.0
pip install furo>=2023.1.1
pip install sphinx-autobuild>=2021.3.14
pip install sphinx-intl>=2.0.0
pip install myst-parser>=2.0.0

```bash

- --

## Docstring Conventions

Backtrader supports both Google-style and NumPy-style docstrings via the Napoleon extension. Google-style is recommended for new code.

### Google-Style Docstrings

```python
class Indicator(LineIterator):
    """Base class for all technical indicators in Backtrader.

    This class provides the foundation for creating custom indicators.
    It manages line data, minimum periods, and calculation logic.

    Attributes:
        _ltype: Line type set to IndType (0) for indicators
        csv: Whether to output this indicator to CSV (default: False)
        aliased: Whether this indicator has an alias name

    Example:
        Create a simple moving average indicator::

            class SMA(bt.Indicator):
                lines = ('sma',)
                params = (('period', 14),)

                def __init__(self):
                    self.lines.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

                def next(self):
                    self.lines.sma[0] = sum(self.data.close.get(size=self.p.period)) / self.p.period

    Note:
        Indicators must register themselves with their owner's
        _lineiterators list during initialization.

    See Also:
        LineIterator: Base class for line iteration
        Observer: Base class for chart observers
    """

    def next(self):
        """Calculate the next value of the indicator.

        This method is called on each bar during backtesting.
        Subclasses must implement this method to define the
        indicator's calculation logic.

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        raise NotImplementedError

```bash

### NumPy-Style Docstrings

```python
class Cerebro(ParameterizedBase):
    """Main backtesting/trading engine.

    The Cerebro class orchestrates all components of a trading system
    including data feeds, strategies, brokers, and analyzers.

    Parameters

    - ---------

    preload : bool, optional
        Whether to preload data feeds into memory (default: True)
    runonce : bool, optional
        Use vectorized execution mode (default: True)
    maxcpu : int, optional
        Maximum number of CPU cores for optimization (default: None)

    Attributes

    - ---------

    datas : list
        List of data feeds added to cerebro
    strategies : list
        List of strategy instances
    brokers : BrokerBase
        Broker instance for order execution

    Examples

    - -------

    Basic backtest setup::

        cerebro = bt.Cerebro()
        data = bt.feeds.GenericCSVData(dataname='data.csv')
        cerebro.adddata(data)
        cerebro.addstrategy(MyStrategy)
        results = cerebro.run()

    Notes

    - ----

    Cerebro manages the entire backtesting lifecycle from data loading
    to strategy execution and result collection.

    See Also

    - -------

    Strategy : Base class for trading strategies
    Analyzer : Base class for performance analyzers
    """

```bash

### Docstring Sections

| Section | Purpose | Required |

|---------|---------|----------|

| Summary | One-line description | Yes |

| Extended Description | Detailed explanation | Recommended |

| Parameters | Function/method parameters | For functions with params |

| Attributes | Class attributes | For classes |

| Returns | Return value description | For functions that return |

| Raises | Exceptions that may be raised | When applicable |

| Examples | Usage examples | Highly recommended |

| Note | Important notes | Optional |

| Warning | Warnings about usage | Optional |

| See Also | Related classes/functions | Recommended |

| References | External references | Optional |

- --

## Type Hints Integration

Type hints are automatically extracted and displayed in the documentation using the `autodoc-typehints` extension.

### Basic Type Hints

```python
from typing import List, Optional, Dict, Union

def addstrategy(self, strategy, *args, **kwargs):
    """Add a strategy to the system.

    Args:
        strategy: Strategy class to add

        - args: Positional arguments for strategy
        - *kwargs: Keyword arguments for strategy

    Returns:
        Self for method chaining
    """
    pass

```bash

### Advanced Type Hints

```python
from typing import Type, TypeVar, Generic, Protocol
from dataclasses import dataclass

T = TypeVar('T')

class DataFeed(Protocol):
    """Protocol for data feed implementations."""

    def __getitem__(self, ago: int) -> 'LineSeries':
        """Get data from ago periods ago."""
        ...

@dataclass
class Order:
    """Represents a trading order.

    Attributes:
        order_id: Unique order identifier
        symbol: Trading symbol
        size: Order size (positive for buy, negative for sell)
        price: Limit price (None for market orders)
        status: Current order status
    """
    order_id: int
    symbol: str
    size: float
    price: Optional[float]
    status: Order.Status

```bash

### Type Hint Configuration

In `conf.py`:

```python

# How to display type hints

autodoc_typehints = 'description'  # 'description', 'signature', 'none'

autodoc_class_signature = 'separated'  # 'separated', 'full', 'hidden'

# Type aliases for better documentation

napoleon_type_aliases = {
    'sequence': 'typing.Sequence',
    'iterable': 'typing.Iterable',
    'array_like': 'numpy.typing.ArrayLike',
}

```bash

- --

## Sphinx Configuration

### Basic Configuration

The main Sphinx configuration is in `docs/source/conf.py`:

```python
"""Sphinx configuration for Backtrader documentation."""
import os
import sys
from datetime import datetime

# Add project root to path for autodoc

sys.path.insert(0, os.path.abspath('../..'))

# -- Project information -----------------------------------------------------

project = 'Backtrader'
copyright = f'{datetime.now().year}, Backtrader Contributors'
author = 'Backtrader Contributors'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',           # Auto-generate docs from docstrings
    'sphinx.ext.autosummary',       # Generate summary tables
    'sphinx.ext.viewcode',          # Add links to source code
    'sphinx.ext.napoleon',          # Support Google/NumPy docstrings
    'sphinx.ext.intersphinx',       # Link to other project docs
    'sphinx.ext.todo',              # Support TODO items
    'sphinx.ext.coverage',          # Check documentation coverage
    'sphinx.ext.inheritance_diagram',  # Generate inheritance diagrams
    'sphinx_copybutton',            # Copy button for code blocks
    'myst_parser',                 # Markdown support

]

```bash

### Napoleon Settings

```python

# Napoleon settings for Google/NumPy docstrings

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = True
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True

```bash

### Intersphinx Configuration

```python

# Link to external documentation

intersphinx_mapping = {
    'python': ('<https://docs.python.org/3',> None),
    'numpy': ('<https://numpy.org/doc/stable/',> None),
    'pandas': ('<https://pandas.pydata.org/docs/',> None),
    'matplotlib': ('<https://matplotlib.org/stable/',> None),
}

```bash

- --

## AutoDoc Settings

### Default Options

```python
autodoc_default_options = {
    'members': True,              # Document class members
    'member-order': 'bysource',   # Order by source appearance
    'special-members': '__init__',  # Include __init__ in docs
    'undoc-members': True,        # Include members without docstrings
    'exclude-members': '__weakref__,__dict__,__module__',  # Exclude these
    'show-inheritance': True,     # Show base classes
    'inherited-members': False,   # Don't show inherited members

}

# Type hints display

autodoc_typehints = 'description'  # Show types in parameter descriptions

autodoc_class_signature = 'separated'  # Separate class signature from docstring

```bash

### Skipping Dynamically Generated Classes

Backtrader uses dynamic class generation for Lines and Params. These should be skipped:

```python

# Patterns for dynamically generated classes to skip

_SKIP_PATTERNS = [
    'Lines_lines',  # Dynamically generated Lines classes
    'Params_',      # Dynamically generated Params classes
    '_lines',       # Internal lines attributes

]

def autodoc_skip_member(app, what, name, obj, skip, options):
    """Skip dynamically generated classes and internal members."""
    try:

# Skip private members (starting with _) except __init__
        if name.startswith('_') and name != '__init__':
            return True

# Skip dynamically generated classes with weird names
        obj_name = getattr(obj, '__name__', '')
        if obj_name is None:
            obj_name = type(obj).__name__

        for pattern in _SKIP_PATTERNS:
            if pattern in str(obj_name) or pattern in name:
                return True

# Skip classes with very long names (likely dynamically generated)
        if len(name) > 50:
            return True

        return skip
    except Exception:
        return skip

# Register the skip handler

def setup(app):
    """Custom Sphinx setup."""
    app.connect('autodoc-skip-member', autodoc_skip_member)

```bash

- --

## Generating API Docs

### Using sphinx-apidoc

```bash

# Generate API documentation from source code

cd docs
sphinx-apidoc -o source/api ../backtrader \

    - -force \
    - -module-first \
    - -implicit-namespaces \
    - -separate

# Options explained:

# --force: Overwrite existing files

# --module-first: Put module documentation before class documentation

# --implicit-namespaces: Use implicit namespace packages

# --separate: Create separate pages for each module

```bash

### Manual API Reference Files

For better control, create manual API reference files in `docs/source/api/`:

- *modules.rst:**

```rst
API Reference
=============

This section contains the API reference documentation for Backtrader.

.. toctree::
   :maxdepth: 4

   cerebro
   strategy
   indicators
   analyzers
   feeds
   brokers

```bash

- *cerebro.rst:**

```rst
Cerebro - Main Engine
=====================

.. automodule:: backtrader.cerebro
    :members:
    :undoc-members:
    :show-inheritance:

Cerebro Class

- ------------

.. autoclass:: backtrader.Cerebro
    :members:
    :undoc-members:
    :show-inheritance:
    :private-members:

OptReturn Class

- ---------------

.. autoclass:: backtrader.OptReturn
    :members:
    :undoc-members:

```bash

### Using autosummary

Generate summary tables for quick reference:

```rst
Indicators Summary
==================

.. currentmodule:: backtrader.indicators

.. autosummary::
   :toctree: _autosummary
   :nosignatures:
   :template: custom_class_template.rst

   SMA
   EMA
   RSI
   MACD
   BBands
   Stochastic

```bash

### Custom Templates

Create `docs/source/_templates/custom_class_template.rst`:

```jinja
{{ fullname }}
{{ underline }}

.. currentmodule:: {{ module }}

.. autoclass:: {{ objname }}
   :members:
   :show-inheritance:
   :undoc-members:

{% if methods %}
Methods

- ------

.. autosummary::
   :toctree:
   :nosignatures:

{% for method in methods %}
   {{ name }}.{{ method }}
{% endfor %}
{% endif %}

```bash

- --

## Cross-Reference Generation

### Internal References

Use Sphinx roles to create cross-references:

```rst
:py:class:`backtrader.Cerebro`
:py:meth:`backtrader.Cerebro.run`
:py:attr:`backtrader.Strategy.data`
:py:func:`backtrader.indicators.SMA`
:py:exc:`backtrader.errors.StrategyError`
:py:data:`backtrader.__version__`

```bash

### External References

Using intersphinx:

```rst
The strategy uses :class:`pandas.DataFrame` for data input.
Refer to :func:`numpy.array` for array operations.
See :meth:`matplotlib.pyplot.plot` for plotting options.

```bash

### Custom Cross-References

Define custom cross-reference targets:

```rst
.. _cerebro-api:

Cerebro API Documentation

- -------------------------

See the :ref:`cerebro-api` section for detailed information.

Link to indicator documentation: :ref:`indicators-index`

```bash

### Inheritance Diagrams

Generate class hierarchy diagrams:

```rst
.. inheritance-diagram:: backtrader.indicators.SMA
    :parts: 2

```bash

- --

## Automated Build Pipeline

### Makefile Integration

```makefile

# Documentation build targets

.PHONY: docs docs-live docs-clean docs-api

# Build all documentation (en + zh)

docs: docs-en docs-zh

# Build English documentation

docs-en:
    cd docs && sphinx-build -b html source build/html/en -D language=en

# Build Chinese documentation

docs-zh:
    cd docs && sphinx-build -b html source build/html/zh -D language=zh_CN

# Build with live reload

docs-live:
    cd docs && sphinx-autobuild source build/html/en --host 0.0.0.0 --port 8000

# Generate API docs from source

docs-api:
    cd docs && sphinx-apidoc -o source/api ../backtrader --force --module-first

# Clean build artifacts

docs-clean:
    rm -rf docs/build
    rm -rf docs/source/api

# View documentation

docs-view:
    open docs/build/html/en/index.html

```bash

### Pre-commit Hook

```bash

# .git/hooks/pre-commit

# !/bin/bash

# Build docs to check for errors

cd docs
sphinx-build -b html source build/html/check -W --keep-going

if [$? -ne 0]; then
    echo "Documentation build failed. Please fix docstring errors."
    exit 1
fi

exit 0

```bash

### Docstring Coverage

```bash

# Check documentation coverage

sphinx-build -b coverage source build/html/coverage

# View report

cat build/html/coverage/python.txt

```bash

- --

## GitHub Actions Integration

### Documentation Workflow

`.github/workflows/docs.yml`:

```yaml
name: Documentation

on:
  push:
    branches:

      - development
      - master

    paths:

      - 'docs/**'
      - 'backtrader/**'
      - '.github/workflows/docs.yml'

  pull_request:
    branches:

      - development
      - master

    paths:

      - 'docs/**'

  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:

      - name: Checkout

        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python

        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies

        run: |

          python -m pip install --upgrade pip
          pip install -r docs/requirements.txt
          pip install -e .

      - name: Regenerate API docs

        run: |

          cd docs
          sphinx-apidoc -o source/api ../backtrader --force --module-first

      - name: Build English documentation

        run: |

          cd docs
          sphinx-build -b html source build/html/en -D language=en -W

      - name: Build Chinese documentation

        run: |

          cd docs
          sphinx-build -b html source build/html/zh -D language=zh_CN

      - name: Create index redirect

        run: |

          cat > docs/build/html/index.html << 'EOF'
          <!DOCTYPE html>
          <html>
          <head>
            <meta charset="utf-8">
            <title>Backtrader Documentation</title>
            <meta http-equiv="refresh" content="0; url=en/index.html">
            <style>
              body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
              a { color: #007bff; text-decoration: none; margin: 0 20px; font-size: 18px; }
            </style>
          </head>
          <body>
            <h1>Backtrader Documentation</h1>
            <p>
              <a href="en/index.html">English</a> |

              <a href="zh/index.html">中文</a>
            </p>
          </body>
          </html>
          EOF

      - name: Upload artifact

        uses: actions/upload-pages-artifact@v3
        with:
          path: './docs/build/html'

  deploy:
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    runs-on: ubuntu-latest
    needs: build
    if: github.event_name == 'push' && (github.ref == 'refs/heads/development' || github.ref == 'refs/heads/master')

    steps:

      - name: Deploy to GitHub Pages

        id: deployment
        uses: actions/deploy-pages@v4

```bash

### Read the Docs Integration

`.readthedocs.yaml`:

```yaml

# .readthedocs.yaml

version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.11"
  jobs:
    post_create_environment:

      - pip install -r docs/requirements.txt

    post_install:

      - pip install -e .

sphinx:
  configuration: docs/source/conf.py

formats:

  - pdf
  - htmlzip

```bash

- --

## Example Configurations

### Complete conf.py

```python
"""Sphinx configuration for Backtrader documentation."""
import os
import sys
from datetime import datetime

# Add project root to path

sys.path.insert(0, os.path.abspath('../..'))

# -- Project information -----------------------------------------------------

project = 'Backtrader'
copyright = f'{datetime.now().year}, Backtrader Contributors'
author = 'Backtrader Contributors'

try:
    from backtrader.version import __version__
    version = __version__
    release = __version__
except ImportError:
    version = '0.1'
    release = '0.1'

# -- General configuration ---------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'sphinx.ext.todo',
    'sphinx.ext.coverage',
    'sphinx.ext.inheritance_diagram',
    'sphinx_copybutton',
    'myst_parser',
]

# MyST Parser

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "dollarmath",
    "fieldlist",
    "html_admonition",
    "html_image",
    "replacements",
    "smartquotes",
    "substitution",
    "tasklist",
]

# Autosummary

autosummary_generate = True
autosummary_imported_members = False
autosummary_generate_overwrite = False

# Autodoc

autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__,__dict__,__module__',
    'show-inheritance': True,
    'inherited-members': False,
}
autodoc_typehints = 'description'
autodoc_class_signature = 'separated'

# Skip patterns

_SKIP_PATTERNS = ['Lines_lines', 'Params_', '_lines']

def autodoc_skip_member(app, what, name, obj, skip, options):
    if name.startswith('_') and name != '__init__':
        return True
    obj_name = getattr(obj, '__name__', '')
    for pattern in _SKIP_PATTERNS:
        if pattern in str(obj_name) or pattern in name:
            return True
    if len(name) > 50:
        return True
    return skip

# Napoleon

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_use_param = True
napoleon_use_rtype = True

# Intersphinx

intersphinx_mapping = {
    'python': ('<https://docs.python.org/3',> None),
    'numpy': ('<https://numpy.org/doc/stable/',> None),
    'pandas': ('<https://pandas.pydata.org/docs/',> None),
}

# HTML Theme

html_theme = 'furo'
html_theme_options = {
    'light_css_variables': {
        'color-brand-primary': '#2962FF',
    },
    'navigation_with_keys': True,
    'source_repository': '<https://github.com/cloudQuant/backtrader/',>
    'source_branch': 'development',
}

# Static files

html_static_path = ['_static']
html_css_files = ['custom.css']

# Language

language = 'en'
on_rtd = os.environ.get('READTHEDOCS', None) == 'True'
rtd_language = os.environ.get('READTHEDOCS_LANGUAGE', 'en')

if rtd_language in ('zh', 'zh_CN', 'zh-cn'):
    language = 'zh_CN'
    master_doc = 'index_zh'
    html_title = f'{project} 中文文档'
else:
    language = 'en'
    html_title = f'{project} Documentation'

# Suppress warnings

suppress_warnings = [
    'ref.python',
    'autosummary',
    'autodoc.import_object',
]

def setup(app):
    app.add_css_file('custom.css')
    app.connect('autodoc-skip-member', autodoc_skip_member)

```bash

### requirements.txt

```txt

# Sphinx documentation dependencies

sphinx>=5.0.0
sphinx-copybutton>=0.5.0
furo>=2023.1.1
sphinx-autobuild>=2021.3.14
sphinx-intl>=2.0.0
myst-parser>=2.0.0

# Optional enhancements

sphinx-autodoc-typehints>=1.23.0
sphinxcontrib-apidoc>=0.3.0

```bash

- --

## Best Practices

### 1. Consistent Docstring Format

Choose one style (Google or NumPy) and use it consistently throughout the codebase.

### 2. Type Hints

Always include type hints for function parameters and return values. This improves IDE support and documentation quality.

### 3. Examples

Include usage examples in docstrings. These are automatically rendered in the documentation.

### 4. Cross-References

Use Sphinx roles to link to related classes, methods, and functions.

### 5. Keep it Current

Update docstrings when modifying code. The CI/CD pipeline will catch any docstring errors.

### 6. Module Documentation

Each module should have a module-level docstring explaining its purpose.

### 7. Private Members

Document private members (starting with `_`) if they are part of the public API or important for subclassing.

- --

## Troubleshooting

### Common Issues

- *Issue**: Autodoc can't import a module

- *Solution**: Ensure the module is in `sys.path` and can be imported. Check `conf.py` for correct path configuration.

- *Issue**: Type hints not showing

- *Solution**: Install `sphinx-autodoc-typehints` and add to extensions.

- *Issue**: Inheritance diagrams not rendering

- *Solution**: Install Graphiz: `apt-get install graphviz` (Linux) or `brew install graphviz` (macOS).

- *Issue**: Build warnings about missing references

- *Solution**: Add to `suppress_warnings` in `conf.py` or fix the references.

- --

## Additional Resources

- [Sphinx Documentation](<https://www.sphinx-doc.org/)>
- [Napoleon Extension](<https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html)>
- [sphinx-apidoc](<https://www.sphinx-doc.org/en/master/man/sphinx-apidoc.html)>
- [MyST Parser](<https://myst-parser.readthedocs.io/)>
- [Furo Theme](<https://pradyunsg.me/furo/)>
