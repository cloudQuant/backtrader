# Project Structure

```
backtrader/                   # Root
├── backtrader/               # Core library source
│   ├── cerebro.py            # Main backtesting engine & orchestrator
│   ├── strategy.py           # Strategy base class
│   ├── indicator.py          # Indicator base class
│   ├── analyzer.py           # Analyzer base class
│   ├── observer.py           # Observer base class
│   ├── broker.py             # Broker base class
│   ├── feed.py               # Data feed base class
│   ├── order.py              # Order management
│   ├── trade.py              # Trade tracking
│   ├── position.py           # Position management
│   ├── sizer.py              # Position sizing base
│   ├── signal.py             # Signal-based trading
│   ├── metabase.py           # BaseMixin, findowner() — replaces metaclasses
│   ├── parameters.py         # Parameter system (AutoOrderedDict)
│   ├── lineroot.py           # Line system base interfaces
│   ├── linebuffer.py         # Line data storage with circular buffers
│   ├── lineseries.py         # Time series operations
│   ├── lineiterator.py       # Iteration logic, prenext/next/once phases
│   ├── dataseries.py         # Data accessor interfaces
│   ├── resamplerfilter.py    # Data resampling/filtering
│   ├── indicators/           # 50+ technical indicators
│   ├── analyzers/            # 17+ performance analyzers
│   ├── observers/            # Chart observers (cash, trades, etc.)
│   ├── feeds/                # Data source implementations (CSV, pandas, IB, CCXT, etc.)
│   ├── brokers/              # Broker implementations
│   ├── filters/              # Data filters
│   ├── sizers/               # Position sizing implementations
│   ├── stores/               # Data store connections
│   ├── commissions/          # Commission models
│   ├── signals/              # Signal definitions
│   ├── plot/                 # Matplotlib & Plotly visualization
│   ├── bokeh/                # Bokeh visualization backend
│   ├── reports/              # Report generation (HTML/PDF/JSON)
│   ├── utils/                # Utilities, Cython extensions, performance helpers
│   │   ├── ts_cal_value/     # Time series Cython implementations
│   │   ├── cs_cal_value/     # Cross-section Cython implementations
│   │   └── cal_performance_indicators/  # Performance metrics in Cython
│   ├── channels/             # Communication channels
│   ├── mixins/               # Shared mixin classes
│   └── configs/              # Configuration files
├── tests/                    # Test suite
│   ├── unit/                 # Unit tests
│   ├── functional/           # Functional tests
│   ├── integration/          # Integration tests
│   ├── performance/          # Performance/benchmark tests
│   ├── bench/                # Benchmark utilities
│   ├── datas/                # Test data files
│   ├── fixtures/             # Test fixtures
│   ├── factories/            # Test factories
│   ├── assets/               # Test assets
│   └── test_utils/           # Test helper utilities
├── examples/                 # Example strategies and usage
├── docs/                     # Sphinx documentation (EN + ZH)
├── scripts/                  # Dev scripts (optimize_code.sh, etc.)
├── tools/                    # Utility tools
├── studies/                  # Research/study scripts
├── Makefile                  # Build/test/lint commands
├── pyproject.toml            # Tool configuration (black, ruff, mypy, etc.)
├── setup.py                  # Package setup
├── pytest.ini                # Test configuration
├── requirements.txt          # All dependencies (core + dev)
└── conftest.py               # Root pytest configuration
```

## Architecture Layers

1. **Line System** (data foundation): `lineroot` → `linebuffer` → `lineseries` → `lineiterator`
2. **Components**: `indicator`, `observer`, `analyzer`, `sizer` — all extend LineIterator
3. **Data**: `feed` + `feeds/` — load and deliver market data
4. **Execution**: `broker` + `brokers/` — order matching and portfolio state
5. **Orchestration**: `cerebro` — wires everything together and runs the backtest loop
6. **Strategy**: User-facing class that receives data and generates orders

## Key Conventions

- New indicators go in `backtrader/indicators/` and must be registered in `indicators/__init__.py`
- New analyzers go in `backtrader/analyzers/` with registration in `analyzers/__init__.py`
- New data feeds go in `backtrader/feeds/` with registration in `feeds/__init__.py`
- Tests mirror source structure: unit tests for isolated logic, functional for end-to-end flows
- Test data files live in `tests/datas/`
