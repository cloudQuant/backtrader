# Source Tree Analysis

## Complete Directory Structure

```
backtrader/
├── __init__.py                 # Package initialization
├── cerebro.py                  # Main backtesting engine (~88K LOC)
├── cerebro_ext.py              # Cerebro extensions for TS/CS modes
├── strategy.py                 # Base strategy class
├── broker.py                   # Base broker class
├── indicator.py                # Base indicator class
├── observer.py                 # Base observer class
├── analyzer.py                 # Base analyzer class
├── feed.py                     # Base feed class
├── store.py                    # Base store class
│
├── Core System (Lines & Initialization)              │
├── lineroot.py                 # Line system base interface
├── linebuffer.py               # Circular buffer data storage (~1950 LOC)
├── lineseries.py               # Time series operations (~75K LOC)
├── lineiterator.py             # Iterator logic & phases (~94K LOC)
├── dataseries.py               # Data accessor interfaces
├── metabase.py                 # Base mixins & owner finding (critical)
├── metabase_abc.py             # Abstract base classes
├── utils/                      # Utility functions
│   ├── __init__.py
│   ├── date.py                 # Date handling utilities
│   ├── flushfile.py            # Flush file utility
│   ├── autodict.py             # Auto dictionary
│   ├── ordereddefaultdict.py   # Ordered default dict
│   └── py3.py                  # Python 3 compatibility
│
├── indicators/                 # 60+ Technical indicators
│   ├── __init__.py
│   ├── accdecoscillator.py
│   ├── aroon.py
│   ├── atr.py
│   ├── awesomeoscillator.py
│   ├── basicops.py
│   ├── bollinger.py            # Bollinger Bands
│   ├── cci.py
│   ├── crossover.py            # Crossover signal indicator
│   ├── dema.py
│   ├── deviation.py
│   ├── directionalmove.py
│   ├── dma.py
│   ├── dpo.py
│   ├── dv2.py
│   ├── envelope.py             # Price envelope
│   ├── hullma.py
│   ├── ichimoku.py             # Ichimoku Kinko Hyo
│   ├── kes.py
│   ├── macd.py                 # MACD indicator
│   ├── momentum.py
│   ├── oscar.py
│   ├── osc.py                  # Oscillator
│   ├── ppo.py
│   ├── roc.py                  # Rate of Change
│   ├── rsi.py                  # RSI indicator
│   ├── sar.py                  # Parabolic SAR
│   ├── stdev.py                # Standard Deviation
│   ├── sma.py                  # Simple Moving Average
│   ├── wma.py                  # Weighted Moving Average
│   ├── ema.py                  # Exponential Moving Average
│   └── contrib/                # Community-contributed indicators
│       └── vortex.py
│
├── observers/                  # Chart observers & data recorders
│   ├── __init__.py
│   ├── benchmark.py            # Benchmark comparison
│   ├── broker.py               # Broker state observer
│   ├── buysell.py              # Buy/Sell signal markers
│   ├── datacoder.py            # Data coding observer
│   ├── drawdown.py             # Drawdown observer
│   ├── logreturns.py           # Log returns
│   ├── timereturn.py           # Time-based returns
│   ├── trades.py               # Trade tracking
│   └── trade_logger.py         # Trade logging observer
│
├── analyzers/                  # Performance metrics & statistics
│   ├── __init__.py
│   ├── annualreturn.py         # Annual return
│   ├── calmar.py               # Calmar ratio
│   ├── drawdown.py             # Drawdown analysis
│   ├── leverage.py             # Leverage analysis
│   ├── logreturnsrolling.py    # Rolling log returns
│   ├── periodstats.py          # Period statistics
│   ├── positions.py            # Position analysis
│   ├── pyfolio.py              # PyFolio integration
│   ├── returns.py              # Return analysis
│   ├── sharpe.py               # Sharpe ratio
│   ├── sharpe_ratio_stats.py   # Sharpe ratio statistics
│   ├── sqn.py                  # SQN ratio
│   ├── timereturn.py           # Time return analysis
│   ├── total_value.py          # Total value
│   ├── tradeanalyzer.py        # Trade analysis
│   ├── transactions.py         # Transaction tracking
│   └── vwr.py                  # Volume weighted return
│
├── feeds/                      # Data source implementations
│   ├── __init__.py
│   ├── btcsv.py                # BTC CSV data feed
│   ├── chainer.py              # Chain multiple feeds
│   ├── cryptofeed.py           # Crypto data feed
│   ├── csvgeneric.py           # Generic CSV parser
│   ├── ibdata.py               # Interactive Brokers data
│   ├── influxfeed.py           # InfluxDB feed
│   ├── mt4csv.py               # MT4 CSV data
│   ├── oanda.py                # OANDA data feed
│   ├── pandafeed.py            # Pandas DataFrame feed
│   ├── rollover.py             # Contract rollover
│   ├── sierrachart.py          # Sierra Chart data
│   ├── vcdata.py               # VisualChart data
│   ├── vchart.py               # VisualChart file
│   ├── vchartcsv.py            # VisualChart CSV
│   ├── vchartfile.py           # VisualChart file data
│   ├── yahoo.py                # Yahoo Finance data
│   ├── ccxtfeed.py             # CCXT exchange data
│   ├── ccxtfeed_funding.py     # CCXT funding rate data
│   ├── ccxt_live_tick.py      # CCXT live tick data
│   ├── ctpdata.py              # CTP futures data
│   ├── futufeed.py             # Futu futures data
│   ├── blaze.py                # Blaze data feed
│   └── quandl.py               # Quandl data feed
│
├── brokers/                    # Broker implementations
│   ├── __init__.py
│   ├── bbroker.py              # Base broker (backtrader default)
│   ├── cryptobroker.py         # Crypto broker
│   ├── ibbroker.py             # Interactive Brokers broker
│   ├── oandabroker.py          # OANDA broker
│   ├── vcbroker.py             # VisualChart broker
│   ├── ccxtbroker.py           # CCXT exchange broker
│   ├── ctpbroker.py            # CTP futures broker
│   ├── mixbroker.py            # Mixed broker implementation
│   ├── obbroker.py             # OrderBook broker
│   ├── impact_models.py        # Market impact models
│   ├── tickbroker.py           # Tick-level broker
│   └── livebroker.py           # Live broker abstract base
│
├── stores/                     # Data storage & connection management
│   ├── __init__.py
│   ├── oandastore.py           # OANDA store
│   ├── cryptostore.py          # Crypto store
│   ├── ccxtstore.py            # CCXT store (WebSocket shared)
│   ├── ibstore.py              # Interactive Brokers store
│   ├── vcstore.py              # VisualChart store
│   ├── ctpstore.py             # CTP futures store
│   └── filestore.py            # File-based store
│
├── signals/                    # Signal system
│   ├── __init__.py
│   ├── signal.py               # Base signal class
│   ├── btindicator.py         # Indicator-based signal
│   ├── btfiltersignal.py       # Filter-based signal
│   └── ...
│
├── filters/                    # Data filters
│   ├── __init__.py
│   ├── bsplitter.py            # Session splitter
│   ├── calendardays.py         # Calendar days filter
│   ├── datafiller.py           # Data filling
│   ├── datafilter.py           # Data filtering
│   ├── daysteps.py             # Day steps filter
│   ├── heikinashi.py           # Heikin Ashi candles
│   ├── renko.py                # Renko charts
│   └── session.py              # Session filter
│
├── sizers/                     # Position sizers
│   ├── __init__.py
│   └── fixedsize.py            # Fixed position sizing
│
├── plot/                       # Plotting module
│   ├── __init__.py
│   ├── plot.py                 # Matplotlib plotting
│   ├── plot_plotly.py          # Plotly interactive plotting
│   ├── finance.py              # Financial plotting utilities
│   ├── formatters.py           # Plot formatters
│   ├── multicursor.py          # Multi-cursor support
│   ├── locator.py              # Plot locator
│   ├── scheme.py               # Plot schemes
│   └── utils.py                # Plot utilities
│
├── bokeh/                      # Bokeh plotting framework
│   ├── __init__.py
│   ├── app.py                  # Bokeh app
│   ├── scheme.py               # Schemes
│   ├── tab.py                  # Tab interface
│   ├── analyzers/              # Bokeh analyzers
│   ├── tabs/                   # Bokeh tabs
│   ├── schemes/                # Bokeh color schemes
│   ├── utils/                  # Bokeh utilities
│   └── live/                   # Bokeh live plotting
│
├── ccxt/                       # CCXT enhancement module
│   ├── websocket.py            # WebSocket manager
│   ├── threaded.py             # Threaded data/order managers
│   ├── ratelimit.py            # Rate limiter
│   └── ...
│
├── channels/                   # Event channels
│   └── ...
│
├── configs/                    # Configuration files
│   └── ...
│
├── btrun/                      # Command-line tool
│   └── ...
│
├── reports/                    # Report generation
│   └── ...
│
├── mixins/                     # Mixin classes
│   └── singleton.py           # Singleton pattern
│
└── utils/                      # Utility modules
    ├── __init__.py
    ├── date.py
    ├── flushfile.py
    ├── autodict.py
    ├── ordereddefaultdict.py
    └── py3.py
```

