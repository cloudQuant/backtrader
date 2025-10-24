# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Backtrader is a Python-based quantitative trading and backtesting framework for mid-to-low frequency strategies. This is a fork that removes metaclass-based metaprogramming in favor of explicit initialization patterns while maintaining API compatibility with the original backtrader.

**Current Branch**: `remove-metaprogramming` - Major refactoring to eliminate metaclass usage
**Main Branch**: `master` - Stable version aligned with official backtrader
**Development Branch**: `dev` - New features and C++ integration for tick-level testing

## Development Commands

### Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Compile Cython files (Unix/Mac)
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U .

# Compile Cython files (Windows)
cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U .
```

### Testing
```bash
# Run all tests (parallel execution recommended)
pytest tests/ -n 4 -v

# Run only original tests
pytest tests/original_tests/ -v

# Run indicator tests
pytest tests/add_tests/test_ind*.py tests/original_tests/test_ind*.py -v

# Run strategy tests
pytest tests/add_tests/test_strategy*.py tests/original_tests/test_strategy*.py -v

# Run analyzer tests
pytest tests/add_tests/test_analyzer*.py tests/original_tests/test_analyzer*.py -v

# Run single test with detailed output
pytest tests/path/to/test_file.py::test_function_name -v --tb=short

# Run tests with coverage
make test-coverage
```

### Code Quality
```bash
# Format code (Black)
make format

# Check formatting
make format-check

# Run linter
make lint

# Type checking
make type-check

# Security checks
make security

# Run all quality checks
make quality-check
```

### Using Makefile
```bash
# See all available commands
make help

# Install for development
make dev-install

# Clean build artifacts
make clean
```

## Architecture Overview

### Core Class Hierarchy (After Metaclass Removal)

The codebase is transitioning from metaclass-based to mixin-based architecture:

1. **Base Layer**: `metabase.py`
   - `BaseMixin`: Provides `donew()` pattern for explicit initialization
   - `findowner()`: Locates owner objects in the call stack
   - Replaces metaclass logic with explicit method calls

2. **Line System** (bottom-up):
   - `LineRoot` → `LineBuffer` → `LineSeries` → `LineIterator`
   - `LineRoot`: Base interface for line operations and period management
   - `LineBuffer`: Data storage with circular buffer support (`linebuffer.py:~1950 lines`)
   - `LineSeries`: Time series operations and data access
   - `LineIterator`: Iteration logic, prenext/next/once phase management

3. **Operational Classes**:
   - `Indicator` (lineiterator.py): Technical indicators base class
   - `Observer`: Chart observers (volume, cash, etc.)
   - `Analyzer`: Performance metrics and statistics
   - `Strategy`: Trading strategy base class
   - `Data/Feed`: Data source management

4. **Engine**: `cerebro.py` (~2000 lines)
   - Main orchestration engine
   - Manages strategies, data feeds, brokers, analyzers
   - Handles backtesting execution flow

### Critical Initialization Pattern

**After metaclass removal, initialization follows this pattern:**

```python
# Old metaclass way (deprecated):
# __new__ + metaclass magic

# New explicit way:
def __new__(cls, *args, **kwargs):
    _obj, args, kwargs = cls.donew(*args, **kwargs)
    return _obj

def __init__(self, *args, **kwargs):
    # Initialize attributes early
    # Call parent class __init__
    super().__init__(*args, **kwargs)
```

**Key Points**:
- `donew()` method replaces metaclass `__call__`
- Owner finding happens in `donew()` via `metabase.findowner()`
- Parameters are initialized before `__init__` is called
- Line buffers are created during parent `__init__` chain

### Indicator Registration System

**Critical**: Indicators must register themselves with their owner's `_lineiterators` list.

**Location**: `lineiterator.py:528-556`

**How it works**:
1. Indicator sets `_ltype = LineIterator.IndType` (value: 0)
2. During `__init__`, if indicator has an owner, it auto-registers
3. Owner's `_next()` method iterates `_lineiterators` to update all indicators
4. Registration must happen early, before any data processing

**Common Bug**: If indicators aren't registered, they won't update during backtesting.

### Parameter System

**Location**: `parameters.py` (~1850 lines)

Parameters use `AutoOrderedDict` and are initialized via `donew()`:
- Parameters defined at class level with `params = (...)` or `params = dict(...)`
- Values passed as kwargs override defaults
- Accessed via `self.p.parametername` or `self.params.parametername`

### Data Flow

```
Data Feed → Cerebro → Strategy → Indicators/Observers/Analyzers
                ↓
             Broker ← Orders
