---
title: Backtrader Documentation
description: Professional Python Algorithmic Trading Backtesting Framework
---

# Backtrader Documentation

Welcome to the official documentation for Backtrader - a professional Python algorithmic trading backtesting framework.

## Quick Links

| For | Link |
|-----|------|
| **Getting Started** | [Installation Guide](user-guide/installation.md) |
| **First Strategy** | [Quick Start Tutorial](user-guide/quickstart.md) |
| **Core Concepts** | [Basic Concepts](user-guide/concepts.md) |
| **API Reference** | [API Documentation](api-reference/) |
| **Contributing** | [Developer Guide](developer-guide/) |

## What is Backtrader?

Backtrader is a Python library for:
- **Backtesting** - Test trading strategies with historical data
- **Live Trading** - Execute trades in real-time via CCXT and CTP
- **Strategy Development** - Build and analyze custom trading algorithms
- **Performance Analysis** - Evaluate strategy effectiveness

## Key Features

- **Event-Driven Architecture** - Efficient strategy execution
- **60+ Built-in Indicators** - SMA, EMA, RSI, MACD, Bollinger Bands, and more
- **Multiple Data Sources** - CSV, Pandas, Yahoo Finance, CCXT, CTP
- **Live Trading Support** - CCXT (crypto) and CTP (futures)
- **Comprehensive Analytics** - Sharpe ratio, drawdown, returns, and more

## Performance

The `dev` branch achieves **45% faster execution** compared to the original backtrader through:
- Elimination of metaclass-based metaprogramming
- Broker optimization
- Direct C++ integration (planned)

## Documentation Structure

### User Guide

Learn how to use Backtrader:
- [Installation](user-guide/installation.md)
- [Quick Start](user-guide/quickstart.md)
- [Basic Concepts](user-guide/concepts.md)
- [Data Feeds](user-guide/data-feeds.md)
- [Indicators](user-guide/indicators.md)
- [Strategies](user-guide/strategies.md)
- [Analyzers](user-guide/analyzers.md)
- [Observers](user-guide/observers.md)
- [Plotting](user-guide/plotting.md)

### Live Trading

- [CCXT Live Trading](live-trading/ccxt-guide.md)
- [WebSocket Guide](live-trading/websocket.md)
- [CTP Futures Trading](live-trading/ctp-guide.md)
- [Funding Rate Strategies](live-trading/funding-rate.md)

### API Reference

Complete API documentation:
- [Cerebro](api-reference/cerebro.md)
- [Strategy](api-reference/strategy.md)
- [Indicators](api-reference/indicators.md)
- [Data Feeds](api-reference/feeds.md)
- [Brokers](api-reference/brokers.md)

### Architecture

For developers and contributors:
- [Architecture Overview](architecture/overview.md)
- [Line System](architecture/line-system.md)
- [Phase System](architecture/phase-system.md)
- [Post-Metaclass Design](architecture/post-metaclass.md)

### Developer Guide

For contributors:
- [Development Setup](developer-guide/setup.md)
- [Testing](developer-guide/testing.md)
- [Code Style](developer-guide/style.md)
- [Contributing](developer-guide/contributing.md)

## Need Help?

- [GitHub Issues](https://github.com/cloudQuant/backtrader/issues) - Report bugs
- [GitHub Discussions](https://github.com/cloudQuant/backtrader/discussions) - Ask questions
- [Contributing Guide](developer-guide/contributing.md) - Contribute code

## License

GPLv3 - See [LICENSE](https://github.com/cloudQuant/backtrader/blob/master/LICENSE) for details.