## Critical Folders Summary

| Folder | Purpose | Key Files |
|--------|---------|-----------|
| `indicators/` | 60+ technical indicators | sma.py, ema.py, rsi.py, macd.py, bollinger.py |
| `observers/` | Chart observers & data recorders | drawdown.py, trades.py, trade_logger.py |
| `analyzers/` | Performance metrics | sharpe.py, returns.py, positions.py, drawdown.py |
| `feeds/` | Data source adapters | pandas, ccxt, ctp, yahoo, csv |
| `brokers/` | Order execution | ccxt, ctp, ibbroker, oanda |
| `stores/` | Connection & data management | ccxtstore, ctpstore |
| `signals/` | Signal system | Signal base classes |
| `plot/` | Visualization | Plotly interactive charts |
| `utils/` | Utility functions | Date, flushfile, autodict |
| `filters/` | Data filters | Session, calendar, data filling |
| `ccxt/` | CCXT enhancement | WebSocket, rate limiting, threading |

## Entry Points

- **Cerebro**: Main backtesting engine (`cerebro.py`)
- **Strategy Base**: `strategy.py`
- **Command Line**: `backtrader/btrun/`

## Integration Points

- **CCXT Module**: `backtrader/ccxt/` (WebSocket shared connection)
- **CTP Module**: `backtrader/stores/ctpstore.py`, `backtrader/brokers/ctpbroker.py`, `backtrader/feeds/ctpdata.py`
- **Live Trading**: `backtrader/brokers/livebroker.py` (abstract base class)
