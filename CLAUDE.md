# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Backtrader is a Python algorithmic-trading framework for low/mid/high-frequency
backtesting and live trading. This repo is a performance-oriented fork of the
original [backtrader](https://www.backtrader.com/) that **removes metaclass-based
metaprogramming** in favor of explicit mixin + factory initialization while
keeping the public API compatible.

- **Version**: `1.4.0` (`backtrader/version.py`)
- **License**: GPLv3 (`LICENSE`). Note: `setup.py`'s classifier still says MIT —
  trust `LICENSE`, and do not "fix" one without confirming with the maintainer.
- **Python**: 3.8–3.13 (3.11 recommended); research features require 3.11+pandas.
- **PyPI**: distribution `back-trader-python` (import name stays `backtrader`).
  A separate pybind11/C++ wheel ships as `back-trader-cpp`; this repo is the
  pure-Python implementation.

> `AGENTS.md` (4,250 lines) is the large sibling guide. It carries current
> iteration acceptance records, evidence links, and operational detail. This
> file is the condensed working guide; when they disagree, verify against the
> source tree and prefer `AGENTS.md` for iteration-specific status.

### Branch model

Authoritative source: `docs/source/developer-guide/branch-governance.md`.

- `dev` — daily development entry. Features, ordinary fixes, docs, tests.
- `development` — improved/optimized release branch; controlled promotions.
- `master` — original upstream baseline; only baseline-reproducible
  bug/compatibility/security hotfixes. Regression tests bake master's metrics
  as expected values.

**Push to `dev`.** Do not push directly to `master` or `development`. `git push`
targets both GitHub (`cloudQuant/backtrader`) and Gitee (`yunjinqi/backtrader`).

### Private inputs

Ignored `.env` files, real `config.yaml` files, secrets, and private captures
are **not** review material. Use only public source, templates, tests, and
sanitized snapshots. An authorized account read must use the protected bounded
reader and emit only categories/booleans — never values or raw lines. Never
fall back to `cat`/`Get-Content`/`rg` on a private input.

## Development commands

### Install

```bash
pip install -r requirements.txt   # core + dev deps
pip install -U .                  # build & install
pip install -e .                  # editable/dev install
```

No Cython step is required: there are no tracked `.pyx` files and no
`ext_modules`. The only native-ish acceleration is `numba` inside
`backtrader/utils/dateintern.py`.

### Makefile caveat

`Makefile`'s `BT_CONDA_PYTHON` defaults to a hardcoded macOS Conda path
(`/Users/yunjinqi/opt/anaconda3/...`). On Windows/Linux, override it:

```bash
make test-fast BT_CONDA_PYTHON=python
```

### Testing

```bash
make test             # ONLY tests/original_tests/ (not the whole suite)
make test-fast        # parallel non-slow/non-performance suite + serial
                      #   performance lane. Daily "did I break anything" loop.
make test-slow        # only the slow-tier strategy tests
make test-strategies  # all tests/functional/strategies (~9 min)
make test-all         # parallel suite (no performance marker) + perf lane
make test-performance # wall-clock microbenchmarks, no xdist, no coverage
make test-coverage    # coverage over tests/original_tests/ only

# Single test:
pytest tests/path/to/test_file.py::test_name -v --tb=short
```

Equivalent underlying commands (from `Makefile`):

```bash
pytest tests -m "not slow and not performance" -n 8 -q   # test-fast part 1
pytest tests -m slow -n 8 -q                            # test-slow
pytest tests/functional/strategies -n 8 -q              # test-strategies
pytest tests -m "not performance" -n 8 -q               # test-all part 1
```

**Dynamic slow tier** (`conftest.py`): reads the committed
`tests/functional/strategies/.test_durations.json`, computes the
`BT_SLOW_PERCENTILE`th percentile (default **35**) of per-file durations, and
tags files at/above it `slow` at collection time. New/unknown files default to
the **fast** tier. Tune with `BT_SLOW_PERCENTILE=25|50 make test-fast`; refresh
timings with `python scripts/refresh_strategy_durations.py`.

**Performance lane**: tests marked `performance` measure wall-clock time and are
auto-skipped under xdist or coverage tracing. `make test-performance` runs them
serially; it also isolates one RSS-stress test into its own process.

**Installed-vs-local package**: pytest from the repo root imports the local
`backtrader/`. To test the installed copy:

```bash
BACKTRADER_USE_INSTALLED=1 pytest ...        # env var
pytest ... --use-installed-backtrader        # CLI flag
```

The active `backtrader.__file__` is printed in the pytest session header.

### Code quality

```bash
make format         # black --line-length 100
make format-check
make lint           # pylint with .pylintrc  (NOT ruff)
make type-check     # mypy (pyproject.toml, core backtrader/ only)
make security       # bandit + safety
make quality-check  # all of the above
bash scripts/optimize_code.sh   # pyupgrade + isort + black + ruff + tests
```

ruff is configured in `pyproject.toml` but has **no Makefile target**; it runs
through `scripts/optimize_code.sh`. `mypy` intentionally excludes
`backtrader_runtime/` diagnostics (see the override in `pyproject.toml`).

### Docs

```bash
make docs / docs-en / docs-zh   # Sphinx, English + Chinese
make help                       # list targets
make clean
```

Git LFS tracks Iteration 41 wheelhouse evidence archives; install Git LFS
before checkout so they materialize.

## Architecture

### Construction pipeline (replaces the metaclass)

`backtrader/metabase.py`:

- `ObjectFactory.create(cls, *args, **kwargs)` runs lifecycle hooks:
  `doprenew → donew → dopreinit → doinit → dopostinit`.
- `BaseMixin` supplies default `donew/dopreinit/doinit/dopostinit`.
- `ParamsMixin.__init_subclass__` installs a `patched_init` wrapper
  (`metabase.py:924`, assigned at `:1183`) that wires `self.p`/`self.params`,
  `data0/data1` aliases, and the lifecycle. Most indicators go through this
  path, not `ObjectFactory.create`.
- Owner discovery uses `metabase.OwnerContext` (a context stack) and
  `metabase.findowner()`; the legacy stack-frame inspection is gone.

**Initialization rules:**

- `ParamsMixin` objects (indicators, analyzers, observers, feeds): call
  `super().__init__()` **before** touching `self.p`/`self.params`/lines.
- **`bt.Strategy` direct subclasses are the exception**: `Strategy.__new__()`
  creates params and broker/analyzer state; `Strategy.__init__()`
  (`strategy.py:328`) creates datas/aliases/`_clock`. Calling
  `super().__init__()` from a direct subclass re-enters `Strategy.__init__()`.
  Cooperative custom Strategy parents/mixins must still call `super()` when
  their own parent init is required.
- Never reintroduce a metaclass — use mixins + `donew()`.

### Line system (bottom-up)

`LineRoot → LineBuffer → LineSeries → LineIterator`

- `lineroot.py` — base interfaces, period management, stage1/stage2.
- `linebuffer.py` (~3,600 lines) — circular-buffer storage; also defines
  `LineActions`/`LinesOperation` produced by expressions like
  `(data.high + data.low) / 2.0`.
- `lineseries.py` (~2,560 lines) — `Lines`/`LineSeries`, `LineSeriesStub`,
  `LineSeriesMaker`.
- `lineiterator.py` (~3,000 lines) — `LineIterator`, `IndicatorBase`,
  `DataAccessor`, iteration phases, and `_clock` resolution helpers
  (`_line_like_source_clock`, `_resolve_authoritative_buflen`,
  `_ensure_lineactions_inputs_computed`).

Access: `data.close[0]` (current bar), `data.close[-1]` (previous).

### Components (all extend LineIterator)

- `indicator.py` (`_ltype=IndType=0`) + `indicators/` (59 files).
- `observer.py` + `observers/`; `observers/trade_logger.py` (`TradeLogger`)
  emits JSON order/trade/signal/position logs used by branch-compare tooling.
- `analyzer.py` + `analyzers/` (18 files) — Sharpe, drawdown, returns, SQN, …
- `sizer.py` + `sizers/`, `signal.py` + `signals/`, `comminfo.py` +
  `commissions/`.

### Data, broker, engine

- `feed.py` + `feeds/` (31 files) — CSV, pandas, IB, CCXT, CTP, …
- `resamplerfilter.py` — resample/replay.
- `broker.py` + `brokers/` — order matching and portfolio state.
- `cerebro.py` (~990 lines, public facade) + `_cerebro/` (9 private mixin
  modules, iteration-28 split): `registry`, `notifications`, `lifecycle`,
  `channel`, `execution`, `presentation`, and the four engine loops in
  `runnext`/`runonce`. `run()` → `runstrategies()` → `_runonce()` (vectorized)
  or `_runnext()` (event-driven); tick-level mode is also supported.
- `strategy.py` (~4,700 lines) — `Strategy.__new__`/`__init__`, order and
  broker/analyzer state, notification hooks.

### Indicator registration & multi-data clocks (high-bug-risk)

- Indicators register with their owner via `LineIterator.addindicator()`
  (`lineiterator.py:1684`), appending to `owner._lineiterators[ind._ltype]`.
  Unregistered indicators never update.
- **Multi-timeframe gotcha**: an indicator built on a secondary feed — e.g.
  `SMA((h1.high + h1.low)/2.0)` or `EMA(EMA(h4.close))` in an M15 strategy —
  must advance on the *secondary* feed's clock. In runonce mode
  `Strategy._periodset()` resolves each indicator's data dependency and pins
  `indicator._resolved_secondary_clock`; the post-phase advance loop in
  `_oncepost()` and `Indicator.advance()` honor it. Full diagnosis:
  `docs/DEV_REGRESSION_FAILURES.md`. Run `make test-strategies` after touching
  clock/minperiod logic.

### Execution phases

`prenext` (before minperiod) → `nextstart` (minperiod first met) → `next`.
Vectorized mode uses `once()` (`preonce`/`oncestart`/`once`) to fill whole
arrays, then replays per bar.

### Research, live factors, and runtime

- `backtrader/research/` — `FactorIndicator`, `FactorSpec`, `ResearchSpec`,
  `FactorStrategy`, `FactorPanel`/`FactorSink`, `align_to_grid`, and the thin
  `evaluate_frames` fincore adapter. Native `alpha101/` (101 formula classes)
  supports two modes per class: native `next` and classmethod `build`;
  `FactorSpec(mode=...)` selects. No string DSL and no second scheduler.
  Evaluation delegates to `fincore`; do not duplicate its IC/label/report
  algorithms here.
- `research/live.py`, `live_cohort.py`, `live_capacity.py` — live factor plans
  and snapshot/cohort publication inside an ordinary `bt.Strategy`.
- `backtrader/live_trading/`, `backtrader/runtime/`, `backtrader/stores/` —
  live execution surfaces, service execution sessions, durable execution
  journals, and factor execution. Config-first launcher lives in the separate
  top-level `backtrader_runtime/` package (`bt-runtime` console entry point).

### Special modes

- TS (time series) and CS (cross-section) modes for multi-asset portfolios.
- Plotting: `cerebro.plot()` defaults to **bokeh**; also supports
  `backend='matplotlib'|'plotly'`. Missing bokeh → matplotlib + `RuntimeWarning`;
  passing `use=` also forces matplotlib. See `docs/PLOTTING_BACKENDS.md`.
- Reports: `reports/` (`reporter.py`, `performance.py`, `charts.py`).

## Repository layout

```
backtrader/            core library
  cerebro.py + _cerebro/  strategy.py  indicator.py  analyzer.py  observer.py
  broker.py  feed.py  metabase.py  parameters.py  order.py  errors.py
  lineroot.py  linebuffer.py  lineseries.py  lineiterator.py  dataseries.py
  indicators/ analyzers/ observers/ feeds/ brokers/ filters/ sizers/ signals/
  commissions/ stores/ channels/ mixins/ plot/ bokeh/ reports/ configs/ utils/
  research/            native factors, panel/sinks, fincore adapter, live cohorts
  notifications/       dingtalk/wecom/feishu/telegram/email/slack/... delivery
  runtime/ live_trading/ btrun/
backtrader_runtime/    config-first CLI, preset policy, runtime registry
                       (`bt-runtime` entry point)
tests/                 unit/ functional/ integration/ performance/ original_tests/
  add_tests/ strategies/ bench/ datas/ fixtures/ factories/ test_utils/
  functional/strategies/   ~1,150 self-contained regression files
docs/                  Sphinx (EN+ZH) + design/bug notes + _internal iteration
                       requirement/evidence records
scripts/               optimize_code.sh, refresh_strategy_durations.py,
                       run_strategy_branch_compare.py, …
studies/               research/diagnostic scripts (branch_compare/)
examples/              backtest/, unified/ (backtest+live), live/, _support/
```

AI products (`backtrader-skills`, `backtrader-mcp`, `backtrader-agent`) and the
`fincore` analytics library are maintained in separate repositories.

## Tests

- `tests/functional/strategies/` — ~1,150 inlined test files (~1,170 test
  functions) across ~30 categories (trend_following, mean_reversion,
  asset_allocation, machine_learning, options, pairs_trading, …). Each is
  self-contained: inline strategy + data loader + `cerebro.run()` + assertions
  against master-baselined metrics.
- `tests/unit/`, `tests/integration/`, `tests/performance/`,
  `tests/original_tests/`, `tests/add_tests/` cover the framework itself.
- New regression tests should pass on **both** `dev` and `master` (bake
  master's output as expected values).
- Several `tests/unit/brokers/*_performance` tests are timing-sensitive and
  flaky under `-n 8`; they pass in isolation.
- `tests/datas/` holds fixtures (MT5 daily CSVs in `tests/datas/mt5_1d_data/`).
- `pytest.ini` markers include `slow`, `performance`, `integration`,
  `websocket`, `trading`, `live`, and priority tags.

## Common tasks

### Add an indicator

1. New file in `backtrader/indicators/`; subclass `bt.Indicator`.
2. `lines = ('out',)`, `params = (('period', 30),)`.
3. Calculate in `__init__` (`self.lines.out = ...`) and/or implement
   `next()` / `once(start, end)`.
4. Register in `indicators/__init__.py`.
5. If it consumes a secondary feed or a `LinesOperation`, test runonce vs
   runnext parity.

### Add a strategy

1. Subclass `bt.Strategy`; declare `params`.
2. Build indicators in `__init__`; trading logic in `next()`.
3. Do **not** call `super().__init__()` in a direct subclass (see above).
4. Use `self.buy()/sell()/close()`.

### Debug line/indicator issues

- Inspect `len(obj)`, `obj._minperiod`, `obj._owner`, `obj._ltype == 0`.
- Confirm `obj in owner._lineiterators[0]`.
- For multi-data drift, inspect `obj._clock` and
  `obj._resolved_secondary_clock`, and compare runonce vs runnext output using
  `studies/branch_compare/` + `scripts/run_strategy_branch_compare.py` with
  `TradeLogger`.

## Logging & notifications

- Logging: single entry point `backtrader/utils/log_message.py`
  (`get_logger`, `configure_logging`, throttled storm suppression). Silent
  until configured. See `docs/LOGGING_GUIDELINES.md`. No new `except: pass`
  without a log line; keep INFO out of per-bar hot paths.
- Notifications: `backtrader/notifications/` (`configure_notifications`,
  `send_message`, `Strategy.send_message`, `flush_notifications`). Opt-in and
  silent; async with one bounded queue/thread per channel; failures classified,
  never raised into strategy code. See `docs/NOTIFICATIONS_GUIDELINES.md`.
- Inside the notification network layer use `backtrader.utils.py3.urlopen` and
  `smtplib`; do not add `requests`/async HTTP/WebSocket clients.

## Code style & constraints

- Line length 100 (black, ruff, isort all use 100 in `pyproject.toml`).
- Type hints encouraged; `mypy` gate covers `backtrader/` only.
- Bilingual (EN/ZH) comments are normal.
- **Never introduce new metaclasses** — use mixins with `donew()`.
- Preserve public API compatibility.
- Minimize `isinstance()`/`hasattr()`/`len()` in hot paths.
- Config: `pyproject.toml` (black/ruff/isort/mypy/bandit/coverage),
  `pytest.ini` (discovery/markers/warnings), `conftest.py` (cleanup, installed
  switch, dynamic slow marking). There is **no** `.kiro/` steering directory;
  use this file, `AGENTS.md`, `README.md`, and the config files.
