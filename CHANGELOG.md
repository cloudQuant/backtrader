# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased] - dev branch

### Added
- **CCXT Broker Error Handling & Reconnection** (P0)
  - `_retry_api_call()` with exponential backoff for all broker API calls
  - Connection awareness in `next()` — skips API calls when exchange disconnected
  - Adaptive polling backoff after consecutive failures (3s → 30s)
  - `_process_threaded_updates()` — ThreadedOrderManager integration in broker loop
  - `_submit()` error handling — returns rejected order with notification on failure
  - `cancel()` error handling — graceful degradation on network failure
  - "Order not found" detection for stale orders

- **CCXT Feed WebSocket Enhancement** (P1)
  - `_check_ws_health()` — stale WebSocket connection detection
  - Automatic REST fallback when WebSocket disconnects
  - Automatic data backfill after WebSocket reconnection (gap > 60s)
  - `_fetch_ohlcv_with_retry()` — retry logic for OHLCV data fetching
  - Consecutive error tracking with progressive backoff

- **CCXT Enhancement Module** (`backtrader/ccxt/`)
  - `CCXTWebSocketManager` — ccxt.pro WebSocket with auto-reconnect
  - `ThreadedDataManager` / `ThreadedOrderManager` — non-blocking background threads
  - `RateLimiter` / `AdaptiveRateLimiter` — smart API rate limiting
  - `ConnectionManager` — health monitoring with disconnect/reconnect callbacks
  - `ExchangeConfig` — centralized exchange configurations (Binance/OKX/Bybit/etc.)
  - `BracketOrderManager` — OCO bracket order support
  - `config_helper` — .env based configuration loading

- **Visualization & Reporting**
  - Plotly interactive charts
  - Bokeh chart module
  - TradeLogger observer for trade recording
  - HTML report generation

- **Testing Infrastructure**
  - pytest fixtures and data factory pattern
  - Priority markers (P0-P3) for selective test execution
  - Test ID convention (`EPIC.STORY-LEVEL-SEQ`)
  - 34 new tests for CCXT error handling and reconnection

- **Project Documentation**
  - `docs/PROJECT_STATUS.md` — consolidated project status
  - `CHANGELOG.md` — this file
  - `CONTRIBUTING.md` — contribution guidelines
  - `docs/ARCHITECTURE.md` — system architecture overview
  - `docs/CCXT_LIVE_TRADING_GUIDE.md` — CCXT live trading user guide

### Changed
- **Performance**: 45% faster execution vs original backtrader
  - Removed 8 metaclasses (MetaBase, MetaLineRoot, MetaIndicator, MetaStrategy, etc.)
  - Explicit `donew()` + `BaseMixin` initialization pattern
  - Cython-accelerated core calculations (10-100x for hot paths)
  - Circular buffer memory optimization (`qbuffer`)
  - Cached attribute access in hot paths (broker, analyzer, feed)

- **CCXTBroker** (`brokers/ccxtbroker.py`)
  - `next()` now checks connection status before API calls
  - `next()` dispatches to ThreadedOrderManager when available
  - `_next()` wrapped with try/except and retry logic
  - `_submit()` returns rejected order on failure instead of crashing
  - `cancel()` handles network errors gracefully

- **CCXTFeed** (`feeds/ccxtfeed.py`)
  - `_load()` performs WS health check and handles fallback
  - `_update_bar()` checks connection before fetching
  - `_on_websocket_ohlcv()` detects reconnection gaps for backfill

### Fixed
- Multiple data length inconsistency causing early strategy termination
- CrossOver indicator dependency ordering in exactbars mode
- Indicator clock initialization in cerebro._runonce()
- Data.__bool__() trap causing `if clock:` to fail for empty data

---

## [1.0.0] - 2025 (dev branch baseline)

### Summary
Initial release of the performance-optimized fork with metaclass removal.

- 45% performance improvement over original backtrader
- 119 strategy tests passing at 100%
- Metaclass-free architecture with API backward compatibility
- Cython integration for performance-critical calculations
- Multi-asset portfolio support (CS mode)
- Vectorized backtesting (TS mode)
