# backtrader

<div align="center">

[![CI Tests](https://github.com/cloudQuant/backtrader/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/cloudQuant/backtrader/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL%203.0-green)](LICENSE)

[![Code style: flake8](https://img.shields.io/badge/code%20style-flake8-black)](https://flake8.pycqa.org/)
[![GitHub stars](https://img.shields.io/github/stars/cloudQuant/backtrader?style=social)](https://github.com/cloudQuant/backtrader/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/cloudQuant/backtrader?style=social)](https://github.com/cloudQuant/backtrader/network/members)
[![Gitee](https://img.shields.io/badge/mirror-Gitee-red)](https://gitee.com/yunjinqi/backtrader)

**高性能量化交易框架 | High-performance Quantitative Trading Framework**

[English](#english) | [中文](#中文)

</div>

---

## English

### Introduction

An enhanced version of the backtrader Python library for quantitative trading and backtesting. This project maintains full compatibility with the original backtrader while adding extensive support for cryptocurrency trading, futures markets, and improved stability across Python 3.8-3.13.

### Core Features

- 🚀 **Event-Driven Architecture**: Fast and efficient event-driven backtesting engine
- 🪙 **Cryptocurrency Support**:
  - CCXT integration supporting 100+ cryptocurrency exchanges
  - Funding rate backtesting for perpetual contracts
  - Real-time and historical data streaming
  - Support for spot and futures markets
- 🏦 **Multi-Market Support**:
  - Interactive Brokers (IB) - Stocks and options
  - CTP - China Futures Market
  - Oanda - Forex trading
  - Traditional stock markets
- 📈 **Rich Technical Indicators**: 50+ built-in indicators including:
  - Trend indicators (SMA, EMA, WMA, DEMA, TEMA, HMA, KAMA)
  - Oscillators (RSI, MACD, Stochastic, CCI, Williams %R)
  - Volatility indicators (ATR, Bollinger Bands)
  - Custom indicator framework
- 📊 **Comprehensive Analyzers**: 
  - Sharpe Ratio, Calmar Ratio, Sortino Ratio
  - Maximum Drawdown analysis
  - Trade statistics and performance metrics
  - PyFolio integration
- 🎯 **Flexible Order Types**: Market, Limit, Stop, Stop-Limit, OCO orders
- 💼 **Position Sizing**: Built-in position sizers and custom sizing strategies
- 📉 **Data Processing**: Resampling, replaying, and multi-timeframe analysis

### Version Information

- **Current Version**: 1.9.76.123
- **master branch**: Stable version, compatible with official backtrader, with bug fixes
- **dev branch**: Development version with latest features and experimental functionality

### Quick Start

#### System Requirements

- Python 3.8 - 3.13 (Python 3.11 recommended for best performance)
- Operating Systems: Windows, Linux, macOS

#### Installation

**Method 1: Install via pip (Recommended)**

```bash
pip install -U git+https://gitee.com/yunjinqi/backtrader.git
```

Or from GitHub:

```bash
pip install -U git+https://github.com/cloudQuant/backtrader.git
```

**Method 2: Install from Source**

```bash
# Clone the repository
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

**Method 3: Using Anaconda**

```bash
# Create virtual environment
conda create -n backtrader python=3.11
conda activate backtrader

# Install dependencies
pip install -r requirements.txt

# Install backtrader
pip install -e .
```

#### Quick Example - Simple Moving Average Strategy

```python
import backtrader as bt
from datetime import datetime

# Create a strategy
class SMAStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        # Add moving average indicators
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
        
    def next(self):
        if not self.position:
            if self.crossover > 0:  # Fast SMA crosses above Slow SMA
                self.buy()
        elif self.crossover < 0:  # Fast SMA crosses below Slow SMA
            self.close()

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'BUY EXECUTED, Price: {order.executed.price:.2f}')
            elif order.issell():
                self.log(f'SELL EXECUTED, Price: {order.executed.price:.2f}')
                
    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

# Create Cerebro engine
cerebro = bt.Cerebro()

# Add strategy
cerebro.addstrategy(SMAStrategy)

# Load data (using sample CSV data)
data = bt.feeds.GenericCSVData(
    dataname='path/to/your/data.csv',
    dtformat='%Y-%m-%d',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
cerebro.adddata(data)

# Set initial cash
cerebro.broker.setcash(100000.0)

# Set commission
cerebro.broker.setcommission(commission=0.001)

# Add analyzers
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# Run backtest
print(f'Starting Portfolio Value: {cerebro.broker.getvalue():.2f}')
results = cerebro.run()
print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

# Print analysis
strat = results[0]
print(f'Sharpe Ratio: {strat.analyzers.sharpe.get_analysis()}')
print(f'Max Drawdown: {strat.analyzers.drawdown.get_analysis()}')

# Plot results
cerebro.plot()
```

### Main Functional Modules

#### 1. Data Feeds

Supports multiple data sources:

**File-based Data**:
- CSV files (generic and specific formats)
- Pandas DataFrame
- Yahoo Finance CSV
- MT4 CSV
- Sierra Chart files

**Live Data Feeds**:
- **CCXT**: 100+ cryptocurrency exchanges (Binance, OKX, Huobi, etc.)
- **Interactive Brokers**: Real-time stock and options data
- **CTP**: China futures market data
- **Oanda**: Forex real-time data
- **InfluxDB**: Time-series database integration

**Data Processing**:
- Resampling: Convert to different timeframes
- Replaying: Simulate real-time data
- Multi-timeframe: Use multiple periods in one strategy

#### 2. Strategy Development

**Event-Driven Framework**:
```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # Initialize indicators
        pass
        
    def prenext(self):
        # Called when not all indicators are ready
        pass
        
    def next(self):
        # Main trading logic
        pass
        
    def notify_order(self, order):
        # Order notifications
        pass
        
    def notify_trade(self, trade):
        # Trade notifications
        pass
```

**Strategy Features**:
- Multi-asset trading
- Multi-timeframe analysis
- Parameter optimization
- Position sizing
- Order management

#### 3. Technical Indicators (50+)

**Trend Indicators**:
- SMA, EMA, WMA, DEMA, TEMA, ZLEMA
- HMA (Hull Moving Average)
- KAMA (Kaufman Adaptive Moving Average)
- DMA (Double Moving Average)

**Oscillators**:
- RSI (Relative Strength Index)
- MACD (Moving Average Convergence Divergence)
- Stochastic Oscillator
- CCI (Commodity Channel Index)
- Williams %R
- RMI (Relative Momentum Index)

**Volatility Indicators**:
- ATR (Average True Range)
- Bollinger Bands
- Envelope (Moving Average Envelope)

**Other Indicators**:
- Aroon Oscillator
- Ichimoku Cloud
- Parabolic SAR
- Vortex Indicator
- DPO (Detrended Price Oscillator)
- TSI (True Strength Index)
- KST (Know Sure Thing)

**Custom Indicators**:
```python
class MyIndicator(bt.Indicator):
    lines = ('signal',)
    params = (('period', 20),)
    
    def __init__(self):
        self.lines.signal = self.data.close - bt.indicators.SMA(period=self.p.period)
```

#### 4. Order Management

**Order Types**:
- Market Orders
- Limit Orders
- Stop Orders
- Stop-Limit Orders
- Bracket Orders (Entry + Stop Loss + Take Profit)
- OCO Orders (One-Cancels-Other)

**Order Execution**:
```python
# Market order
self.buy()
self.sell()

# Limit order
self.buy(exectype=bt.Order.Limit, price=100.0)

# Stop order
self.sell(exectype=bt.Order.Stop, price=95.0)

# Close position
self.close()

# Size specification
self.buy(size=100)
```

#### 5. Performance Analysis (Analyzers)

**Built-in Analyzers**:
- **Returns**: Return analysis
- **SharpeRatio**: Risk-adjusted returns
- **DrawDown**: Maximum drawdown analysis
- **TimeReturn**: Time-series returns
- **TradeAnalyzer**: Detailed trade statistics
- **SQN**: System Quality Number
- **Calmar**: Calmar ratio
- **VWR**: Variable Weight Return
- **PyFolio**: Integration with PyFolio library

**Usage**:
```python
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.01)
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
results = cerebro.run()
print(results[0].analyzers.sharpe.get_analysis())
```

#### 6. Position Sizing

**Built-in Sizers**:
- FixedSize: Fixed position size
- PercentSizer: Percentage of portfolio
- AllInSizer: All available cash

**Custom Sizer**:
```python
class MyPositionSizer(bt.Sizer):
    params = (('percent', 0.95),)
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            return int((cash * self.params.percent) / data.close[0])
        return self.broker.getposition(data).size

cerebro.addsizer(MyPositionSizer)
```

### Advanced Usage

#### Cryptocurrency Trading with CCXT

```python
import backtrader as bt
from datetime import datetime, timedelta

# Create cerebro
cerebro = bt.Cerebro()

# Configure CCXT store
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'YOUR_API_KEY',
        'secret': 'YOUR_SECRET',
        'enableRateLimit': True,
    },
    retries=5,
    debug=False
)

# Historical data
hist_start = datetime.utcnow() - timedelta(days=30)
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    fromdate=hist_start,
    compression=60,  # 1-hour bars
    ohlcv_limit=1000
)

cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# Use CCXT broker
broker = store.getbroker()
cerebro.setbroker(broker)

# Run
cerebro.run()
```

#### Parameter Optimization

```python
# Add strategy with parameter ranges
cerebro.optstrategy(
    SMAStrategy,
    fast_period=range(5, 20),
    slow_period=range(20, 50)
)

# Run optimization
results = cerebro.run(maxcpus=4)  # Use 4 CPU cores

# Analyze results
for result in results:
    for strat in result:
        print(f'Fast: {strat.p.fast_period}, Slow: {strat.p.slow_period}, '
              f'Final Value: {cerebro.broker.getvalue():.2f}')
```

#### Multi-Timeframe Analysis

```python
class MultiTimeframeStrategy(bt.Strategy):
    def __init__(self):
        # Daily data (data0)
        self.sma_daily = bt.indicators.SMA(self.data0, period=50)
        
        # Hourly data (data1) - resampled
        self.sma_hourly = bt.indicators.SMA(self.data1, period=20)
    
    def next(self):
        # Use both timeframes for decision making
        if self.sma_hourly[0] > self.sma_daily[0]:
            if not self.position:
                self.buy()

# Load daily data
data_daily = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=start, todate=end)
cerebro.adddata(data_daily)

# Resample to hourly
data_hourly = cerebro.resampledata(data_daily, timeframe=bt.TimeFrame.Minutes, compression=60)
```

#### Funding Rate Backtesting (Crypto Perpetual Contracts)

```python
# Example for perpetual contract with funding rate
class FundingRateStrategy(bt.Strategy):
    def __init__(self):
        self.funding_rate = self.data.funding_rate  # If available in data feed
        
    def next(self):
        # Account for funding rate in position cost
        if self.position:
            funding_cost = self.position.size * self.data.close[0] * self.funding_rate[0]
            # Adjust strategy based on funding rate
```

### Documentation & Resources

- 📚 [Official Backtrader Documentation](https://www.backtrader.com/)
- 📝 [CSDN Tutorial Series (Chinese)](https://blog.csdn.net/qq_26948675/category_10220116.html)
- 💬 [Issue Tracker - Gitee](https://gitee.com/yunjinqi/backtrader/issues)
- 💬 [Issue Tracker - GitHub](https://github.com/cloudQuant/backtrader/issues)
- 🔧 [Development Guide](CLAUDE.md)

### Testing

```bash
# Run all tests
pytest tests

# Run with coverage
pytest tests --cov=backtrader --cov-report=html

# Run specific test category
pytest tests/original_tests  # Core functionality
pytest tests/funding_rate_examples  # Crypto features

# Run in parallel
pytest tests -n 4
```

### Contributing

We welcome code contributions, bug reports, and feature suggestions:

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Changelog

#### 2024 Updates
- ✅ Added funding rate backtesting support for cryptocurrency perpetual contracts
- ✅ Fixed Python 3.12 and 3.13 compatibility issues
- ✅ Improved CCXT integration stability
- ✅ Added CI/CD automated testing
- ✅ Enhanced documentation

#### 2023 Updates
- ✅ Improved multi-exchange support
- ✅ Fixed multiple known bugs
- ✅ Enhanced CTP integration

For detailed changelog, see [CHANGELOG.md](CHANGELOG.md) (if available)

### License

This project is open source under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.

### Acknowledgments

- Thanks to [Daniel Rodriguez](https://github.com/mementum) for creating the original backtrader
- Thanks to all contributors for their support and help
- Special thanks to the CCXT team for their excellent library

### Contact

- Author: cloudQuant
- Email: yunjinqi@qq.com
- Blog: [CSDN](https://blog.csdn.net/qq_26948675)

---

## 中文

### 简介

backtrader 的增强版本，专注于量化交易和回测。本项目在保持与原版 backtrader 完全兼容的基础上，增加了对加密货币交易、期货市场的广泛支持，并改进了 Python 3.8-3.13 的稳定性。

### 核心特性

- 🚀 **事件驱动架构**：快速高效的事件驱动回测引擎
- 🪙 **加密货币支持**：
  - CCXT 集成，支持 100+ 加密货币交易所
  - 永续合约资金费率回测
  - 实时和历史数据流
  - 支持现货和期货市场
- 🏦 **多市场支持**：
  - Interactive Brokers (IB) - 股票和期权
  - CTP - 中国期货市场
  - Oanda - 外汇交易
  - 传统股票市场
- 📈 **丰富的技术指标**：50+ 内置指标，包括：
  - 趋势指标（SMA、EMA、WMA、DEMA、TEMA、HMA、KAMA）
  - 震荡指标（RSI、MACD、Stochastic、CCI、Williams %R）
  - 波动率指标（ATR、布林带）
  - 自定义指标框架
- 📊 **全面的分析器**：
  - 夏普比率、卡玛比率、索提诺比率
  - 最大回撤分析
  - 交易统计和性能指标
  - PyFolio 集成
- 🎯 **灵活的订单类型**：市价单、限价单、止损单、止损限价单、OCO 订单
- 💼 **仓位管理**：内置仓位管理器和自定义仓位策略
- 📉 **数据处理**：重采样、回放和多时间周期分析

### 版本说明

- **当前版本**：1.9.76.123
- **master 分支**：稳定版本，与官方 backtrader 兼容，修复了已知 bug
- **dev 分支**：开发版本，包含最新特性和实验性功能

### 快速开始

#### 系统要求

- Python 3.8 - 3.13（推荐使用 Python 3.11 以获得最佳性能）
- 操作系统：Windows、Linux、macOS

#### 安装方法

**方法1：使用 pip 安装（推荐）**

```bash
pip install -U git+https://gitee.com/yunjinqi/backtrader.git
```

或从 GitHub 安装：

```bash
pip install -U git+https://github.com/cloudQuant/backtrader.git
```

**方法2：从源码安装**

```bash
# 克隆项目
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# 安装依赖
pip install -r requirements.txt

# 安装包
pip install -e .
```

**方法3：使用 Anaconda**

```bash
# 创建虚拟环境
conda create -n backtrader python=3.11
conda activate backtrader

# 安装依赖
pip install -r requirements.txt

# 安装 backtrader
pip install -e .
```

#### 快速示例 - 简单移动平均线策略

```python
import backtrader as bt
from datetime import datetime

# 创建策略
class SMAStrategy(bt.Strategy):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
    )

    def __init__(self):
        # 添加移动平均线指标
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
        
    def next(self):
        if not self.position:
            if self.crossover > 0:  # 快线上穿慢线
                self.buy()
        elif self.crossover < 0:  # 快线下穿慢线
            self.close()

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f'买入执行, 价格: {order.executed.price:.2f}')
            elif order.issell():
                self.log(f'卖出执行, 价格: {order.executed.price:.2f}')
                
    def log(self, txt):
        dt = self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')

# 创建 Cerebro 引擎
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(SMAStrategy)

# 加载数据（使用示例 CSV 数据）
data = bt.feeds.GenericCSVData(
    dataname='path/to/your/data.csv',
    dtformat='%Y-%m-%d',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
cerebro.adddata(data)

# 设置初始资金
cerebro.broker.setcash(100000.0)

# 设置佣金
cerebro.broker.setcommission(commission=0.001)

# 添加分析器
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# 运行回测
print(f'初始资产价值: {cerebro.broker.getvalue():.2f}')
results = cerebro.run()
print(f'最终资产价值: {cerebro.broker.getvalue():.2f}')

# 打印分析结果
strat = results[0]
print(f'夏普比率: {strat.analyzers.sharpe.get_analysis()}')
print(f'最大回撤: {strat.analyzers.drawdown.get_analysis()}')

# 绘制结果
cerebro.plot()
```

### 主要功能模块

#### 1. 数据源 (Data Feeds)

支持多种数据源：

**基于文件的数据**：
- CSV 文件（通用和特定格式）
- Pandas DataFrame
- Yahoo Finance CSV
- MT4 CSV
- Sierra Chart 文件

**实时数据源**：
- **CCXT**：100+ 加密货币交易所（Binance、OKX、Huobi 等）
- **Interactive Brokers**：实时股票和期权数据
- **CTP**：中国期货市场数据
- **Oanda**：外汇实时数据
- **InfluxDB**：时序数据库集成

**数据处理**：
- 重采样：转换到不同时间周期
- 回放：模拟实时数据
- 多时间周期：在一个策略中使用多个周期

#### 2. 策略开发 (Strategies)

**事件驱动框架**：
```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 初始化指标
        pass
        
    def prenext(self):
        # 当指标未全部就绪时调用
        pass
        
    def next(self):
        # 主要交易逻辑
        pass
        
    def notify_order(self, order):
        # 订单通知
        pass
        
    def notify_trade(self, trade):
        # 交易通知
        pass
```

**策略特性**：
- 多品种交易
- 多时间周期分析
- 参数优化
- 仓位管理
- 订单管理

#### 3. 技术指标 (50+)

**趋势指标**：
- SMA、EMA、WMA、DEMA、TEMA、ZLEMA
- HMA（赫尔移动平均线）
- KAMA（考夫曼自适应移动平均线）
- DMA（双移动平均线）

**震荡指标**：
- RSI（相对强弱指标）
- MACD（异同移动平均线）
- Stochastic（随机指标）
- CCI（商品通道指标）
- Williams %R（威廉指标）
- RMI（相对动量指标）

**波动率指标**：
- ATR（真实波动幅度）
- 布林带
- 包络线

**其他指标**：
- Aroon 振荡器
- Ichimoku 云图
- 抛物线 SAR
- Vortex 指标
- DPO（去趋势价格振荡器）
- TSI（真实强度指标）
- KST（Know Sure Thing）

**自定义指标**：
```python
class MyIndicator(bt.Indicator):
    lines = ('signal',)
    params = (('period', 20),)
    
    def __init__(self):
        self.lines.signal = self.data.close - bt.indicators.SMA(period=self.p.period)
```

#### 4. 订单管理 (Orders)

**订单类型**：
- 市价单
- 限价单
- 止损单
- 止损限价单
- 括号订单（入场 + 止损 + 止盈）
- OCO 订单（一取消全部）

**订单执行**：
```python
# 市价单
self.buy()
self.sell()

# 限价单
self.buy(exectype=bt.Order.Limit, price=100.0)

# 止损单
self.sell(exectype=bt.Order.Stop, price=95.0)

# 平仓
self.close()

# 指定数量
self.buy(size=100)
```

#### 5. 性能分析 (Analyzers)

**内置分析器**：
- **Returns**：收益率分析
- **SharpeRatio**：夏普比率
- **DrawDown**：最大回撤分析
- **TimeReturn**：时间序列收益
- **TradeAnalyzer**：详细交易统计
- **SQN**：系统质量数
- **Calmar**：卡玛比率
- **VWR**：可变权重收益
- **PyFolio**：PyFolio 库集成

**使用方法**：
```python
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.01)
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
results = cerebro.run()
print(results[0].analyzers.sharpe.get_analysis())
```

#### 6. 仓位管理 (Position Sizing)

**内置仓位管理器**：
- FixedSize：固定仓位大小
- PercentSizer：按投资组合百分比
- AllInSizer：全部可用资金

**自定义仓位管理器**：
```python
class MyPositionSizer(bt.Sizer):
    params = (('percent', 0.95),)
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            return int((cash * self.params.percent) / data.close[0])
        return self.broker.getposition(data).size

cerebro.addsizer(MyPositionSizer)
```

### 进阶使用

#### CCXT 加密货币交易

```python
import backtrader as bt
from datetime import datetime, timedelta

# 创建 cerebro
cerebro = bt.Cerebro()

# 配置 CCXT 存储
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'YOUR_API_KEY',
        'secret': 'YOUR_SECRET',
        'enableRateLimit': True,
    },
    retries=5,
    debug=False
)

