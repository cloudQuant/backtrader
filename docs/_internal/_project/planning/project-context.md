---
project_name: 'backtrader'
user_name: 'cloud'
date: '2025-02-28'
sections_completed:
  - technology_stack
  - language_rules
  - framework_rules
  - testing_rules
  - quality_rules
  - workflow_rules
  - anti_patterns
status: 'complete'
rule_count: 42
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

### Core Technologies

| Category | Technology | Version | Notes |
|----------|-----------|---------|-------|
| **Language** | Python | 3.8+ | Tested up to 3.13 |
| **Data** | pandas | >=1.3.0 | Time series processing |
| **Numerical** | numpy | >=1.20.0 | Computations |
| **Visualization** | matplotlib | >=3.3.0 | Static charts |
| **Visualization** | plotly | >=5.0.0 | Interactive charts |
| **Visualization** | pyecharts | >=1.9.0 | Web charts |
| **Testing** | pytest | >=6.0.0 | Test framework |
| **Exchange API** | CCXT | latest | Crypto trading |
| **Futures API** | ctp-python | latest | China futures (native CTP) |

### Key Version Constraints

- **NO Cython** - Removed, will use C++ directly for future optimizations
- **NO numba** - Platform compatibility issues, commented out
- **Python 2 code removed** - Legacy compatibility code cleaned up
- **C++ for performance** - Future optimizations will use C++ instead of Cython

---

## Critical Implementation Rules

### Language-Specific Rules (Python)

#### CRITICAL: Initialization Order (Post-Metaclass Architecture)

```python
# ❌ WRONG - self.p not available yet
class BadStrategy(bt.Strategy):
    def __init__(self):
        print(self.p.period)  # Will fail!

# ✅ CORRECT - Call super().__init__() FIRST
class GoodStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()  # Sets up self.p
        print(self.p.period)  # Now works
```

#### CRITICAL: donew() Pattern (Core of Post-Metaclass Architecture)

```python
def __new__(cls, *args, **kwargs):
    _obj, args, kwargs = cls.donew(*args, **kwargs)  # Owner detection happens here
    return _obj

def __init__(self, *args, **kwargs):
    # Initialize attributes early
    # Then call parent __init__
    super().__init__(*args, **kwargs)
```

**Key Points:**
- `donew()` replaces metaclass `__call__`
- Owner assignment happens via `metabase.findowner()` in `donew()`
- Line buffers are created during parent `__init__` chain

#### CRITICAL: Indicator Registration System (lineiterator.py:528-556)

```python
# Indicators MUST register to owner's _lineiterators
class MyIndicator(bt.Indicator):
    _ltype = LineIterator.IndType  # Value: 0

    def __init__(self):
        super().__init__()
        # If owner exists, auto-registers to owner._lineiterators[0]
```

**Common Bug:** If indicators aren't registered, they won't update during backtesting.

#### Error Handling Pattern

```python
# ❌ WRONG - Broad exception catching
try:
    order = api.place_order(...)
except Exception:
    pass  # Hides all errors

# ✅ CORRECT - Catch specific exceptions
try:
    order = api.place_order(...)
except (NetworkError, ExchangeError) as e:
    logger.error(f"Order failed: {e}")
    raise
```

#### Logging Standards

- **Use `SpdLogManager`** for all logging
- If using stdlib logging or DummyLogger, fix to use SpdLogManager
- Use structured logging for quant trading-specific contexts

#### Type Annotations

- Type hints are **encouraged** but not mandatory
- Core APIs (e.g., Cerebro) have type annotations added

---

## Framework-Specific Rules (Backtrader)

### Line System Architecture (Core Data Structure)

```python
# Line hierarchy (bottom-up)
LineRoot → LineBuffer → LineSeries → LineIterator

# Access patterns
data.close[0]   # Current value
data.close[-1]  # Previous value
data.close[1]   # Future value (backtesting only)
```

### Three Execution Phases

```python
class MyStrategy(bt.Strategy):
    def prenext(self):
        # Phase 1: Initial bars before minperiod satisfied
        pass

    def nextstart(self):
        # Phase 2: Transition bar when minperiod first satisfied (called once)
        pass

    def next(self):
        # Phase 3: Normal operation, called every bar
        pass
```

### Data Flow Architecture

```
Data Feed → Cerebro → Strategy → Indicators/Observers/Analyzers
                    ↓
                 Broker ← Orders
```

### Observer Extension Pattern (Primary Extension Method)

```python
from ..observer import Observer

class CustomObserver(Observer):
    _stclock = True  # Use system clock
    _ltype = 2        # LineIterator.ObsType
    lines = ('dummy',)  # Must have at least one line

    params = dict(enabled=True)

    def start(self):
        # Called when backtest/live starts
        # Register to _lineiterators
        self._ltype = 2
        if hasattr(self, '_owner') and self._owner:
            if hasattr(self._owner', '_lineiterators'):
                if self._ltype in self._owner._lineiterators:
                    if self not in self._owner._lineiterators[self._ltype]:
                        self._owner._lineiterators[self._ltype].append(self)

    def next(self):
        # Called every bar
        self.lines.dummy[0] = 0  # Must set
```

