# backtrader

English | [中文](README.md)

[![CI Tests](https://github.com/cloudQuant/backtrader/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/cloudQuant/backtrader/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.8%20%7C%203.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-GPL%203.0-green)](LICENSE)
[![Code style: flake8](https://img.shields.io/badge/code%20style-flake8-black)](https://flake8.pycqa.org/)
[![GitHub stars](https://img.shields.io/github/stars/cloudQuant/backtrader?style=social)](https://github.com/cloudQuant/backtrader/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/cloudQuant/backtrader?style=social)](https://github.com/cloudQuant/backtrader/network/members)
[![Gitee](https://img.shields.io/badge/mirror-Gitee-red)](https://gitee.com/yunjinqi/backtrader)

## Introduction

An enhanced version of the backtrader Python library for quantitative trading and backtesting. This project keeps compatibility with the original backtrader while adding cryptocurrency support, futures-market integrations, extra testing utilities, and improved stability across Python 3.8-3.13.

### Core Features

- � **Event-Driven Architecture**: Fast and efficient event-driven backtesting engine
- 🪙 **Cryptocurrency Support**:
  - CCXT integration supporting 100+ cryptocurrency exchanges
  - Funding rate backtesting for crypto perpetual contracts
  - Real-time data streaming and historical data backtesting
- 🏦 **Multi-Market Support**:
  - Interactive Brokers (IB) integration
  - CTP futures trading interface
  - Oanda forex trading
  - Traditional stock markets
- 📈 **Rich Technical Indicators**: 50+ built-in indicators with custom indicator development support
- � **Comprehensive Analyzers**: Sharpe ratio, drawdown, trade statistics, PyFolio integration, and custom analyzers
- 🎯 **Flexible Order Types**: Market, limit, stop, stop-limit, bracket, and OCO orders
- 📉 **Data Processing**: Resampling, replaying, and multi-timeframe analysis

### Version Information

- **master branch**: Stable version, compatible with official backtrader, with known bugs fixed
- **dev branch**: Development version with latest features and experimental functionality

## Quick Start

### System Requirements

- Python 3.8 - 3.13 (Python 3.11 recommended for best performance)
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

## Documentation & Resources

- 📚 [Project Documentation Index](docs/README.md)
- 🛠️ [Installation & Troubleshooting Guide](docs/INSTALLATION_GUIDE.md)
- 🧾 [Changelog](docs/CHANGELOG.md)
- 🐛 [DataTrades Fix Note](docs/DATATRADES_FIX.md)
- 🔌 [ExtendPandasFeed Fix Note](docs/EXTENDED_FEED_FIX.md)
- 📚 [Official Documentation](https://www.backtrader.com/)
- 📝 [CSDN Tutorial Series](https://blog.csdn.net/qq_26948675/category_10220116.html)
- 💬 [Issue Tracker](https://gitee.com/yunjinqi/backtrader/issues)
- 🔧 [Development Guide](CLAUDE.md)

## Contributing

We welcome code contributions, bug reports, and feature suggestions:

1. Fork this repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## Changelog

### 2026 Updates
- ✅ Reorganized helper scripts under `scripts/`
- ✅ Added the strategies regression framework (generated locally and gitignored)
- ✅ Made `backtrader.analyzers.pyfolio` lazy-load `empyrical`

### 2024 Updates
- ✅ Added funding rate backtesting support for cryptocurrency perpetual contracts
- ✅ Fixed Python 3.12 and 3.13 compatibility issues
- ✅ Improved CCXT integration stability
- ✅ Added CI/CD automated testing

### 2023 Updates
- ✅ Improved multi-exchange support
- ✅ Fixed multiple known bugs

For detailed changelog, see [docs/CHANGELOG.md](docs/CHANGELOG.md)

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