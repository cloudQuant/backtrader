- --

title: Architecture Overview
description: System architecture and design

- --

# Architecture Overview

Backtrader uses an event-driven architecture for efficient backtesting and live trading.

## System Architecture

```mermaid
flowchart TB
    subgraph Data
        CSV[CSV Files]
        DF[Pandas DataFrame]
        YF[Yahoo Finance]
        CCXT[CCXT Live]
        CTP[CTP Futures]
    end

    subgraph Backtrader Core
        Cerebro[Cerebro Engine]
        LF[Line System]
        PS[Phase System]
    end

    subgraph Execution
        Strat[Strategy]
        Ind[Indicators]
        Obs[Observers]
        An[Analyzers]
    end

    subgraph Trading
        Brk[Broker]
        Ord[Orders]
    end

    Data --> Cerebro
    Cerebro --> Strat
    Strat --> Ind
    Strat --> Obs
    Strat -->|Orders| Brk

    Brk -->|Fills| Strat

    Cerebro --> An

    LF --> Cerebro
    PS --> Strat

```bash

## Core Components

### Cerebro

The central engine that orchestrates everything:

- Manages data feeds
- Executes strategies
- Handles broker operations
- Coordinates analyzers and observers

### Line System

The fundamental data structure for time series:

```mermaid
classDiagram
    class LineRoot {

        - get(size)
        - len()
        - datetime

    }

    class LineBuffer {

        - __getitem__(key)
        - __setitem__(key, value)
        - minperiod

    }

    class LineSeries {

        - align()
        - date()
        - time()

    }

    class LineIterator {

        - prenext()
        - nextstart()
        - next()
        - once()

    }

    LineRoot <|-- LineBuffer

    LineBuffer <|-- LineSeries

    LineSeries <|-- LineIterator

```bash

### Phase System

Execution phases for strategy lifecycle:

```mermaid
stateDiagram-v2
    [*] --> __init__: Strategy created
    __init__ --> prenext: Indicators warming up
    prenext --> prenext: Processing bars
    prenext --> nextstart: Minperiod reached
    nextstart --> next: Transition complete
    next --> next: Normal operation
    next --> [*]: Backtest ends

```bash

| Phase | Description | Usage |

|-------|-------------|-------|

| `__init__` | Initialize strategy and indicators | Create indicators, set up state |

| `prenext()` | Called before enough data | Skip trading logic |

| `nextstart()` | First bar with valid data | One-time setup |

| `next()` | Normal operation | Main trading logic |

### Observer Extension Pattern

Observers are the primary way to extend functionality:

```mermaid
flowchart LR
    Strategy[Strategy] -->|1. Register| LI[_lineiterators]

    Observer[Observer] -->|2. Append| LI

    Cerebro[Cerebro] -->|3. Iterate| LI

    LI -->|4. Call next| Observer

```bash

## Data Flow

### Backtest Flow

```mermaid
sequenceDiagram
    participant C as Cerebro
    participant D as Data Feed
    participant S as Strategy
    participant I as Indicators
    participant B as Broker

    C->>D: Load next bar
    D->>C: Return OHLCV data
    C->>I: Update indicators
    I->>I: Calculate values
    C->>S: Call next()
    S->>S: Execute logic
    S->>B: Place order (if any)
    B->>B: Execute order
    C->>C: Continue to next bar

```bash

### Live Trading Flow

```mermaid
sequenceDiagram
    participant E as Exchange
    participant S as Store/Feed
    participant C as Cerebro
    participant S2 as Strategy
    participant B as Broker

    E->>S: Market data (WebSocket)
    S->>C: Push data
    C->>C: Update indicators
    C->>S2: Call next()
    S2->>B: Place order
    B->>S: Submit order
    S->>E: Send order
    E->>S: Order fill
    S->>C: Update position

```bash

## Component Hierarchy

```bash
backtrader/
├── Core Layer
│   ├── metabase.py          # Base mixins and owner finding

│   ├── lineroot.py           # Line system base

│   ├── linebuffer.py         # Circular buffer storage

│   ├── lineseries.py         # Time series operations

│   └── lineiterator.py       # Iterator logic and phases

│
├── Data Layer
│   ├── feed.py               # Base feed classes

│   └── feeds/                # Feed implementations

│
├── Execution Layer
│   ├── strategy.py           # Base strategy class

│   ├── indicator.py          # Base indicator class

│   ├── observer.py           # Base observer class

│   ├── analyzer.py           # Base analyzer class

│   └── broker.py             # Base broker class

│
└── Application Layer
    └── cerebro.py            # Main engine

```bash

## Design Principles

### 1. Event-Driven

Cerebro processes data bar-by-bar, triggering:

1. Indicator updates
2. Strategy execution
3. Order handling
4. Observer notifications

### 2. Decoupled Components

- Strategies don't depend on specific data sources
- Brokers are pluggable
- Indicators work with any data feed

### 3. Extensibility

Primary extension points:

1. **Observers**- Data collection and monitoring

2.**Analyzers**- Performance metrics
3.**Indicators**- Custom calculations
4.**Strategies**- Trading logic
5.**Data Feeds**- New data sources
6.**Brokers** - Order execution

## Post-Metaclass Architecture

The codebase has removed metaclass-based metaprogramming:

### Old Pattern (Removed)

```python

# ❌ No longer used

class MetaStrategy(type):
    def __call__(cls, *args, **kwargs):

# Metaclass magic
        pass

```bash

### New Pattern (Current)

```python

# ✅ Explicit donew() pattern

def __new__(cls, *args, **kwargs):
    _obj, args, kwargs = cls.donew(*args, **kwargs)
    return _obj

def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

```bash

- *Benefits:**
- 45% performance improvement
- Explicit initialization
- Easier debugging
- Better IDE support

## See Also

- [Line System](line-system.md)
- [Phase System](phase-system.md)
- [Post-Metaclass Design](post-metaclass.md)
