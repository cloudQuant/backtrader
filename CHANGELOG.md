# Changelog

All notable changes to this project are recorded here. This is the single
canonical changelog for the repository.

## [Unreleased]

### Added

- Added the optional ``CryptoHFTData`` historical crypto feed for exchange-native trade ticks
  and trade-derived OHLCV bars.

### Repository Maintenance

- Consolidated the root changelog files into this single `CHANGELOG.md`.
- Removed the generated `mypy-report.txt` artifact from version control and
  added it to `.gitignore`; CI still creates it transiently during the mypy
  gate.
- Moved root helper scripts into `scripts/`:
  - `scripts/install_unix.sh`
  - `scripts/install_win.bat`
  - `scripts/run_tests.sh`
  - `scripts/run_tests.bat`
- Removed legacy local workflow metadata from `.windsurf/workflows`.
- Removed obsolete `.kiro/steering` project guidance; use `AGENTS.md`,
  `README.md`, and project config files instead.

## [1.2.0] - 2026-06-01

**Base branch**: `dev` merged into `development`

### Highlights

| Metric | Value |
| --- | --- |
| Strategy regression tests | 1,271 passing |
| Regression suite speedup | 7m18s to 3m56s |
| Python support | 3.8-3.13 in the pure-Python package |
| Main development focus | API compatibility with lower runtime overhead |

### Breaking Changes

Legacy live-trading integrations were removed in favor of the unified
`bt_api_py`-based live-trading path.

| Removed Module | Replacement |
| --- | --- |
| `backtrader/ccxt/` | `backtrader/stores/btapistore.py` + `bt_api_py` |
| `backtrader/stores/ccxtstore.py` | `btapistore` |
| `backtrader/stores/cryptostore.py` | `btapistore` |
| `backtrader/stores/ctpstore.py` | `btapistore` |
| `backtrader/stores/futustore.py` | `btapistore` |
| `backtrader/stores/ibstore.py` | `btapistore` |
| `backtrader/stores/oandastore.py` | `btapistore` |
| `backtrader/stores/vcstore.py` | `btapistore` |
| `backtrader/brokers/ccxtbroker.py` | `btapibroker` |
| `backtrader/brokers/cryptobroker.py` | `btapibroker` |
| `backtrader/brokers/ctpbroker.py` | `btapibroker` |
| `backtrader/brokers/futubroker.py` | `btapibroker` |
| `backtrader/brokers/ibbroker.py` | `btapibroker` |
| `backtrader/brokers/oandabroker.py` | `btapibroker` |
| `backtrader/brokers/obbroker.py` | `btapibroker` |
| `backtrader/brokers/vcbroker.py` | `btapibroker` |
| `backtrader/feeds/ccxt_live_tick.py` | `btapifeed` |
| `backtrader/feeds/ccxtfeed.py` | `btapifeed` |
| `backtrader/feeds/cryptofeed.py` | `btapifeed` |
| `backtrader/feeds/ctpdata.py` | `btapifeed` |
| `backtrader/feeds/futufeed.py` | `btapifeed` |
| `backtrader/feeds/ibdata.py` | `btapifeed` |
| `backtrader/feeds/oanda.py` | `btapifeed` |
| `backtrader/feeds/vcdata.py` | `btapifeed` |
| `backtrader/commissions/dc_commission.py` | Removed dead code |

Static CSV, Pandas, and Yahoo Finance feeds are unaffected.

### Added

- Unified live-trading store/feed/broker path:
  - `backtrader/stores/btapistore.py`
  - `backtrader/feeds/btapifeed.py`
  - `backtrader/brokers/btapibroker.py`
- HFT package under `backtrader/brokers/hft/` for tick-level backtesting and
  live-trading research.
- `backtrader/indicators/mt5atr.py`, an MT5-style ATR implementation.
- `backtrader/position_modes.py` for explicit position mode management.
- `backtrader/profiles.py` for trade profile/account configuration.
- Duration-based strategy test splitting in `conftest.py`.
- Installed-vs-local import selection for tests:
  - `BACKTRADER_USE_INSTALLED=1`
  - `pytest --use-installed-backtrader`

