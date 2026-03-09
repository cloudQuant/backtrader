- --

title: Installation Guide
description: How to install and set up Backtrader

- --

# Installation Guide

## Requirements

- Python 3.8 or higher (tested up to 3.13)
- pip package manager

## Installation (From Source)

> **Note**: This project is NOT available on PyPI. Please install from source.

### From GitHub (Recommended)

```bash
git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader
pip install -r requirements.txt
pip install -U .

```bash

### From Gitee (For users in China)

```bash
git clone <https://gitee.com/yunjinqi/backtrader.git>
cd backtrader
pip install -r requirements.txt
pip install -U .

```bash

### Development Mode

If you plan to modify the source code:

```bash
git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader
pip install -r requirements.txt
pip install -e .

```bash

## Dependencies

### Core Dependencies

These are installed automatically:

```bash
pandas>=1.3.0
numpy>=1.20.0
matplotlib>=3.3.0
python-dateutil>=2.8.0
pytz>=2021.1

```bash

### Optional Dependencies

#### Visualization

```bash

# Interactive plotting with Plotly

pip install plotly>=5.0.0

# Web charts with Pyecharts

pip install pyecharts>=1.9.0

```bash

#### Live Trading

```bash

# CCXT for cryptocurrency exchanges

pip install ccxt

# CTP for futures trading (China)

pip install ctp-python

```bash

#### Development

```bash

# Install development dependencies

pip install -r requirements.txt

```bash

## Verify Installation

```python
import backtrader as bt

print(f"Backtrader version: {bt.__version__}")
print("Installation successful!")

```bash

## Development Setup

For contributors, see the [Developer Guide](/developer-guide/setup.md).

## Troubleshooting

### Import Errors

If you encounter import errors, ensure you have the correct Python version:

```bash
python --version  # Should be 3.8+

```bash

### Plotting Issues

For matplotlib issues on macOS:

```bash
pip install python.app

```bash
For headless environments, use the Agg backend:

```python
import matplotlib
matplotlib.use('Agg')

```bash

## Next Steps

- [Quick Start Tutorial](quickstart.md) - Create your first strategy
- [Basic Concepts](concepts.md) - Understand core concepts
- [Data Feeds](data-feeds.md) - Load market data
