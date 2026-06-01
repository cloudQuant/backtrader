# Changelog — Version 1.2.0

**Base branch**: `dev` (merged into `development`)
**Commit range**: `5a886266` … `4f05beb0` (276 commits)
**Period**: 2026-03-08 — 2026-06-01

---

## Highlights

| Metric | Value |
|--------|-------|
| Commits | 276 |
| Files changed | ~3,078 |
| Lines added | +3,346,623 |
| Lines removed | −233,658 |
| Strategy regression tests | 1,271 (all passing) |
| Regression suite speedup | **−46%** (7m18s → 3m56s) |

---

## Breaking Changes

> The following legacy live-trading integrations have been removed. If you rely on any of these, **do not upgrade** and stay on the `development` branch.

| Removed Module | Replacement |
|----------------|------------|
| `backtrader/ccxt/` (full module) | Use `backtrader/stores/btapistore.py` + `bt_api_py` |
| `backtrader/stores/ccxtstore.py` | Use `btapistore` |
| `backtrader/stores/cryptostore.py` | Use `btapistore` |
| `backtrader/stores/ctpstore.py` | Use `btapistore` (SimNow support) |
| `backtrader/stores/futustore.py` | Use `btapistore` (Futu not yet migrated) |
| `backtrader/stores/ibstore.py` | Use `btapistore` (IB not yet migrated) |
| `backtrader/stores/oandastore.py` | Use `btapistore` (OANDA not yet migrated) |
| `backtrader/stores/vcstore.py` | Use `btapistore` (VC not yet migrated) |
| `backtrader/brokers/ccxtbroker.py` | Use `btapibroker` |
| `backtrader/brokers/cryptobroker.py` | Use `btapibroker` |
| `backtrader/brokers/ctpbroker.py` | Use `btapibroker` |
| `backtrader/brokers/futubroker.py` | Use `btapibroker` |
| `backtrader/brokers/ibbroker.py` | Use `btapibroker` |
| `backtrader/brokers/oandabroker.py` | Use `btapibroker` |
| `backtrader/brokers/obbroker.py` | Use `btapibroker` |
| `backtrader/brokers/vcbroker.py` | Use `btapibroker` |
| `backtrader/feeds/ccxt_live_tick.py` | Use `btapifeed` |
| `backtrader/feeds/ccxtfeed.py` | Use `btapifeed` |
| `backtrader/feeds/cryptofeed.py` | Use `btapifeed` |
| `backtrader/feeds/ctpdata.py` | Use `btapifeed` |
| `backtrader/feeds/futufeed.py` | Use `btapifeed` |
| `backtrader/feeds/ibdata.py` | Use `btapifeed` |
| `backtrader/feeds/oanda.py` | Use `btapifeed` |
| `backtrader/feeds/vcdata.py` | Use `btapifeed` |
| `backtrader/commissions/dc_commission.py` | (dead code) |

**Static data feeds** (CSV, Pandas, Yahoo Finance) are **unaffected**.

---

## New Features

### `bt_api_py` Unified Live-Trading API

A new unified store architecture via `bt_api_py` replaces the fragmented per-broker implementations.

- **`backtrader/stores/btapistore.py`** — Central store implementing the `bt_api_py` protocol
- **`backtrader/feeds/btapifeed.py`** — Generic data feed for `bt_api_py` sources
- **`backtrader/brokers/btapibroker.py`** — Generic broker for `bt_api_py` sources

### HFT (High-Frequency Trading) Framework

New `backtrader/brokers/hft/` package for tick-level backtesting and live trading:

| File | Purpose |
|------|---------|
| `binance_bbo.py` | Binance Best Bid-Offer capture |
| `binance_bbo_compare.py` | BBO cross-exchange comparison |
| `matching_core.py` | Order matching engine |
| `latency.py` | Latency modeling |
| `recorder.py` | Trade recording |
| `queue.py` | Priority queue for order book |
| `state.py` | Session state management |
| `exchange.py` | Exchange interface |
| `examples.py` | Usage examples |

### New Indicators

- **`backtrader/indicators/mt5atr.py`** — MT5-style ATR implementation

### Position Modes

- **`backtrader/position_modes.py`** — Explicit position mode management

