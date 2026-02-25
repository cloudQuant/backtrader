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

- **WebSocket Order Push — P2-1** (`brokers/ccxtbroker.py`)
  - `use_websocket_orders=True` enables `watch_my_trades` real-time fill push
  - `_init_ws_order_manager()` / `_ws_subscribe_symbol()` / `_on_ws_my_trades()`
  - `_process_ws_order_updates()` matches fills to open orders with dedup
  - `next()` priority: WS push > ThreadedOrderManager > REST polling
  - `_submit()` auto-subscribes WS for new symbols on order placement

- **Multi-Symbol Shared WebSocket — P2-2** (`stores/ccxtstore.py` + `feeds/ccxtfeed.py`)
  - `CCXTStore.get_websocket_manager()` — lazy-init shared WS manager
  - Multiple feeds share single WS connection, each subscribing its own OHLCV channel
  - Reduces connection count and exchange rate-limit pressure

- **Funding Rate Real-Time Push — P2-3** (`feeds/ccxtfeed_funding.py`)
  - `CCXTFeedWithFunding` uses shared WS for OHLCV + funding_rate + mark_price
  - `_ws_is_shared` flag prevents `stop()` from killing shared connections

- **Integration Test Framework** (`tests/integration/`)
  - Sandbox/testnet integration tests for OKX (extendable to Binance/Bybit)
  - `test_ccxt_connectivity.py` — REST API connectivity and data fetch validation
  - `test_ccxt_websocket.py` — WS lifecycle, OHLCV/ticker/funding streaming, shared WS
  - `test_ccxt_trading.py` — order lifecycle (place/cancel/fill), WS order push
  - Graceful skip for IP whitelist and missing credentials

- **Testing Infrastructure**
  - pytest fixtures and data factory pattern
  - Priority markers (P0-P3) for selective test execution
  - Test ID convention (`EPIC.STORY-LEVEL-SEQ`)
  - 34 new tests for CCXT error handling and reconnection
  - 24 new tests for P2 WebSocket features

- **CTP Futures Trading Refactor** (`stores/ctpstore.py`, `brokers/ctpbroker.py`, `feeds/ctpdata.py`)
  - Complete rewrite from `ctpbee` to native `ctp-python` (SWIG wrapper for CTP C++ API)
  - `CTPStore` — singleton managing TraderSpi/MdSpi connections with thread-safe callbacks
  - `CTPBroker` — order submission/cancellation, account/position queries via CTP TraderApi
  - `CTPData` — live tick aggregation into bars, market data subscription via CTP MdApi
  - Lazy import for `DataCls`/`BrokerCls` in `CTPStore.getdata()`/`getbroker()`
  - Auto-detect reachable CTP server (SimNow 7x24 / SimNow Trade / OpenCTP)
  - 66 unit tests for CTP store, broker, and data feed
  - Example scripts: `test_ctp_sample.py` (gold futures), `ctp_sa_dual_ma_strategy.py` (SA dual-MA)

- **Project Documentation**
  - `docs/PROJECT_STATUS.md` — consolidated project status
  - `CHANGELOG.md` — this file
  - `CONTRIBUTING.md` — contribution guidelines
  - `docs/ARCHITECTURE.md` — system architecture overview
  - `docs/CCXT_LIVE_TRADING_GUIDE.md` — CCXT live trading user guide
  - `docs/opts/优化需求/INDEX.md` — categorized index for 80+ optimization requirement docs

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

### Removed
- `docs/opts/project_status_summary.md` — severely outdated (2024), replaced by `docs/PROJECT_STATUS.md`

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
