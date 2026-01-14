<div align="center">

# 🚀 Backtrader

**Professional Python Algorithmic Trading Backtesting Framework**

[![Version](https://img.shields.io/badge/Version-1.0.0-blue.svg)]()
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPLv3-orange.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

**English** | [**中文**](README.md)

[📖 Documentation](https://gitee.com/cloudquant/backtrader/wikis) · 
[🐛 Report Bug](https://gitee.com/cloudquant/backtrader/issues) · 
[💬 Discussions](https://gitee.com/cloudquant/backtrader/issues)

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
- **dev branch**: Development version, exploring C++ rewrite for high-frequency support

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
# Clone from Gitee
git clone https://gitee.com/cloudquant/backtrader.git
cd backtrader

# Or clone from GitHub
git clone https://github.com/cloudquant/backtrader.git
cd backtrader

# Install dependencies
pip install -r requirements.txt

# Install backtrader
pip install -e .
```

### Option 2: With Cython Acceleration

```bash
# macOS / Linux
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U ./

# Windows
cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U ./
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
    # Strategy parameters (adjustable at runtime)
    params = (
        ('fast_period', 10),   # Fast SMA period
        ('slow_period', 30),   # Slow SMA period
    )
    
    def __init__(self):
        """Initialize: Calculate indicators (runs once)"""
        # Calculate SMAs
        self.fast_sma = bt.indicators.SMA(
            self.data.close, 
            period=self.params.fast_period
        )
        self.slow_sma = bt.indicators.SMA(
            self.data.close, 
            period=self.params.slow_period
        )
        # Calculate crossover signal
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
    
    def next(self):
        """Trading logic executed each bar"""
        if not self.position:  # No position
            if self.crossover > 0:  # Golden cross
                self.buy()  # Buy
        else:  # Has position
            if self.crossover < 0:  # Death cross
                self.close()  # Close position
```

### Step 3: Prepare Data

```python
# Option 1: Load from CSV file
data = bt.feeds.GenericCSVData(
    dataname='your_data.csv',
    datetime=0,      # Date column index
    open=1,          # Open price column index
    high=2,          # High price column index
    low=3,           # Low price column index
    close=4,         # Close price column index
    volume=5,        # Volume column index
    openinterest=-1, # No open interest
    dtformat='%Y-%m-%d',  # Date format
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
# Create backtest engine
cerebro = bt.Cerebro()

# Add data
cerebro.adddata(data)

# Add strategy
cerebro.addstrategy(SmaCrossStrategy)

# Set initial capital
cerebro.broker.setcash(100000)

# Set commission (0.03%)
cerebro.broker.setcommission(commission=0.0003)

# Add analyzers
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# Run backtest
print(f'Starting Portfolio Value: {cerebro.broker.getvalue():,.2f}')
results = cerebro.run()
print(f'Final Portfolio Value: {cerebro.broker.getvalue():,.2f}')

# Get analysis results
strat = results[0]
sharpe = strat.analyzers.sharpe.get_analysis()
drawdown = strat.analyzers.drawdown.get_analysis()
trades = strat.analyzers.trades.get_analysis()

print(f"Sharpe Ratio: {sharpe.get('sharperatio', 'N/A')}")
print(f"Max Drawdown: {drawdown['max']['drawdown']:.2f}%")
print(f"Total Trades: {trades['total']['total']}")
```

### Step 5: Visualize Results

```python
# Use Plotly interactive charts (recommended)
cerebro.plot(backend='plotly', style='candle')

# Or use traditional Matplotlib
cerebro.plot()

# Save to HTML file
from backtrader.plot import PlotlyPlot
plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html('backtest_chart.html')
```

---

## 📚 Core Concepts

### 1. Cerebro - The Engine

Cerebro is the core engine that coordinates all components.

```python
cerebro = bt.Cerebro()

# Core methods
cerebro.adddata(data)              # Add data
cerebro.addstrategy(Strategy)      # Add strategy
cerebro.addanalyzer(Analyzer)      # Add analyzer
cerebro.addobserver(Observer)      # Add observer
cerebro.addsizer(Sizer)            # Add position sizer
cerebro.broker.setcash(100000)     # Set initial capital
cerebro.broker.setcommission(0.001) # Set commission
results = cerebro.run()            # Run backtest
cerebro.plot()                     # Plot results
```

### 2. Strategy

Strategy is the core of trading logic. Must implement `next()` method.

```python
class MyStrategy(bt.Strategy):
    params = (
        ('param1', 10),
        ('param2', 0.5),
    )
    
    def __init__(self):
        """Initialize indicators and variables"""
        self.sma = bt.indicators.SMA(period=self.params.param1)
    
    def next(self):
        """Trading logic for each bar"""
        pass
    
    def notify_order(self, order):
        """Order status change notification"""
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f'BUY EXECUTED: {order.executed.price}')
            else:
                print(f'SELL EXECUTED: {order.executed.price}')
    
    def notify_trade(self, trade):
        """Trade completion notification"""
        if trade.isclosed:
            print(f'Trade P&L: {trade.pnl:.2f}')
```

### 3. Lines - Data Structure

Backtrader's core data structure for time-series data access.

```python
# Accessing data in strategy
self.data.close[0]     # Current bar's close price
self.data.close[-1]    # Previous bar's close price
self.data.close[-2]    # Two bars ago close price
self.data.open[0]      # Current bar's open price
self.data.high[0]      # Current bar's high price
self.data.low[0]       # Current bar's low price
self.data.volume[0]    # Current bar's volume
self.data.datetime[0]  # Current bar's datetime (numeric)

# Convert to datetime
current_dt = bt.num2date(self.data.datetime[0])
```

### 4. Order Types

```python
# Market orders
self.buy()                          # Market buy
self.sell()                         # Market sell
self.close()                        # Close position

# Limit orders
self.buy(price=100, exectype=bt.Order.Limit)
self.sell(price=110, exectype=bt.Order.Limit)

# Stop orders
self.sell(price=95, exectype=bt.Order.Stop)

# Bracket orders (entry + stop loss + take profit)
self.buy_bracket(
    price=100,           # Entry price
    stopprice=95,        # Stop loss price
    limitprice=110,      # Take profit price
)

# Specify quantity
self.buy(size=100)      # Buy 100 shares

# Target position
self.order_target_size(target=100)    # Adjust to 100 shares
self.order_target_percent(target=0.5) # Adjust to 50% of portfolio
self.order_target_value(target=10000) # Adjust to $10,000 value
```

---

## 📦 Built-in Components

### Technical Indicators (50+)

| Category | Indicators |
|----------|------------|
| **Moving Averages** | SMA, EMA, WMA, SMMA, DEMA, TEMA, KAMA, HMA, ZLEMA |
| **Momentum** | RSI, ROC, Momentum, Williams %R, Ultimate Oscillator |
| **Volatility** | ATR, Bollinger Bands, Standard Deviation, True Range |
| **Trend** | ADX, Aroon, Parabolic SAR, Ichimoku, DPO |
| **Oscillators** | MACD, Stochastic, CCI, TSI, TRIX |
| **Volume** | OBV, MFI, AD, Volume Oscillator |
| **Other** | Pivot Points, Heikin Ashi, CrossOver |

### Analyzers (17+)

| Analyzer | Purpose |
|----------|---------|
| `SharpeRatio` | Sharpe ratio calculation |
| `DrawDown` | Maximum drawdown |
| `TradeAnalyzer` | Trade statistics |
| `Returns` | Return analysis |
| `AnnualReturn` | Annual returns |
| `Calmar` | Calmar ratio |
| `SQN` | System Quality Number |
| `VWR` | Variability-Weighted Return |
| `TimeReturn` | Time-weighted returns |
| `PyFolio` | PyFolio integration |
| `Positions` | Position analysis |
| `Transactions` | Transaction log |
| `Leverage` | Leverage analysis |

### Data Sources (20+)

| Data Source | Description |
|-------------|-------------|
| `GenericCSVData` | Generic CSV files |
| `PandasData` | Pandas DataFrame |
| `YahooFinanceData` | Yahoo Finance |
| `IBData` | Interactive Brokers |
| `CCXTFeed` | CCXT cryptocurrency |
| `OandaData` | Oanda forex |
| `QuandlData` | Quandl data |
| `InfluxData` | InfluxDB |
| `VCData` | VisualChart |

---

## 🔬 Advanced Topics

### Parameter Optimization

```python
# Grid search optimization
cerebro.optstrategy(
    SmaCrossStrategy,
    fast_period=range(5, 20, 5),    # 5, 10, 15
    slow_period=range(20, 60, 10),  # 20, 30, 40, 50
)

# Run optimization
results = cerebro.run(maxcpus=4)  # Use 4 cores

# Get best parameters
for result in results:
    strat = result[0]
    sharpe = strat.analyzers.sharpe.get_analysis()
    print(f"Params: fast={strat.params.fast_period}, slow={strat.params.slow_period}")
    print(f"Sharpe: {sharpe.get('sharperatio', 'N/A')}")
```

### Multiple Data Sources

```python
# Add multiple data sources
data1 = bt.feeds.PandasData(dataname=df1, name='stock1')
data2 = bt.feeds.PandasData(dataname=df2, name='stock2')

cerebro.adddata(data1)
cerebro.adddata(data2)

# Access in strategy
class MultiDataStrategy(bt.Strategy):
    def next(self):
        # Access first data source
        price1 = self.datas[0].close[0]
        # Access second data source
        price2 = self.datas[1].close[0]
        
        # Or access by name
        # self.getdatabyname('stock1').close[0]
```

### Custom Indicators

```python
class MyIndicator(bt.Indicator):
    """Custom indicator example"""
    lines = ('myline',)  # Define output lines
    params = (('period', 20),)  # Define parameters
    
    def __init__(self):
        self.lines.myline = bt.indicators.SMA(
            self.data.close, 
            period=self.params.period
        ) * 2 - bt.indicators.SMA(
            self.data.close, 
            period=self.params.period * 2
        )
```

### Custom Analyzers

```python
class MyAnalyzer(bt.Analyzer):
    """Custom analyzer example"""
    
    def __init__(self):
        self.returns = []
    
    def next(self):
        self.returns.append(self.strategy.broker.getvalue())
    
    def get_analysis(self):
        return {
            'total_return': (self.returns[-1] / self.returns[0] - 1) * 100,
            'max_value': max(self.returns),
            'min_value': min(self.returns),
        }
```

### Professional Reports

```python
# Add analyzers required for reporting
cerebro.add_report_analyzers(riskfree_rate=0.02)

# Run backtest
results = cerebro.run()

# Generate HTML report
cerebro.generate_report(
    'backtest_report.html',
    user='Quant Researcher',
    memo='SMA Crossover Strategy Report'
)

# Generate PDF report
cerebro.generate_report('backtest_report.pdf', format='pdf')

# Export JSON data
cerebro.generate_report('backtest_data.json', format='json')
```

---

## 🏗 Project Architecture

```
backtrader/
├── backtrader/                 # Core codebase
│   ├── __init__.py            # Package entry
│   ├── version.py             # Version info
│   │
│   ├── # === Core Engine ===
│   ├── cerebro.py             # Main engine (88KB)
│   ├── strategy.py            # Strategy base (100KB)
│   │
│   ├── # === Data System ===
│   ├── linebuffer.py          # Line buffer (103KB)
│   ├── lineiterator.py        # Iterator (95KB)
│   ├── lineseries.py          # Line series (76KB)
│   ├── lineroot.py            # Root class (37KB)
│   ├── dataseries.py          # Data series (12KB)
│   ├── feed.py                # Data feed base (51KB)
│   ├── feeds/                 # Data sources (21)
│   │
│   ├── # === Trading System ===
│   ├── broker.py              # Broker base
│   ├── brokers/               # Broker implementations
│   ├── order.py               # Order class (37KB)
│   ├── trade.py               # Trade class (16KB)
│   ├── position.py            # Position class (11KB)
│   ├── comminfo.py            # Commission (16KB)
│   │
│   ├── # === Indicator System ===
│   ├── indicator.py           # Indicator base (15KB)
│   ├── indicators/            # Technical indicators (52)
│   │
│   ├── # === Analysis System ===
│   ├── analyzer.py            # Analyzer base (21KB)
│   ├── analyzers/             # Analyzers (17)
│   │
│   ├── # === Visualization ===
│   ├── plot/                  # Plotting module
│   ├── bokeh/                 # Bokeh charts
│   ├── reports/               # Report generation
│   │
│   ├── # === Other Modules ===
│   ├── sizer.py               # Position sizing
│   ├── sizers/                # Sizer implementations
│   ├── observer.py            # Observer base
│   ├── observers/             # Observers
│   ├── filters/               # Data filters
│   ├── timer.py               # Timer
│   ├── signal.py              # Signal system
│   ├── metabase.py            # Metaclass system (83KB)
│   └── parameters.py          # Parameter system (76KB)
│
├── examples/                   # Example code
├── tests/                      # Test cases
├── docs/                       # Documentation
├── requirements.txt            # Dependencies
├── setup.py                   # Install script
├── README.md                  # Chinese README
└── README.en.md               # English README
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
cerebro.addstrategy(Strategy, param1=value1)
cerebro.addanalyzer(bt.analyzers.SharpeRatio)
cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.001)
results = cerebro.run()
cerebro.plot()

# Strategy
self.buy(size=100)
self.sell(size=100)
self.close()
self.order_target_percent(target=0.5)
self.position.size  # Current position
self.broker.getvalue()  # Portfolio value
self.broker.getcash()  # Available cash

# Data
self.data.close[0]   # Current close
self.data.close[-1]  # Previous close
len(self.data)       # Bars processed

# Indicators
bt.indicators.SMA(data, period=20)
bt.indicators.EMA(data, period=20)
bt.indicators.RSI(data, period=14)
bt.indicators.MACD(data)
bt.indicators.BollingerBands(data)
bt.indicators.ATR(data)
bt.indicators.CrossOver(line1, line2)
```

---

## ❓ FAQ

### Q1: How to handle adjusted prices?

```python
# Recommend using adjusted prices for backtesting
data = bt.feeds.PandasData(
    dataname=df,
    adjclose=True,  # Use adjusted close
)
```

### Q2: How to set slippage?

```python
cerebro.broker.set_slippage_fixed(0.01)  # Fixed slippage
cerebro.broker.set_slippage_perc(0.001)  # Percentage slippage
```

### Q3: How to limit trade size?

```python
class FixedSizer(bt.Sizer):
    params = (('stake', 100),)
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        return self.params.stake

cerebro.addsizer(FixedSizer, stake=100)
```

### Q4: How to get all transactions?

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()
transactions = results[0].analyzers.txn.get_analysis()
```

### Q5: Backtest too slow?

```python
# 1. Use runonce mode (default)
cerebro.run(runonce=True)

# 2. Reduce data size
# 3. Install Cython acceleration
# 4. Use multiprocessing (for optimization)
cerebro.run(maxcpus=4)
```

---

## 🤝 Contributing

We welcome all contributions!

### Reporting Issues

1. Check if a similar issue exists
2. Provide detailed reproduction steps
3. Include error logs and environment info

### Submitting Code

```bash
# 1. Fork the repository
# 2. Create a branch
git checkout -b feature/your-feature

# 3. Commit changes
git commit -m "feat: add your feature"

# 4. Push branch
git push origin feature/your-feature

# 5. Create Pull Request
```

### Code Guidelines

- Follow PEP 8
- Add appropriate docstrings
- Write unit tests

---

## 📄 License

This project is licensed under [GPLv3](LICENSE).

---

## 📞 Contact

- **Gitee**: [https://gitee.com/cloudquant/backtrader](https://gitee.com/cloudquant/backtrader)
- **GitHub**: [https://github.com/cloudquant/backtrader](https://github.com/cloudquant/backtrader)
- **Author Blog**: [https://yunjinqi.blog.csdn.net/](https://yunjinqi.blog.csdn.net/)
- **Issues**: [https://gitee.com/cloudquant/backtrader/issues](https://gitee.com/cloudquant/backtrader/issues)

---

<div align="center">

**If this project helps you, please give us a ⭐ Star!**

Made with ❤️ by CloudQuant

</div>



