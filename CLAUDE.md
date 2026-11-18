# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Before every change, read the [repository responsibilities guide](docs/source/developer-guide/repository-responsibilities_zh.md) and follow its ownership and placement rules.

## Project Overview

Backtrader is a Python algorithmic-trading framework for low/mid/high-frequency
backtesting and live trading. This repo is a performance-oriented fork of the
original [backtrader](https://www.backtrader.com/) that **removes metaclass-based
metaprogramming** in favor of explicit mixin + factory initialization while
keeping the public API compatible.

- **Version**: `1.4.0` (`backtrader/version.py`)
- **License**: GPLv3 (`LICENSE`; `setup.py`'s classifier also declares GPLv3).
- **Python**: 3.8–3.13 (3.11 recommended); research features require 3.11+pandas.
- **PyPI**: distribution `back-trader-python` (import name stays `backtrader`).
  A separate pybind11/C++ wheel ships as `back-trader-cpp`; this repo is the
  pure-Python implementation.

> `AGENTS.md` is the short, Chinese-language current-iteration and
> cross-repository ownership guide. It tracks the current iteration,
> acceptance status, and operational restrictions. This file is the
> architecture and commands reference. When they disagree, verify against the
> source tree and prefer `AGENTS.md` for iteration-specific status; neither
> file's status claims are proof that a capability is accepted.

> Recent work (iterations 64–68, opts line; local `dev`, unpushed). Iteration
> 64 (Risk): v1 decisions stay source-quarantined (A-1), counters-less v2
> policies activate (B-1), the full R-04/R-11 v2 rule is wired (B-2), and the
> SDK holds one exact Risk core with instance ports (C-1); the authenticated
> source contract (A-2) is frozen but not implemented. Iteration 65
> (Execution): parent/child journal, UNKNOWN latch, scheduler recovery,
> opt-in netting, Gateway parent-fault recovery and day-switch proof.
> Iteration 66 (Runtime): run-file/heartbeat plumbing, opt-in stop file, and a
> loopback HTTP/JSON control transport (D66-03 option a). Iteration 67
> (calendar): file-backed trading calendar, day-switch Feed re-read,
> instrument-status chain, package seed. Iteration 68 (Monitor): frozen event
> contracts, base alert catalog, heartbeat responder.
>
> Status and evidence live in `docs/_internal/opts/requirements/迭代<NN>-…/`
> (`迭代计划.md`, `开发验收状态矩阵.md`, handoff notes); the 2026-11-16
> cross-iteration handoff is
> `迭代65-bt_api_execution独立执行服务/迭代64-68开发交接说明-2026-11-16.md`.
> Nothing there is ACCEPTED; real accounts, SimNow, real Gateway/Risk,
> SMTP/Webhook and Windows/Ubuntu are NOT_RUN. Iteration 60 (unified
> containers, direct/Gateway access) remains the base contract. Iteration 53
> was abandoned by the user on 2026-11-02; its "stop for review" restriction
> no longer applies.

### Branch model

Authoritative source: `docs/source/developer-guide/branch-governance.md`.

- `dev` — daily development entry. Features, ordinary fixes, docs, tests.
- `development` — improved/optimized release branch; controlled promotions.
- `master` — original upstream baseline; only baseline-reproducible
  bug/compatibility/security hotfixes. Regression tests bake master's metrics
  as expected values.

**Push to `dev`.** Do not push directly to `master` or `development`. `git push`
targets both GitHub (`cloudQuant/backtrader`) and Gitee (`yunjinqi/backtrader`).
Commit messages follow Conventional Commits (`feat:`, `fix:`, `perf:`, `docs:`,
`test:`, `refactor:`).

### Private inputs

Ignored `.env` files, real `config.yaml` files, secrets, and private captures
are **not** review material. Use only public source, templates, tests, and
sanitized snapshots. An authorized account read must use the protected bounded
reader and emit only categories/booleans — never values or raw lines. Never
fall back to `cat`/`Get-Content`/`rg` on a private input.

### Status and evidence discipline

- Iteration status/evidence lives in `docs/_internal/opts/requirements/迭代<NN>-…/`
  (`迭代计划.md`, `开发验收状态矩阵.md`, handoff notes). Source code proves
  intent, not acceptance; neither these docs nor a green local run makes a step
  ACCEPTED — only the user's acceptance does. Keep `NO-GO` / `IN_PROGRESS` /
  `NOT_RUN` visible rather than quietly dropping them.
- Evidence levels: `UNIT/FAKE` (synthetic ports), `INTEGRATION_SIM` (real
  components, simulated provider), `REAL` or `NOT_RUN`. Never promote a
  fake/sim result into a real-account, SimNow, provider or release claim.
- "Suite green" means the failure set was compared test-by-test against a clean
  baseline. Several suites carry long-standing failures (Risk state-machine and
  counter fixtures; Gateway `test_iter65_parent_*` errors that appear only in a
  full-suite run). Record them as pre-existing with the ids, not as green.
- Guard and contract changes need a mutation check: remove the guard, see the
  intended test fail, restore the file and verify its hash.
- `UNKNOWN` stays `UNKNOWN`: never clear pending rows, reset ledgers, release
  reservations, swap identities or auto-resend; journal backups are not a
  rollback path.

## Development commands

### Install

```bash
pip install -r requirements.txt   # core + dev deps
pip install -U .                  # build & install
pip install -e .                  # editable install
pip install -e '.[dev]'           # editable + test/lint extras
pip install -e '.[live]'          # BtApi SDK live integration (Python 3.11+)
pip install -e '.[execution]'     # optional durable-execution journal deps
```

No Cython step is required: there are no tracked `.pyx` files and no
`ext_modules`. This checkout is pure Python; `numba` is only an optional,
currently commented-out import in `backtrader/utils/dateintern.py`.

### Makefile caveat

`Makefile`'s `BT_CONDA_PYTHON` defaults to a hardcoded macOS Conda path
(`/Users/yunjinqi/opt/anaconda3/...`). On Windows/Linux, override it:

```bash
make test-fast BT_CONDA_PYTHON=python
```

### Testing

```bash
make test-fast        # parallel non-slow/non-performance suite + serial
                      #   performance lane. Daily "did I break anything" loop.
make test-slow        # only the slow-tier strategy tests
make test-strategies  # all tests/functional/strategies (~4–9 min)
make test-all         # parallel suite (no performance marker) + perf lane
make test-performance # wall-clock microbenchmarks, no xdist, no coverage

# Single test:
pytest tests/path/to/test_file.py::test_name -v --tb=short
pytest tests/unit/brokers/test_broker.py -v
```

> `make test`, `make test-original`, `make test-coverage`, and `make benchmark`
> still reference the removed `tests/original_tests/` tree and currently fail.
> Use `make test-fast` / `make test-all`, or the CI coverage command:
> `pytest tests --ignore=tests/functional/strategies --cov=backtrader --cov-report=term-missing --cov-fail-under=55`.

Equivalent underlying commands (from `Makefile`):

```bash
pytest tests -m "not slow and not performance" -n 8 -q   # test-fast part 1
pytest tests -m slow -n 8 -q                            # test-slow
pytest tests/functional/strategies -n 8 -q              # test-strategies
pytest tests -m "not performance" -n 8 -q               # test-all part 1
```

**xdist caveat (this machine).** Full-suite `pytest -n` runs have twice hung
at ~0% CPU with no progress (the functional fast loop, then `tests/unit`); the
same tree completes serially. For verification prefer serial pytest
(`PYTHONDONTWRITEBYTECODE=1 python -m pytest … -q -p no:cacheprovider`) or
split by directory, and treat a 0%-CPU stall as an environment hang, not a
product failure. `tests/unit -n 4` took ~10–15 min serial for ~6,470 tests.

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

**CI gates** (`.github/workflows/test.yml`): PRs run
`pytest tests/ -m "not slow and not performance" -n auto --timeout=300 -q`;
pushes run `pytest tests/ -m "not performance" ...`. The coverage job runs
`pytest tests --ignore=tests/functional/strategies --cov=backtrader
--cov-report=term-missing --cov-fail-under=55`; the performance gate is
`make test-performance BT_CONDA_PYTHON=python`; strategies run through
`make test-strategies BT_CONDA_PYTHON=python`.

**Project subagents** (`.claude/agents/`): `bt-code-scanner` (read-only
inventories), `bt-lint-fixer` (only findings introduced by a change),
`bt-test-runner` (baseline comparison), `bt-docs-sync` (iteration-doc sync,
never marks ACCEPTED), `bt-opus-engineer` (design/high-risk cross-repo work).

### Code quality

```bash
make format         # black --line-length 100
make format-check
make lint           # pylint with .pylintrc  (NOT ruff)
make type-check     # mypy (pyproject.toml, core backtrader/ only)
make security       # bandit + safety
make quality-check  # all of the above
make pre-commit     # format + quality-check; its test step currently fails
                    #   (Makefile still points at removed tests/original_tests/)
bash scripts/optimize_code.sh   # pyupgrade + isort + black + ruff + tests
```

ruff is configured in `pyproject.toml` but has **no Makefile target**; it runs
through `scripts/optimize_code.sh`. `mypy` relaxes dynamic-pattern error codes
per module group — the line system, metabase/core model, `cerebro`/`strategy`/
`brokers`/`feeds`/`stores`, indicator/analyzer/observer/filter packages,
plot/bokeh, and `btrun` (see `[[tool.mypy.overrides]]` in `pyproject.toml`).

### Docs

```bash
make docs                       # offline Sphinx build, English + Chinese
make docs-en / docs-zh          # one language each
make docs-offline / docs-offline-zh   # explicit no-network variants
make docs-view / docs-view-zh   # open the built HTML
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
  (`strategy.py:346`) creates datas/aliases/`_clock`. Calling
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
- `analyzer.py` + `analyzers/` (19 files) — Sharpe, drawdown, returns, SQN, …
- `sizer.py` + `sizers/`, `signal.py` + `signals/`, `comminfo.py` +
  `commissions/`.

### Data, broker, engine

- `feed.py` + `feeds/` (24 modules) — CSV, pandas, bt_api, CryptoHFTData,
  vchart, Yahoo, …
- `resamplerfilter.py` — resample/replay.
- `broker.py` + `brokers/` — order matching and portfolio state.
- `cerebro.py` (~990 lines, public facade) + `_cerebro/` (8 private mixin
  modules, iteration-28 split): `registry`, `notifications`, `lifecycle`,
  `channel`, `execution`, `presentation`, and the engine loops in
  `runnext`/`runonce`. `run()` → `runstrategies()` → `_runonce()` (vectorized)
  or `_runnext()` (event-driven); tick-level mode is also supported.
- `strategy.py` (~5,370 lines) — `Strategy.__new__`/`__init__`, order and
  broker/analyzer state, notification hooks.
- `strategies/` — built-in strategy classes (`FactorStrategy`, `CTPFuture`),
  distinct from user strategies defined in tests/examples.

### Indicator registration & multi-data clocks (high-bug-risk)

- Indicators register with their owner via `LineIterator.addindicator()`
  (`lineiterator.py`, search `def addindicator`), appending to
  `owner._lineiterators[ind._ltype]`.
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
  `FactorPanel`/`FactorSink`, `align_to_grid`, and the thin `evaluate_frames`
  fincore adapter. `FactorStrategy` itself lives in
  `backtrader/strategies/factor_strategy.py`. Native `alpha101/` (101 classes)
  supports two modes per class: native `next` and classmethod `build`;
  `FactorSpec(mode=...)` selects. No string DSL and no second scheduler.
  Evaluation delegates to `fincore`; do not duplicate its IC/label/report
  algorithms here.
- `research/live.py`, `live_cohort.py`, `live_capacity.py` — live factor plans
  and snapshot/cohort publication inside an ordinary `bt.Strategy`.
- `backtrader/live_trading/`, `backtrader/execution/`, `backtrader/service/`,
  `backtrader/factor_execution/`, `backtrader/futures/`, and
  `backtrader/stores/` — live execution surfaces, service execution sessions,
  durable execution journals, and factor execution. There is no
  `backtrader/runtime/` package in this checkout.

### Live execution and the SDK boundary (current iteration focus)

`execution/`, `service/`, `stores/btapistore.py`, `feeds/btapifeed.py`, and
`brokers/btapibroker.py` are framework adapters, not provider clients. Provider
facts, route selection, reconciliation contracts, and neutral DTOs belong to
the separate `bt_api_*` SDK packages. Backtrader retains order/position/trade
projection, Store/Feed/Broker lifecycle, and framework error mapping. Read
`docs/source/developer-guide/repository-responsibilities_zh.md` before changing
any `bt_api*` integration; `docs/TRADING_SYSTEM_ARCHITECTURE.md` covers the
cross-repository topology. Existence of source code is not evidence that a
route, account capability, or acceptance test is approved.

### Cross-repo workspace (`bt_api_py` SDK family)

Work that spans BT and the SDKs is routine on this line, so know the layout
before editing:

- The SDK parent checkout is a **sibling** of this repo (`../bt_api_py`), with
  provider/service submodules under `../bt_api_py/bt_api/` (`bt_api_base`,
  `bt_api_ctp`, `bt_api_risk`, `bt_api_execution`, `bt_api_runtime`,
  `bt_api_monitor`, `bt_api_gateway`, `bt_api_transport_zmq`, …). Each has its
  own `dev` branch, tests, and its own `AGENTS.md`.
- Commit order for a cross-repo change: **subrepo → SDK parent gitlink → Backtrader**.
  Never leave a parent pointing at an unpushed subrepo state that reviewers
  cannot reproduce.
- Run SDK tests from the submodule root, e.g.
  `cd ../bt_api_py/bt_api/bt_api_execution && python -m pytest tests -q`.
  Cross-submodule tests need the sibling `tests`/`src` dirs on `PYTHONPATH`;
  the SDK root `conftest.py` registers three cross-module fixture providers.
- The interpreter used here is `/Users/yunjinqi/opt/anaconda3/bin/python` (3.11).
  Subagents must not commit or push; the main session reviews the diff and
  commits.

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
  strategies/          built-in FactorStrategy / CTPFuture classes
  research/            native factors, panel/sinks, fincore adapter, live cohorts
  notifications/       dingtalk/wecom/feishu/telegram/email/slack/... delivery
  execution/ service/ factor_execution/ futures/
                       execution adapters, service bridges, factor execution,
                       futures calendar/rollover projections
  live_state/          durable local state for BT direct mode (iteration 62)
  live_trading/ btrun/  live-trading interface and legacy CLI
tests/                 unit/ functional/ integration/ performance/ bench/
  datas/ fixtures/ factories/ test_utils/ + root-level test_*.py
  functional/strategies/   ~1,175 self-contained regression files
docs/                  Sphinx (EN+ZH) + design/bug notes + _internal iteration
                       requirement/evidence records
scripts/               optimize_code.sh, refresh_strategy_durations.py,
                       run_strategy_branch_compare.py, …
studies/               research/diagnostic scripts (branch_compare/)
examples/              backtest/, live/ (007_ctp), service_execution_session/;
                       one self-contained folder per strategy (README + config
                       + strategy + run.py)
```

A config-first `bt-runtime` launcher was previously shipped from a top-level
`backtrader_runtime/` package; that directory is not present in this checkout,
so do not assume its imports or console entry point exist. Non-product
top-level directories include `archived/` (frozen iteration snapshots),
`promotion/`, `tools/`, `_bmad/`/`_bmad-output/`, and `test_support/`.
`pytest.ini`'s `norecursedirs` lists `archive` (singular) while the directory
is `archived/`; `testpaths = tests` is what actually keeps these out of the
default run.

AI products (`backtrader-skills`, `backtrader-mcp`, `backtrader-agent`), the
`backtrader_web` platform, and the `fincore` analytics library are maintained
in separate repositories.

## Tests

- `tests/functional/strategies/` — ~1,175 inlined test files / ~1,270
  collected tests across ~28 category directories (trend_following,
  mean_reversion, asset_allocation, machine_learning, options, pairs_trading,
  …). Each is
  self-contained: inline strategy + data loader + `cerebro.run()` + assertions
  against master-baselined metrics.
- `tests/unit/`, `tests/integration/`, `tests/performance/`, and the
  root-level `tests/test_*.py` files cover the framework itself. The former
  `tests/original_tests/` and `tests/add_tests/` trees have been removed.
- New regression tests should pass on **both** `dev` and `master` (bake
  master's output as expected values).
- Several `tests/unit/brokers/*_performance` tests are timing-sensitive and
  flaky under `-n 8`; they pass in isolation.
- `tests/datas/` holds fixtures (MT5 daily CSVs in `tests/datas/mt5_1d_data/`).
- `pytest.ini` markers include `slow`, `performance`, `integration`,
  `websocket`, `trading`, `live`, `simnow_serial`, and priority tags.

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
- Bilingual (EN/ZH) comments are normal. New or updated Chinese Markdown
  defaults to UTF-8 with BOM; preserve frozen evidence and existing format
  exceptions.
- **Never introduce new metaclasses** — use mixins with `donew()`.
- Preserve public API compatibility.
- Minimize `isinstance()`/`hasattr()`/`len()` in hot paths.
- Config: `pyproject.toml` (black/ruff/isort/mypy/bandit/coverage),
  `pytest.ini` (discovery/markers/warnings), `conftest.py` (cleanup, installed
  switch, dynamic slow marking). `.kiro/` contains installed BMAD/WDS/GDS
  skills, not steering rules, and there is no steering directory; use this
  file, `AGENTS.md`, `README.md`, and the config files.