# 历史数据
hist_start = datetime.utcnow() - timedelta(days=30)
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    fromdate=hist_start,
    compression=60,  # 1小时K线
    ohlcv_limit=1000
)

cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# 使用 CCXT 经纪商
broker = store.getbroker()
cerebro.setbroker(broker)

# 运行
cerebro.run()
```

#### 参数优化

```python
# 添加带参数范围的策略
cerebro.optstrategy(
    SMAStrategy,
    fast_period=range(5, 20),
    slow_period=range(20, 50)
)

# 运行优化
results = cerebro.run(maxcpus=4)  # 使用4个CPU核心

# 分析结果
for result in results:
    for strat in result:
        print(f'快线: {strat.p.fast_period}, 慢线: {strat.p.slow_period}, '
              f'最终价值: {cerebro.broker.getvalue():.2f}')
```

#### 多时间周期分析

```python
class MultiTimeframeStrategy(bt.Strategy):
    def __init__(self):
        # 日线数据 (data0)
        self.sma_daily = bt.indicators.SMA(self.data0, period=50)
        
        # 小时数据 (data1) - 重采样
        self.sma_hourly = bt.indicators.SMA(self.data1, period=20)
    
    def next(self):
        # 使用两个时间周期进行决策
        if self.sma_hourly[0] > self.sma_daily[0]:
            if not self.position:
                self.buy()

