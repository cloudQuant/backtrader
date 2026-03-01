# Sphinx/RST Conversion Guide for Backtrader Documentation

> Version: 1.0
> Last Updated: 2026-03-01
> Status: Active

## Table of Contents

1. [Overview](#overview)
2. [Current Documentation Structure](#current-documentation-structure)
3. [Sphinx/RST Benefits for ReadTheDocs](#sphinxrst-benefits-for-readthedocs)
4. [Conversion Strategy and Tools](#conversion-strategy-and-tools)
5. [RST Syntax Guide for Backtrader Docs](#rst-syntax-guide-for-backtrader-docs)
6. [MyST Parser Integration](#myst-parser-integration)
7. [Automated Conversion Workflow](#automated-conversion-workflow)
8. [ReadTheDocs Deployment](#readthedocs-deployment)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

- --

## Overview

This guide explains how to convert the existing Markdown documentation to Sphinx/RST format for better integration with ReadTheDocs (RTD). The Backtrader project currently maintains documentation in two formats:

- **Markdown** (`docs/*.md`, `docs/user_guide/*.md`, etc.) - Used for content authoring
- **RST** (`docs/source/*.rst`, `docs/source/user_guide/*.rst`) - Used for Sphinx builds

The conversion process leverages MyST Parser to support both Markdown and RST content, allowing for gradual migration.

- --

## Current Documentation Structure

```bash
docs/
├── source/                          # Sphinx/RST source files

│   ├── conf.py                      # Sphinx configuration

│   ├── index.rst                    # English index

│   ├── index_zh.rst                 # Chinese index

│   ├── user_guide/                  # User guide RST files

│   │   ├── installation.rst
│   │   ├── quickstart.rst
│   │   ├── concepts.rst
│   │   ├── data_feeds.rst
│   │   ├── indicators.rst
│   │   ├── strategies.rst
│   │   ├── brokers.rst
│   │   ├── analyzers.rst
│   │   ├── optimization.rst
│   │   ├── visualization.rst
│   │   ├── live_trading.rst
│   │   ├── performance.rst
│   │   └── faq.rst
│   ├── api/                         # Auto-generated API docs

│   ├── dev/                         # Development docs (EN)

│   ├── dev_zh/                      # Development docs (ZH)

│   ├── locales/                     # Translation files

│   └── _static/                     # Static assets

├── user_guide/                      # Markdown versions (for reference)

├── api_reference/                   # Markdown API reference

├── architecture/                    # Markdown architecture docs

├── advanced/                        # Markdown advanced topics

├── examples/                        # Markdown examples

├── tutorials/                       # Markdown tutorials

├── developer_guide/                 # Markdown developer docs

├── migration/                       # Markdown migration guides

├── support/                         # Markdown support docs

├── index.md                         # Main documentation index

├── Makefile                         # Build commands

├── requirements.txt                 # Documentation dependencies

└── .readthedocs.yaml               # RTD configuration

```bash

### Key Files

| File | Purpose |

|------|---------|

| `docs/source/conf.py` | Main Sphinx configuration with MyST support |

| `docs/Makefile` | Build automation for multiple languages |

| `docs/requirements.txt` | Python dependencies for documentation |

| `docs/.readthedocs.yaml` | RTD build configuration |

- --

## Sphinx/RST Benefits for ReadTheDocs

### Why Sphinx?

1. **Auto-Documentation**: Generate API docs directly from source code docstrings
2. **Cross-References**: Sophisticated internal and external linking system
3. **Multi-Format Output**: HTML, PDF, EPub from single source
4. **Internationalization**: Built-in support for translations
5. **Extensibility**: Rich ecosystem of extensions
6. **Search**: Built-in full-text search with JavaScript
7. **Code Highlighting**: Automatic syntax detection and highlighting

### Why RST over Markdown?

| Feature | RST | Markdown |

|---------|-----|----------|

| Sphinx Integration | Native | Requires MyST |

| Auto-Doc Directives | Built-in | Limited |

| Cross-References | `:ref:`, `:doc:` | Manual links |

| Figures/Tables | Advanced directives | Basic HTML |

| Admonitions | `.. note::` etc. | HTML blocks |

| Metadata | Standard | Frontmatter only |

| Extensions | 100+ available | Limited |

### ReadTheDocs Advantages

- **Free hosting**for open source projects
- **Automatic builds**on git push
- **Versioned docs**for multiple branches/tags
- **Analytics**for user engagement
- **Custom domains**support
- **PDF generation**on demand
- **Search indexing**by major search engines

- --

## Conversion Strategy and Tools

### Conversion Approach

The Backtrader project uses a**hybrid approach** with MyST Parser:

```bash
┌─────────────────────────────────────────────────────────────┐
│                    Documentation Sources                     │
├─────────────────────────────────────────────────────────────┤
│  Markdown files (.md) ────────┐                            │
│                                ├──► MyST Parser ──► Sphinx  │
│  RST files (.rst) ────────────┘                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   Sphinx Build  │
                    └─────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  HTML / PDF     │
                    │  Documentation  │
                    └─────────────────┘

```bash

### Recommended Tools

| Tool | Purpose | Installation |

|------|---------|--------------|

| `pandoc` | Universal document converter | `brew install pandoc` |

| `sphinx-build` | Sphinx build command | `pip install sphinx` |

| `sphinx-apidoc` | Auto-generate API docs | Included with Sphinx |

| `myst-parser` | Markdown support in Sphinx | `pip install myst-parser` |

| `sphinx-intl` | Translation management | `pip install sphinx-intl` |

### Conversion Methods

#### Method 1: Using Pandoc (Recommended for New Files)

```bash

# Convert Markdown to RST

pandoc -f markdown -t rst input.md -o output.rst

# Convert entire directory

for file in *.md; do
    pandoc -f markdown -t rst "$file" -o "${file%.md}.rst"
done

```bash

#### Method 2: Using MyST Parser (Keep as Markdown)

Configure MyST Parser to parse Markdown directly. No conversion needed - just ensure proper frontmatter and syntax.

#### Method 3: Manual Conversion (For Complex Documents)

For documents with:

- Complex tables
- Nested code blocks
- Special directives
- Cross-references

Manual conversion ensures highest quality.

- --

## RST Syntax Guide for Backtrader Docs

### Markdown to RST Mapping Table

| Markdown | RST Equivalent | Notes |

|----------|----------------|-------|

| `# Heading` | `=====\nHeading\n=====` | Underline length matches title |

| `## Subheading` | `Subheading\n-----------` | |

| `**bold**` | `**bold**` | Same syntax |

| `*italic*` | `*italic*` | Same syntax |

| `` `code` `` | ``` ``code`` ``` | |

| ```python\ncode\n``` | `.. code-block:: python` | |

| `[text](url)` | `` `text <url>`_ `` | |

| `![alt](img.png)` | `.. image:: img.png` | |

| `- item` | `* item` | Bullet lists |

| `1. item` | `#. item` | Enumerated lists |

| `> quote` | `.. note::` or block quote | Use admonitions |

### RST Directives for Backtrader

#### Code Blocks

```rst
.. code-block:: python
   :linenos:
   :emphasize-lines: 3,5

   import backtrader as bt

   class MyStrategy(bt.Strategy):
       def next(self):
           self.buy()

```bash

#### Admonitions

```rst
.. note::
   This is an important note for users.

.. warning::
   Be careful with live trading!

.. tip::
   Use the runonce mode for faster backtesting.

.. danger::
   Never use real money without proper testing!

.. code-block:: python

# Code inside admonition
   cerebro.run()

```bash

#### Figures and Images

```rst
.. image:: images/architecture.png
   :alt: System Architecture
   :align: center
   :width: 800px

Figure: The Backtrader architecture overview

```bash

#### Tables

```rst
.. list-table:: Data Feed Options
   :widths: 25 50 25
   :header-rows: 1

   - - Feed Type
     - Description
     - Live Support
   - - CSV
     - Load data from CSV files
     - No
   - - Pandas
     - Use pandas DataFrames
     - No
   - - CCXT
     - Cryptocurrency exchanges
     - Yes
   - - CTP
     - Chinese futures market
     - Yes

```bash

#### Cross-References

```rst

# Reference to another document

See :doc:`installation` for setup instructions.

# Reference to a section within document

See :ref:`cerebro-configuration` for details.

# Reference to external documentation

Python's `datetime module <https://docs.python.org/3/library/datetime.html>`_

# Reference to API documentation

:class:`bt.Strategy` provides the base for all strategies.

# Reference to another project's docs

:py:class:`pandas.DataFrame`

```bash

#### Including Code Files

```rst
.. literalinclude:: ../../examples/simple_strategy.py
   :language: python
   :lines: 1-30
   :emphasize-lines: 10-15

```bash

### Document Structure Template

```rst
.. _document-reference-label:

=====================
Document Title
=====================

:Author: Backtrader Contributors
:Date: 2026-03-01

.. contents:: Table of Contents
   :depth: 2
   :local:

Introduction
============

Paragraph text with **bold** and *italic*text.

Section

- ------

Subsection
~~~~~~~~~~

.. code-block:: python

# Code example here
   import backtrader as bt

.. note::

   Important information here.

.. toctree::
   :maxdepth: 2

   related-page1
   related-page2

```bash

- --

## MyST Parser Integration

MyST (Markedly Structured Text) Parser allows Markdown to be used directly in Sphinx with support for RST directives.

### Configuration in conf.py

```python
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.autosummary',
    'sphinx.ext.viewcode',
    'sphinx.ext.napoleon',
    'sphinx.ext.intersphinx',
    'myst_parser',  # Enable Markdown support

]

myst_enable_extensions = [
    "colon_fence",      # Allow ::: for directives
    "deflist",          # Definition lists
    "dollarmath",       # $...$ for math
    "fieldlist",        # Field lists
    "html_admonition",  # HTML admonitions
    "html_image",       # HTML images
    "replacements",     # Text replacements
    "smartquotes",      # Smart quote conversion
    "substitution",     # Substitutions
    "tasklist",         # GitHub-style task lists

]

# Allow parsing of Markdown files in any directory

myst_parser_silent_implicit_level = True

```bash

### MyST Syntax Examples

#### Using RST Directives in Markdown

````markdown

```{note}
This is a note using MyST syntax in Markdown!

```bash

````

#### Cross-References in Markdown

```markdown
See [Installation Guide](installation.md) for setup.

Or use explicit syntax: {doc}`installation`

```bash

#### Code Blocks with Options

````markdown

```{code-block} python
:linenos:
:emphasize-lines: 3

import backtrader as bt

class MyStrategy(bt.Strategy):
    def next(self):  # This line is emphasized
        self.buy()

```bash

````

#### Figures in Markdown

```markdown

```{image} images/architecture.png
:alt: System Architecture
:align: center
:width: 800px

```bash

```bash

### MyST-Specific Features

| Feature | Syntax | Output |

|---------|--------|--------|

| Role | `{py:class}`\`bt.Strategy\` | `bt.Strategy` link |

| Directive | `:::{note}` ... `:::` | Note block |

| Target | `(my-target)=` | Reference target |

| Citations | `[citation-key]` | Footnote citation |

- --

## Automated Conversion Workflow

### Build Commands

```bash

# Build English HTML documentation

make html

# Build Chinese HTML documentation

make html-zh

# Build both languages

make html-all

# Generate translation templates

make gettext

# Update translation files

make update-po

# Clean build directory

make clean

# Live reload server for development

make livehtml

# Build PDF documentation

make pdf

# Generate API documentation from source

make apidoc

```bash

### sphinx-build Commands

```bash

# Basic build

sphinx-build -b html source build/html

# Build with specific language

sphinx-build -b html source build/html -D language=zh_CN

# Build with warnings as errors

sphinx-build -b html -W source build/html

# Build with nitpicky mode (strict references)

sphinx-build -b html -n --nitpicky source build/html

# Verbose output

sphinx-build -b html -v source build/html

# Parallel build (faster for large docs)

sphinx-build -b html -j auto source build/html

```bash

### conf.py Configuration Options

```python

# Project information

project = 'Backtrader'
copyright = '2026, Backtrader Contributors'
author = 'Backtrader Contributors'

# Version info

version = '0.1'     # Short version

release = '0.1.0'   # Full version

# Language

language = 'en'     # or 'zh_CN' for Chinese

# Extensions

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

# Autodoc settings

autodoc_default_options = {
    'members': True,
    'member-order': 'bysource',
    'special-members': '__init__',
    'undoc-members': True,
    'exclude-members': '__weakref__,__dict__,__module__',
    'show-inheritance': True,
    'inherited-members': False,
}

# HTML theme

html_theme = 'furo'
html_title = 'Backtrader Documentation'
html_short_title = 'Backtrader'

# Theme options

html_theme_options = {
    'light_css_variables': {
        'color-brand-primary': '#2962FF',
    },
    'sidebar_hide_name': False,
    'navigation_with_keys': True,
}

# Static files

html_static_path = ['_static']
html_css_files = ['custom.css']

```bash

### Auto-Documentation from Docstrings

The project uses `sphinx.ext.autodoc` to generate API documentation:

```rst
.. _cerebro-api:

Cerebro API Reference
=====================

.. autoclass:: backtrader.Cerebro
   :members:
   :undoc-members:
   :show-inheritance:

   .. autoattribute:: Cerebro.strats
   .. automethod:: Cerebro.run
   .. automethod:: Cerebro.addstrategy

```bash

### Google-Style Docstrings

```python
class Cerebro(object):
    """The backtesting engine.

    Cerebro is the main engine that coordinates all components
    in a backtesting scenario.

    Attributes:
        strats (list): List of strategy instances
        datas (list): List of data feeds
        brokers (Broker): Broker instance for order execution

    Examples:
        Create a simple backtest:

        >>> cerebro = bt.Cerebro()
        >>> data = bt.feeds.YahooFinanceData(dataname='AAPL')
        >>> cerebro.adddata(data)
        >>> cerebro.run()

    Args:
        preload (bool): Preload data feeds in memory
        runonce (bool): Run in vectorized mode (faster)
        maxcpu (int): Maximum CPU cores for optimization
    """

    def addstrategy(self, strategy,*args, **kwargs):
        """Add a strategy to the system.

        Args:
            strategy (Strategy): Strategy class to add

            - args: Positional arguments for strategy
            - *kwargs: Keyword arguments for strategy parameters

        Returns:
            Strategy: The strategy instance
        """
        pass

```bash

- --

## ReadTheDocs Deployment

### RTD Configuration File

`.readthedocs.yaml` (English project):

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.10"
  commands:

    - cd docs
    - pip install -r requirements.txt
    - sphinx-build -b html source build/html

sphinx:
  configuration: docs/source/conf.py
  fail_on_warning: false

formats:

  - pdf
  - htmlzip

```bash
`.readthedocs-zh.yaml` (Chinese project):

```yaml
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.10"
  commands:

    - cd docs
    - pip install -r requirements.txt
    - sphinx-build -b html source build/html -D language=zh_CN

sphinx:
  configuration: docs/source/conf.py
  fail_on_warning: false

formats:

  - pdf
  - htmlzip

```bash

### Deployment Workflow

```mermaid
graph LR
    A[Push to Git] --> B[RTD Webhook]
    B --> C[Build Triggered]
    C --> D[Install Dependencies]
    D --> E[Sphinx Build]
    E --> F[Generate HTML/PDF]
    F --> G[Deploy to CDN]
    G --> H[Available Online]

```bash

### Environment Variables

| Variable | Description | Default |

|----------|-------------|---------|

| `READTHEDOCS` | True if building on RTD | `False` |

| `READTHEDOCS_LANGUAGE` | Project language code | `en` |

| `READTHEDOCS_VERSION` | Current version being built | `latest` |

### Language Switcher

The `conf.py` automatically detects the language and sets the appropriate index:

```python
on_rtd = os.environ.get('READTHEDOCS', None) == 'True'
rtd_language = os.environ.get('READTHEDOCS_LANGUAGE', 'en')

if rtd_language in ('zh', 'zh_CN', 'zh-cn'):
    language = 'zh_CN'
    master_doc = 'index_zh'
    html_title = f'{project} 中文文档'
else:
    language = 'en'
    html_title = f'{project} Documentation'

```bash

### URL Structure

| Language | URL Pattern |

|----------|-------------|

| English | `<https://backtrader.readthedocs.io/en/latest/`> |

| Chinese | `<https://backtrader-zh.readthedocs.io/zh-cn/latest/`> |

- --

## Best Practices

### File Naming Conventions

- Use lowercase with underscores: `quick_start.rst`
- Chinese files append `_zh`: `quick_start_zh.rst`
- Index files named `index.rst` or `index_zh.rst`

### Cross-Reference Guidelines

```rst

# Good: Explicit document reference

:doc:`installation`

# Good: Section reference with label

:ref:`cerebro-configuration`

# Good: API reference

:class:`bt.Strategy`
:meth:`Cerebro.run`
:attr:`Strategy.params`

# Bad: Hardcoded links (breaks on version change)

`<https://backtrader.readthedocs.io/en/latest/installation.html>`_

```bash

### Code Block Guidelines

```rst

# Always specify language for syntax highlighting

.. code-block:: python

# Use line numbers for long examples

.. code-block:: python
   :linenos:

# Emphasize important lines

.. code-block:: python
   :emphasize-lines: 3,5

```bash

### Image Guidelines

```rst

# Always provide alt text

.. image:: architecture.png
   :alt: System architecture diagram

# Specify alignment for better layout

.. image:: logo.png
   :align: center

# Limit width for large images

.. image:: large_chart.png
   :width: 800px

```bash

### Translation Guidelines

1. Keep English as source of truth
2. Use `sphinx-intl` for translation management
3. Update `.po` files, never `.pot` files directly
4. Test builds with both languages before committing

### Documentation Updates

When updating code:

1. Update docstrings in source code
2. Run `make apidoc` to regenerate API docs
3. Update affected user guide sections
4. Build both languages locally
5. Test on RTD preview branch

- --

## Troubleshooting

### Common Issues and Solutions

#### Issue: Build fails with "WARNING: undefined label"

- *Solution**: Ensure all referenced sections have labels:

```rst
.. _my-section-label:

My Section

- ----------

Then reference as: :ref:`my-section-label`

```bash

#### Issue: Math equations not rendering

- *Solution**: Install math extension and use proper syntax:

```python
extensions.append('sphinx.ext.mathjax')

```bash

```rst
:math:`E = mc^2`

.. math::

   \int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}

```bash

#### Issue: Code blocks not highlighting

- *Solution**: Specify language explicitly:

```rst
.. code-block:: python

# NOT: .. code:: python (missing -block)

```bash

#### Issue: Chinese characters showing as squares

- *Solution**: Ensure font support in HTML theme:

```python
html_theme_options = {
    'font_css_variables': {
        'font-code': 'Noto Sans SC',
    }
}

```bash

#### Issue: API docs not generating

- *Solution**: Ensure module is importable:

```python

# In conf.py, add project root to path

import sys
import os
sys.path.insert(0, os.path.abspath('../..'))

```bash

### Debug Build Issues

```bash

# Verbose build output

sphinx-build -b html -v source build/html

# Show all warnings

sphinx-build -b html -W --keep-going source build/html

# Nitpicky mode for reference checking

sphinx-build -b html -n --nitpicky source build/html

```bash

### Validation Tools

```bash

# Check for broken links

sphinx-build -b linkcheck source build/html

# Check documentation coverage

sphinx-build -b coverage source build/html
cat build/html/python.txt.coverage

```bash

- --

## Appendix

### Quick Reference: RST Syntax

```rst
Headings
========

Sub-Headings

- -----------

- Italic* and **bold** text

- Bullet list item 1
- Bullet list item 2

1. Numbered list item 1
2. Numbered list item 2

.. code-block:: python

   def hello():
       print("Hello, World!")

.. note::
   This is a note.

.. warning::
   This is a warning.

.. image:: path/to/image.png
   :alt: Alternative text

`Link text <https://example.com>`_

:doc:`another-document`

:ref:`section-label`

:class:`backtrader.Strategy`

```bash

### Resources

- [Sphinx Documentation](<https://www.sphinx-doc.org/)>
- [reStructuredText Primer](<https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html)>
- [MyST Parser Guide](<https://myst-parser.readthedocs.io/)>
- [ReadThe Docs Documentation](<https://docs.readthedocs.io/)>
- [Furo Theme Documentation](<https://pradyunsg.me/furo/)>

- --

- *Document Version**: 1.0
- *Maintained By**: Backtrader Documentation Team
- *Last Updated**: March 1, 2026
