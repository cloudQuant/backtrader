# backtrader

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPLv3-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

**English** | **[中文](README.md)**

---

## Introduction

Building the most user-friendly quantitative research and trading tool based on backtrader (mainly for mid-to-low frequency; will later rewrite in C++ to support high-frequency trading).

- **master branch**: Aligned with the official mainstream backtrader, includes minor additional features and bug fixes
- **dev branch**: New feature development, C++ underlying rewrite attempt, tick-level backtesting support

### Key Features

- 🚀 **High-Performance Backtesting**: Supports both vectorized and event-driven modes
- 📊 **Plotly Interactive Charts**: High-performance interactive charts supporting 100k+ data points
- 📈 **One-Click Report Generation**: Professional backtest reports in HTML/PDF/JSON formats
- 🔧 **Rich Analyzers**: Comprehensive metrics including Sharpe ratio, max drawdown, SQN, etc.
- 📦 **Easy to Extend**: Modular design for custom strategies and indicators

---

## Installation Guide

```bash
# Install Python 3.11 (performance improvements, wide package support)
# Windows: https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Windows-x86_64.exe
# Mac (M-series): https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-MacOSX-arm64.sh
# Ubuntu: https://mirrors.tuna.tsinghua.edu.cn/anaconda/archive/Anaconda3-2023.09-0-Linux-x86_64.sh

# Clone the project
git clone https://gitee.com/yunjinqi/backtrader.git

# Install dependencies
pip install -r ./backtrader/requirements.txt

# Compile Cython files and install (macOS/Ubuntu)
cd ./backtrader/backtrader && python -W ignore compile_cython_numba_files.py && cd .. && cd .. && pip install -U ./backtrader/

# Compile Cython files and install (Windows)
cd ./backtrader/backtrader; python -W ignore compile_cython_numba_files.py; cd ..; cd ..; pip install -U ./backtrader/

# Run tests
pytest ./backtrader/tests -n 4
```

---

## Usage Instructions

1. [Official documentation and forum](https://www.backtrader.com/)
2. [My paid CSDN column](https://blog.csdn.net/qq_26948675/category_10220116.html)
3. [Instructions for `ts` and `cs`](https://yunjinqi.blog.csdn.net/article/details/130507409)

---

## 📊 Plotly Charts (High-Performance Interactive)

For large datasets, a Plotly backend is available with the following advantages:
- **High Performance**: Supports 100k+ data points without lag
- **Interactive**: Zoom, pan, hover to display data
- **Linked**: Multiple subplots share X-axis with synchronized operations

### Basic Usage

```python
import backtrader as bt

cerebro = bt.Cerebro()
# ... add strategy and data ...
cerebro.run()

# Use Plotly backend (recommended for large datasets)
cerebro.plot(backend="plotly", style="candle")

# Use original matplotlib backend (default)
cerebro.plot(backend="matplotlib")
```

### Save as HTML File

```python
from backtrader.plot import PlotlyPlot

plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html("backtrader_chart.html")
```

### Supported Features
- **Chart Types**: Candlestick (`candle`), OHLC (`bar`), Line (`line`)
- **Volume**: Overlay or separate subplot
- **Technical Indicators**: SMA, RSI, MACD auto-rendered
- **Range Slider**: Bottom navigation bar for easy browsing

---

## 📈 Backtest Report Generation

Generate professional backtest reports with one click, supporting HTML, PDF, and JSON formats.

### Basic Usage

```python
import backtrader as bt

cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy)
cerebro.adddata(data)

# Auto-add analyzers required for reporting
cerebro.add_report_analyzers()

cerebro.run()

# Generate HTML report with one click
cerebro.generate_report('report.html')

# Generate PDF report
cerebro.generate_report('report.pdf', format='pdf')

# Export JSON data
cerebro.generate_report('report.json', format='json')
```

### Custom Report Information

```python
cerebro.generate_report(
    'report.html',
    user='Trading John',           # Username
    memo='Golden Cross Strategy'   # Notes
)
```

### Using Performance Calculator Standalone

```python
from backtrader.reports import PerformanceCalculator, ReportGenerator

# Run strategy
results = cerebro.run()
strategy = results[0]

# Get all performance metrics
calc = PerformanceCalculator(strategy)
metrics = calc.get_all_metrics()

print(f"Sharpe Ratio: {metrics['sharpe_ratio']}")
print(f"Max Drawdown: {metrics['max_pct_drawdown']}%")
print(f"SQN Rating: {metrics['sqn_human']}")

# Print performance summary
report = ReportGenerator(strategy)
report.print_summary()
```

### Report Metrics

| Category | Metrics |
|----------|---------|
| **PnL** | Start Cash, End Value, Net Profit, Total Return, Annual Return, Profit Factor |
| **Risk** | Max Drawdown ($/%), Sharpe Ratio, Calmar Ratio, SQN Score |
| **Trade Stats** | Total Trades, Win Rate, Avg Win/Loss, Best/Worst Trade |

### SQN Human Rating

| SQN Score | Rating |
|-----------|--------|
| < 1.6 | Poor |
| 1.6 - 1.9 | Below Average |
| 1.9 - 2.4 | Average |
| 2.4 - 2.9 | Good |
| 2.9 - 5.0 | Excellent |
| 5.0 - 6.9 | Superb |
| ≥ 7.0 | Holy Grail |

---

## 📁 Examples

The `examples/` directory provides complete example code:

| Example File | Description |
|--------------|-------------|
| `example_plotly_charts.py` | Plotly interactive charts: color schemes, save to HTML |
| `example_bokeh_charts.py` | Bokeh charts: themes, tabs, RecorderAnalyzer |
| `example_report_generation.py` | Report generation: HTML/JSON/PDF reports, metrics |

### Running Examples

```bash
# Plotly charts example
python examples/example_plotly_charts.py

# Bokeh charts example
python examples/example_bokeh_charts.py

# Report generation example
python examples/example_report_generation.py
```

### Example Preview

**Plotly Interactive Charts**:
- Zoom, pan, hover data display
- Tableau professional color schemes
- Export to standalone HTML file

**Backtest Reports**:
- Professional HTML report pages
- Equity curve, drawdown chart, return bars
- SQN rating and complete performance metrics

---

## Changelog

Tracking changes since 2022:

- [x] **2025-01-11** Added report generation module with HTML/PDF/JSON support
- [x] **2025-01-10** Added Plotly plotting backend with Tableau color schemes
- [x] **2025-01-25** Removed `__future__` references; future versions support Python 3 only
- [x] **2024-03-15** Created `dev` branch for new feature development
- [x] **2024-03-14** Fixed Cython compilation issues
- [x] **2023-05-05** Implemented `ts` code for time-series strategies
- [x] **2023-03-03** Fixed bugs in `cs.py`, `cal_performance.py`
- [x] **2022-12-18** Modified `ts` and `cs` framework to avoid bugs
- [x] **2022-12-13** PEP8 formatting in `sharpe.py`
- [x] **2022-12-05** Added pandas-based vectorized backtesting class
- [x] **2022-12-01** Fixed `drowdown` typo to `drawdown`
- [x] **2022-11-21** Modified `getsize` in `comminfo.py`
- [x] **2022-11-08** Added `name` attribute to `data`

---

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details



