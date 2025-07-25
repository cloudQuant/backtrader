# backtrader

English | [中文](README.md)

[![Tests](https://github.com/yunjinqi/backtrader/actions/workflows/tests.yml/badge.svg)](https://github.com/yunjinqi/backtrader/actions/workflows/tests.yml)
[![Build](https://github.com/yunjinqi/backtrader/actions/workflows/publish.yml/badge.svg)](https://github.com/yunjinqi/backtrader/actions/workflows/publish.yml)
[![CodeQL](https://github.com/yunjinqi/backtrader/actions/workflows/codeql.yml/badge.svg)](https://github.com/yunjinqi/backtrader/actions/workflows/codeql.yml)
[![Python Versions](https://img.shields.io/pypi/pyversions/backtrader.svg)](https://pypi.org/project/backtrader/)
[![PyPI Version](https://img.shields.io/pypi/v/backtrader.svg)](https://pypi.org/project/backtrader/)
[![License](https://img.shields.io/badge/license-GPL-blue.svg)](LICENSE)

## Introduction

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

## Quick Start

### System Requirements

- Python 3.8 - 3.12 (Python 3.11 recommended for best performance)
- Operating Systems: Windows, Linux, macOS

### Installation

#### Method 1: Install via pip (Recommended)

```bash
pip install -U git+https://gitee.com/yunjinqi/backtrader.git
```

#### Method 2: Install from Source

```bash
# Clone the repository
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

#### Method 3: Using Anaconda

```bash
# Create virtual environment
conda create -n backtrader python=3.11
conda activate backtrader

# Install dependencies
pip install -r requirements.txt

# Install backtrader
pip install -e .
```

### Quick Example

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

## Main Functional Modules

### 1. Data Feeds
- CSV file import
- Pandas DataFrame
- Real-time data streams (IB, CCXT, CTP)
- Online data sources (Yahoo Finance, Quandl, etc.)

### 2. Strategy Development
- Event-driven strategy framework
- Vectorized strategy framework (CS/TS)
- Multi-asset, multi-timeframe strategy support
- Signal system

### 3. Technical Indicators
- Moving average series (SMA, EMA, WMA, etc.)
- Oscillators (RSI, MACD, Stochastic, etc.)
- Volatility indicators (ATR, Bollinger Bands, etc.)
- Custom indicator development framework

### 4. Order Management
- Market orders, limit orders, stop orders
- Bracket orders
- OCO orders (One-Cancels-Other)
- Order validity management

### 5. Performance Analysis (Analyzers)
- Returns analysis
- Sharpe ratio
- Maximum drawdown
- Trade statistics
- Custom analyzers

## Advanced Usage

### Cryptocurrency Trading Example

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

### Vectorized Backtesting Example

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

## Documentation & Resources

- 📚 [Official Documentation](https://www.backtrader.com/)
- 📝 [CSDN Tutorial Series](https://blog.csdn.net/qq_26948675/category_10220116.html)
- 💬 [Issue Tracker](https://gitee.com/yunjinqi/backtrader/issues)
- 🔧 [Development Guide](CONTRIBUTING.md)

## Performance Comparison

Performance improvements with Cython optimization:

| Module | Original Speed | Optimized Speed | Improvement |
|--------|---------------|-----------------|-------------|
| Indicator Calculations | 1.00x | 3-5x | 200-400% |
| Vectorized Backtesting | N/A | 10-20x | - |
| Order Matching | 1.00x | 2-3x | 100-200% |

## Contributing

We welcome code contributions, bug reports, and feature suggestions:

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Changelog

### Latest Updates 2024
- ✅ Added funding rate backtesting support for cryptocurrency
- ✅ Fixed Python 3.12+ compatibility issues
- ✅ Optimized Cython compilation process
- ✅ Added CI/CD automated testing

### 2023 Updates
- ✅ Implemented Time Series (TS) vectorized backtesting framework
- ✅ Optimized Cross-Sectional (CS) strategy performance
- ✅ Fixed multiple known bugs

For detailed changelog, see [CHANGELOG.md](CHANGELOG.md)

## License

This project is open source under the GNU General Public License v3.0. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Thanks to [Daniel Rodriguez](https://github.com/mementum) for creating the original backtrader
- Thanks to all contributors for their support and help

## Contact

- Author: cloudQuant
- Email: yunjinqi@qq.com
- Blog: [CSDN](https://blog.csdn.net/qq_26948675)

---
⭐ If this project helps you, please give it a Star!