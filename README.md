<div align="center">

# 🚀 Backtrader

**Professional Python Algorithmic Trading Backtesting Framework**

[![Version](https://img.shields.io/badge/Version-1.0.0-blue.svg)]()
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPLv3-orange.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

**English** | [**中文**](#-中文文档)

[📖 Documentation](https://github.com/cloudQuant/backtrader/wiki) · 
[🐛 Report Bug](https://github.com/cloudQuant/backtrader/issues) · 
[💬 Discussions](https://github.com/cloudQuant/backtrader/discussions)

</div>

---

## 📋 Table of Contents

- [Introduction](#-introduction)
- [Key Features](#-key-features)
- [Quick Installation](#-quick-installation)
- [5-Minute Quickstart](#-5-minute-quickstart)
- [Core Concepts](#-core-concepts)
- [Built-in Components](#-built-in-components)
- [Advanced Topics](#-advanced-topics)
- [Project Architecture](#-project-architecture)
- [API Documentation](#-api-documentation)
- [FAQ](#-faq)
- [Contributing](#-contributing)
- [License](#-license)
- [中文文档](#-中文文档)

---

## 🎯 Introduction

Backtrader is a powerful and flexible Python framework for backtesting trading strategies. This project is based on [backtrader](https://www.backtrader.com/) with extensive optimizations and feature enhancements, focusing on medium to low-frequency strategy development and backtesting.

### Why Choose Backtrader?

| Comparison | Backtrader | Other Frameworks |
|------------|------------|------------------|
| Learning Curve | ⭐⭐ Gentle | ⭐⭐⭐⭐ Steep |
| Development Efficiency | ⭐⭐⭐⭐⭐ Very High | ⭐⭐⭐ Average |
| Built-in Indicators | 50+ | 10-30 |
| Data Source Support | 20+ | 5-10 |
| Community Activity | ⭐⭐⭐⭐ Active | ⭐⭐ Average |
| Documentation | ⭐⭐⭐⭐⭐ Complete | ⭐⭐⭐ Average |

### Project Branches

- **master branch**: Stable version with feature extensions and bug fixes
- **development branch**: Development version, exploring C++ rewrite for high-frequency support

---

## ✨ Key Features

### 🚀 High-Performance Backtesting Engine

```
Two backtesting modes supported:
├── runonce (Vectorized) - Batch computation, optimal performance
└── runnext (Event-driven) - Bar-by-bar, suitable for complex logic
```

### 📊 Rich Visualization

- **Plotly Interactive Charts**: Supports 100k+ data points with zoom, pan, hover
- **Bokeh Real-time Charts**: Real-time data updates and multi-tab support
- **Matplotlib Static Charts**: Classic plotting for papers and reports

### 📈 Professional Reports

One-click generation of professional reports including:
- Equity curves and drawdown charts
- Sharpe ratio, Calmar ratio, SQN rating
- Detailed trade statistics and P&L analysis
- Export to HTML, PDF, JSON formats

### 🔧 50+ Built-in Technical Indicators

Covering moving averages, momentum, volatility, trend indicators, and more.

### 📦 Modular Architecture

Strategies, indicators, analyzers, and data sources can be independently extended.

### 🌍 20+ Data Source Support

CSV, Pandas, Yahoo Finance, Interactive Brokers, CCXT cryptocurrency, and more.

---

## 📥 Quick Installation

### Requirements

- **Python**: 3.9+ (3.11 recommended for ~15% performance boost)
- **OS**: Windows / macOS / Linux
- **RAM**: 4GB+ recommended

### Option 1: pip Install (Recommended)

```bash
# Clone from GitHub
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader

# Or clone from Gitee (for Chinese users)
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# Install dependencies
pip install -r requirements.txt

# Install backtrader
pip install -e .
```

### Verify Installation

```python
import backtrader as bt
print(f"Backtrader version: {bt.__version__}")
# Output: Backtrader version: 1.0.0
```

### Run Tests

```bash
pytest ./backtrader/tests -n 4 -v
```

---

## 🎓 5-Minute Quickstart

### Step 1: Understand the Workflow

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Prepare    │ -> │   Write     │ -> │    Run      │
│   Data      │    │  Strategy   │    │  Backtest   │
└─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │
       v                  v                  v
  CSV/Pandas/API    Extend Strategy    cerebro.run()
                    Implement next()
```

### Step 2: Write Your First Strategy

```python
import backtrader as bt

# Define strategy: SMA crossover
class SmaCrossStrategy(bt.Strategy):
    """
    Moving Average Crossover Strategy:
    - Buy when fast SMA crosses above slow SMA
    - Sell when fast SMA crosses below slow SMA
    """
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )
    
    def __init__(self):
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.params.fast_period)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.params.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
    
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()
```

### Step 3: Prepare Data

```python
# Option 1: Load from CSV file
data = bt.feeds.GenericCSVData(
    dataname='your_data.csv',
    datetime=0, open=1, high=2, low=3, close=4, volume=5,
    openinterest=-1, dtformat='%Y-%m-%d',
)

# Option 2: Load from Pandas DataFrame
import pandas as pd
df = pd.read_csv('your_data.csv', parse_dates=['date'], index_col='date')
data = bt.feeds.PandasData(dataname=df)

# Option 3: Download from Yahoo Finance
from datetime import datetime
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31),
)
```

### Step 4: Run Backtest

```python
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(SmaCrossStrategy)
cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.0003)

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

print(f'Starting: {cerebro.broker.getvalue():,.2f}')
results = cerebro.run()
print(f'Final: {cerebro.broker.getvalue():,.2f}')

strat = results[0]
print(f"Sharpe: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")
print(f"Max DD: {strat.analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")
```

### Step 5: Visualize Results

```python
# Plotly interactive charts (recommended)
cerebro.plot(backend='plotly', style='candle')

# Save to HTML
from backtrader.plot import PlotlyPlot
plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html('backtest_chart.html')
```

---

## 📚 Core Concepts

### 1. Cerebro - The Engine

```python
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(Strategy)
cerebro.addanalyzer(Analyzer)
cerebro.broker.setcash(100000)
results = cerebro.run()
cerebro.plot()
```

### 2. Strategy

```python
class MyStrategy(bt.Strategy):
    params = (('period', 20),)
    
    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.params.period)
    
    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()
    
    def notify_order(self, order):
        if order.status == order.Completed:
            print(f'Order executed at {order.executed.price}')
```

### 3. Lines - Data Structure

```python
self.data.close[0]     # Current bar
self.data.close[-1]    # Previous bar
self.data.open[0]      # Current open
self.data.high[0]      # Current high
self.data.volume[0]    # Current volume
```

### 4. Order Types

```python
self.buy()                                    # Market buy
self.sell(price=100, exectype=bt.Order.Limit) # Limit sell
self.buy_bracket(price=100, stopprice=95, limitprice=110)  # Bracket order
self.order_target_percent(target=0.5)         # Target 50% position
```

---

## 📦 Built-in Components

### Technical Indicators (50+)

| Category | Indicators |
|----------|------------|
| **Moving Averages** | SMA, EMA, WMA, DEMA, TEMA, KAMA, HMA, ZLEMA |
| **Momentum** | RSI, ROC, Momentum, Williams %R, Ultimate Oscillator |
| **Volatility** | ATR, Bollinger Bands, Standard Deviation |
| **Trend** | ADX, Aroon, Parabolic SAR, Ichimoku, DPO |
| **Oscillators** | MACD, Stochastic, CCI, TSI, TRIX |

### Analyzers (17+)

| Analyzer | Purpose |
|----------|---------|
| `SharpeRatio` | Risk-adjusted returns |
| `DrawDown` | Maximum drawdown |
| `TradeAnalyzer` | Trade statistics |
| `Returns` | Return analysis |
| `SQN` | System Quality Number |

### Data Sources (20+)

| Data Source | Description |
|-------------|-------------|
| `GenericCSVData` | Generic CSV files |
| `PandasData` | Pandas DataFrame |
| `YahooFinanceData` | Yahoo Finance |
| `IBData` | Interactive Brokers |
| `CCXTFeed` | Cryptocurrency |

---

## 🔬 Advanced Topics

### Parameter Optimization

```python
cerebro.optstrategy(
    SmaCrossStrategy,
    fast_period=range(5, 20, 5),
    slow_period=range(20, 60, 10),
)
results = cerebro.run(maxcpus=4)
```

### Multiple Data Sources

```python
cerebro.adddata(data1)
cerebro.adddata(data2)

# In strategy
price1 = self.datas[0].close[0]
price2 = self.datas[1].close[0]
```

### Custom Indicators

```python
class MyIndicator(bt.Indicator):
    lines = ('myline',)
    params = (('period', 20),)
    
    def __init__(self):
        self.lines.myline = bt.indicators.SMA(self.data, period=self.params.period)
```

### Professional Reports

```python
cerebro.add_report_analyzers(riskfree_rate=0.02)
cerebro.run()
cerebro.generate_report('report.html', user='Trader', memo='Strategy Report')
```

---

## 🏗 Project Architecture

```
backtrader/
├── backtrader/           # Core codebase
│   ├── cerebro.py        # Main engine
│   ├── strategy.py       # Strategy base
│   ├── indicator.py      # Indicator base
│   ├── analyzer.py       # Analyzer base
│   ├── feed.py           # Data feed base
│   ├── broker.py         # Broker base
│   ├── indicators/       # 52 technical indicators
│   ├── analyzers/        # 17 analyzers
│   ├── feeds/            # 21 data sources
│   ├── plot/             # Visualization
│   └── reports/          # Report generation
├── examples/             # Example code
├── tests/                # Test cases
└── docs/                 # Documentation
```

---

## 📖 API Documentation

### Build Local Documentation

```bash
cd docs
pip install -r requirements.txt
./build_docs.sh all
./build_docs.sh serve
# Visit http://localhost:8000
```

### Quick API Reference

```python
import backtrader as bt

# Cerebro
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(Strategy)
cerebro.broker.setcash(100000)
results = cerebro.run()
cerebro.plot()

# Strategy methods
self.buy(size=100)
self.sell(size=100)
self.close()
self.order_target_percent(target=0.5)

# Common indicators
bt.indicators.SMA(data, period=20)
bt.indicators.RSI(data, period=14)
bt.indicators.MACD(data)
bt.indicators.BollingerBands(data)
```

---

## ❓ FAQ

### Q1: How to set slippage?

```python
cerebro.broker.set_slippage_fixed(0.01)  # Fixed slippage
cerebro.broker.set_slippage_perc(0.001)  # Percentage slippage
```

### Q2: How to limit trade size?

```python
class FixedSizer(bt.Sizer):
    params = (('stake', 100),)
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        return self.params.stake

cerebro.addsizer(FixedSizer, stake=100)
```

### Q3: How to get all transactions?

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()
transactions = results[0].analyzers.txn.get_analysis()
```

### Q4: Backtest too slow?

```python
cerebro.run(runonce=True)  # Use vectorized mode (default)
cerebro.run(maxcpus=4)     # Use multiprocessing for optimization
```

---

## 🤝 Contributing

We welcome all contributions!

1. Fork the repository
2. Create a branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m "feat: add your feature"`
4. Push: `git push origin feature/your-feature`
5. Create Pull Request

---

## 📄 License

This project is licensed under [GPLv3](LICENSE).

---

## 📞 Contact

- **GitHub**: [https://github.com/cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)
- **Gitee**: [https://gitee.com/yunjinqi/backtrader](https://gitee.com/yunjinqi/backtrader)
- **Author Blog**: [https://yunjinqi.blog.csdn.net/](https://yunjinqi.blog.csdn.net/)

---

<div align="center">

**If this project helps you, please give us a ⭐ Star!**

</div>

---

# 📖 中文文档

[**English**](#-backtrader) | **中文**

---

## 🎯 项目简介

Backtrader 是一个功能强大、灵活易用的 Python 量化交易回测框架。本项目基于 [backtrader](https://www.backtrader.com/) 进行了大量优化和功能扩展，专注于中低频交易策略的研发与回测。

### 为什么选择 Backtrader？

| 对比项 | Backtrader | 其他框架 |
|--------|------------|----------|
| 学习曲线 | ⭐⭐ 平缓 | ⭐⭐⭐⭐ 陡峭 |
| 策略开发效率 | ⭐⭐⭐⭐⭐ 极高 | ⭐⭐⭐ 一般 |
| 内置指标数量 | 50+ | 10-30 |
| 数据源支持 | 20+ | 5-10 |

---

## ✨ 核心特性

- 🚀 **高性能回测引擎**：支持向量化和事件驱动两种模式
- 📊 **丰富的可视化**：Plotly 交互图表、Bokeh 实时图表
- 📈 **专业回测报告**：一键生成 HTML/PDF/JSON 格式报告
- 🔧 **50+ 内置技术指标**：均线、动量、波动率、趋势等
- 📦 **模块化架构**：策略、指标、分析器可独立扩展
- 🌍 **20+ 数据源支持**：CSV、Pandas、Yahoo、IB、CCXT 等

---

## 📥 快速安装

```bash
# 从 GitHub 克隆
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader

# 或从 Gitee 克隆（国内用户推荐）
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# 安装依赖
pip install -r requirements.txt

# 安装 backtrader
pip install -e .

# 验证安装
python -c "import backtrader as bt; print(bt.__version__)"
```

---

## 🎓 5 分钟入门

```python
import backtrader as bt

# 定义策略
class SmaCrossStrategy(bt.Strategy):
    params = (('fast', 10), ('slow', 30))
    
    def __init__(self):
        fast_sma = bt.indicators.SMA(period=self.params.fast)
        slow_sma = bt.indicators.SMA(period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(fast_sma, slow_sma)
    
    def next(self):
        if not self.position and self.crossover > 0:
            self.buy()
        elif self.position and self.crossover < 0:
            self.close()

# 创建引擎
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(SmaCrossStrategy)
cerebro.broker.setcash(100000)

# 运行回测
results = cerebro.run()
cerebro.plot(backend='plotly')
```

---

## ❓ 常见问题

### Q1: 如何设置滑点？

```python
cerebro.broker.set_slippage_fixed(0.01)  # 固定滑点
cerebro.broker.set_slippage_perc(0.001)  # 百分比滑点
```

### Q2: 如何限制单笔交易数量？

```python
class FixedSizer(bt.Sizer):
    params = (('stake', 100),)
    def _getsizing(self, comminfo, cash, data, isbuy):
        return self.params.stake

cerebro.addsizer(FixedSizer, stake=100)
```

### Q3: 如何获取所有交易记录？

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()
transactions = results[0].analyzers.txn.get_analysis()
```

### Q4: 回测速度慢怎么办？

```python
cerebro.run(runonce=True)  # 使用向量化模式（默认）
cerebro.run(maxcpus=4)     # 参数优化时使用多进程
```

---

## 📞 联系方式

- **GitHub**: [https://github.com/cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)
- **Gitee**: [https://gitee.com/yunjinqi/backtrader](https://gitee.com/yunjinqi/backtrader)
- **作者博客**: [https://yunjinqi.blog.csdn.net/](https://yunjinqi.blog.csdn.net/)

---

<div align="center">

**如果本项目对您有帮助，请点个 ⭐ Star 支持我们！**

Made with ❤️ by CloudQuant

</div>