### CCXT Live Trading Pattern

```python
# CCXT Store/Broker/Feed three-layer architecture
store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': ..., 'secret': ...}
)

# WebSocket shared mode
data = store.getdata(
    dataname='BTC/USDT',
    use_websocket=True,  # Shared WebSocket connection
    timeframe=bt.TimeFrame.Minutes
)

cerebro.adddata(data)
cerebro.setbroker(store.getbroker())
```

### CTP Futures Trading Pattern

```python
# CTP uses native ctp-python (NOT ctpbee)
store = CTPStore(
    userid='...',
    password='...',
    brokerid='9999',  # SimNow
    # Auto-detect reachable CTP server (SimNow 7x24 / SimNow Trade / OpenCTP)
)

cerebro.setbroker(store.getbroker())
cerebro.adddata(store.getdata(dataname='au2506'))
```

### Live Broker/Feed/Store Abstract Base Classes

```python
# Live trading unified interface
class LiveStore(ABC):
    @abstractmethod
    def getbroker(self) -> LiveBroker: ...

    @abstractmethod
    def getdata(self, **kwargs) -> LiveFeed: ...

class LiveBroker(ABC):
    @abstractmethod
    def is_connected(self) -> bool: ...

class LiveFeed(ABC):
    @abstractmethod
    def is_live(self) -> bool: ...
```

---

## Testing Rules

### Test Organization

```
tests/
├── original_tests/     # Core functionality (300+ tests)
├── add_tests/          # Additional coverage
├── refactor_tests/     # Metaclass removal tests
└── strategies/         # Strategy-specific tests
```

### Test Execution

```bash
# Parallel execution (recommended)
pytest tests/ -n 4 -v

# Unit tests only (fast)
pytest tests/ -m "not integration" -v

# Integration tests (requires testnet keys)
pytest tests/ -m "integration" -v
```

### Priority Markers (pytest markers)

| Marker | Description | Priority |
|--------|-------------|----------|
| `priority_p0` | Core functionality | Critical |
| `priority_p1` | Core user journeys | High |
| `priority_p2` | Secondary features | Medium |
| `priority_p3` | Rarely used features | Low |
| `integration` | Requires live connection | - |
| `websocket` | WebSocket-specific | - |
| `trading` | Sandbox order tests | - |

### Test Naming Conventions

- Files: `test_<module>.py` (e.g., `test_ccxtbroker.py`)
- Functions: `test_<feature>_<scenario>()`
- Test IDs: `EPIC.STORY-LEVEL-SEQ` format

### Test Data Pattern

```python
# Unit tests use minimal data (10-20 bars)
def test_indicator_calculation():
    data = pd.DataFrame({
        'close': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    })
    # ... test logic

# Indicator registration verification
def test_indicator_registration(strategy):
    assert indicator in strategy._lineiterators[0]
```

### Coverage Targets

- CCXT modules: ~80% (WebSocket 78%, Broker 82%, Feed 77%)
- CTP modules: 66 new unit tests
- Warnings filtered: `RuntimeWarning` and `DeprecationWarning` by default

### Mock Pattern

```python
# Use mocks to avoid real API calls
@pytest.fixture
def mock_ccxt_exchange():
    with mock.patch('ccxt.binance') as mock_exchange:
        mock_exchange.return_value.fetch_ohlcv.return_value = [...]
        yield mock_exchange
```

---

## Code Quality & Style Rules

### Code Formatting (Black)

```toml
[tool.black]
line-length = 124  # Maximum line length
target-version = ["py38", "py39", "py310", "py311", "py312", "py313"]
```

### Naming Conventions (Pylint config)

| Type | Convention | Example |
|------|------------|---------|
| Classes | PascalCase | `TradeLogger`, `CCXTBroker` |
| Functions/Methods | snake_case | `log_signal()`, `_init_mysql()` |
| Constants | UPPER_CASE | `MYSQL_AVAILABLE`, `OBS_TYPE` |
| Private members | `_prefix` | `_loggers_initialized`, `_owner` |
| Variables | snake_case | `data_name`, `order_type` |

### Import Order (isort)

```python
# Standard library
import os
import sys

# Third-party
import pandas as pd
import ccxt

# Local modules
from backtrader import Strategy
from backtrader.observers import TradeLogger
```

### Comment Style

- **Code comments in ENGLISH**
- **Google-style docstrings**

```python
def calculate_sma(period, data):
    """Calculate Simple Moving Average.

    Args:
        period (int): Number of periods for the average.
        data (array-like): Input data series.

    Returns:
        numpy.ndarray: Calculated SMA values.

    Raises:
        ValueError: If period is less than or equal to zero.
    """
    pass
```

### Code Organization

```
backtrader/
├── core/              # Core modules
├── indicators/        # Technical indicators
├── observers/         # Observers (including logging)
├── analyzers/         # Performance analyzers
├── feeds/            # Data sources
├── brokers/          # Broker implementations
├── utils/            # Utility functions
└── signals/          # Signal system
```

### Code Quality Workflow (based on `scripts/optimize_code.sh`)

