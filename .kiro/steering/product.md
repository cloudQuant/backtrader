# Product Overview

Backtrader is a Python algorithmic trading backtesting framework supporting low-frequency, mid-frequency, and high-frequency strategy development, backtesting, and live trading.

This is a performance-optimized fork of the original backtrader project (https://www.backtrader.com/). The `dev` branch achieves ~45% faster execution through metaclass removal, broker optimization, and Cython-accelerated calculations.

## Key Capabilities

- Three backtesting modes: vectorized (runonce), event-driven (runnext), and tick-level
- 50+ built-in technical indicators, 17+ analyzers, 20+ data source integrations
- Multiple visualization backends: Plotly (interactive), Bokeh (real-time), Matplotlib (static)
- Professional HTML/PDF/JSON report generation
- Parameter optimization with multiprocessing support
- TradeLogger observer for real-time trade logging with optional MySQL persistence
- TS (time series) and CS (cross-section) modes for multi-asset portfolio backtesting

## Project Context

- **License**: GPLv3
- **Python**: 3.9+ (3.11 recommended)
- **Not on PyPI** — install from source only
- **Branches**: `master` (stable), `dev` (active development with performance work)
- **Bilingual**: Documentation and comments exist in both English and Chinese
