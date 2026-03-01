---
title: Installation Guide
description: How to install and set up Backtrader
---

# Installation Guide

## Requirements

- Python 3.8 or higher (tested up to 3.13)
- pip package manager

## Basic Installation

### From PyPI

```bash
pip install backtrader
```

### From Source (Development Version)

```bash
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader
pip install -e .
```

## Dependencies

### Core Dependencies

These are installed automatically:

```
pandas>=1.3.0
numpy>=1.20.0
matplotlib>=3.3.0
python-dateutil>=2.8.0
pytz>=2021.1
```

### Optional Dependencies

#### Visualization

```bash
# Interactive plotting with Plotly
pip install plotly>=5.0.0

# Web charts with Pyecharts
pip install pyecharts>=1.9.0
```

#### Live Trading

```bash
# CCXT for cryptocurrency exchanges
pip install ccxt

# CTP for futures trading (China)
pip install ctp-python
```

#### Development

```bash
# Install development dependencies
pip install -r requirements.txt
```

## Verify Installation

```python
import backtrader as bt

print(f"Backtrader version: {bt.__version__}")
print("Installation successful!")
```

## Development Setup

For contributors, see the [Developer Guide](/developer-guide/setup.md).

## Troubleshooting

### Import Errors

If you encounter import errors, ensure you have the correct Python version:

```bash
python --version  # Should be 3.8+
```

### Plotting Issues

For matplotlib issues on macOS:

```bash
pip install python.app
```

For headless environments, use the Agg backend:

```python
import matplotlib
matplotlib.use('Agg')
```

## Next Steps

- [Quick Start Tutorial](quickstart.md) - Create your first strategy
- [Basic Concepts](concepts.md) - Understand core concepts
- [Data Feeds](data-feeds.md) - Load market data