```bash
# Complete optimization pipeline (execute in order)
1. pyupgrade --py38-plus     # Upgrade Python syntax
2. isort                      # Organize imports
3. black --line-length 124    # Format code
4. ruff check --fix           # Lint with auto-fix
5. pip install -U .           # Update installation
# 6. pytest tests -n 8        # Verify (optional)
```

### One-Command Optimization

```bash
bash scripts/optimize_code.sh
```

---

## Development Workflow Rules

### Branch Strategy

| Branch | Purpose |
|--------|---------|
| `dev` | Active development (45% performance, tick-level tests, C++ integration) |
| `master` | Stable version (aligned with official backtrader) |
| `development` | Main branch (PR target) |

### Commit Message Format (Conventional Commits)

```
<type>: <description>

[optional body]
```

| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat: add CCXT WebSocket support` |
| `fix` | Bug fix | `fix: correct CTP order cancellation` |
| `refactor` | Refactor | `refactor: unify logging with SpdLogManager` |
| `docs` | Documentation | `docs: update live trading guide` |
| `test` | Testing | `test: add CCXT broker integration tests` |
| `chore` | Build/config | `chore: upgrade pytest to 8.0` |

### Release Process

Based on `CHANGELOG.md`:
1. Update `[Unreleased]` section in CHANGELOG.md
2. Create version tag (e.g., `v1.1.0`)
3. Merge to `master` branch

### Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest tests/ -n 4 -v

# Code optimization
bash scripts/optimize_code.sh

# Generate documentation
make docs

# View all Makefile commands
make help
```

---

## Critical Don't-Miss Rules (Anti-Patterns)

### 🚫 ABSOLUTELY FORBIDDEN Patterns

#### 1. NEVER Introduce New Metaclasses

```python
# ❌ FORBIDDEN
class MetaMyClass(type):
    pass

class MyClass(metaclass=MetaMyClass):
    pass

# ✅ CORRECT - Use donew() pattern
from ..metabase import BaseMixin

class MyClass(BaseMixin):
    def __new__(cls, *args, **kwargs):
        _obj, args, kwargs = cls.donew(*args, **kwargs)
        return _obj
```

#### 2. NEVER Access self.p Before super().__init__()

```python
# ❌ FORBIDDEN
class Bad(bt.Strategy):
    def __init__(self):
        period = self.p.period  # AttributeError!
        super().__init__()

# ✅ CORRECT
class Good(bt.Strategy):
    def __init__(self):
        super().__init__()
        period = self.p.period  # Now OK
```

#### 3. NEVER Use Broad Exception Catching

```python
# ❌ FORBIDDEN
try:
    order = api.place_order(...)
except Exception:
    pass  # Hides all errors

# ✅ CORRECT
try:
    order = api.place_order(...)
except (NetworkError, ExchangeError) as e:
    logger.error(f"Order failed: {e}")
    raise
```

#### 4. NEVER Break API Backward Compatibility

```python
# ❌ FORBIDDEN - Changing existing API signature
def buy(self, new_required_param):  # Breaks existing user code
    pass

# ✅ CORRECT - Use optional parameters
def buy(self, new_optional_param=None):
    pass
```

#### 5. NEVER Forget Indicator Registration

```python
# ❌ Common bug - indicator won't update
class MyStrategy(bt.Strategy):
    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(period=20)
        # If owner detection fails, sma won't update!

# ✅ Verify registration
def __init__(self):
    super().__init__()
    self.sma = bt.indicators.SMA(period=20)
    assert self.sma in self._lineiterators[0]  # Verify
```

### ⚠️ Critical Edge Cases

#### WebSocket Connection Sharing

```python
# ⚠️ Multiple feeds share same WebSocket connection
# Don't close shared connection in Feed.stop()
class CCXTFeed:
    def stop(self):
        if not self._ws_is_shared:
            self._ws_manager.stop()
```

#### CTP Server Auto-Detection

```python
# ⚠️ CTP auto-detects available servers
# Don't hardcode SimNow addresses
store = CTPStore(
    # No td_address/md_address needed, auto-detects
    userid='...',
    password='...'
)
```

#### Order Status Tracking

```python
# ⚠️ Order status is asynchronous in live trading
# Don't assume immediate execution
order = self.buy()
# order.status may still be Submitted
# Check order.status == Order.Completed in next()
```

### 🔒 Security Rules

| Rule | Description |
|------|-------------|
| API Keys | Never commit to repo, use `.env` files |
| Log Sanitization | Never log API keys or sensitive info |
| Order Validation | Always test in sandbox/testnet before live |

### ⚡ Performance Traps

| Pattern | Description |
|---------|-------------|
| `len()` in hot paths | Minimize `isinstance()`, `hasattr()`, `len()` calls |
| Redundant indicator calculations | Use Line's lazy evaluation |
| Unnecessary loops | Use vectorized operations (pandas/numpy) |

---

## Usage Guidelines

### For AI Agents:
- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

### For Humans:
- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

---

**Last Updated:** 2025-02-28
**Status:** Complete and optimized for LLM consumption