```

1. Cerebro loads data feeds and runs the main loop
2. Data is fed bar-by-bar (or tick-by-tick in dev branch)
3. Strategy receives data updates via `prenext()`, `nextstart()`, `next()`
4. Indicators are calculated automatically before strategy logic
5. Strategy generates orders sent to broker
6. Analyzers collect performance metrics

### Phase System

Backtrader has three execution phases:

1. **prenext**: Initial bars where minperiod hasn't been reached
2. **nextstart**: Transition bar where minperiod is first satisfied
3. **next**: Normal operation after minperiod

Alternative optimized mode uses:
- **once**: Batch processing all bars at once (faster but more complex)

## Key Files and Their Purposes

### Core Engine
- `cerebro.py`: Main backtesting engine and orchestrator
- `broker.py`, `brokers/`: Order execution and portfolio management
- `strategy.py`: Base class for trading strategies

### Line System
- `lineroot.py`: Base classes and interfaces
- `linebuffer.py`: Data storage with circular buffers
- `lineseries.py`: Time series operations
- `lineiterator.py`: Iterator logic and execution phases
- `dataseries.py`: Data accessor interfaces

### Data Management
- `feed.py`: Base data feed classes
- `feeds/`: Various data source implementations (CSV, pandas, live feeds)
- `resamplerfilter.py`: Data resampling and filtering

### Indicators
- `indicator.py`: Base indicator class
- `indicators/`: 60+ technical indicators
- `indicators/contrib/`: Community-contributed indicators

### Analysis
- `analyzer.py`: Base analyzer class
- `analyzers/`: Performance metrics (Sharpe, drawdown, returns, etc.)
- `observer.py`, `observers/`: Chart observers

### Utilities
- `metabase.py`: Base mixins and owner-finding logic (critical for post-metaclass code)
- `utils/`: Date handling, performance calculations, logging
- `utils/*_cython/`: Cython-optimized calculations for `ts` and `cs` modes

## Special Features

### TS (Time Series) Mode
Fast vectorized backtesting using pandas operations. See `utils/ts_cal_value/` for Cython implementations.

### CS (Cross-Section) Mode
Multi-asset portfolio backtesting with cross-sectional signals. See `utils/cs_cal_value/` and `utils/cs_long_short_signals/`.

### Cython Optimization
Performance-critical calculations are implemented in Cython:
- `utils/cal_performance_indicators/`: Performance metrics
- Compile via `compile_cython_numba_files.py`

## Testing Notes

### Test Organization
- `tests/original_tests/`: Core functionality tests
- `tests/add_tests/`: Additional test coverage
- `tests/refactor_tests/`: Tests for metaclass removal refactoring

### Known Issues (as of remove-metaprogramming branch)
See `PROGRESS_INDICATOR_FIXES.md` for detailed status. Current pass rate: ~91% (291/318 tests).

**Main remaining issues**:
1. Some indicator value calculations don't match expected results
2. Strategy trading logic may not trigger properly in certain tests
3. Cascading analyzer failures due to no-trade scenarios

### When Writing Tests
- Use fixtures from `conftest.py` if available
- Test with minimal data (10-20 bars) for unit tests
- Verify indicator registration via `strategy._lineiterators`
- Check minperiod handling in prenext/next phases
- Ensure cleanup after tests (no shared state)

## Common Tasks

### Adding a New Indicator
1. Create file in `backtrader/indicators/`
2. Inherit from `bt.Indicator`
3. Define `lines = ('output_line',)` for result storage
4. Define `params = (('param_name', default_value),)`
5. Implement `__init__()` with calculation logic
6. Set `self.lines.output_line = calculation`
7. Add to `indicators/__init__.py`

### Adding a New Strategy
1. Inherit from `bt.Strategy`
2. Define parameters with `params = (...)`
3. Implement `__init__()` to set up indicators
4. Implement `next()` for trading logic
5. Use `self.buy()`, `self.sell()`, `self.close()` for orders

### Debugging Line Issues
- Check `len(obj)` returns expected value
- Verify `obj._minperiod` is set correctly
- Ensure `obj._owner` is assigned
- For indicators, verify `obj._ltype == 0` (IndType)
- Check `obj` appears in `owner._lineiterators`

## Code Style

- Line length: 100 characters (Black configuration)
- Python 3.7+ (future versions will require Python 3 only)
- Type hints are encouraged but not strictly required
- Use descriptive variable names (avoid single letters except in loops)
- Comments in Chinese and English are both present in the codebase

## Important Constraints

### Metaclass Removal Project
The current branch (`remove-metaprogramming`) is removing all metaclass usage. When working on this:

1. **Never use metaclasses** - use mixins with `donew()` pattern instead
2. **Preserve API compatibility** - existing user code must work unchanged
3. **Maintain initialization order** - parent `__init__` before accessing `self.p` or lines
4. **Test extensively** - metaclass removal can break subtle dependencies

### Parameter Access
Always call `super().__init__()` **before** accessing `self.p` or `self.params`. The initialization chain sets up these attributes.

### Owner Assignment
Objects need to know their owner (e.g., indicator needs its strategy/data). This happens via:
- `metabase.findowner()` in `donew()` method
- Manual assignment if auto-detection fails
- Owner is needed for indicator registration and data access

## Performance Considerations

- Cython extensions provide 10-100x speedup for calculations
- Use `qbuffer()` to limit memory for long backtests
- The `once()` mode is faster than `next()` mode but harder to implement
- TS/CS modes are optimized for multi-asset portfolios