### Trade Profiles

- **`backtrader/profiles.py`** — Trade profile/account configuration

---

## Performance Improvements

### Regression Suite Speedup (−46%)

The full 1,271-strategy regression suite now completes in **3m56s** vs 7m18s previously (macOS, Python 3.11, 8 parallel workers).

| Strategy Category | Speedup |
|-----------------|---------|
| Simple MA Cross | ~40-45% |
| Multi-Indicator | ~45-50% |
| Multi-Data | ~42-48% |
| Complex Strategies | ~38-42% |

### Core Optimizations

| Module | What was changed |
|--------|-----------------|
| `linebuffer.py` | Hot-path scalar reads, NaN-check optimization |
| `broker.py` | Parameter cache, hot-path method inlining |
| Indicators `once()` | Math-function and constant caching |
| `cerebro.py` | Phase extraction, complexity reduction |

### Multi-Data Clock Fix

Fixed secondary-feed indicator clock advancement in `runonce` mode. Indicators like `SMA((h1.high + h1.low)/2.0)` or `EMA(EMA(h4.close))` inside an M15 strategy now correctly advance on the **secondary feed's clock**, not the strategy's primary feed.

---

## Code Quality Improvements

### S1–S8 Iterations Summary

The dev branch underwent aggressive code-quality remediation across 8 sprint iterations:

| Category | Work Done |
|---------|---------|
| **Exception visibility** | All `except Exception: pass` converted to `except Exception as e` with debug logging |
| **Analyzer hardening** | 49 rounds of sanitization — NaN/Inf handling, divide-by-zero guards, boundary checks |
| **Sharpe Ratio** | Complete rewrite of input validation, trial-count bounds, annualization |
| **Drawdown analyzers** | Invalid value sanitization end-to-end |
| **Mypy compliance** | All core modules cleared (200+ errors → 0) |
| **Ruff/Black** | All files formatted to line-length 100 |
| **Dead code** | ~680 lines of commented-out code removed |
| **Silent except** | Every silent catch replaced with logging/raising |

### Complexity Reductions (selected)

| File | Cyclomatic Complexity | Before → After |
|------|---------------------|----------------|
| `BackBroker._get_value` | Split into 3 helpers | 36 → 11 |
| `SignalStrategy._next_signal` | Phase extraction | 84 → 28 |
| `cerebro.run` flag setup | Extracted to helper | 41 → 32 |
| `TradeAnalyzer.closed_trade_stats` | Extracted to helper | 32 → 3 |
| `SharpeRatio.stop` | Split | 40 → 2 |
| `PandasData` column mapping | Extracted resolver | 22 → 12 |
| `get_pnl_metrics` trade block | Extracted | 26 → 12 |
| `btrun` CLI | Refactored config tabs | reduced |

---

## Testing Improvements

### Strategy Regression Suite

- **1,271 inline regression tests** — All strategy tests migrated from source files into self-contained inline test files
- Test duration tracking — each strategy test is timed; slowest 65% auto-tagged `slow`
- `test-fast` (fastest 35%) completes in ~3.5 min
- `test-slow` (slowest 65%) runs separately
- `test-strategies` (all 1,271) completes in ~4 min on `dev`

### New Unit Test Coverage

- `tests/unit/observers/test_trade_logger_edge_cases.py` (368 lines)
- `tests/unit/observers/test_trade_logger_internal_errors.py` (56 lines)
- `tests/unit/observers/test_trade_logger_monitoring.py` (105 lines)
- `tests/unit/reports/test_performance_calculator_edge_cases.py` (565 lines)
- `tests/unit/reports/test_performance_edge_cases.py` (491 lines)
- `tests/unit/stores/test_btapistore.py` (1,890 lines)
- `tests/unit/stores/test_btapistore_edge_cases.py` (244 lines)
- `tests/unit/stores/test_btapistore_notifications.py` (291 lines)
- `tests/unit/stores/test_credential_safety.py` (85 lines)
- `tests/unit/test_live_profile.py` (577 lines)
- `tests/unit/test_live_validator.py` (45 lines)
- Plus: broker observers, benchmark, buysell, drawdown, logreturns, trades, Sizer/CommInfo zero-price edge cases, and more

---

## Bug Fixes