### Performance

- Full 1,271-strategy regression suite reduced from about 7m18s to 3m56s on
  the benchmark machine.
- Core hot paths optimized across `linebuffer.py`, `broker.py`, indicator
  `once()` methods, and `cerebro.py`.
- Multi-data runonce clock handling now pins secondary-feed indicators to their
  concrete feed clocks rather than the strategy primary feed.

### Code Quality

- Removed metaclass-based construction overhead in favor of explicit mixin and
  factory initialization.
- Cleared mypy errors in the core package for the configured CI gate.
- Applied ruff/black/isort formatting to the package.
- Reduced complexity in selected large functions including broker valuation,
  signal processing, analyzers, and CLI paths.
- Replaced silent exception handling with debug logging or explicit errors in
  security-sensitive and observability-sensitive paths.

### Fixed

- Non-finite value propagation in line buffers, lineseries reads, analyzers,
  broker calculations, and report generation.
- Runonce parity issues around secondary-feed indicators, child indicator
  registration, `LinesOperation` sources, and `bt.If`/logic subclasses.
- Broker/order edge cases including stale tick prices for stacked bars,
  submitted cash projection, cancellation handling, `Order.__ne__` with `None`,
  order status lookup, and divide-by-zero paths.
- Data-feed edge cases including calendar fill price handling, Renko autosize,
  resample clone behavior, and Pandas column mapping regression.
- TradeLogger datetime, broker value/cash, and diagnostic output behavior.

### Security

- Credential masking in `btapistore` and live-trading paths.
- Explicit network timeout configuration where applicable.
- Diagnostic output routed through `get_logger` instead of `print`.

### Documentation

- Added `docs/ARCHITECTURE.md`.
- Refreshed `README.md` with test tiers, performance benchmarks, and installed
  package source switching.
- Updated `CONTRIBUTING.md`.
- Added module docstrings to modules that previously lacked them.

### Migration Notes

For legacy live-trading integrations, migrate to the `bt_api_py` store/feed/
broker path:

```python
import backtrader as bt
from backtrader.stores.btapistore import btapistore

store = btapistore(token="your_token")
data = bt.feeds.BTAPIFeed(store=store)
broker = bt.brokers.BTAPIBroker(store=store)
```

## Historical Unreleased Notes - 2026-02-07

### Mid-Frequency Backtesting

- Refactored `MixBroker` into a mid-frequency coordination layer. The old
  `bar_fallback` and `tick_timeout` semantics were removed; `process_bar` now
  updates low-frequency state without performing order matching.
- Added `MidFreqContext` for unified access to high-frequency windows,
  completed bars, SMA state, account state, and multi-symbol snapshots.
- Normalized channel ordering for identical timestamps as
  `tick -> orderbook -> bar`.
- Added mixed-channel and arbitrage examples:
  - `build_mixed_channel()`
  - `examples/004_midfreq_demo/`
  - `examples/005_midfreq_arbitrage/`
- Added tests for single-symbol and multi-symbol mid-frequency behavior,
  high-frequency-priority execution, no matching on bar updates, cross-symbol
  snapshots, and `get_ob_ratio()` latency baselines.

### Fixed

- Position logs now skip data sources with no available data (`len(data) == 0`)
  to avoid empty datetimes.

### TradeLogger Observer

- Added real-time log writes during backtest execution.
- Added `log_time` as the first field for order, trade, position, and data log
  records.
- Added `current_position.json`, updated after each bar.
- Added `log_indicators` to record strategy-created indicators in data logs.
- Added configurable output formats: tab-separated `.log` and standard `.csv`.
- Added optional MySQL persistence for order, trade, and position logs.
- Added `scripts/setup_mysql_db.py` to initialize the MySQL schema.
- Renamed log files and MySQL tables to drop the `_log` suffix:
  `order.log`, `trade.log`, `position.log`, `bt_order`, `bt_trade`, and
  `bt_position`.
- Added tests for real-time writes, `log_time`, file formats,
  `current_position.json`, strategy indicators, and MySQL behavior.