# 加载日线数据
data_daily = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=start, todate=end)
cerebro.adddata(data_daily)

# 重采样为小时数据
data_hourly = cerebro.resampledata(data_daily, timeframe=bt.TimeFrame.Minutes, compression=60)
```

#### 资金费率回测（加密货币永续合约）

```python
# 永续合约资金费率示例
class FundingRateStrategy(bt.Strategy):
    def __init__(self):
        self.funding_rate = self.data.funding_rate  # 如果数据源中有
        
    def next(self):
        # 在持仓成本中考虑资金费率
        if self.position:
            funding_cost = self.position.size * self.data.close[0] * self.funding_rate[0]
            # 根据资金费率调整策略
```

### 文档与资源

- 📚 [官方 Backtrader 文档](https://www.backtrader.com/)
- 📝 [CSDN 教程系列](https://blog.csdn.net/qq_26948675/category_10220116.html)
- 💬 [问题反馈 - Gitee](https://gitee.com/yunjinqi/backtrader/issues)
- 💬 [问题反馈 - GitHub](https://github.com/cloudQuant/backtrader/issues)
- 🔧 [开发指南](CLAUDE.md)

### 测试

```bash
# 运行所有测试
pytest tests

# 运行测试并查看覆盖率
pytest tests --cov=backtrader --cov-report=html