### Batch 1–57 (Non-Finite Value Sanitization)

57 rounds of fixes for NaN/Inf propagation in:

- `linebuffer.py` — hot-path scalar reads, extend, write entrypoints, binary/unary operations
- `lineseries.py` — index reads, current values, stage2 arithmetic
- `report` charts — equity curve, drawdown, trade metrics, benchmark
- `bbroker.py` — fundstartval=0 division-by-zero, orderbook floats
- `tradingcal.py` — `nextday_week` return value

### Runonce Fixes

- Secondary-feed indicator clock advancement (WMA fsum parity)
- Line action consistency and clocks
- Indicator warmup parity
- Child indicator registration in `bt.If` and `Logic` subclasses
- `LinesOperation` as indicator data source in runonce mode
- `bt.If` self-referencing patterns

### Order/Broker Fixes

- Stale tick prices for stacked bars
- Submitted order cash projection
- Order cancellation handling
- Order `__ne__` None crash
- `orderstatus int.status` bug
- `BackBroker._get_value` divide-by-zero
- `ComminfoDC` credit interest `.seconds` bug

### Data Feed Fixes

- `calendars.fill_price` None TypeError
- Renko autosize divide-by-zero
- Resample data clone
- `PandasData` column mapping resolution (regression)

### Indicator Fixes

- Minperiod propagation for line-bound indicators
- Pre-allocate `dst` array in `Logic` subclass `once()` methods

### TradeLogger Fixes

- Include `datetime` in text logs
- Broker value/cash in bar and position logs

---

## Security Hardening

- **Diagnostic logging** — All `TradeLogger` diagnostic output routed through `get_logger` (no `print`)
- **Credential masking** — API keys/secrets masked in logs for `btapistore` and live-trading paths
- **Network timeout** — Explicit timeout configuration on all network operations
- **Exception visibility** — No more silent failures; all catch blocks log or raise

---

## Documentation

- **ARCHITECTURE.md** — New architecture reference document
- **CLAUDE.md** — Fully rewritten with verified current state
- **README.md** — Refreshed with tiered test commands, performance benchmarks, and backtrader source-switch documentation
- **CONTRIBUTING.md** — Updated with sprint documentation
- Module docstrings added to all 11 modules previously missing them

---

## Test Infrastructure

- **Duration-based test splitting** — `conftest.py` auto-tags slow strategy tests
- `tests/datas/mt5_1d_data/` — MT5 daily CSV fixtures for all regression symbols (XAUUSD, XAGUSD, IVV, IEF, GLD, IWM, etc.)
- `BACKTRADER_USE_INSTALLED` env var and `--use-installed-backtrader` CLI flag to test installed vs local copy
- Scripts: `scripts/refresh_strategy_durations.py`, `scripts/run_strategy_branch_compare.py`

---

## Deprecations

| Deprecated | Status |
|------------|--------|
| `backtrader/commissions/dc_commission.py` | **Removed** (was dead code) |
| All legacy store/broker modules | **Removed** — use `btapistore` + `btapibroker` |
| CCXT-based feeds and stores | **Removed** — use `btapifeed` + `btapistore` |

---

## Migration Guide

### From Any Version < 1.2.0 Using Legacy Live Trading

If you use IB, OANDA, CCXT, CTP, Futu, or VC live trading:

1. Install `bt_api_py`: `pip install bt_api_py`
2. Replace store instantiation:

```python
# Before (removed)
import backtrader as bt
data = bt.feeds.OandaData(...)
broker = bt.brokers.OandaBroker(...)

# After
import backtrader as bt
from backtrader.stores.btapistore import btapistore
store = btapistore(token="your_oanda_token")
data = bt.feeds.BTAPIFeed(store=store, ...)
broker = bt.brokers.BTAPIBroker(store=store)
```

> **Note**: `bt_api_py` support varies by broker. Check `backtrader/stores/btapistore.py` for current broker coverage.

### Static Data Users (CSV, Pandas, Yahoo)

**No action required.** These are completely unaffected.

---

## Version Reference

| Version | Branch | Status |
|---------|--------|--------|
| 1.1.0 | `master` | Stable |
| 1.2.0 | `dev` → `development` | **Release candidate** |

