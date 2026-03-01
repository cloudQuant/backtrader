<div align="center">

# 🚀 Backtrader

- *Professional Python Algorithmic Trading Backtesting Framework**

[![Version](<https://img.shields.io/badge/Version-1.1.0-blue.svg)]()>
[![Python](<https://img.shields.io/badge/Python-3.9%2B-green.svg)](<https://www.python.org/>)>
[![License](<https://img.shields.io/badge/License-GPLv3-orange.svg)](<https://www.gnu.org/licenses/gpl-3.0>)>
[![Platform](<https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()>

- *English** | [**中文**](#-中文文档)

[📖 Documentation (EN)](<https://backtrader.readthedocs.io/en/latest/)> ·
[📖 中文文档](<https://backtrader-zh.readthedocs.io/zh-cn/latest/)> ·
[🌐 GitHub Pages](<https://cloudquant.github.io/backtrader/)>

[🐛 Report Bug](<https://github.com/cloudQuant/backtrader/issues)> ·
[💬 Discussions](<https://github.com/cloudQuant/backtrader/discussions)>

</div>

- --

## ⚡ Performance Improvements (Development Branch)

The `development` branch has undergone extensive performance optimizations, achieving **45% faster execution**compared to the master branch while removing metaprogramming complexity.

### 📊 Benchmark Results

| Metric | Master Branch | Development Branch | Improvement |

|--------|---------------|-------------------|-------------|

|**Total Execution Time**| 553.12s | 305.36s |**-44.8%**⚡ |

|**Strategies Tested**| 119 | 119 | ✓ |

|**Test Pass Rate**| 100% | 100% | ✓ |

|**Code Quality** | ✓ | ✓ | ✓ |

- Benchmark: 119 strategy backtests on identical hardware (Python 3.13, 12 parallel processes)*


### 📈 Performance by Strategy Type

| Strategy Category | Avg Speedup | Example |

|-------------------|-------------|---------|

| Simple MA Cross | 40-45% | `test_03_two_ma`: 2.6s → 1.5s |

| Multi-Indicator | 45-50% | `test_09_dual_thrust`: 59.2s → 26.9s |

| Multi-Data | 42-48% | `test_02_multi_extend_data`: 23.5s → 12.6s |

| Complex Strategies | 38-42% | `test_08_kelter_strategy`: 36.9s → 11.3s |


- --

## 🤝 Contributing

We welcome contributions to improve code quality, fix bugs, and enhance performance!

### 🐛 Reporting Indicator Discrepancies

If you find that the `development` branch produces different results than the `master` branch for the same strategy, this likely indicates an indicator calculation bug. Please help us fix it!

### 📝 Pull Request Guidelines

To submit a pull request, please follow these steps:

#### 1️⃣ Create a Test Case

Add a new test case that:

- ✅ Passes on **both**`master` and `development` branches
- ✅ Demonstrates the bug or validates the fix
- ✅ Includes clear assertions and expected values

```python

# Example: tests/strategies/test_XXX_your_indicator.py

import backtrader as bt

class TestYourIndicator(bt.Strategy):
    def __init__(self):
        self.indicator = bt.indicators.YourIndicator(self.data)

    def next(self):

# Add assertions to validate correctness
        pass

def test_your_indicator():
    cerebro = bt.Cerebro()

# ... setup and run
    assert result == expected_value

```bash

#### 2️⃣ Run Code Quality Checks

Ensure your code passes all quality checks:

```bash

# Option 1: Run the full optimization script (recommended)

bash scripts/optimize_code.sh

# Option 2: Run tests manually

pytest tests -n 4

# Both commands must pass without errors

```bash

#### 3️⃣ Verify All Tests Pass

```bash

# Run all existing tests to ensure no regressions

pytest tests -n 4 -v

# Expected output: All 478+ tests should pass

```bash

#### 4️⃣ Submit Your PR

1. Fork the repository
2. Create a feature branch: `git checkout -b fix/indicator-name`
3. Commit your changes: `git commit -m "fix: correct calculation in YourIndicator"`
4. Push to your fork: `git push origin fix/indicator-name`
5. Open a Pull Request with:
   - Clear description of the issue
   - Reference to the test case
   - Explanation of the fix

### 🎯 Contribution Areas

We especially welcome contributions in:

- 🐛**Bug Fixes**: Indicator calculation errors, edge cases
- ✅ **Test Coverage**: Additional test cases for existing indicators
- 📊 **Performance**: Further optimization opportunities
- 📚 **Documentation**: Improved examples and tutorials
- 🔧 **Features**: New indicators, analyzers, or data feeds

### 💡 Best Practices

- Write clear, self-documenting code
- Add docstrings to all public methods
- Follow existing code style (enforced by `ruff` and `black`)
- Keep changes focused and atomic
- Update documentation when adding features

- --

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

- --

## 🎯 Introduction

Backtrader is a powerful and flexible Python framework for backtesting trading strategies. This project is based on [backtrader](<https://www.backtrader.com/)> with extensive optimizations and feature enhancements, supporting **low-frequency, mid-frequency, and high-frequency** strategy development, backtesting, and live trading.

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
- **development branch**: Development version with tick-level backtesting, multi-frequency trading support, and performance optimizations

- --

## ✨ Key Features

### 🚀 High-Performance Multi-Frequency Backtesting Engine

```
Three backtesting modes supported:
├── runonce (Vectorized)    - Batch computation, optimal performance
├── runnext (Event-driven)  - Bar-by-bar, suitable for complex logic
└── Tick-level backtesting  - Tick data support with tick+bar mixed mode

Trading frequency spectrum:
├── Low-frequency   - Daily/weekly bars, position trading
├── Mid-frequency   - Minute/hour bars, intraday trading
└── High-frequency  - Tick-level data, market microstructure
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

### 🔄 Tick-Level & Mixed-Frequency Trading

- **Tick-level backtesting**: Process individual tick data for high-frequency strategy research
- **Tick + Bar mixed mode**: Combine tick and bar data in the same strategy for multi-frequency analysis
- **Seamless live trading**: Same strategy code works for backtesting and live trading across all frequencies
- **Full spectrum coverage**: Low-frequency (daily), mid-frequency (minute), and high-frequency (tick) — all unified in one framework

### 📦 Modular Architecture

Strategies, indicators, analyzers, and data sources can be independently extended.

### 🌍 20+ Data Source Support

CSV, Pandas, Yahoo Finance, Interactive Brokers, CCXT cryptocurrency, CTP futures, and more.

- --

## 📥 Quick Installation

### Requirements

- **Python**: 3.9+ (3.11 recommended for ~15% performance boost)
- **OS**: Windows / macOS / Linux
- **RAM**: 4GB+ recommended

### From GitHub (Recommended)

> **Note**: This project is NOT on PyPI. Install from source only.

```bash
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader
pip install -r requirements.txt
pip install -U .
```

### From Gitee (For users in China)

```bash
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader
pip install -r requirements.txt
pip install -U .
```

### Verify Installation

```python
import backtrader as bt
print(f"Backtrader version: {bt.__version__}")

# Output: Backtrader version: 1.0.0

```bash

### Run Tests

```bash
pytest tests -n 4 -v
```

- --

## 🎓 5-Minute Quickstart

### Step 1: Understand the Workflow

```bash
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Prepare    │ -> │   Write     │ -> │    Run      │
│   Data      │    │  Strategy   │    │  Backtest   │
└─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │
       v                  v                  v
  CSV/Pandas/API    Extend Strategy    cerebro.run()
                    Implement next()

```bash

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

```bash

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

```bash

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

```bash

### Step 5: Visualize Results

```python

# Plotly interactive charts (recommended)

cerebro.plot(backend='plotly', style='candle')

# Save to HTML

from backtrader.plot import PlotlyPlot
plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html('backtest_chart.html')

```bash

- --

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

```bash

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

```bash

### 3. Lines - Data Structure

```python
self.data.close[0]     # Current bar

self.data.close[-1]    # Previous bar

self.data.open[0]      # Current open

self.data.high[0]      # Current high

self.data.volume[0]    # Current volume

```bash

### 4. Order Types

```python
self.buy()                                    # Market buy

self.sell(price=100, exectype=bt.Order.Limit) # Limit sell

self.buy_bracket(price=100, stopprice=95, limitprice=110)  # Bracket order

self.order_target_percent(target=0.5)         # Target 50% position

```bash

- --

## 📦 Built-in Components

### Technical Indicators (50+)

| Category | Indicators |

|----------|------------|

| **Moving Averages**| SMA, EMA, WMA, DEMA, TEMA, KAMA, HMA, ZLEMA |

|**Momentum**| RSI, ROC, Momentum, Williams %R, Ultimate Oscillator |

|**Volatility**| ATR, Bollinger Bands, Standard Deviation |

|**Trend**| ADX, Aroon, Parabolic SAR, Ichimoku, DPO |

|**Oscillators** | MACD, Stochastic, CCI, TSI, TRIX |

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

- --

## 🔬 Advanced Topics

### Parameter Optimization

```python
cerebro.optstrategy(
    SmaCrossStrategy,
    fast_period=range(5, 20, 5),
    slow_period=range(20, 60, 10),
)
results = cerebro.run(maxcpus=4)

```bash

### Multiple Data Sources

```python
cerebro.adddata(data1)
cerebro.adddata(data2)

# In strategy

price1 = self.datas[0].close[0]
price2 = self.datas[1].close[0]

```bash

### Custom Indicators

```python
class MyIndicator(bt.Indicator):
    lines = ('myline',)
    params = (('period', 20),)

    def __init__(self):
        self.lines.myline = bt.indicators.SMA(self.data, period=self.params.period)

```bash

### Professional Reports

```python
cerebro.add_report_analyzers(riskfree_rate=0.02)
cerebro.run()
cerebro.generate_report('report.html', user='Trader', memo='Strategy Report')

```bash

- --

## 🏗 Project Architecture

```bash
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

```bash

- --

## 📖 API Documentation

### Online Documentation

- **ReadTheDocs (EN)**: <https://backtrader.readthedocs.io/en/latest/>
- **ReadTheDocs (ZH)**: <https://backtrader-zh.readthedocs.io/zh-cn/latest/>
- **GitHub Pages**: <https://cloudquant.github.io/backtrader/>

### Build Local Documentation

```bash
cd docs
pip install -r requirements.txt
make html
make serve
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

```bash

- --

## ❓ FAQ

### Q1: How to set slippage?

```python
cerebro.broker.set_slippage_fixed(0.01)  # Fixed slippage

cerebro.broker.set_slippage_perc(0.001)  # Percentage slippage

```bash

### Q2: How to limit trade size?

```python
class FixedSizer(bt.Sizer):
    params = (('stake', 100),)

    def _getsizing(self, comminfo, cash, data, isbuy):
        return self.params.stake

cerebro.addsizer(FixedSizer, stake=100)

```bash

### Q3: How to get all transactions?

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()
transactions = results[0].analyzers.txn.get_analysis()

```bash

### Q4: Backtest too slow?

```python
cerebro.run(runonce=True)  # Use vectorized mode (default)

cerebro.run(maxcpus=4)     # Use multiprocessing for optimization

```bash

- --

## ⚠️ Important Disclaimer

### Risk Warning

- *THIS SOFTWARE IS PROVIDED FOR EDUCATIONAL AND RESEARCH PURPOSES ONLY.**

- ⚠️ **Trading Risk**: Algorithmic trading involves substantial risk of loss. Past performance does not guarantee future results.
- 🐛 **Software Status**: This project is under active development and may contain bugs or calculation errors.
- 💰 **Financial Liability**: **You are solely responsible for any financial losses**incurred from using this software.
- 🔍**Verification Required**: Always verify backtest results against known benchmarks before live trading.
- 📊 **No Warranty**: This software is provided "AS IS" without warranty of any kind, express or implied.

- *By using this software, you acknowledge and accept all risks associated with algorithmic trading.**

- --

## 📄 License

This project is licensed under [GPLv3](LICENSE).

- --

## 📞 Contact

- **GitHub**: [<https://github.com/cloudQuant/backtrader](<https://github.com/cloudQuant/backtrader>)>
- **Gitee**: [<https://gitee.com/yunjinqi/backtrader](<https://gitee.com/yunjinqi/backtrader>)>
- **Author Blog**: [<https://yunjinqi.blog.csdn.net/](<https://yunjinqi.blog.csdn.net/>)>
- **ReadTheDocs (EN)**: <https://backtrader.readthedocs.io/en/latest/>
- **ReadTheDocs (ZH)**: <https://backtrader-zh.readthedocs.io/zh-cn/latest/>
- **GitHub Pages**: <https://cloudquant.github.io/backtrader/>

- --

<div align="center">

- *If this project helps you, please give us a ⭐ Star!**

</div>

- --

# 📖 中文文档

[**English**](#-backtrader) | **中文**

- --

## ⚡ 性能优化成果（Development 分支）

`development` 分支经过大量性能优化，在移除元编程复杂性的同时，实现了相比 master 分支 **45% 的性能提升**。

### 📊 基准测试结果

| 指标 | Master 分支 | Development 分支 | 提升幅度 |

|------|-------------|------------------|----------|

| **总执行时间**| 553.12 秒 | 305.36 秒 |**-44.8%**⚡ |

|**测试策略数**| 119 | 119 | ✓ |

|**测试通过率**| 100% | 100% | ✓ |

|**代码质量** | ✓ | ✓ | ✓ |

- 基准测试：在相同硬件上运行 119 个策略回测（Python 3.13，12 并行进程）*

### 🔧 核心优化项

1. **移除元编程开销**
   - 消除动态元类属性拦截机制
   - 采用显式描述符参数系统
   - 结果：属性访问开销降低约 40%

1. **经纪商性能增强**
   - 移除 `BackBroker` 和 `CommInfoBase` 的全局 `__getattribute__` 重载
   - 在热路径（`BackBroker.next()`、`_get_value()`）实现本地参数缓存
   - 缓存高频访问参数（`mult`、`cash`、`stocklike`）
   - 结果：经纪商操作速度提升 42.5%

1. **指标计算优化**
   - 优化布林带 `once()` 方法，使用更快的 NaN 检查
   - 减少冗余数组边界检查
   - 缓存数学函数和常量
   - 结果：指标计算速度提升 15-20%

1. **减少内置函数调用**
   - 最小化热路径中的 `isinstance()`、`hasattr()` 和 `len()` 调用
   - 在适当场景使用类型恒等检查
   - 结果：Python 层面开销降低约 10%

### 📈 不同策略类型的性能提升

| 策略类别 | 平均加速 | 示例 |

|---------|---------|------|

| 简单均线交叉 | 40-45% | `test_03_two_ma`: 2.6 秒 → 1.5 秒 |

| 多指标策略 | 45-50% | `test_09_dual_thrust`: 59.2 秒 → 26.9 秒 |

| 多数据源 | 42-48% | `test_02_multi_extend_data`: 23.5 秒 → 12.6 秒 |

| 复杂策略 | 38-42% | `test_08_kelter_strategy`: 36.9 秒 → 11.3 秒 |


- --

## 🤝 贡献指南

我们欢迎所有有助于提升代码质量、修复 bug 和增强性能的贡献！

### 🐛 报告指标差异

如果您发现 `development` 分支与 `master` 分支在相同策略下产生不同结果，这很可能表明存在指标计算 bug。请帮助我们修复！

### 📝 Pull Request 提交规范

提交 Pull Request 时，请遵循以下步骤：

#### 1️⃣ 创建测试用例

添加一个新的测试用例，要求：

- ✅ 在 **master**和**development**分支上都能通过
- ✅ 能够演示 bug 或验证修复
- ✅ 包含清晰的断言和预期值

```python

# 示例：tests/strategies/test_XXX_your_indicator.py

import backtrader as bt

class TestYourIndicator(bt.Strategy):
    def __init__(self):
        self.indicator = bt.indicators.YourIndicator(self.data)

    def next(self):

# 添加断言验证正确性
        pass

def test_your_indicator():
    cerebro = bt.Cerebro()

# ... 设置并运行
    assert result == expected_value

```bash

#### 2️⃣ 运行代码质量检查

确保您的代码通过所有质量检查：

```bash

# 方式 1：运行完整优化脚本（推荐）

bash scripts/optimize_code.sh

# 方式 2：手动运行测试

pytest tests -n 4

# 两个命令都必须无错误通过

```bash

#### 3️⃣ 验证所有测试通过

```bash

# 运行所有现有测试，确保没有回归

pytest tests -n 4 -v

# 预期输出：所有 478+ 个测试都应通过

```bash

#### 4️⃣ 提交您的 PR

1. Fork 本仓库
2. 创建功能分支：`git checkout -b fix/indicator-name`
3. 提交更改：`git commit -m "fix: 修正 YourIndicator 的计算"`
4. 推送到您的 fork：`git push origin fix/indicator-name`
5. 创建 Pull Request，包含：
   - 问题的清晰描述
   - 测试用例的引用
   - 修复方案的说明

### 🎯 贡献方向

我们特别欢迎以下方面的贡献：

- 🐛**Bug 修复**：指标计算错误、边界情况处理
- ✅ **测试覆盖**：为现有指标添加更多测试用例
- 📊 **性能优化**：进一步的优化机会
- 📚 **文档完善**：改进示例和教程
- 🔧 **功能扩展**：新指标、分析器或数据源

### 💡 最佳实践

- 编写清晰、自文档化的代码
- 为所有公共方法添加文档字符串
- 遵循现有代码风格（由 `ruff` 和 `black` 强制执行）
- 保持更改集中和原子化
- 添加功能时更新文档

- --

## 🎯 项目简介

Backtrader 是一个功能强大、灵活易用的 Python 量化交易回测框架。本项目基于 [backtrader](<https://www.backtrader.com/)> 进行了大量优化和功能扩展，支持**低频、中频、高频**全频段交易策略的研发、回测与实盘交易。

### 为什么选择 Backtrader？

| 对比项 | Backtrader | 其他框架 |

|--------|------------|----------|

| 学习曲线 | ⭐⭐ 平缓 | ⭐⭐⭐⭐ 陡峭 |

| 策略开发效率 | ⭐⭐⭐⭐⭐ 极高 | ⭐⭐⭐ 一般 |

| 内置指标数量 | 50+ | 10-30 |

| 数据源支持 | 20+ | 5-10 |

- --

## ✨ 核心特性

- 🚀 **高性能多频段回测引擎**：支持向量化、事件驱动和 Tick 级别三种模式
- 🔄 **Tick 级别回测与混合交易**：支持 Tick 数据回测、Tick + Bar 混合模式，打通低频、中频、高频全频段交易
- 📊 **丰富的可视化**：Plotly 交互图表、Bokeh 实时图表
- 📈 **专业回测报告**：一键生成 HTML/PDF/JSON 格式报告
- 🔧 **50+ 内置技术指标**：均线、动量、波动率、趋势等
- 📦 **模块化架构**：策略、指标、分析器可独立扩展
- 🌍 **20+ 数据源支持**：CSV、Pandas、Yahoo、IB、CCXT、CTP 期货等
- 🔗 **回测与实盘无缝衔接**：同一套策略代码可直接用于回测和实盘交易

- --

## 📥 快速安装

```bash

# 注意：本项目未发布到 PyPI，请从源码安装

# 从 GitHub 克隆
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader
pip install -r requirements.txt
pip install -U .

# 或从 Gitee 克隆（国内用户推荐）
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader
pip install -r requirements.txt
pip install -U .

# 验证安装
python -c "import backtrader as bt; print(bt.__version__)"

```bash

- --

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

```bash

- --

## ❓ 常见问题

### Q1: 如何设置滑点？

```python
cerebro.broker.set_slippage_fixed(0.01)  # 固定滑点

cerebro.broker.set_slippage_perc(0.001)  # 百分比滑点

```bash

### Q2: 如何限制单笔交易数量？

```python
class FixedSizer(bt.Sizer):
    params = (('stake', 100),)
    def _getsizing(self, comminfo, cash, data, isbuy):
        return self.params.stake

cerebro.addsizer(FixedSizer, stake=100)

```bash

### Q3: 如何获取所有交易记录？

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()
transactions = results[0].analyzers.txn.get_analysis()

```bash

### Q4: 回测速度慢怎么办？

```python
cerebro.run(runonce=True)  # 使用向量化模式（默认）

cerebro.run(maxcpus=4)     # 参数优化时使用多进程

```bash

- --

## ⚠️ 重要声明

### 风险警示

- *本软件仅供教育和研究目的使用。**

- ⚠️ **交易风险**：算法交易存在重大亏损风险。历史业绩不代表未来表现。
- 🐛 **软件状态**：本项目正在积极开发中，可能包含 bug 或计算错误。
- 💰 **财务责任**：**使用本软件产生的任何财务损失由您自行承担**。
- 🔍 **验证要求**：实盘交易前，务必对照已知基准验证回测结果。
- 📊 **无担保**：本软件按"原样"提供，不提供任何明示或暗示的担保。

- *使用本软件即表示您承认并接受算法交易相关的所有风险。**

- --

## 📞 联系方式

- **GitHub**: [<https://github.com/cloudQuant/backtrader](<https://github.com/cloudQuant/backtrader>)>
- **Gitee**: [<https://gitee.com/yunjinqi/backtrader](<https://gitee.com/yunjinqi/backtrader>)>
- **作者博客**: [<https://yunjinqi.blog.csdn.net/](<https://yunjinqi.blog.csdn.net/>)>
- **在线文档 (EN)**: <https://backtrader.readthedocs.io/en/latest/>
- **在线文档 (ZH)**: <https://backtrader-zh.readthedocs.io/zh-cn/latest/>
- **GitHub Pages**: <https://cloudquant.github.io/backtrader/>

- --

<div align="center">

- *如果本项目对您有帮助，请点个 ⭐ Star 支持我们！**

Made with ❤️ by CloudQuant

</div>
