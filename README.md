# backtrader

<div align="center">

[![CI Tests](https://github.com/cloudQuant/backtrader/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/cloudQuant/backtrader/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL%203.0-green)](LICENSE)
[![PyPI](https://img.shields.io/badge/pypi-v1.9.76.123-orange)](https://pypi.org/project/backtrader/)

[![Code style: flake8](https://img.shields.io/badge/code%20style-flake8-black)](https://flake8.pycqa.org/)
[![GitHub stars](https://img.shields.io/github/stars/cloudQuant/backtrader?style=social)](https://github.com/cloudQuant/backtrader/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/cloudQuant/backtrader?style=social)](https://github.com/cloudQuant/backtrader/network/members)
[![Gitee](https://img.shields.io/badge/mirror-Gitee-red)](https://gitee.com/yunjinqi/backtrader)

**High-performance quantitative trading framework | 高性能量化交易框架**

[English](#english) | [中文](#中文)

</div>

---

## English

### Introduction

A high-performance quantitative research tool built on backtrader, focused on medium-to-low frequency trading strategies with Cython/Numba optimizations for improved backtesting efficiency. This project is an enhanced version of backtrader that maintains compatibility while adding numerous practical features.

### Core Features

- 🚀 **Performance Optimization**: Core computation modules optimized with Cython and Numba for significantly faster backtesting
- 📊 **Vectorized Backtesting**: Support for Time Series (TS) and Cross-Sectional (CS) vectorized backtesting frameworks
- 🪙 **Cryptocurrency Support**:
  - CCXT integration supporting 100+ cryptocurrency exchanges
  - Funding rate backtesting for crypto perpetual contracts
  - Real-time data streaming and historical data backtesting
- 🏦 **Multi-Market Support**:
  - Interactive Brokers (IB) integration
  - CTP futures trading interface
  - Oanda forex trading
  - Traditional stock markets
- 📈 **Rich Technical Indicators**: 60+ built-in technical indicators with custom indicator development support
- 📝 **Strategy Analyzers**: Multiple performance analysis tools (Sharpe ratio, maximum drawdown, SQN, etc.)

### Version Information

- **master branch**: Stable version, compatible with official backtrader, with known bugs fixed
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

#### Quick Example

```python
import backtrader as bt
import pandas as pd
from datetime import datetime

# Create a strategy
class SMAStrategy(bt.Strategy):
    params = (
        ('maperiod', 15),
    )

    def __init__(self):
        # Add moving average indicator
        self.sma = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.maperiod)
        
    def next(self):
        # Buy logic
        if self.data.close[0] > self.sma[0]:
            if not self.position:
                self.buy()
        # Sell logic
        elif self.position:
            self.sell()

# Create Cerebro engine
cerebro = bt.Cerebro()

# Add strategy
cerebro.addstrategy(SMAStrategy)

# Load data
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)
cerebro.adddata(data)

# Set initial cash
cerebro.broker.setcash(100000.0)

# Run backtest
results = cerebro.run()

# Print final portfolio value
print(f'Final Portfolio Value: {cerebro.broker.getvalue():.2f}')

# Plot results
cerebro.plot()
```

### Main Functional Modules

#### 1. Data Feeds
- CSV file import
- Pandas DataFrame
- Real-time data streams (IB, CCXT, CTP)
- Online data sources (Yahoo Finance, Quandl, etc.)

#### 2. Strategy Development
- Event-driven strategy framework
- Vectorized strategy framework (CS/TS)
- Multi-asset, multi-timeframe strategy support
- Signal system

#### 3. Technical Indicators
- Moving average series (SMA, EMA, WMA, etc.)
- Oscillators (RSI, MACD, Stochastic, etc.)
- Volatility indicators (ATR, Bollinger Bands, etc.)
- Custom indicator development framework

#### 4. Order Management
- Market orders, limit orders, stop orders
- Bracket orders
- OCO orders (One-Cancels-Other)
- Order validity management

#### 5. Performance Analysis (Analyzers)
- Returns analysis
- Sharpe ratio
- Maximum drawdown
- Trade statistics
- Custom analyzers

### Advanced Usage

#### Cryptocurrency Trading Example

```python
from datetime import datetime, timedelta
import backtrader as bt
from backtrader.feeds import CCXT

# Use CCXT data source
cerebro = bt.Cerebro()

# Configure exchange
config = {'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET'}
store = bt.stores.CCXTStore(exchange='binance', config=config)

# Get data
hist_start_date = datetime.utcnow() - timedelta(days=30)
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    fromdate=hist_start_date,
    compression=60  # 60-minute bars
)

cerebro.adddata(data)
```

#### Vectorized Backtesting Example

```python
# Time series vectorized strategy
from backtrader.vectors import TimeSeriesStrategy

class MyTSStrategy(TimeSeriesStrategy):
    def compute_signal(self, data):
        # Use numpy for vectorized calculations
        sma_20 = data['close'].rolling(20).mean()
        sma_50 = data['close'].rolling(50).mean()
        
        # Generate signals
        signal = (sma_20 > sma_50).astype(int)
        return signal
```

### Documentation & Resources

- 📚 [Official Documentation](https://www.backtrader.com/)
- 📝 [CSDN Tutorial Series](https://blog.csdn.net/qq_26948675/category_10220116.html)
- 💬 [Issue Tracker](https://gitee.com/yunjinqi/backtrader/issues)
- 🔧 [Development Guide](CONTRIBUTING.md)

### Performance Comparison

Performance improvements with Cython optimization:

| Module | Original Speed | Optimized Speed | Improvement |
|--------|---------------|-----------------|-------------|
| Indicator Calculations | 1.00x | 3-5x | 200-400% |
| Vectorized Backtesting | N/A | 10-20x | - |
| Order Matching | 1.00x | 2-3x | 100-200% |

### Contributing

We welcome code contributions, bug reports, and feature suggestions:

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Changelog

#### Latest Updates 2024
- ✅ Added funding rate backtesting support for cryptocurrency
- ✅ Fixed Python 3.12+ compatibility issues
- ✅ Optimized Cython compilation process
- ✅ Added CI/CD automated testing

#### 2023 Updates
- ✅ Implemented Time Series (TS) vectorized backtesting framework
- ✅ Optimized Cross-Sectional (CS) strategy performance
- ✅ Fixed multiple known bugs

For detailed changelog, see [CHANGELOG.md](CHANGELOG.md)

### License

This project is open source under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.

### Acknowledgments

- Thanks to [Daniel Rodriguez](https://github.com/mementum) for creating the original backtrader
- Thanks to all contributors for their support and help

### Contact

- Author: cloudQuant
- Email: yunjinqi@qq.com
- Blog: [CSDN](https://blog.csdn.net/qq_26948675)

---

## 中文

### 简介

基于backtrader打造的高性能量化投研工具，专注于中低频交易策略，通过Cython/Numba优化提升回测效率。本项目是backtrader的增强版本，在保持原有功能的基础上，新增了多项实用功能。

### 核心特性

- 🚀 **性能优化**：使用Cython和Numba对核心计算模块进行优化，大幅提升回测速度
- 📊 **向量化回测**：支持时间序列(TS)和横截面(CS)向量化回测框架
- 🪙 **加密货币支持**：
  - 集成CCXT，支持100+加密货币交易所
  - 支持资金费率回测（数字货币永续合约）
  - 实时数据流和历史数据回测
- 🏦 **多市场支持**：
  - Interactive Brokers (IB) 集成
  - CTP期货交易接口
  - Oanda外汇交易
  - 传统股票市场
- 📈 **丰富的技术指标**：60+内置技术指标，支持自定义指标开发
- 📝 **策略分析器**：多种性能分析工具（夏普比率、最大回撤、SQN等）

### 版本说明

- **master分支**：稳定版本，与官方backtrader保持兼容，修复了已知bug
- **dev分支**：开发版本，包含最新特性和实验性功能

### 快速开始

#### 系统要求

- Python 3.8 - 3.13（推荐使用Python 3.11以获得最佳性能）
- 操作系统：Windows、Linux、macOS

#### 安装方法

**方法1：使用pip安装（推荐）**

```bash
pip install -U git+https://gitee.com/yunjinqi/backtrader.git
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

**方法3：使用Anaconda**

```bash
# 创建虚拟环境
conda create -n backtrader python=3.11
conda activate backtrader

# 安装依赖
pip install -r requirements.txt

# 安装backtrader
pip install -e .
```

#### 快速示例

```python
import backtrader as bt
import pandas as pd
from datetime import datetime

# 创建策略
class SMAStrategy(bt.Strategy):
    params = (
        ('maperiod', 15),
    )

    def __init__(self):
        # 添加移动平均线指标
        self.sma = bt.indicators.SimpleMovingAverage(
            self.datas[0], period=self.params.maperiod)
        
    def next(self):
        # 买入逻辑
        if self.data.close[0] > self.sma[0]:
            if not self.position:
                self.buy()
        # 卖出逻辑
        elif self.position:
            self.sell()

# 创建Cerebro引擎
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(SMAStrategy)

# 加载数据
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31)
)
cerebro.adddata(data)

# 设置初始资金
cerebro.broker.setcash(100000.0)

# 运行回测
results = cerebro.run()

# 打印最终资产
print(f'最终资产价值: {cerebro.broker.getvalue():.2f}')

# 绘制结果
cerebro.plot()
```

### 主要功能模块

#### 1. 数据源 (Data Feeds)
- CSV文件导入
- Pandas DataFrame
- 实时数据流（IB、CCXT、CTP）
- Yahoo Finance、Quandl等在线数据源

#### 2. 策略开发 (Strategies)
- 事件驱动策略框架
- 向量化策略框架（CS/TS）
- 多品种、多周期策略支持
- 信号系统（Signal）

#### 3. 技术指标 (Indicators)
- 移动平均线系列（SMA、EMA、WMA等）
- 震荡指标（RSI、MACD、Stochastic等）
- 波动率指标（ATR、Bollinger Bands等）
- 自定义指标开发框架

#### 4. 订单管理 (Orders)
- 市价单、限价单、止损单
- 括号订单（Bracket Orders）
- OCO订单（One-Cancels-Other）
- 订单有效期管理

#### 5. 性能分析 (Analyzers)
- 收益率分析
- 夏普比率
- 最大回撤
- 交易统计
- 自定义分析器

### 进阶使用

#### 加密货币交易示例

```python
from datetime import datetime, timedelta
import backtrader as bt
from backtrader.feeds import CCXT

# 使用CCXT数据源
cerebro = bt.Cerebro()

# 配置交易所
config = {'apiKey': 'YOUR_KEY', 'secret': 'YOUR_SECRET'}
store = bt.stores.CCXTStore(exchange='binance', config=config)

# 获取数据
hist_start_date = datetime.utcnow() - timedelta(days=30)
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    fromdate=hist_start_date,
    compression=60  # 60分钟K线
)

cerebro.adddata(data)
```

#### 向量化回测示例

```python
# 时间序列向量化策略
from backtrader.vectors import TimeSeriesStrategy

class MyTSStrategy(TimeSeriesStrategy):
    def compute_signal(self, data):
        # 使用numpy进行向量化计算
        sma_20 = data['close'].rolling(20).mean()
        sma_50 = data['close'].rolling(50).mean()
        
        # 生成信号
        signal = (sma_20 > sma_50).astype(int)
        return signal
```

### 文档与资源

- 📚 [官方文档](https://www.backtrader.com/)
- 📝 [CSDN专栏教程](https://blog.csdn.net/qq_26948675/category_10220116.html)
- 💬 [问题反馈](https://gitee.com/yunjinqi/backtrader/issues)
- 🔧 [开发指南](CONTRIBUTING.md)

### 性能对比

使用Cython优化后的性能提升：

| 功能模块 | 原始速度 | 优化后速度 | 提升比例 |
|---------|---------|-----------|---------| 
| 指标计算 | 1.00x | 3-5x | 200-400% |
| 向量化回测 | N/A | 10-20x | - |
| 订单撮合 | 1.00x | 2-3x | 100-200% |

### 贡献指南

欢迎贡献代码、报告问题或提出新功能建议：

1. Fork 本仓库
2. 创建您的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启一个 Pull Request

### 更新日志

#### 2024年最新更新
- ✅ 增加了数字货币资金费率回测支持
- ✅ 修复了Python 3.12+兼容性问题
- ✅ 优化了Cython编译流程
- ✅ 添加了CI/CD自动化测试

#### 2023年更新
- ✅ 实现了时间序列(TS)向量化回测框架
- ✅ 优化了横截面(CS)策略性能
- ✅ 修复了多个已知bug

详细更新日志请查看[CHANGELOG.md](CHANGELOG.md)

### 许可证

本项目基于 GNU General Public License v3.0 开源，详见 [LICENSE](LICENSE) 文件。

### 致谢

- 感谢 [Daniel Rodriguez](https://github.com/mementum) 创建了原始的backtrader
- 感谢所有贡献者的支持与帮助

### 联系方式

- 作者：cloudQuant
- 邮箱：yunjinqi@qq.com
- 博客：[CSDN](https://blog.csdn.net/qq_26948675)

### 镜像仓库 / Mirror Repositories

- 主仓库 / Main: https://gitee.com/yunjinqi/backtrader
- 镜像 / Mirror: https://github.com/cloudQuant/backtrader

---

<div align="center">

**[⬆ Back to Top](#backtrader) | [English](#english) | [中文](#中文)**

⭐ 如果这个项目对您有帮助，请给个Star支持一下！| If this project helps you, please give it a Star!

Made with ❤️ by [cloudQuant](https://github.com/cloudQuant)

</div>