# 运行特定测试类别
pytest tests/original_tests  # 核心功能
pytest tests/funding_rate_examples  # 加密货币特性

# 并行运行
pytest tests -n 4
```

### 贡献指南

欢迎贡献代码、报告问题或提出新功能建议：

1. Fork 本仓库
2. 创建您的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 更新日志

#### 2024年更新
- ✅ 增加了加密货币永续合约资金费率回测支持
- ✅ 修复了 Python 3.12 和 3.13 兼容性问题
- ✅ 改进了 CCXT 集成稳定性
- ✅ 添加了 CI/CD 自动化测试
- ✅ 增强了文档

#### 2023年更新
- ✅ 改进了多交易所支持
- ✅ 修复了多个已知 bug
- ✅ 增强了 CTP 集成

详细更新日志请查看 [CHANGELOG.md](CHANGELOG.md)（如果有）

### 许可证

本项目基于 GNU General Public License v3.0 开源，详见 [LICENSE](LICENSE) 文件。

### 致谢

- 感谢 [Daniel Rodriguez](https://github.com/mementum) 创建了原始的 backtrader
- 感谢所有贡献者的支持与帮助
- 特别感谢 CCXT 团队提供的优秀库

### 联系方式

- 作者：cloudQuant
- 邮箱：yunjinqi@qq.com
- 博客：[CSDN](https://blog.csdn.net/qq_26948675)

### 镜像仓库 / Mirror Repositories

- 主仓库 / Main: https://gitee.com/yunjinqi/backtrader
- 镜像 / Mirror: https://github.com/cloudQuant/backtrader

---

<div align="center">

**[⬆ 回到顶部](#backtrader) | [English](#english) | [中文](#中文)**

⭐ 如果这个项目对您有帮助，请给个 Star 支持一下！| If this project helps you, please give it a Star!

Made with ❤️ by [cloudQuant](https://github.com/cloudQuant)

</div>
