# Backtrader Project Context

**Generated for LLM and Developer Optimization**

## 1. Project Overview and Goals

### Core Identity
Backtrader is a Python-based quantitative trading and backtesting framework designed for mid-to-low frequency strategies. This is a performance-optimized fork of the original backtrader that eliminates metaclass-based metaprogramming in favor of explicit initialization patterns.

### Key Performance Metrics
- **45% performance improvement** over original backtrader
- **Tick-level testing support** in dev branch
- **C++ integration** for high-frequency calculations
- **Multi-asset portfolio support** (CS mode)
- **Vectorized backtesting** (TS mode)

### Branch Strategy
- `dev`: Active development branch with all optimizations
- `master`: Stable version aligned with official backtrader
- `development`: Legacy branch (mostly merged into dev)

## 2. Critical Architecture Rules and Patterns

### The New Post-Metaclass Architecture

#### Base Layer: `metabase.py`
- **`BaseMixin`**: Provides `donew()` pattern for explicit initialization
- **Owner Finding**: `metabase.findowner()` locates owner objects in call stack
- **No Metaclasses**: All initialization is explicit and predictable

#### Line System (Bottom-Up Architecture)
```
LineRoot → LineBuffer → LineSeries → LineIterator
```

- **LineRoot**: Base interface for line operations and period management
- **LineBuffer**: Circular buffer storage (~1950 lines) with performance optimizations
- **LineSeries**: Time series operations and data access (~75K lines)
- **LineIterator**: Iteration logic, prenext/next/once phase management (~94K lines)

#### Critical Initialization Pattern
```python
# NEW explicit way (POST-METACLASS):
def __new__(cls, *args, **kwargs):
    _obj, args, kwargs = cls.donew(*args, **kwargs)  # Owner detection here
    return _obj

def __init__(self, *args, **kwargs):
    # Initialize attributes early
    super().__init__(*args, **kwargs)
```

**Key Rules**:
1. Always call `super().__init__()` **before** accessing `self.p` or `self.params`
2. Parameters are set up during the initialization chain
3. Owner assignment happens via `metabase.findowner()` in `donew()`

### Indicator Registration System (CRITICAL)

**Location**: `lineiterator.py:528-556`

**How it works**:
1. Indicators set `_ltype = LineIterator.IndType` (value: 0)
2. During `__init__`, if indicator has an owner, it auto-registers
3. Owner's `_next()` method iterates `_lineiterators` to update all indicators

**Common Bug**: If indicators aren't registered, they won't update during backtesting.

### The Three Execution Phases

1. **prenext**: Initial bars where minperiod hasn't been reached
2. **nextstart**: Transition bar where minperiod is first satisfied
3. **next**: Normal operation after minperiod

## 3. Code Organization Conventions

### Package Structure
```
backtrader/
├── core_modules/           # Core engine (~340K lines total)
│   ├── cerebro.py         # Main engine
│   ├── strategy.py        # Strategy base
│   ├── indicator.py       # Indicator base
│   ├── metabase.py        # Base architecture
│   └── line_system/       # Line infrastructure
├── analyzers/             # Performance metrics
├── brokers/               # Order execution
├── feeds/                # Data sources
├── indicators/           # Technical indicators
├── observers/            # Chart observers
├── utils/                # Utilities + Cython optimizations
└── plot/                 # Visualization
```

### Naming Conventions
- **Line-related**: `LineRoot`, `LineBuffer`, `LineSeries`
- **Iterator types**: `IndType=0`, `ObsType=1`, `StratType=2`
- **Private attributes**: `_minperiod`, `_lineiterators`, `_owner`
- **Parameters**: `self.p.parametername` (available after `super().__init__()`)

## 4. Important Design Decisions

### Performance Optimizations

#### Cython Integration
Critical calculations implemented in Cython for 10-100x speedup:
- `utils/cal_performance_indicators/`: Performance metrics
- `utils/ts_cal_value/`: Time series calculations
- `utils/cs_cal_value/`: Cross-section calculations

### Memory Management
- **Circular Buffer**: LineBuffer implements circular buffer for memory efficiency
- **qbuffer()**: Limits memory usage for long backtests
- **Lazy Evaluation**: Indicators calculated only when needed

### API Compatibility
- **Zero Breaking Changes**: All existing user code works unchanged
- **Explicit Initialization**: Replaces metaclass magic with clear patterns

## 5. Developer Conventions to Know

### Parameter Access Pattern
```python
class MyStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('multiplier', 2.0)
    )

    def __init__(self):
        # CRITICAL: Call super().__init__() FIRST
        super().__init__()

        # NOW you can access parameters
        sma = bt.indicators.SMA(self.data, period=self.p.period)
```

### Owner Assignment Pattern
```python
# Automatic owner detection (preferred)
indicator = bt.indicators.RSI(data, period=14)

# Manual assignment if needed
indicator._owner = strategy
strategy._lineiterators[0].append(indicator)
```

### Minimum Period Handling
```python
def prenext(self):
    # Called before minperiod is reached
    pass

def nextstart(self):
    # Called once when minperiod is first reached
    pass

def next(self):
    # Main strategy logic - called every bar
    pass
```

## 6. Common Task Guides

### Adding a New Indicator
1. Create file in `backtrader/indicators/`
2. Inherit from `bt.Indicator`
3. Define `lines = ('output_line',)` for result storage
4. Define `params = (('param_name', default_value),)`
5. Implement `__init__()` with calculation logic

### Adding a New Strategy
1. Inherit from `bt.Strategy`
2. Define parameters with `params = (...)`
3. Implement `__init__()` to set up indicators
4. Implement `next()` for trading logic

## 7. Critical Constraints and Warnings

### Metaclass Removal Project
1. **Never introduce new metaclasses** - use mixins with `donew()` pattern
2. **Preserve API compatibility** - existing user code must work unchanged
3. **Maintain initialization order** - parent `__init__` before accessing attributes

### Parameter Access
```python
# WRONG - self.p not available yet
class BadStrategy(Strategy):
    def __init__(self):
        print(self.p.period)  # Will fail!

# CORRECT - call super().__init__() first
class GoodStrategy(Strategy):
    def __init__(self):
        super().__init__()  # Setup self.p
        print(self.p.period)  # Now works
```

## 8. Development Workflow

### Quick Start
```bash
# Install dependencies
pip install -r requirements.txt

# Compile Cython files
cd backtrader && python -W ignore compile_cython_numba_files.py && cd ..

# Install package
pip install -e .

# Run tests
pytest tests/ -n 4 -v
```

---

**Note**: This document focuses on the architectural patterns and conventions critical for LLM and developer productivity. For detailed API documentation, see the main project documentation.
