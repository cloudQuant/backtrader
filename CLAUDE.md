# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repository.
It is kept deliberately factual — every claim below was verified against the
source tree. When you change something structural, update this file.

## Project Overview

Backtrader is a Python algorithmic-trading backtesting framework supporting
low-, mid-, and high-frequency strategy development, backtesting, and live
trading. This repo is a performance-oriented fork of the original
[backtrader](https://www.backtrader.com/) that **removes metaclass-based
metaprogramming** in favor of explicit mixin + factory initialization while
keeping the public API compatible.

- **Version**: `1.1.0` (see `backtrader/version.py`)
- **License**: GPLv3
- **Python**: 3.8–3.13 (classifiers in `setup.py`; 3.11 recommended)
- **Not on PyPI** — install from source only.

### Branch context

- `dev` — active development; the canonical branch. All work lands here first.
- `master` — stable, aligned with upstream behavior. Used as the correctness
  baseline (regression tests bake master's metrics as expected values).
- Other branches (`crypto`, `ctp`, `dev_cython`, `development`, etc.) are
  feature/experiment branches; do not target them unless asked.

> **Do not push directly to `master`.** Push to `dev`. `git push` is configured
> to push to both GitHub (`cloudQuant/backtrader`) and Gitee
> (`yunjinqi/backtrader`) remotes.

## Implementation status / reality checks

These correct common stale assumptions — verify before relying on docs:

- **Pure Python today.** Although `cython>=0.29.0` is a declared dependency and
  older docs reference `compile_cython_numba_files.py`, there are currently
  **no tracked `.pyx` files and no `ext_modules` in `setup.py`**. `pip install`
  builds a pure-Python package. The only native-ish acceleration in the tree is
  `numba` used inside `backtrader/utils/dateintern.py`. Do not assume a Cython
  build step is required or present.
- **Metaclasses are gone.** Object construction goes through
  `metabase.ObjectFactory` / `BaseMixin.donew` and `ParamsMixin.__init_subclass__`
  (a `patched_init` wrapper), not a metaclass `__call__`.
- File sizes below are real line counts, not the inflated numbers in earlier
  revisions of this doc.

## Development commands

### Install

```bash
pip install -r requirements.txt   # core + dev deps
pip install -U .                  # build & install
pip install -e .                  # editable/dev install
```

No separate Cython compile step is needed for a normal install.

### Testing (tiered — see `Makefile` and `conftest.py`)

The strategy regression suite is large (~10 min full). Tests are split into
tiers by **measured per-file duration**, applied dynamically at collection time
(no test files are edited):

```bash
make test-fast        # ~3.5 min: all non-strategy tests + fastest ~35% of
                      #   strategy tests. Daily "did I break anything" loop.
                      #   == pytest tests -m "not slow" -n 8 -q
make test-slow        # the slowest ~65% strategy tests test-fast skips
make test-strategies  # all 1,271 strategy regression tests (~9 min)
make test-all         # entire suite in parallel (~10 min)
make test-coverage    # coverage report

# Single test, verbose:
pytest tests/path/to/test_file.py::test_name -v --tb=short
```

How the split works:

- `conftest.py::pytest_collection_modifyitems` reads
  `tests/functional/strategies/.test_durations.json` (committed), computes the
  `BT_SLOW_PERCENTILE`th percentile (default **35**) of recorded durations, and
  tags any strategy file at/above it with the existing `slow` marker.
- **Unknown/new files default to the FAST tier**, so newly added or regenerated
  tests always run on `test-fast` — exactly what you want for catching new bugs.
- Tune coverage vs speed: `BT_SLOW_PERCENTILE=25 make test-fast` (faster) …
  `=50` (broader).
- Refresh timings after adding/removing strategy tests:
  `python scripts/refresh_strategy_durations.py`.

### Choosing which `backtrader` to test against

Running pytest from the repo root resolves `import backtrader` to the **local
repo copy** by default. To test the installed site-packages copy instead:

```bash
BACKTRADER_USE_INSTALLED=1 pytest ...        # env var
pytest ... --use-installed-backtrader        # CLI flag
```

The active `backtrader.__file__` is printed in the pytest session header. The
switch works under `pytest-xdist` parallel mode. Logic lives in `conftest.py`.

### Code quality

```bash
make format         # black, line-length 100
make format-check
make lint           # ruff
make type-check     # mypy
make security       # bandit
make quality-check  # all of the above (no tests)
bash scripts/optimize_code.sh   # pyupgrade + isort + black + ruff + tests
```

### Docs & utilities

```bash
make docs / docs-en / docs-zh   # Sphinx docs (English + Chinese)
make help                       # list all make targets
make clean                      # clean build artifacts
```

## Architecture

### Construction pipeline (replaces the old metaclass)

Object creation flows through `backtrader/metabase.py`:

- `ObjectFactory.create(cls, *args, **kwargs)` runs the lifecycle hooks:
  `doprenew → donew → dopreinit → doinit → dopostinit`.
- `BaseMixin` provides default `donew/dopreinit/doinit/dopostinit`.
- `ParamsMixin.__init_subclass__` installs a `patched_init` wrapper on each
  subclass's `__init__` that wires up `self.p`/`self.params`, sets `data0/data1`
  aliases, and runs the lifecycle. **Most indicators are constructed through
  this `patched_init` path, not `ObjectFactory.create` directly.**
- Owner discovery uses `metabase.OwnerContext` (a context stack) and
  `metabase.findowner()` — the legacy stack-frame inspection is gone.

> Key rule: call `super().__init__()` **before** accessing `self.p`/`self.params`
> or lines. Never reintroduce a metaclass — use mixins + `donew()`.

### Line system (bottom-up)

`LineRoot → LineBuffer → LineSeries → LineIterator`

- `lineroot.py` — base interfaces, period management, stage1/stage2.
- `linebuffer.py` (~2,800 lines) — circular-buffer line storage; also defines
  `LineActions` / `LinesOperation` (the objects produced by expressions like
  `(data.high + data.low) / 2.0`).
- `lineseries.py` (~2,450 lines) — `Lines`/`LineSeries`, `LineSeriesStub`,
  `LineSeriesMaker`.
- `lineiterator.py` (~2,920 lines) — `LineIterator`, `IndicatorBase`,
  `DataAccessor`; iteration phases and the `_clock` resolution helpers
  (`_line_like_source_clock`, `_resolve_authoritative_buflen`,
  `_ensure_lineactions_inputs_computed`).

Access patterns: `data.close[0]` (current bar), `data.close[-1]` (previous).

### Components (all extend LineIterator)

- `indicator.py` (`Indicator`, `_ltype=IndType=0`) + `indicators/` (50 files).
- `observer.py` + `observers/` — chart observers; notably
  `observers/trade_logger.py` (`TradeLogger`) for JSON order/trade/signal/
  position logs (used by the branch-compare tooling).
- `analyzer.py` + `analyzers/` (17 files) — Sharpe, drawdown, returns, SQN, …
- `sizer.py` + `sizers/`, `signal.py` + `signals/`, `comminfo.py` +
  `commissions/`.

### Data, broker, engine

- `feed.py` + `feeds/` (17 files) — CSV, pandas, IB, CCXT, etc.;
  `resamplerfilter.py` for resample/replay.
- `broker.py` + `brokers/` — order matching and portfolio state.
- `cerebro.py` (~2,440 lines) — orchestrator. `run()` → `runstrategies()` →
  `_runonce()` (vectorized) or `_runnext()` (event-driven). Tick-level mode is
  also supported.

### Indicator registration & multi-data clocks (high-bug-risk area)

- An indicator registers with its owner via `LineIterator.addindicator()`
  (`lineiterator.py:1584`), appending to `owner._lineiterators[ind._ltype]`.
  If an indicator isn't registered it won't update during the run.
- **Multi-timeframe gotcha:** an indicator built on a secondary feed — e.g.
  `SMA((h1.high + h1.low)/2.0)` or `EMA(EMA(h4.close))` inside an M15 strategy —
  must advance on the *secondary* feed's clock, not the strategy's primary feed.
  In runonce mode this is handled in `Strategy._periodset()`, which resolves each
  indicator's data dependency to its concrete feed and pins
  `indicator._resolved_secondary_clock`; the post-phase advance loop in
  `_oncepost()` and `Indicator.advance()` honor that clock. See
  `docs/DEV_REGRESSION_FAILURES.md` for the full diagnosis of the bug class this
  fixes. When touching clock/minperiod logic, run `make test-strategies` — these
  multi-data cases are exactly what regress.

### Execution phases

`prenext` (before minperiod) → `nextstart` (minperiod first met) → `next`
(normal). Vectorized mode uses `once()` (`preonce`/`oncestart`/`once`) to fill
whole line arrays in batch, then replays per bar.

### Data flow

```text
Data Feed(s) → Cerebro → Strategy → Indicators / Observers / Analyzers
                   ↓
                Broker ← Orders
```

## Special modes

- **TS (time series)** and **CS (cross-section)** modes for multi-asset
  portfolio backtests (`utils/` helpers; some docs reference dedicated value
  calculators — confirm presence before relying on them).
- Multiple plotting backends: Plotly (`plot/`), Bokeh (`bokeh/`), Matplotlib.
- Report generation: `reports/` (`reporter.py`, `performance.py`, `charts.py`).

## Repository layout

```
backtrader/            core library
  cerebro.py strategy.py indicator.py analyzer.py observer.py broker.py feed.py
  metabase.py parameters.py
  lineroot.py linebuffer.py lineseries.py lineiterator.py dataseries.py
  indicators/ analyzers/ observers/ feeds/ brokers/ filters/ sizers/ signals/
  commissions/ stores/ channels/ mixins/ plot/ bokeh/ reports/ configs/ utils/
tests/                 unit/ functional/ integration/ performance/ original_tests/
  add_tests/ strategies/ bench/ datas/ fixtures/ factories/ test_utils/
  functional/strategies/   1,271 inlined regression tests in ~30 categories
docs/                  Sphinx docs (EN + ZH) + design/bug notes
scripts/               optimize_code.sh, refresh_strategy_durations.py,
                       run_strategy_branch_compare.py, …
studies/               research/diagnostic scripts (e.g. branch_compare/)
Makefile pyproject.toml setup.py pytest.ini requirements.txt conftest.py
```

## Tests

- `tests/functional/strategies/` holds 1,271 inlined regression tests across ~30
  categories (trend_following, mean_reversion, asset_allocation,
  machine_learning, options, pairs_trading, …). Each is self-contained: inline
  strategy + data loader + `cerebro.run()` + assertions against master-baselined
  metrics.
- `tests/unit/`, `tests/integration/`, `tests/performance/`,
  `tests/original_tests/`, `tests/add_tests/` cover the framework itself.
- Config: `pytest.ini` (markers incl. `slow`, warning filters), `conftest.py`
  (temp cleanup, installed-vs-local switch, slow auto-marking).
- `tests/datas/` holds fixtures; MT5 daily CSVs in `tests/datas/mt5_1d_data/`.
- New regression tests should pass on **both** `dev` and `master` (bake master's
  output as the expected values). Some `tests/unit/brokers/*_performance` tests
  are flaky under heavy `-n 8` parallelism (timing-sensitive; pass in isolation).

## Common tasks

### Add an indicator

1. New file in `backtrader/indicators/`; subclass `bt.Indicator`.
2. `lines = ('out',)`, `params = (('period', 30),)`.
3. Build the calculation in `__init__` (assign `self.lines.out = ...`) and/or
   implement `next()` / `once(start, end)` for explicit modes.
4. Register in `indicators/__init__.py`.
5. If it consumes a secondary feed or a `LinesOperation`, test runonce vs
   runnext parity (multi-data clock alignment).

### Add a strategy

1. Subclass `bt.Strategy`; declare `params`.
2. Build indicators in `__init__`; trading logic in `next()`.
3. Use `self.buy()/sell()/close()`.

### Debug line/indicator issues

- `len(obj)`, `obj._minperiod`, `obj._owner`, `obj._ltype == 0` (IndType).
- Confirm `obj in owner._lineiterators[0]`.
- For multi-data drift, inspect `obj._clock` and `obj._resolved_secondary_clock`
  and compare runonce vs runnext output (the branch-compare harness in
  `studies/branch_compare/` + `scripts/run_strategy_branch_compare.py` with
  `TradeLogger` is the established way to localize divergences).

## Code style & constraints

- Line length 100 (black); ruff/isort at 121. Type hints encouraged.
- Bilingual (EN/ZH) comments are normal in this codebase.
- **Never introduce new metaclasses** — use mixins with the `donew()` pattern.
- Preserve public API compatibility.
- Minimize `isinstance()`/`hasattr()`/`len()` in hot paths.
- Performance work already done: metaclass removal, broker
  `__getattribute__`/param-cache optimization, indicator `once()` tuning.

### Config files

- `pyproject.toml` — black, ruff, isort, mypy, bandit, coverage.
- `pytest.ini` — discovery, markers, warning filters.
- `.kiro/steering/{product,tech,structure}.md` — project conventions
  (authoritative for build/test/structure norms).
