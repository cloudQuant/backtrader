# AGENTS.md

## 用户长期开发原则（2026-10-08）

- Backtrader、实际使用的 `D:\bt_api_py` 及其相关子包，直接在各自现有的 `dev` 工作区修改；用户未要求时，不另建开发 worktree。
- 每轮按“修复或优化 → 完成本轮约定的验收 → 提交到对应 `dev` → 下一轮”推进，不等整个大项目全部完成才提交。
- 验收失败则继续修复本轮；必须区分源码、模拟测试与真实账户验收，不能用模拟测试替代真实账户通过结果。
- 仅提交本轮已验收的明确文件或改动块，保留其他已有修改。SDK 子包先提交，再更新并提交父仓库的 gitlink。
- 对历史工作区中的相关修改逐项登记、核对和归并，避免已完成代码遗留在其他工作区造成重复开发。
- 每轮记录范围、验收结果、仓库/分支及提交哈希，后续从已提交状态继续。

## Subagent model preference

When spawning a collaboration subagent, explicitly use `model="gpt-6-luna"`
and `reasoning_effort="max"`, with `fork_turns="none"` or a supported positive
integer and the context needed for the delegated task. Preserve the main
agent's model unless the user explicitly requests a change.

This file guides Codex (Codex.ai/code) when working in this repository.
It is kept deliberately factual — every claim below was verified against the
source tree. When you change something structural, update this file.

## Project Overview

Backtrader is a Python algorithmic-trading backtesting framework supporting
low-, mid-, and high-frequency strategy development, backtesting, and live
trading. This repo is a performance-oriented fork of the original
[backtrader](https://www.backtrader.com/) that **removes metaclass-based
metaprogramming** in favor of explicit mixin + factory initialization while
keeping the public API compatible.

- **Version**: `1.4.0` (see `backtrader/version.py`)
- **License**: GPLv3
- **Python**: 3.8–3.13 (classifiers in `setup.py`; 3.11 recommended)
- **Not on PyPI** — install from source only.

### Branch context

This repository uses a **three-branch model** (authoritative source:
`docs/source/developer-guide/branch-governance.md`):

- `dev` — daily development entry. Routine features, ordinary bug fixes, docs,
  tests, refactors, and community contributions land here first.
- `development` — improved & optimized version. Optimization capabilities,
  architecture improvements, and optimization-only regression fixes.
- `master` — original Backtrader baseline. Only bug/compatibility/security
  fixes that reproduce on the original baseline, via `hotfix/master-*` PRs.
  Used as the correctness baseline (regression tests bake master's metrics as
  expected values).

Other branches (`crypto`, `ctp`, `dev_cython`, etc.) are feature/experiment
branches; do not target them unless asked.

> **Do not push directly to `master` or `development`.** Push to `dev`. `git
> push` is configured to push to both GitHub (`cloudQuant/backtrader`) and Gitee
> (`yunjinqi/backtrader`) remotes.

## Private-input handling for source and evidence reviews

Ignored `.env` files, real ignored `config.yaml` files, secrets, and private
captures are not source-review material. Reviewers and subagents use only
public source, templates, tests, and sanitized public snapshots. An authorized
root-owned account read must use the protected bounded reader and emit only
categories or booleans; never emit values, raw lines, or credential-bearing
hashes. If a required public sample is unavailable, record that limitation and
stop the check. Do not fall back to `Get-Content`, `cat`, `rg`, or another
unbounded read of a private input.

## Implementation status / reality checks

These correct common stale assumptions — verify before relying on docs:

- Optional managed execution can use the explicit one-shot
  `backtrader.stores.service_execution_session.ServiceExecutionSession.run(cerebro)`
  entry. It owns a new SDK client runtime; Broker polling maintains leases and
  refreshes durable order projections on that same thread, and the entry closes
  runtime after Broker shutdown handling. Unconfigured brokers keep the existing
  path. Channel/optimization modes and the read-only `ServiceReadProxy` are not
  supported by this execution entry. See
  `docs/source/developer-guide/optional-service-execution-session.md`; local
  synthetic-provider lifecycle tests are not full BT01/BT02 or account acceptance.
  `run_configured_cerebro` is the narrow SDK-config composition entry: one
  strategy client with required `broker.orders` and `broker.order_query` routes
  and a trusted runtime factory. `None` keeps the ordinary `cerebro.run()` path;
  invalid configured input never falls back. Its synthetic runnable example is
  documented at `examples/service_execution_session/README.md` and is not full
  stage P7 or account acceptance. A caller may additionally pass explicit
  `ServiceStrategyAccountBookRoute` objects and bind each real Strategy through
  the managed session/Broker; this provides owner-book position reads only.
  Shared Broker cash/value/position getters keep their account-level meaning,
  and the strategy view reports cash/value unavailable until Execution supplies
  an authoritative accounting and valuation contract.
  The opt-in `ServiceExecutionRecoveryJournal` candidate persists immutable
  logical-run intent/cancel manifests, restore-only snapshots, event receipts
  and cursors, and callback work before invoking caller code. It does not
  reconstruct arbitrary Backtrader Order/Strategy objects; callback delivery is
  at-least-once, not exactly-once. Local tests do not establish BT02 or account
  acceptance; the SDK-backed process-restart integration remains required.

- Optional service reads can be explicitly injected through
  `backtrader.stores.service_read_proxy.ServiceReadProxy` and
  `BtApiStore(api=proxy)`. This bridge uses SDK account/market facades and neutral
  `bt_api_base` contracts; explicit `ServiceCtpTickBinding` routes bind the
  account-session generation and authenticated CTP source/clock domain/quote
  generation, then preserve the contiguous market-event cursor, subscription
  epoch, and strictly increasing provider ingest sequence without creating
  bars. Source identity alone does not qualify clock mapping or freshness. It
  does not embed the four service components in a strategy.
  Broker requires `market_data_only=True`, and Store write entrypoints
  reject this proxy. Successful close is terminal; create fresh facades for a
  new run. See `docs/source/developer-guide/optional-service-read-proxy.md` for
  usage, scope, and the Round07 B acceptance record. This is not execution,
  provider-account, reconnect, or full BT01/BT02 acceptance.

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

The local Iteration 41 risk candidate at `2201316f` keeps root/core analytical
exports lazy, so durable admission no longer imports NumPy/scikit-learn and
related analytical modules. Its source suite passed 206 tests and independent
fresh-process import/reserve checks passed 3. Packaging metadata still lists
the prior required dependencies; this is not optional-dependency packaging.
Separate clean-clone builds of base `3de0fa4`, risk `2201316f`, and monitor
`f3583e7` produced byte-identical wheel pairs. A real isolated consumer venv
passed the risk/monitor suites (206/90), RECORD/payload/origin checks and
`pip check`; initial global-interpreter hybrid runs were excluded. This base
is version 0.15.4. The risk artifact at that checkpoint has a metadata/module
version mismatch (0.1.0/1.0.0). The later clean commit `d4bc0304` aligns the
public module version to metadata 0.1.0. Its two independent builds produce
the same wheel SHA-256 `d7e7bb28cfd049be3aa0b50f1e9deb7a83e97f24da3bc9bce51dc6f599a5202f`;
an actual isolated consumer venv passes all 206 risk tests, installed
RECORD/origin/pip checks and module/metadata version equality. Base and
monitor wheels were reused, without rerunning their suites. These are local
artifacts, not a release or a unified CTP pin.
The parent SDK MD identity consumer at
`62e683bc` independently passed 82 contract tests and 21 extra fake cases;
the SDK producer, unified wheel and native account lifecycle remain separate
acceptance work.

The Framework source-outbox projection now derives incremental price and fee
from adjacent immutable Decimal snapshots with exact Fraction arithmetic,
then converts each increment once for the existing Broker float interface.
It verifies the actual execution bits and cumulative state before advancing
the cursor; unsupported quantity resolution and economic corrections fail
closed. The frozen three-file focus independently passed 64 tests, including
large cumulative-value cancellation and restart recovery. The final source
also imports and runs its Fraction/ULP helpers on actual CPython 3.8.20 without
loading an execution SDK. This is an AC41-27 slice; the combined multi-data,
partial-fill runonce/runnext fixture and account integration remain separate.

Iteration 41's standalone `scripts/run_iteration41_monitor_benchmark.py`
measures a separate synthetic monitor process at 20 events/s using the real
SQLite outbox and checkpoint API. Its consumer polls every 100ms with a
32-event batch limit and retains per-event WAL/FULL acknowledgements; resource
sampling remains 50ms. Its default 30-minute profile and `--smoke`
both require an explicit new evidence directory and Python 3.11. Smoke is
only harness verification; the current short run exceeds the 5% single-core
CPU target, and the full serial/platform performance matrix is not accepted.
The harness now reports raw process-CPU boundaries and planned-window offsets;
the observed short-run Windows CPU granularity does not excuse a failed check
or establish the 30-minute average.
A later five-minute diagnostic consumed all 6,000 measured events and used
4.03% of one core, but four producer arrivals exceeded the unchanged 50ms
lateness limit. It remains `SMOKE_ONLY / NOT_ACCEPTED_FULL_MATRIX` (exit 2);
the five-round Windows/Linux 30-minute matrix has not run.
`scripts/run_iteration41_direct_benchmark.py` separately measures real
Store submit/cancel methods with a synthetic replay config and fake API.
Its smoke and four focused contracts passed independent review; the full
five-paired-round p50/p99 regression gate is <=5% per operation. Performance
failures return exit 3, harness failures exit 2; smoke does not evaluate the
performance gate. The formal Windows/Linux matrix remains unrun.
`scripts/run_iteration41_actor_capacity_benchmark.py` is a separate,
standard-library-only BM58 diagnostic with two spawned clients and its own
shared SQLite admission/claim tables. The default profile is a 10-intent/s,
2-second smoke; `--profile capacity-30m` explicitly selects 50 intents/s for
30 minutes. It reports duplicate attempts, losses, peak backlog, drain time,
and backpressure. It does not call a registered runtime or actor-server API,
and every result is `FAKE_LOCAL_DIAGNOSTIC / NOT_ACCEPTED`; smoke does not
establish AC41-58 acceptance.

Iteration 41 source-integration tests use
`tests/test_utils/iteration41_source_roots.py`. An explicit
`BT_API_TEST_SOURCE_ROOTS` JSON map supplies validated absolute package roots;
subprocesses do not inherit an ambient `PYTHONPATH`. Optional guard and
source-only metadata roots are separate. Source metadata enables API tests,
but is not installed-wheel, RECORD, release or deployment evidence. The
dedicated source-QA environment uses MCP-compatible Pydantic 2.13.5; it is
separate from the accepted risk-wheel consumer environment with 2.5.0.

```bash
make test-fast        # parallel non-performance tests + serial wall-clock
                      #   microbenchmarks; excludes slowest ~65% of strategy tests.
                      #   Daily "did I break anything" loop.
make test-slow        # the slowest ~65% strategy tests test-fast skips
make test-strategies  # all 1,286 strategy regression tests (~9 min)
make test-all         # parallel functional suite + serial wall-clock microbenchmarks
make test-performance # wall-clock microbenchmarks without xdist
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

Wall-clock microbenchmarks and time-bounded latency contracts have a separate
serial lane: those tests are explicitly skipped under xdist or coverage tracing
and `make test-performance` runs them without either. Its short RSS stress
profile uses a separate fresh pytest process so suite-import RSS cannot be
mistaken for the profile's process-tree budget. `make test-fast` and
`make test-all` include that serial lane after their parallel functional tests,
preserving each performance contract without treating worker scheduling noise
as an application regression.

### Choosing which `backtrader` to test against

Running pytest from the repo root resolves `import backtrader` to the **local
repo copy** by default. To test the installed site-packages copy instead:

```bash
BACKTRADER_USE_INSTALLED=1 pytest ...        # env var
pytest ... --use-installed-backtrader        # CLI flag
```

The active `backtrader.__file__` is printed in the pytest session header. The
switch works under `pytest-xdist` parallel mode. Logic lives in `conftest.py`.

The Iteration 41 CPython 3.8 core harness also executes fresh-process import
boundary tests. Store binding dataclasses use slots only on Python >=3.10,
preserving default package import on 3.8/3.9 without loading the optional SDK.
The latest local Windows 3.8 harness passed 111 tests and skipped 8; the
managed SDK still requires its newer interpreter and hosted CI remains separate.

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

The `mypy backtrader` gate checks the core package. Its `pyproject.toml`
override keeps type information from the separate `backtrader_runtime` package
but silences that package's diagnostics; runtime is not yet covered by a
dedicated mypy gate.
The release wheel consumer verifies every packaged Python source file in both
`backtrader/` and `backtrader_runtime/` against the source and isolated install.

### Docs & utilities

```bash
make docs / docs-en / docs-zh   # Sphinx docs (English + Chinese)
make help                       # list all make targets
make clean                      # clean build artifacts
```

Git LFS tracks the three Iteration 41 copies of
`unified-offline-wheelhouse-settlement-evidence-r1.zip`. Install Git LFS before
checkout so these archives are materialized instead of left as pointer files.

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

`Strategy` has a separate explicit path: `Strategy.__new__()` creates `self.p`
and broker/analyzer state, and `Strategy.__init__()` creates datas/data aliases
and `_clock` before calling the direct subclass's user `__init__()`. Therefore a
class that directly subclasses `bt.Strategy` does **not** need to call
`super().__init__()`; doing so currently re-enters `Strategy.__init__()`.
Cooperative custom Strategy parents/mixins must still call `super()` when their
own parent initialization is required. Indicators and other `ParamsMixin`
objects follow their own patched-init lifecycle and must not be validated using
the direct-Strategy exception. Never reintroduce a metaclass — use mixins +
`donew()`.

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
- `cerebro.py` (~830 lines, public facade) + `_cerebro/` private mixin package
  (9 files, iteration 28 split) — orchestrator. The facade keeps the `Cerebro`
  class definition (params/descriptors/`__init__`/`run`/pickle protocol) and
  `OptReturn`; `registry/notifications/lifecycle/channel/execution` hold
  configuration, dispatch and orchestration; `runnext`/`runonce` hold the
  four engine loops (hot paths — verbatim-moved, see
  `docs/_internal/opts/requirements/迭代28-Cerebro模块化拆分/`).
  `run()` → `runstrategies()` → `_runonce()` (vectorized) or `_runnext()`
  (event-driven). Tick-level mode is also supported.

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

### Native factor research (Iterations 45–47)

`backtrader.research` provides `FactorIndicator`, `FactorSpec`, `ResearchSpec`,
`FactorStrategy`, plain-frame `FactorPanel`/`FactorSink` (memory/CSV),
`align_to_grid`, and the thin `evaluate_frames` adapter. Research requires
Python 3.11 and pandas. Cerebro owns the normal indicator lifecycle; the strategy
assembles and collects outputs without manually advancing factors or placing
orders. Ordinary Indicators remain usable as factor children. Research rejects
the old `execution` selector and unsupported live/replay/mixed-clock inputs.

Research exceptions and `FactorComputationContext` are defined only in
`backtrader/errors.py`; there is no `research/errors.py` module. `ResearchError`
derives from `BacktraderError`. `ResearchConfigError` retains the research
`code`/immutable `report` contract and `ValueError` compatibility, while the
framework's `ConfigError` remains a separate category. `backtrader.research`
re-exports the research exceptions and keeps `ConfigError` as an alias of
`ResearchConfigError`. New direct exception imports use `backtrader.errors`.

Importing the root package or `backtrader.research` does not require pandas or
fincore; actual panel construction and evaluation check their dependencies.
Collection and CSV exchange work without fincore. Evaluation lazily calls the
separately developed fincore public research API
(`fincore.factor_analysis.research.evaluate_factor_research`); do not duplicate
its IC, labels, signal-combination or reporting algorithms in Backtrader. The
native operators use the frozen `alpha101-v2` float64 profile. Correlation and
covariance use stable centered/scaled float arithmetic; production does not
use Fraction or Decimal. Rank ties use exact float64 equality. The full-registry
tests validate formula wiring, each asset and each intermediate node rather
than sorting outputs or allowing final rank-error budgets. `research/alpha101/alpha001.py`
through `alpha101.py` contain the 101 concrete formula classes, each directly
subclassing `FactorIndicator` with ordinary `__init__` and `next` methods.
`get_alpha(id)` and `list_alphas()` expose the immutable production registry.
Small package-local helpers only construct native child indicators and retain
their references for intermediate-value diagnostics; they do not schedule
calculations. `alpha101/_metadata.py` validates and normalizes the class
declarations; the duplicate formula/implementation identity objects are removed.
FactorSpec retains the immutable run configuration and source fingerprints.
Tests exercise the production formula classes against independent scalar/matrix
references; the duplicate diagnostic factor implementations have been removed.
The static paper catalog is a test asset at
`tests/fixtures/research/alpha101_dependencies.json` and is not installed as
runtime data. Iteration 47 adds a single package-local `_expression.py` adapter:
an expression-mode FactorIndicator defines a classmethod `build(ctx, **params)`
that constructs the same native operator children once during bound-factor
initialization. The context keeps target-feed and instance identity, rejects
Python boolean conversion and closes construction after build returns; the
ordinary Cerebro lifecycle performs all calculation. Iteration 49 merges each
of the 101 build methods into its original Alpha class. `get_alpha(id)` returns
that one class; select the implementation through `FactorSpec(mode=...)` or
`FactorIndicator.bind(..., mode=...)`, never through `get_alpha`. A class may
implement native next, classmethod build, or both. Omitted mode selects native
when available, otherwise build; unavailable explicit modes fail. Each binding
has a read-only `factor_mode`. Its existing private bound class isolates init,
next and once phases, so build bypasses native callbacks without changing the
original class or global Indicator construction. Mode is reserved configuration,
not a formula parameter, and is included in FactorSpec metadata.
There is no string DSL or second scheduler.

Alpha003 native formula uses two physical paired-panel Indicators (rolling correlation and multiply) with one lightweight logical target view per asset. Cerebro schedules the physical Indicators through its normal lifecycle; the logical views share each panel's output lines and do not register callbacks. G10 adds ordinary once array kernels for these two panels and CrossSectionalRank. Eligibility requires exact standard aligned PandasData, native bindings and unmodified line/feed hooks; unsupported graphs retain once_via_next. Successful kernels synchronize feed cursors at the range end, and failures synchronize the failing date before strict error context is assembled. The 027 quick CLI now defaults to runonce and retains --runnext; the private collection helper keeps its runnext default. Final-source QA passed 96 regressions and the complete all-101 T320/T640/T1280 native/build × runnext/runonce matrix, including node values/reasons and output pairing. Complete fixed-500 comparisons pass, but the full-flow timing dispersion exceeds the 5% stability gate; do not infer stable full-flow speedup or 5,471-asset memory/runtime from that sample. See `docs/_internal/opts/requirements/迭代49-因子分析性能优化/开发与验收记录.md`.

The 025/026 native CloseMA, ROC, KDJ and ordinary RSV child also implement
ordinary Cerebro once ranges for synchronized standard PandasData/full arrays.
Custom callbacks, unsupported feeds and distinct clocks retain the existing
callback path; build mode still uses its ordinary child lifecycle. Strict line
reads/writes and scalar arithmetic are preserved. Factor lifecycle diagnostics
keep `call_count/call_times` as actual next calls (also `next_count/next_times`)
and record genuine batch coverage separately as `once_ranges/once_count/once_times`.
FactorStrategy validates `coverage_matches`; the old `grid_matches` still means
next calls alone match the grid. These helpers are private, not a second scheduler.
025/026 likewise merge CloseMA, ROC and KDJ build into their original classes. The context's
SMA/ROC/Highest/Lowest adapters use the existing ordinary indicators;
`ctx.apply` constructs an ordinary pointwise Indicator for shared scalar
formulas, preserving the examples' native overflow and missing-value rules.
Its callbacks do not receive a time loop or panel scheduler. Quick runners
025/026/027 select `--factor-mode native|build` with CLI > config > native
precedence; saved-panel reevaluation does not calculate factors. The 027 daily
runner binds mode and class identity into actual worker parameters and resume
identity, rejecting cross-mode reuse without changing existing run state.
Iteration 47 passed full 500-asset quick output pairing (12 runs, six exact
comparisons) and pinned-wheel acceptance at `ff486565` with fincore `fc512cdf`
(132 tests plus actual 20-asset quick pairs and CSV reevaluation). These local
checks reuse Anaconda base dependencies; they are not release or deployment
evidence. Iteration 48 adds thin research rolling, scale, neutralization,
returns and explicit scalar-comparison/subtraction constructors. Research
windows retain alpha101-v2 floor semantics; ordinary indicator windows remain
positive integers. Constant-only native subtraction nodes are retained with
`ctx.subtract`. Iteration 48 passed all 101 formulas at T320/T640/T1280 in
native/build × runnext/runonce, including complete node values/reasons and
output pairing. Its pinned-wheel candidate `583c2137` with fincore `4b8f31b1`
passed 149 tests plus actual 20-asset quick pairs and CSV reevaluation.
The separate full-101 downstream check compared 12 tables and 101 pairs of
actual HTML report models; 14 factors remain quantile-unevaluable on its fixed
fixture with matching verified causes, so that evaluation keeps PARTIAL while
the parity check passes. The fincore change only fixes empty-quantile/IC report
rendering. Exact commits, hashes and scope are in Iteration 48's acceptance
record; these are local source/installed checks, not release or deployment.
Iteration 49 single-class candidate `166a644a` passed 725 source unit tests,
34 scenario/data contracts, the all-101 T320/T640/T1280 four-lane matrix,
and the complete 12-table/101-report downstream pair. Its fresh installed
wheels with fincore `4b8f31b1` passed 159 tests (including 10 single-class
mode tests), three actual 20-asset example mode pairs and four CSV reevaluation
pairs. Receipts use schema 2 and `iteration49-single-class-modes`, checking
actual grouped factor instances and allowing native operator descendants.
See `docs/_internal/opts/requirements/迭代49-因子单类双模式重构/实施与验收.md`
for exact hashes and the preserved PARTIAL evaluation boundaries. These checks
do not repeat the earlier 500-asset performance benchmark.
Iteration 46 acceptance is tracked separately in its
development record. Usage and acceptance records are linked from
`docs/source/developer-guide/factor-research.md` and `alpha101-native.md`; 025/026 are the standalone
single/multi-factor examples and 027 is the native Alpha003 demonstration.

### Incremental factor components (Iterations 50–51, in progress)

`scripts/run_iteration50_live_factor_benchmark.py` accepts `--assets 2..256`
(default 20). The 20-target generator is unchanged; scaled profiles include
the target count in their input fingerprint and resource gates. Use explicit
`--warmup-bars 64` for Alpha003 capacity runs. The Windows RSS fallback uses
pointer-sized native handle declarations. Focused checks passed 13; short
87-target native/build smoke results only exceeded waived latency thresholds.
This does not establish 100,000-grid or real-market acceptance.


`research/live.py` exposes `LiveFactorPlan` and `LiveFactorSet` for composition
inside an ordinary `bt.Strategy`. They reuse `FactorSpec`, production native/build
classes, and the existing indicator lifecycle. A snapshot reads a completed
cohort; it neither calculates indicators nor authorizes account writes.
`research/live_cohort.py` owns bounded source envelopes, complete member batches,
receipt windows, source freshness, and per-member session identities. Cerebro's
opt-in cohort path stages every member's raw values and line writes before
atomically publishing a complete receipt batch. A failed pre-publication write
restores member line state and freezes the cohort; a notification failure after
publication preserves the complete batch. Feeds require `cohort_source_mode=True`
and polling Stores require `preserve_raw_bars=True`. Explicit missing fields
carry NaN plus typed presence/quality metadata; registered Alpha101 factors
exclude absent members and wait for complete rolling windows, while unsupported
custom-factor gap semantics freeze the cohort.
The 028 live CTP route binds each feed to its selected contract, the actual
Trader trading day and the independently captured MD connection generation.
`feeds/ctp_factor_source.py` maps untouched native ActionDay/TradingDay and
UpdateTime/UpdateMillisec through the explicit Shanghai UTC+8 source-time
contract and shared immutable product session calendars. Missing timestamps
have no receive-time fallback. Local callback ordinals are observation order,
not exchange wire sequences or authentication proof. Valid native quotes on
the selected product-day's source dates remain available outside the common
factor grid, without assigning a trading session or forming factor bars.
Ordinary feeds do not enable this adapter.
The explicit CTP factor-source opt-in also binds the original MD/Trader client
objects, generations, and Join policy for shutdown. Store cleanup requires
typed SDK stop receipts and propagates incomplete release to the 028 runner;
the opted-in wrapper cannot reconnect or reuse a past receipt for new clients.
Sixteen focused source/fake cases passed; native account cleanup remains a
separate acceptance step. Non-opt-in routes retain their existing stop path.
Store event wakers share a generation-checked engine condition. An injected
clock may implement `wait_interruptibly` to support external wake/runstop;
legacy clocks retain their own `wait` semantics and observe those signals only
after that wait returns. The local component checks and full strategy regression
passed; installed, long-stream and account profiles remain separate acceptance.

The QBuffer component at `e6a38fde5` passed full-buffer versus QBuffer comparisons
for all 101 formulas in native/build modes over 3,072 rows, including each node's
value/reason stream and at least ten actual capacity wraps. The independent T320
scalar-node preflight covers the first twenty formulas. These are distinct from
the pending full live-feed oracle, installed, long-stream, and account profiles.

`feeds/futures_main_contract.py`, the SHFE/CFFEX adapters, ranking aggregation,
and finite/rolling session planners are local components for Iteration 51.
The actual DCE/CZCE/GFEX end-of-day source coverage is still incomplete.
`brokers/factor_replay.py` provides `CausalReplayBroker`. The decision journal,
registered-sim adapter, execution coordinator, owned-position projection, and
028 strategy integration must be accepted at their actual composition boundary;
source or synthetic checks do not establish SimNow account acceptance.
The optional execution-journal net-loss guard uses schema 13 and one durable
state row per account/strategy/logical run. A caller-qualified total-net-PnL
observation latches the loss threshold across restarts; new OPEN admission and
dispatch require a fresh matching guard, while exact readback and CLOSE/CANCEL
remain available. Explicit guard context without a policy fails closed. The
source component is accepted at `d700b0a63`; provider PnL qualification and
strategy-driven exit integration remain separate work.
Account facts optionally expose qualified CNY total-net-PnL from one complete,
current, same-day account query row (CloseProfit + PositionProfit - Commission).
Parsing and exact arithmetic have fixed resource bounds and do not use the
ambient Decimal context. Missing PnL preserves legacy readiness; loss-policy
callers must explicitly require availability. The source component passed 120
synthetic tests; actual account observations and strategy loss-policy wiring
remain separate acceptance work.
RegisteredSimStore exposes a six-field read-only MD identity projection without
creating a connection or query. Qualification binds the SDK active identity,
current source client and typed generation, matching TD/MD day, and stable
pre/post observations. Zero-login readonly acceptance and unbound sources remain
explicitly unqualified. Six final real-SDK/synthetic-leaf tests passed; actual
MD identity, strategy trading authorization and account acceptance are separate.
Coordinator run-loss APIs explicitly bind the durable guard context to qualified
account PnL. New OPEN decisions, intent preparation and dispatch claims recheck
the guard; exact durable replay cannot dispatch, and the independent CANCEL/CLOSE
path remains available. Root accepted 14 earlier Coordinator cases and 10 final
focused cases (not one 24-case run). The latter fixes named PandasData position
refresh by accepting only nonblank string native aliases, retaining exchange
conflict checks. This is synthetic integration only; 028 strategy wiring, real
account PnL and process-restart acceptance remain outstanding.
The all-visible CTP snapshot collector attaches at most two typed, bounded
query-stage observations to refusal errors. The 028 runner emits only a
validated fixed schema; raw query rows, request IDs and provider messages are
excluded. First and latest completion origins use an explicit SDK whitelist;
older results default to unknown, and nonzero errors alone do not identify a
provider failure. Catalog and depth calls share one absolute monotonic deadline
through Store and SDK lock/rate waits. Native request calls are checked before
and after returning but cannot be forcibly interrupted by this deadline.
Synthetic installed-SDK callback composition does not establish
provider query or account acceptance.
Registered-sim DISPATCHING-CANCEL recovery requires the current cross-process
recovery lease, a complete fresh source-bound query, atomic journal terminal
reconciliation, and a durable acknowledgement of Store read-only local absence
before publishing refreshed facts. It preserves the original CANCEL RPC result
as unobserved, never replays that RPC, and preserves the original OPEN owner
through partial-close recovery; local synthetic-provider acceptance is separate
from account acceptance.
The authoritative scope, remaining AC items, and per-round commits are under
`docs/_internal/opts/requirements/迭代50-因子实盘运行与交易接入/` and
`docs/_internal/opts/requirements/迭代51-因子流批一体与Alpha003-SimNow实盘示例/`.

## Repository layout

```
backtrader/            core library
  cerebro.py (facade) + _cerebro/ (private engine mixins) strategy.py
  indicator.py analyzer.py observer.py broker.py feed.py
  metabase.py parameters.py
  lineroot.py linebuffer.py lineseries.py lineiterator.py dataseries.py
  indicators/ analyzers/ observers/ feeds/ brokers/ filters/ sizers/ signals/
  commissions/ stores/ channels/ mixins/ plot/ bokeh/ reports/ configs/ utils/
  research/           native factors, ordinary feed inputs/operators, panel/sinks, fincore adapter
  notifications/  alert delivery: dingtalk/wecom/feishu/telegram/email/slack/
                  discord/ntfy/gotify/bark/webhook/wechat_clawbot/qq_bot
backtrader_runtime/    Iteration 41 config-first CLI, sealed preset policy and
                       reviewed runtime registry (`bt-runtime` entry point)
  _local_fake_account_actor_candidate/ isolated local fake-only protocol
                       snapshot; unregistered and absent from the default runtime
AI strategy products are maintained outside this repository:
  cloudQuant/backtrader-skills   standalone author/review/test skills product
  cloudQuant/backtrader-mcp      standalone local-stdio MCP product
  cloudQuant/backtrader-agent    standalone stateful agent product
tests/                 unit/ functional/ integration/ performance/ original_tests/
  add_tests/ strategies/ bench/ datas/ fixtures/ factories/ test_utils/
  functional/strategies/   1,286 inlined regression tests in ~30 categories
docs/                  Sphinx docs (EN + ZH) + design/bug notes
scripts/               optimize_code.sh, refresh_strategy_durations.py,
                       run_strategy_branch_compare.py, …
studies/               research/diagnostic scripts (e.g. branch_compare/)
examples/backtest/           backtest-only four-file demos (001-017 ids)
examples/unified/            backtest+live entries; run.py resolves its tier from config.entry.tier
examples/live/000_live_certification/  three-venue penetration suites + optional16 (unchanged topology)
examples/_support/           repo-level tooling, admission material and canonical example helpers
  ctp_legacy_example_support.py  fail-closed compatibility surface copied by 013_1/013_2
  entry_tier.py             canonical Iteration 43 config/CLI tier resolver
examples/_support/strategy_candidate_approval.py  candidate-specific receipt/provenance policy
examples/strategy-candidate-manifest.json  hash-bound research/demo admission manifest (root, pending move)
examples/data/               shared read-only CSV fixtures
Makefile pyproject.toml setup.py pytest.ini requirements.txt conftest.py
```

### Iteration 41 runtime configuration

#### Acceptance snapshot (2026-09-27; historical)

Store sdk_api=None r1 was integrated at the historical Store source SHA-256 A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D. The mechanical fail-close source is SHA-256 549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F. The guarded Store/mechanical focus passed 38/38; the Store/Runtime run at that checkpoint passed 2,725, skipped 43, xfailed 2, failed 0. See the [Store r1 main integration archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-store-sdk-api-none-r1-main-integration-2026-09-27/README.md) and the [mechanical fallback fail-close archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-mechanical-sdk-api-none-fail-close-main-integration-2026-09-27/README.md). These are local regression results only.

The separate guarded fake/offline integration QA passed 97 tests and skipped 10. Optional source-gated tests did not execute; CTP account/native-adjacent tests and deployment interop were statically excluded. The [QA archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-fake-offline-main-integration-qa-2026-09-27/README.md) does not establish live or real-provider acceptance. Store getter proxy r0 is NO_MERGE because same-process reflection recovers the raw API. G4 exact CTP pinned-wheel rebuild remains unproven: the rebuilt CTP native payload differs, no fresh install/native acceptance was performed, and G4 remains closed; see the [independent rebuild QA](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/g4-base-ctp-pinned-wheel-rebuild-independent-qa-2026-09-27/README.md).

That 2026-09-27 snapshot's R2 inventory statement is historical. The 2026-09-28 CE04 Store route-identity integration first refreshed the inventory to `0874A81A…`; the later official 2026-09-28 inventory is `A959A3BC…`, as recorded in the current checkpoint below.

V21 native-floor r0 remains SAFE_LOCAL_FAKE / NO_MERGE (271 passed, 2 skipped); it supplies no trusted native-floor authority. A later current-source G5/V21 cross-package fake-contract QA passed 4 focused tests and 275 tests with 2 optional SDK-import tests blocked and skipped. It exercised the current G5 verifier (source SHA-256 7CAED2A83447173FF93755C5561713C2E2F8F410D21AE78E4A07CCCD3F681C66) with the V21 Store claim gate: the claim transaction checks the durable ActionRef allocation mapping before READY-to-CLAIMED, and a missing mapping left the fake sender untouched. The historical dual-ledger repro used only the older SDK allocator candidate (SHA-256 8E7ABDD2819F66B6EC3D5FF1D5A049FCBB91AE8E71327665EE925098D35F647D), not the active verifier. This is LOCAL_FAKE_ONLY contract evidence, not G5/F14 acceptance, trusted floor authority, or an account-wide fence; NO_AUTHORITY / NO_WRITE / LIVE_NO_GO / NO_MERGE. See the [current cross-package QA archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-g5-v21-current-contract-independent-qa-2026-09-27/QA-INDEX.md). I22's 11-node read-port replacement is NO_MERGE_AS_REPLACEMENT / FAKE_PORT_ONLY; the frozen audit remains in D:\temp\ac41-63-store-readonly-query-port-group-r1-20260927 with report SHA-256 3A250265F57D725CB497F7402B63F872AE8BDE96BF45DBDDDB6077967624D022. The current R2 scanner inventory remains 460/460 verified (363 writer, 97 dynamic, 355 files, plus six historical tombstones); a fresh collector found identical IDs, order, and locator lines, with zero additions/removals/moves, so no new inventory version was created. All active rows remain REVIEW_REQUIRED / NOT_AVAILABLE; this is inventory integrity, not writer closure.

The separate [Store lazy-connect audit](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ensure-api-ready-lazy-connect-audit-2026-09-27/report.md), report SHA-256 F799E48F20783B964B63B164E77D19DAEE85E39349A3F82CA36F9917F1695481, is **NO_MERGE_PATCH / BLOCKED_BY_SHARED_I22_LIFECYCLE**. In fake-only probes, six routes reached fake connect/query behavior: get_balance(force=True), get_symbol_info(), direct start(), gateway start(), forwarding start(), and an example-shaped btapi/direct CTP flow. Public sdk_api was None on CTP/gateway/forwarding cases; fake order/cancel writes were zero, and import/network guards were empty. The audit statically identified 14 I22-related bounded-probe test functions in the I21 test file; they were not run. A shared CTP deny at start/_ensure_api_ready would block Store-owned typed read-only I22 lifecycle; allowing the in-process probe still permits Store-owned native startup in-process, so no patch was created. This does not treat sdk_api=None as an isolation boundary and does not establish native/provider behavior.

Default CTP writes, live dispatch, and real SimNow/production trading remain closed: NO_WRITE / LIVE_NO_GO.

The `examples/000_live_certification/{simnow_penetration,hongyuan_penetration}` suites each keep one Git-ignored `config.yaml` at the suite root and only `<ID>_strategy.py` plus `run.py` in each of their 33 case directories. Each strategy class is named `<ID>Strategy`, and its runner derives that class name from the case directory. Corresponding strategy and runner files are identical across the two suites; their local configs select the provider settings. From a suite root, `python cases/C01/run.py` is an offline Cerebro smoke; `--live` remains `BLOCKED` because no managed certification runner is registered, and the smoke does not prove provider certification. The ignored checkout-root `.env` holds Hongyuan-specific account, password, AppID, authorization code, product-info, and connection-mode variables. The case runners do not load `.env` or use the product-info and connection-mode values; a separately admitted provider runner would have to resolve the four config-referenced credential variables from its process environment.

The same `examples/000_live_certification` root also contains 13 sibling live-only venue suites for OKX, Binance, Bitget, Bybit, Coinbase, dYdX, Gate.io, HTX, Hyperliquid, IB Web, MT5, Kraken, and MEXC. Like the SimNow layout, each venue owns 33 `cases/<ID>/{<ID>_strategy.py,run.py}` entries, but these new entries never run the SimNow offline smoke. Each venue also bundles its own `_certification` schema-v2 runtime and `config.example.yaml`; there are no shared `penetration_*.py` files at the 000 root and no import of `bt_api_py` or sibling venue code, so a whole venue directory is portable. The strategy file declares the protected case/risk/evidence contract and the adjacent runner is fixed to that one case ID. Example configs contain environment-variable names and placeholders only, keep all WRITE/DANGEROUS cases and policy grants disabled, and require private real configs outside the repository. READ cases consume referenced provider evidence without creating state; write cases require exact config/CLI grants, bounded runner-authored operations, independent observations, complete snapshots, and cleanup restricted to authorized orders. No reviewed/deployed venue adapter or live result is included, so source presence and static checks establish zero venue `PASS` results. The managed bridge remains a trust boundary; incomplete product metadata, unsupported valuation, missing independent evidence, or uncertain cleanup must be `BLOCKED`. CTP's separate `NO_WRITE / LIVE_NO_GO` status is unchanged.

The Iteration 41 inventory currently has 10 registrations, including a 007 suite-root zero-write `simulation/sandbox` runtime/front-check route (the 013_3 source replay and source managed L2 entries were retired in the 2026-10-11 simplification round, the 014_1/014_2 replay routes were retired in the same day's cleanup, and the `ctp_options_simnow` source managed L2 CLI route followed in its own round that day). Its protected, Git-ignored config and directory ACL are aligned with 013_3; the schema-v4 config is rebound to `example.007_ctp.simnow_penetration` and contains five configured MD/TD pairs. Offline `doctor` exited 0 with `provider_preflight_started=false`, five pairs, and `preflight_available=false`; ordinary `preflight` remains fail-closed pending a bounded Windows Job supervisor and independent acceptance. On 2026-09-28, one explicit credential-free `check-ctp-fronts` TCP probe selected pair index 3 (MD and TD each 3/3 reachable); indexes 0/1/2/4 each had 0/3. This is a host-and-time-specific transport observation only: no SDK import, provider login, market-data subscription, order, or cancel occurred, and it does not establish future reachability. `bt-runtime run` on the suite root returns `profile_dispatch_unavailable`/exit 2 with `provider_preflight_started=false`; this route has no runner. The 007 route has no certification case runner, trading runner, or write permission. All 33 case directories are staged at `examples/007_ctp/live_certification/simnow_penetration/cases/<ID>/{config.yaml,<ID>_strategy.py,run.py}`; per-case configs contain scenario parameters only and must not duplicate account credentials. Their strategy files describe planned real actions and evidence, not executable provider strategies. Historical flat `cases/*.py` remain closed source. `managed_case_entry` returns `BLOCKED`/exit 2 for the cases; that unavailable-case-runner result is never real SimNow `PASS`. The latest six-file fake/offline runtime focus passed 176 tests, skipped 13, with one existing pytest-configuration warning; it does not establish TCP, provider, account, or trading behavior. Keep `NO_WRITE / LIVE_NO_GO`.

The suite-root 007 `config.yaml` and any `secrets.yaml` now have exact Git-ignore rules. Offline CI smoke skips both reviewed CTP private-read runtimes before config loading; the synthetic same-path CLI test clones only its matching read-only binding. These checks do not read the private config or enable a runner.

At an earlier checkpoint, `tests/unit/live_certification` passed 170 offline tests. The legacy SimNow `CaseTimer.pass_result()`, `CaseResult.to_dict()`/`exit_code()`, and `save_result()` fail closed for unverified or hand-built `PASS` results; caller details and JSONL logs cannot establish provider certification. An individual-process check of all 33 staged `run.py` entrypoints returned 33 `BLOCKED` / exit 2 results, zero unexpected results, and zero network/order-write requests. The earlier full `tests/unit/runtime` regression passed 2,118, skipped 30, and xfailed 2; offline CI smoke passed 12 of 14 eligible runtimes, while two managed L2 replay profiles reported the current environment's missing `bt_api_execution` capability. These are local checks, not real SimNow acceptance; 0/33 real cases passed.

At the later 2026-09-28 checkpoint, all 33 case-local strategy files have unregistered read-only typed observation logic; none has provider execution, dispatch, authenticated source proof, or a certification `PASS` route. `common/completion_invariants.py` now checks C01 auth/login/query order, M02/M03 session generation and query/callback order, managed request time against native callbacks and account snapshots, L01 trade-log fields against native facts, EM01/EM02/EM03 external-control references, and V01/V02/V03 actual validation conditions; V02/V03 also bound decimal shapes before exact arithmetic. `common/decision_engine.py` binds the M02/M03 control receipts and TH04 combined submit/cancel threshold to typed request/native references. Independent QA found stale, mismatched-contract, malformed-order, and cross-account synthetic evidence reaching review; the read-only order and typed six-case candidates now require recent evidence, consistent contract/account/session generation, and valid native order states. The 007 read-only `managed_case_scope.py` now derives a scheme-marked pseudonymous account fingerprint only from an already sealed runtime config in memory, includes it in case-scope v2 digest, and passes it to `DecisionScope`; it is guessable and does not authenticate provider callbacks or credentials. At that checkpoint, the full `tests/unit/live_certification` run passed 357 offline tests; `tests/unit/runtime` passed 2,131, skipped 30, and xfailed 2, with a later 48-test 007/static-inventory focus passing; `tests/unit/stores` passed 742 and skipped 13; the Broker module passed 149. A fresh 33-process entry check still returned 33 `BLOCKED` and 0 real `PASS`. The exact old G4 base/CTP pin wheels and clean source commits were located; two isolated dependency-closed environments passed `pip check` and loaded the pinned CTP native extension with its expected hash alongside a clean 0.15.5 parent candidate. Exact old CTP build reproducibility, native lifecycle, and provider behavior remain unaccepted. Strict whole-command G1 remains closed. No real CTP order/cancel has been accepted; keep `NO_WRITE / LIVE_NO_GO`.

The unregistered 007 `managed_case_scope.py` now binds exact case identity to the sealed suite runtime, with SHA-256 digests for the case config, static strategy plan, and `run.py`; it grants no provider I/O. The new `managed_case_invocation.py` adds a non-authorizing, offline per-invocation binding of that scope to a freshly revalidated sealed config, the exact configured MD/TD pair, consistent TCP evidence ranking, contract/account identity. It rejects caller-supplied lease claims until a trusted current owner verifier exists, and rechecks the three case files for drift, hides endpoints from redacted output, and passed 9 focused synthetic tests plus Ruff; TCP evidence and object identity are not provider or selector authenticity. Caller-constructed lease snapshots are rejected; this binding does not verify current lease ownership. Neither module is called by the 33 blocked entries. The unregistered managed_case_front_selection.py binds a freshly resealed 007 config and issued case scope to one credential-free TCP checker result; its issuer-local object check rejects caller-built clones and config/pair-order drift, but gives no provider or write authority. Its 22-test main focus and the 357-test live-certification suite passed. `decision_scope_from_case_scope()` binds case digests to the unregistered `common/decision_engine.py`, whose 33 typed intent specifications are review-only (`dispatch_permitted=false`, certification `PASS=false`). `common/case_engine.py` checks the 33 descriptive plans and offline event provenance, but evidence completeness stops at `REVIEW_REQUIRED`. Historical reconciliation policy now requires a real request for E03/EM01, a real trade for B01, and allows reconciled fill races for cancel cases; B01 `partial_count` no longer accepts a caller-supplied count or local partial label. The separate `ctp_simnow_managed_md_bridge.py` is a read-only, lease-scoped tick handoff contract, not a Feed or client owner. The pinned child SDK's public tick callback lacks callback-bound generation/sequence and its subscription callback drops request ID/terminal flag, so the managed owner cannot yet supply the bridge's required source watermark. None of these source-level changes supplies native callback attestation, a case runner, trusted account snapshot, or write admission. The bridge now requires an owner-issued, strictly increasing per-account lease_generation bound in both lease_snapshot and source identity, rejects boolean-only lease sources, and poisons on generation changes; this remains an unregistered offline owner contract, not independently authenticated lease continuity or provider acceptance.

The unregistered `common/completion_invariants.py` adds pure-data checks across the 33 case IDs for canonical scenario/provenance rows, managed requests, native order/trade lifecycle, and final order/position/account snapshots. Missing scenario evidence keeps all cases below review; the 33-ID negative loop is not full positive/negative coverage for every case class. Independent QA found missing trade/order external-ID and submitted-quantity conservation checks, which now have negative tests. Ordinary required-order cases now reject an unexpected terminal provider rejection; the explicitly expected remote-rejection cases retain that path. A partial-fill-then-cancel synthetic positive test confirms matched trade and position facts remain reviewable. Result flags for certification, dispatch, and source authenticity remain false even when synthetic evidence reaches `REVIEW_REQUIRED`. It does not authenticate caller-provided rows or bind them to a sealed account, and fill-related cash, fee, and margin effects still need independent provider review.

The [CTP MD subscription ACK source audit](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-md-subscription-ack-correlation-source-audit-2026-09-28.md) confirms the native request has no caller request-ID parameter, while the callback's `nRequestID` is not correlated by the current high-level wrapper; a local single-pending epoch is not provider authentication. The clean parent G4 follow-up found `bt_api_py 0.15` lacks five required managed-module paths and the request builder requires 0.15.5; its isolated compatibility report is at `D:/temp/iteration41-g4-parent-compat-gap-analysis-20260928`. No compatibility patch or wheel was made, and neither finding changes `NO_WRITE / LIVE_NO_GO`.

The 013_3 synthetic replay uses an explicit `ReplayClient` with
`LocalReplayStore`, `BtApiFeed(provider="local_replay")`, and
`LocalReplayBroker`. This path does not construct the CTP Store or Broker;
the broker rejects order entry and does not run the inherited matcher.
Replay provenance resolves optional SDK module specs without importing their
parent packages. This local replay is not a SimNow session or trading route.

`backtrader_runtime` requires `<registered-runtime-dir>/config.yaml` and only
accepts schema-v4 `backtest`, `simulation`, or `live` mode/preset pairs. The
CLI does not permit mode or preset overrides through flags, environment, CWD,
or AI-produced files. `bt-runtime bootstrap`, `doctor`, and `run` are routine
operator entry points. The ordinary CTP `preflight --strategy-dir` CLI is
currently fail-closed: synchronous native start/stop/Join/Release may wait
without a hard bound. Reconsider it only after a bounded Windows Job supervisor
is implemented and independently accepted. `doctor` stays offline/read-only;
for the 013_3 private runtime it adds a redacted `operator_actions` summary
without changing legacy `next_actions`. A live config request is shown as
unavailable and unauthorised. `run`, live dispatch, and writes remain closed.
The native lifecycle source
review is at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-native-join-source-review-2026-09-25.md`.
Adding a runnable directory requires an explicit `inventory.py` registration
and tests.
The static candidate tool `scripts/collect_iteration41_writer_inventory.py`
scans its Iteration 41 runtime scope, Python source under `examples/` except
generated output/private runtime state, and every repository-root `.py` file
without importing providers or executing examples. Its controlled path baseline is
`scripts/iteration41_writer_inventory_scope.json`; generated caches/log output
are labeled separately, and the private CTP runtime state subtree is summarized
without scanning its contents. New example directories or root Python scripts
remain `UNCLASSIFIED` until reviewed; the repository contract test fails while
such paths are unclassified. These path/candidate results are static coverage
only and do not prove writer closure or authorize a route. The JSON artifact
uses `source_root: "."` so it carries no host-specific absolute path.
The collector also records simple local aliases of writer methods and indirect
`getattr` callables as conservative candidates; it does not prove their runtime
reachability. Every discovered candidate must have a `REVIEW_REQUIRED` /
`NOT_AVAILABLE` disposition in the checked-in checklist.
The CtpClientWrapper capability/arm-path statement below describes the A039 r4 Store snapshot, not the current Store. At A039, `arm_registered_sim_execution` unconditionally raised the CTP direct registered-sim admission error, and `_send_native_order_insert` / `_send_native_order_action` raised before native dispatch (`backtrader/stores/btapistore.py:1896-1917` in that snapshot). The mutable capability field remained present, but those methods did not accept it to arm or dispatch. This was a narrow wrapper fail-close, not account-level authorization or proof that other writers were closed. See the historical [Store r1 integration evidence](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-store-sdk-api-none-r1-main-integration-2026-09-27/README.md) and [r4 queue evidence](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-ctp-generic-queue-failclose-r4-2026-09-27/README.md). The current CE04 R2 Store has a conditional route-identity guard; its [main integration archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-store-api-route-identity-r2-main-2026-09-28/README.md) documents the remaining same-process case where a custom API hides CTP `exchange_kwargs` through `__getattribute__` and a local fake direct sink is reached. This is not writer closure; `NO_WRITE / LIVE_NO_GO` remains.

Historical pre-Store-r1 Store/Runtime run passed 2,641 tests, skipped 43, and xfailed 2; it is superseded by the 2,725/43/2/0 post-r1 result recorded above. Its raw JUnit/log/exit sidecars remain in [the evidence archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ac41-63-direct-mechanical-cycle-simnow-failclose-main-integration-2026-09-27/README.md); it is regression evidence only, not CTP or write acceptance.
The Iteration 41 generic `MechanicalCycle` and direct `SimNowLiveRunner`
dispatch APIs also fail closed before broker-operation attribute lookup when
trusted dispatch evidence is unavailable. Their three-file focus passed 52
tests and skipped the optional L2 integration because `bt_api_execution` source
roots were unavailable. The registered fake L2 positive remains unverified:
candidate and exact-base copies failed the same `UNKNOWN` assertion, so the
requested 9/1/0 result is not established. This API-boundary regression does
not sandbox arbitrary same-process subclasses or broker calls and does not
enable CTP/SimNow writes; keep `NO_WRITE / LIVE_NO_GO`.
The 013_1 and 013_2 `ctp_example_support` modules no longer invoke
`load_dotenv_if_available()` at import, and their legacy live Store/Broker
helpers reject before config or constructor access. That explicit dotenv helper
remains callable, and strategy submit methods can still use a caller-supplied
custom broker; this is not full writer closure. The three-file main focus passed
33 tests; four existing `SIM112` lower-case environment-alias Ruff findings in
untouched source lines remain. Keep CTP routes `NO_WRITE / LIVE_NO_GO`.
Their byte-identical helper copies now come from
`examples/_support/ctp_legacy_example_support.py`, a small replay-config reader
plus eight retired dotenv, credential, SimNow, Store, Broker, Feed, and direct
runner names that raise the runtime's legacy-entrypoint error before side
effects. The executable `examples/unified/007_ctp/ctp_example_support.py` is a
separate helper and is not the source for those compatibility copies.
The canonical private CTP block is `ctp:` with the same MD/TD, contract,
account, and authentication fields for `simulation/sandbox` and
`live/managed_live_direct`. The explicit `mode`/`preset` in that same
`config.yaml` selects the requested path; parsing a live config does not
register or authorize a live runner. The legacy `ctp_simnow:` and
`ctp_production:` parsing remains only for compatibility tests; new operator
configuration uses canonical `ctp:` in the shared file.
The 013_3 registration declares `live/managed_live_direct` unavailable, with
a dedicated resolution reason; that declaration adds no capabilities and
rejects before credential resolution, SDK import, network access, or runner
dispatch. Its zero-write `simulation/sandbox` RuntimeProfile grants no write
capabilities. The ordinary `preflight` CLI is currently fail-closed pending a
bounded Windows Job supervisor and independent acceptance; this does not
enable `run`, live execution, or writes.
`ctp:` production read-only on the single protected runtime config has an offline candidate contract (104 passed / 1 skipped); the default live route remains closed. The same-file canonical schema is a future production-operation target only after production runner/admission is implemented and independently accepted; changing config alone cannot enable production because the default live route remains unavailable. The canonical `ctp`/`front_pairs` doctor display fix passed 37 tests, and the local protected-config doctor reported only `diagnostic simulation/sandbox` with five pair entries. Backtrader handoff (27) and the risk/monitor/execution production-scope checker (10) are offline and non-authorizing. The combined CTP managed dispatch/adapter plus MD request-ID audit focus passed 38 tests with Ruff clean; it remains opt-in/unregistered, with no provider or default-route integration. The four-file Store/Broker handoff focus passed 125 tests with one existing pytest-configuration warning and targeted Ruff clean. The `bt_api_execution` package suite passed 57 tests; `py_compile` and applicable Ruff checks passed. The v5 command outbox is an offline candidate with 57 package tests, not connected to the SDK or default runner. Caller-supplied seed proof is non-authorizing; UNKNOWN has no trusted reconciliation/resolution path and permanently fences account claims; cross-trading-day cancel is unsupported. No command channel is accepted. ADR-41-15 records `MaxOrderRef`, legacy-mapping, and command-queue blockers. The old CTP-entry audit passed 96 focused tests; its no-reachable-bypass result is limited to static analysis and tests. No real session, order, or cancel has been accepted. At that historical checkpoint, the full runtime suite passed 1,447 tests, skipped 24, with one existing pytest-configuration warning in 65.64s; the latest full runtime result is recorded below; the six-file Iteration 41 integration rerun passed 7 tests with one existing pytest-configuration warning in 36.63s. These local checks do not authorize CTP or live execution.
`RegisteredRuntime` also has an additive `RuntimeProfile` registry contract for
synthetic registrations that need separate policy fields for multiple exact
mode/preset pairs under one runtime identity. It requires inert legacy fields,
includes profile facts in the registration/effective seals, and honors existing
unavailable-profile declarations before selection. The additive `profiles`
field follows the original positional `bootstrap_parameters` field. The
profile-aware sandbox read-only admission and live `sealed_config` scope
binding have local contracts. The default 013_3 sandbox profile remains a
zero-write binding. Ordinary direct CLI native `preflight` is currently
fail-closed pending a bounded Windows Job supervisor and independent
acceptance. The profile-backed production TCP selector rejects before opening
a socket. The pure live scope binder validates the selected `effective.profile`
without authorizing a session. These contracts do not enable production
credentials, SDK access, runner dispatch, or writes.

`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/` has exact Git-ignore
rules for its local `config.yaml` and local state. The default inventory
registers a zero-write CTP SimNow `simulation/sandbox` RuntimeProfile with
`sandbox_write_policy=deny` and no trading runner or execution capabilities.
The ordinary private-read `preflight` CLI is currently fail-closed pending a
bounded Windows Job supervisor and independent acceptance. `doctor` remains
offline, and `check-ctp-fronts` performs only credential-free TCP checks of
sealed-config candidates. The private configuration requires one
explicit `md_front`/`td_front` pair or an ordered `front_pairs` list of 1–8
exact MD/TD pairs, along with its contract/account/authentication fields. A
protected, Git-ignored local private config has been prepared from the
owner-only project `.env`; it currently contains five distinct, ordered
MD/TD pairs under the canonical `ctp:` block, including the directly configured
official SimNow 7x24 pair, and offline `doctor` accepts it. The official pair
was TCP-unreachable from this host at the latest probe; this is not an address
allowlist or a time-based selection rule.
Historical I2/earlier supervised observations below do not make ordinary CLI
`preflight` available. The separate `check-ctp-fronts` command is limited to
credential-free TCP evidence. Historical I2 runs used a scoped, code-owned
base/CTP wheel pin: a real TD login and all seven native query streams reached
terminal replies in H2, I1, and an I2 retry. The I2 certificate accepted the
83-row same-exchange instrument response with one exact target and recorded
both present-but-blank rate `ExchangeID` values as `unverified`, not exact
scope. The historical registered preflight still rejected because native Join
did not complete. The separate I2 MD-only probe observed one login callback
with request ID zero and response error ID zero, rejected by the SDK as a
request-ID mismatch; login timed out, native Join remained pending, and there
was no subscription acknowledgement or tick. The mismatch is not yet
root-caused; see the native Join source review above.
`bt-runtime prepare-ctp-config` creates the canonical `ctp:` block in
the ignored private file from an explicitly named owner-only `.env`, a YAML
`ctp` or legacy `ctp_simnow` source (which may contain an explicit
`front_pairs` list), or a
collector YAML `ctp` source plus an explicit contract/exchange/HedgeFlag source.
`prepare-ctp-simnow-config` remains a legacy CLI alias. The old
`prepare-ctp-production-config` CLI command and its internal writer functions
are retired and reject before inspecting sources or destinations. The
`ctp_production` runtime schema parser remains only for migration/audit
compatibility; no second operator file can be prepared through this module.
At most two sources may be merged and overlapping fields must agree; the
collector's `env` label never selects a front. The helper never infers fronts,
overwrites an existing config, or grants a route.
The CLI and public preparation helpers accept only the code-owned 013_3
default or the exact registered 007 private runtime ID; 007 requires an
explicit `--runtime-id`. Public path and arbitrary strategy overrides are
closed. Existing protected files remain no-overwrite.
The `.env` parser accepts legacy `CTP_INSTRUMENT`/`CTP_EXCHANGE` names and
equal-value aliases for the same CTP field; conflicting aliases reject. During
explicit preparation it also turns complete `CTP_SET1_*` numbered MD/TD pairs
and the complete `CTP_SET2_*` MD/TD pair into one ordered, deduplicated
`front_pairs` list with no set labels. Incomplete pairs reject. Without those
additional fields, the legacy single-pair output is preserved. The runtime
never reads these `.env` names or chooses a front by set or time. The
prepared config's strategy identity matches the selected registered 013_3 or
007 runtime. The local project `.env` is UTF-8 and owner-only; its
original bytes are retained in an ignored, protected local state directory.
On Windows, private config creation is relative to the verified target directory
handle; every target path component rejects reparse points, and an identity
mismatch after creation deletes the new file by its retained handle. A failed
deletion is reported explicitly. On POSIX the target is opened component by
component with `O_NOFOLLOW`; its symlink-ancestor tests still need a POSIX host.
The registered read-only binding uses only addresses in the sealed config. A
single pair is used as configured; for multiple pairs, a bounded,
credential-free TCP probe selects the lowest measured MD/TD pair score and
passes that selected pair unchanged into read-only admission. It never
selects by time, calendar, CLI flag, environment variable, or static SimNow
address allowlist. TCP reachability is transport evidence only, with no
account or write authority. The sealed config supplies the instrument,
exchange, and hedge scope, checked against supported CTP field formats. The
tracked Iteration 22 strategy
`config.yaml` remains separate and cannot supply this runtime contract. The
read-only base/CTP pin does not grant any write route; managed SimNow
requires a third, separately reviewed `bt_api_py` parent pin. That pin is not
accepted: `D:/bt_api_py` source is dirty and the old
`D:/source_code/bt_api_py` wheel is incomplete and cannot be pinned; a clean
isolated candidate is in progress. No CTP orders have been accepted. The
registration grants no write route. The
internal `_ctp_credential_binding.py` derives a keyed, pathless tag from a
freshly validated private config and exact read-only admission; it grants no
approval or write authority and has no key storage. Default SDK
arm/submit/cancel remain closed; the separate opt-in neutral
`config_front_pair` managed SDK contract requires an exact per-action grant.
The module also exposes a typed reviewed
refresh adapter for
the SDK's nominal credential-binding scope. Each refresh rechecks the sealed
config, full candidate list, selected exact fronts, account, and registration
before reading current key material; its versioned HMAC result is
non-authorizing and no deployed key
source is provided. The legacy static profile binding is validation-only and
the CLI/operator dispatcher reject it. The selected-front read-only route has no
injected UTC source requirement; its bounded observation uses a monotonic
deadline. A future write admission needs its own trusted expiry/time policy.

The current default registry has 10 registrations: 7 nonmanaged
`simulation/replay` paths (five ordinary strategy examples, the no-action
legacy profile for `examples/007_ctp`, and
the separate `examples/sample.py` no-action migration profile), two zero-write
CTP SimNow `simulation/sandbox` RuntimeProfiles with read-only bindings: the
013_3 private runtime and the 007 certification-suite root runtime/front-check
route. Offline `doctor` and credential-free `check-ctp-fronts` are available
for both. Ordinary CTP `preflight` for 013_3 and 007 remains fail-closed
pending a bounded hard Windows Job supervisor and independent acceptance. The
registry also has one package-owned
`backtest/local_backtest` fixture. The 013_3 source replay and source managed
L2 entries were retired in the 2026-10-11 simplification round; the
package-owned offline L2 fixtures remain in their separate registry. The
`examples/010_live_examples` directory was retired on 2026-10-11 together with
its legacy SimNow no-action replay profile and its public-market-only
`simulation/shadow` runtime; no `simulation/shadow` registration remains and
the `okx-public-shadow` packaging extra was removed with it. The same day's
second round retired the last source managed L2 CLI route
(`examples/ctp_options_simnow_managed_replay_runtime.py` and its runtime
directory), so no `offline_managed_execution` registration remains in the
default registry; the mechanical P1-B fake-provider rail survives only as a
`backtrader_runtime._iteration41_l2_fixture` package registration reachable
through `iteration41_l2_fixture_registry()`, never through the operator CLI. The
fixture executes four packaged CSV bars
through Cerebro with zero network, external writes, orders, fills, or provider
submissions; it is an acceptance fixture, not a general deployment route.
There is no registered live runner. Do not make a replay configuration or a
template into a live route by adding a fallback or override; live registration
requires its own reviewed implementation and acceptance evidence.

For managed execution, `backtrader_runtime.managed_execution` derives a stable
versioned runtime order ID from the SDK `ExecutionScope.key` and an explicit
`managed_intent_id`; it rejects caller-supplied order/client IDs. The CTP Store
checks the SDK scope before durable OrderRef reservation. The same intent name
in a different scope is a different identity. These are local contracts, not
real-account recovery or write admission.
The managed CTP queue-receipt classifier distinguishes a local queue rejection
from an unknown queued outcome; neither is a provider acknowledgement.
`backtrader_runtime/ctp_managed_reconciliation.py` is an unregistered pure
SimNow snapshot classifier requiring injected native-query evidence. It does
not prove a common cross-query snapshot or account-wide writer exclusion.
The Store now has typed managed CTP order/cancel request contracts that carry
the intent, runtime order and cancel identities into BtApi bindings. The
code-owned runtime still binds CTP Stores to a typed fail-closed placeholder:
current CTP admission is private-read only, and the asynchronous SDK queue
receipt cannot satisfy the managed facade's synchronous provider-observation
contract. No CTP managed write route is enabled.
`ctp_simnow_managed_operator.py` is an unregistered offline selector for a
future SimNow writer. Its code-owned policy fixes the runtime identity,
approval key, and hard risk envelope; the account, ordered 1–8 MD/TD pairs,
instrument, exchange, and HedgeFlag come from a freshly resealed canonical
`ctp:` block. The selected whole pair, candidate-set digest, config digest,
and effective digest are bound to the per-run execution registration and thus
to each short-lived action approval. Changing those config values does not
require a code policy edit, but invalidates an old approval. TCP reachability
alone does not prove native MD/TD login readiness.
`ctp_trader_client_port.py` and `ctp_simnow_managed_composition.py` now provide
an opt-in, unregistered SimNow managed adapter using neutral `simnow` /
`config_front_pair` labels. It revalidates a sealed `simulation/sandbox`
config, requires an explicitly registered MD/TD pair present in its sealed
candidate list, and binds that pair into registration, signed approval,
session identity, and per-action SDK scope. The composition verifies the exact
selected pair against the code-owned SDK artifact pins before extracting
credential fields, importing the SDK, or constructing the unconnected client.
It requires base, CTP, and parent pins; the parent is absent, so the default
managed composition rejects. Its native
write path requires a disarmed gate, current per-action approval, credential
binding, and fresh exact SDK scope verifier. Raw SDK submit codes and exact
immutable request/account/session/target evidence become typed local dispatch
receipts: zero is only `QUEUED`, a negative code is `REJECTED` only with
verified no-callback evidence, and mismatched or uncertain outcomes are
`UNKNOWN` and freeze further writes. None is a provider acknowledgement. The SDK
source now has an explicit MD/profile constructor binding seam, but the
ordinary SDK remains source/editable; the isolated I2 wheel pair has a scoped
read-only code pin but no managed-write or production approval. No real-client
deployment has been accepted.
After journal reservation, failed staging freezes the affected action as
`UNKNOWN`. Local fake-client tests cover submit and cancel; the default
inventory/CLI do not expose this route, and private Python attributes do not
isolate untrusted in-process strategy code from the client.
The account-keyed SQLite managed journal has versioned scope metadata and a
bounded scope history. A newly selected pair or edited config can take over
only after every prior intent is verified terminal; unresolved or unknown
rows block before native client construction. Each historical row retains its
original scope digest. Managed admission reloads the protected config and
checks exact account, contract, and selected candidate pair before the native
factory; it never extracts password material for this comparison.
`ctp_simnow_managed_runtime.py` is a further unregistered composition root:
it selects one configured pair, invokes the artifact-first port helper, and
opens the journaled execution session under the account lease. All approval,
query-evidence, external writer-fence, started native-client, and typed TD/MD
readiness adapters are injected. `ctp_simnow_native_readiness.py` supplies an
unregistered, one-shot public-SDK TD/MD login, exact subscription, and first-
tick adapter; its typed observation is explicitly read-only and does not
prove settlement or trading readiness. The composition root now transfers
the MD client to a lease-scoped resource owner: normal close and failure
rollback stop MD before TD, and failed close poisons the account lease. No
failed login or later uncertain action selects another pair. Local fake tests
cover the lifecycle. The SDK now exposes a bounded stop receipt, but an
active native Join may remain pending and native startup is still synchronous;
there is no accepted real provider session or account-wide writer fence. The default
registry still grants no managed CTP write path.
`ctp_managed_account_runtime_candidate.py` adds an unregistered shared-mode
account-runtime candidate. It holds the existing local account flow lock
before opening the same account journal path used by the legacy SimNow
execution journal, and requires a typed V20 execution Store with a persistent
account-family owner. The simulation-to-live fake integration check confirms
the second mode is blocked on that same account ledger. `_ExecutionJournal`
preflights the typed Store before switching SQLite to WAL and refuses to attach
its legacy tables to a V20 database; recognizable legacy scope failures are
rejected before write-open. The fake session test stops after authenticate/login
and issues no order or cancel request. The local flow lock is not an external
account-wide fence; there is no family-owner handoff/release proof, default
registration, or accepted provider write route.
`ctp_simulation_query_evidence.py` is a separate, unregistered TraderClient
adapter for verifying terminal native query provenance, exact filters and
current callback-history readback. It remains read-only and non-authorizing:
separate queries are not an atomic account snapshot, the SDK has no durable
post-restart cancel-action history, and an account-wide writer fence is still
external. Missing or evicted evidence fails closed.
Direct managed startup fences interrupted cancellation dispatches while holding
the execution writer lease before accepting managed mutations. If another
active runtime owns that lease, startup defers recovery but keeps submit,
cancel, and reconciliation blocked until a retry succeeds.
In local CTP simulation recovery, an explicitly missing cold-restart cancel
callback can resolve to `TARGET_TERMINAL` only when the exact native target
order is terminal and trade/position evidence agrees. Same-process pending
cancels and ambiguous snapshots remain blocked; this is not provider write
admission or real-account recovery evidence.

`backtrader_runtime/provider_deployment.py`, `provider_preflight.py`, and
`test_execution_profile.py` provide pure standard-library prerequisites for
future provider deployment. The version-2 receipt/profile contracts bind a
code-owned runtime, preissued approval digest, opaque OS-secret reference,
account/artifact/config/capability digests, environment, and expiry. The
preflight binding checks the sealed `config.yaml` resolution and rejects
sandbox/production environment mismatch. Default verifiers reject, and every
successful observation remains non-authoritative. `ctp_preflight.py` composes
these checks with an injected, read-only SimNow session protocol; local tests
use only a fake session. Separately, `ctp_sandbox_readonly_admission.py`
validates a sealed `simulation/sandbox` private-read route with no write
approval, `credential_resolver.py` resolves an exact authentication schema
(protected private `config.yaml`, POSIX owner-only `secrets.yaml`, or Windows
Generic Credential Manager), `ctp_sdk_readonly.py` adapts the SDK's seven
native trader read queries with write counters checked, and
`ctp_simnow_readonly_runtime.py` composes these local prerequisites and invokes
`ctp_sdk_market_readonly.py` for one configured `md_front` login and exact-
instrument subscription after the seven TD queries. `ctp_simnow_operator.py`
binds the CLI's zero-write sandbox RuntimeProfile to its private-read
`preflight` binding; ordinary CLI dispatch is fail-closed pending bounded Windows Job supervision and independent acceptance. This profile has no trading runner or execution capability.
`ctp_artifact_provenance.py` checks installed package pin/RECORD and the
selected configured front pair's syntax before credential access; its
code-owned catalog pins the independently reviewed I2 base/CTP wheels only for
registered SimNow sandbox read-only candidate. Managed SimNow additionally
checks a third `bt_api_py` parent wheel, which remains unpinned. The SDK certificate and local
composition tests are not real account evidence. The read-only composition contract imports
`MdClient` only after exact registry/config, artifact, credential, and TD
read-only gates; ordinary CLI dispatch is separately fail-closed pending bounded Windows Job supervision and independent acceptance; it uses the selected configured `md_front` without endpoint fallback
and requires a matching login/subscription response. This composition has
local fake-client tests. In the isolated H2 and I1 installations, real TD login
and all seven query streams completed. The certificate accepted the 83-row
same-exchange instrument set with one selected instrument; the margin and
commission rate exchange fields were present but blank, so their scope remains
`unverified`. Historical native Join shutdown was incomplete, so that preflight attempt
did not accept the combined TD/MD observation.
An unregistered, one-shot `ctp_simnow_md_diagnostic.py` performs only the
config-selected MD login/subscription/tick probe after the TD diagnostic
process exits. In the isolated I2 installation, the selected TCP-reachable
pair returned one MD login callback that the SDK classified as
`request_id_mismatch`: the response error code was zero, but the callback
request ID was zero rather than the pending request ID. Login timed out, with
no subscription ACK or matching tick, and native Join remained pending. The
fifth configured official 7x24 pair was
TCP-unreachable at the latest probe. This is separate diagnostic
evidence, not a successful full preflight or write admission.
An independent, unregistered I4 candidate now uses
`ctp_i4_oneshot_md_diagnostic.py` and the shared one-shot read-only MD adapter.
It has a separate base/CTP artifact pin table; the registered I2 pin and
preflight are unchanged. The isolated I4 SDK source is clean commit
`809239fdc0b7982d3512f4289e3e8dbcbd43a523`; the wheel, installed
RECORDs, module origins, native extension and 85 installed-origin fake tests
passed local offline audit. Main-repo I4 composition/fake tests pass. Two
supervised real SimNow MD-only diagnostics rejected with
`market_client_stop_failed`. The first reported only the broad
`market_login_identity_mismatch`; after value-free callback classification was
added, the second reported one login callback, zero request ID and response
error code, and `broker_id_mismatch`. The SDK observed a mismatch, but the
audit does not reveal whether the response field was blank, transformed, or
from a different account scope. Native Join remained pending in both runs;
neither had a subscription ACK, matching tick, or write. There is still no
accepted real I4 MD login, subscription, tick or shutdown observation, and
this candidate grants no Trader or write route. See
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i4-md-real-diagnostic-2026-09-25.md`.
The later independent I5 candidate uses clean isolated SDK commit
`a101590f5f29070439c13b6062b3487abee936cc`; its wheel/RECORD and import-origin
verifier passed. SDK installed/source focused tests reported 100/83 passed,
the broad offline CTP suite reported 892 passed with one network test
deselected and two parent-dependent write test files excluded. After I5
pin/verifier, the full runtime suite was 1225 passed, 24 skipped, 1 warning in
56.72s; I4/I5 focused tests were 62 passed and Ruff passed. A supervised
one-shot I5 MD diagnostic ended `incomplete / market_client_stop_failed` after
15,141 ms without timeout: the intentional request ID zero matched the
callback, response error status was zero, but the SDK BrokerID getter returned
an empty string/bytes shape and the login was rejected. This does not establish
why the native field was empty or prove an account/configuration error. There
was no login acceptance, subscription ACK, matching tick, or write; client
stop returned while native Join remained pending/uncertain. The protected audit
record passed a scan for configured account, credential, contract and front
literals. The candidate is unregistered and adds no default route or write
authority; see
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i5-md-diagnostic-2026-09-25.md`.
The subsequent independent I6 candidate uses clean isolated SDK commit
`d85cd1571000c63d38bb9417a4942ec2692c5ad6`. Its wheel/installed RECORD,
module origins and native extension passed artifact verification; 94
installed-origin focused SDK tests passed. A local diagnostic entrypoint
initially called a nonexistent verifier symbol and rejected before front
selection; that name was corrected and covered by an offline regression test.
The supervised I6 MD-only retry then reached one login callback with a matching
zero request ID and zero response error status. The SDK observed empty BrokerID
and UserID getter shapes and a valid TradingDay shape, rejected identity, and
received no subscription ACK or matching tick. Native Join remained pending;
trade and settlement write counters stayed at zero. A synthetic installed
native SWIG login-response struct roundtrip returned nonempty BrokerID/UserID
and TradingDay as set, so the actual callback's empty fields remain unexplained.
I6 is unregistered and grants no write or live route; see
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i6-md-diagnostic-2026-09-25.md`.
A separate exact-I6 no-login loopback child, assigned to a kill-on-close
Windows Job before resume, reported `join_required=true`,
`join_completed=false`, `native_released=false`, `thread_alive=true` after a
bounded stop. It submitted zero login requests and observed no front callback.
Normal child exit did not prove native shutdown. An offline fake in which Join
requires Release demonstrates a possible wait cycle, not vendor semantics;
neither probe called Release concurrently with Join. These results do not
change read-only or write admission.
The unregistered `ctp_i7_oneshot_md_diagnostic.py` is a read-only one-shot
MD diagnostic. The I7 SDK wheel/RECORD pin and installed-origin audit passed.
The first supervised run verified process containment (Job empty, no
descendant; `containment_verified=true`) but ended
`incomplete / market_client_stop_failed`, with native Join pending and no
subscription ACK, tick, or writes. The first run's native-shape fields were null because the shared main-repo
I3 failure-diagnostics helper omitted the enums. After that projection fix,
the second supervised run reported native BrokerID/UserID fields empty and
TradingDay shape valid. This rules out a simple SWIG getter loss, but the official Mini API manual does not promise these fields must be nonempty or echoed; the empty observation means strict identity validation failed and identity remains unverified, not that the account configuration is wrong. It does not
explain the empty identity source; the I3/I7 focused set passed 68 tests. The latest profile-focused set passed 230 tests with 14 skipped; after CTP OrderRef reservation/session hardening, writer-fence post-authorization recheck, the production action trust-source contract, I8 tri-state partial evidence, and same-file/legacy-path tests, the latest full runtime run after the CLI preflight gate, I12 private helper, I13 updates, and optional front-probe budget-accounting update (`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p no:asyncio tests/unit/runtime -q`) passed with 1,561 passed, 26 skipped, and one existing pytest-configuration warning in 69.12s (exit 0); the prior 1,558 passed, 26 skipped in 67.04s, 1,536 passed, 26 skipped in 53.52s, and earlier 1,447 passed, 24 skipped in 65.64s are historical checkpoints. The six-file Iteration 41 integration rerun passed 7 tests with one existing pytest-configuration warning in 36.63s; MCP --no-cov boundary tests passed 23. An optional front-probe deadline currently performs budget accounting only; it is not a hard whole-command deadline guarantee. These are offline test results only; they do not establish provider/session readiness, a default live route, or write acceptance. Later code changes require a new full-suite run. An earlier overlay-backed offline fake/replay smoke reported 14 passed, 0 failed, 14 selected, 2 skipped, but used extra local bt_api_risk/bt_api_monitor source overlays and does not prove the clean bt_api_execution wheel alone. The earlier execution-only wheel smoke, with no dirty source overlay, reported 12 passed and 2 failures because bt_api_risk was missing; socket/DNS guard attempts were zero. Clean execution/risk/monitor candidate wheels have been built. The earlier no-system 60-wheel bundle passed pip check, RECORD, and import-origin checks (57 wheel hashes unchanged; 3 replaced). That earlier 60-wheel bundle's offline fake/replay CLI smoke was 12 passed, 2 failed, 14 selected, 2 skipped (private CTP and public shadow), with zero network-guard attempts. Both managed fake replay CLIs reached the runner and failed when the older parent runtime_plugins code used generic resolve_freeze on a dispatch-inflight latch; hardened bt_api_risk correctly rejected that clear, and the safety latch could not be reasserted. The diagnostic conservatively reported provider_io_may_have_started=true and provider_preflight_started=false, but used only a fake provider with no real provider/network access; this is not execution or write acceptance. A separate system-site-packages 14/0 attempt inherited editable SDK sources/provider adapters and is diagnostic only, not clean-origin evidence. This is offline fake/replay evidence, not provider/account evidence. Separately, the main-repo managed-replay integration passed 2/2, but its subprocess harness put dirty SDK base/execution/risk/monitor src paths first on PYTHONPATH; that does not validate candidate-wheel integration. The candidate wheel itself was covered only by 32 package tests in a strict venv. The main repo's dual-field credential-scope bridge passed 40 focused tests and Ruff. The initial review BLOCKED the parent 0.15.5 candidate because its shortened acct_<16> token did not match the full 64-character scope; the frozen dual-field candidate at commit `af538469…` (wheel SHA prefix `cfa83b1a…`) passed independent RECORD and 151-source-member review; this only supports offline fake/replay bundle integration, not CTP or default-route acceptance. After the SDK test-harness-only fix, its normal plugin-enabled broad suite was 999 passed, 2 skipped, 1 warning (test-only commit 3bec55d); the wheel SHA prefix 81c9ee62… was unchanged at that historical test-only checkpoint; it predates frozen candidate `af538469…` and does not establish current CTP-triwheel acceptance. The latest isolated bt_api_risk source suite was 164 passed after test-only commit b809800; candidate dce2c84d API/wheel stayed unchanged. The I8 SDK candidate's offline fake suites reported 10, 61, and 35 passed. One supervised I8 MD-only diagnostic ran with fixed wheel prefix f354…; before run, `doctor` exited 0 while the one-shot latch was absent; the fixed supervisor atomically created it before starting the child, and it was present after the run. No real retry was performed. The parent supervisor verified child create/assign/resume/exit, Job empty, no termination request, and child exit 3. The diagnostic ended incomplete / native_shutdown_uncertain at market_data; the value-free receipt is documented at `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i8-md-diagnostic-2026-09-25.md`. Receipt false callback flags do not prove callbacks were absent because error projection may lose partial state; `identity_unverified=false` does not establish verified identity, `native_join_pending=false` does not prove orderly close, and the historical `client_stop_returned=false` came from an older projection that did not propagate the actual client stop return; current code exposes that value as true/false/null. A separate I8 SDK fake shutdown-contract focus passed 63 tests; it proves only conditional local interface behavior, not vendor semantics. The pure offline `ctp_production_action_binding.py` contract provides per-action production scope/credential binding and rejects the old SimNow binding type; 8 focused synthetic tests and Ruff passed. It is not connected to the SDK or a real verifier and adds no default route; `NO_WRITE / LIVE_NO_GO` remains. The I8 wheel prefix `f354…` and source commit `a7d9…` are located, but independent clean-clone builds with `autocrlf=true` and `autocrlf=false` both differ from the retained wheel because the source has mixed EOL bytes; a fixed EOL policy and build receipt are required before claiming byte reproducibility. The I9 offline candidate has two relevant artifact checkpoints. Clean-clone rebuilds of old commit `353e9d8…` with fixed `SOURCE_DATE_EPOCH` and `LINK=/Brepro` produced identical wheel SHA-256 `29f50faa37d145f9b82bdaf4e38b483eff898272925ac082e0d12eb8125cfaf3`, but the artifact metadata still says i8, so it is not an I9 pin/deployment (receipt: `D:\temp\i9-artifact-repro-20260925\I9-offline-wheel-repro-receipt.md`). The final offline candidate is version `2.0.3+iteration41.i9`, commit `157d0c0cffa4c8a86e196159cdf227e9014e9118`; two independent clean-clone wheels are byte-identical, SHA-256 `aa094c039788a41adf975cfeee839fa3baf1bcef3878ae53d10eefb44410a4a3`, embedded RECORD SHA-256 `d030ccf23d59a5f77230b490df52aa48c4cbecd67b2a78b7e782600126565841` (receipt: `D:\temp\i9-final-wheel-repro-20260925\I9-final-wheel-repro-receipt.md`). Each installed wheel passed 95 fake tests; the main repo adapter focus using the installed wheel passed 26; the six-file SDK source suite passed 204; Ruff/diff were clean. The previously identified submit-rejection race was fixed locally and barrier-tested. The opt-in SDK `managed_outbox_pre_dispatch` fail-closed boundary had 9 focused and 47 combined tests; there is no fresh approval verifier, claim, or native submit. This is offline evidence only: the main-repo pin/default route and default I8 pin are unchanged. I9 locally addresses owned-copy `on_login` handling, callback deferral, and the submit-rejection race; native Join/Release, real-provider/session behavior, and writes remain unaccepted; no real diagnostic or write occurred. `NO_WRITE / LIVE_NO_GO` remains. The I8 read-only wheel and CTP triwheel remain unregistered, with no default route or write acceptance. The bt_api_execution submodule has independent commit 4bf6da1…; exact wheel-byte reproducibility remains under verification. These observations are not full
preflight, account readiness, or write acceptance. I7 has no runtime
registration or CLI route.

The latest official-PyYAML frozen-parent wheel-only fake/replay rerun is documented in `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/clean-wheel-bundle-fake-replay-2026-09-25.md`: its 61-wheel manifest SHA is `4b189520d2a5b5b9b83a3d380096b75137beb1eb375937c916ab9a863f535289`, with 60 prior wheel hashes unchanged and only the local PyYAML repack replaced. The official PyYAML 6.0.1 wheel SHA `bf07ee2fef7014951eeb99f56f39c9bb4af143d8aa3c21b1677805985307da34` matched PyPI JSON; its RECORD was 24 rows / 23 hashed / 0 invalid. A fresh short-path no-system venv passed `pip check`, nine installed SDK/PyYAML RECORD checks, and SDK/YAML import-origin checks. Frozen parent commit `af538469…` / wheel SHA prefix `cfa83b1a…` passed independent RECORD and 151-source-member review. CLI result: `14 passed, 0 failed, 2 skipped` (private CTP/public shadow); both managed fake L2 routes passed, socket/DNS guard attempts were zero, and provider/account I/O was none (only PyPI metadata and wheel download used network). This is offline fake/replay integration only, not CTP, provider/account, SimNow, production-route, or write readiness. `NO_WRITE / LIVE_NO_GO` remains.
I7 containment does not prove SDK orderly-close. The official Mini API manual
and 6.7.7 MD/TD headers define Join as waiting for API-thread exit and Release
as deleting the API object; no Stop/timed Join or concurrent Release/pending
Join or SPI-detach callback-quiescence guarantee was found. Any future native
route requires a supervised worker, account writer lease, and unknown-result
recovery; forced termination records the worker as abandoned. No such worker
route is implemented or accepted. See the [official Mini API manual](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf)
and [API download page](https://www.simnow.com.cn/static/apiDownload.action).

The exact Windows 6.7.7 MD callback identity and shutdown-contract questions
remain an unsent vendor draft at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/CTP原生关闭厂商确认问题.md`.
The MD probe's same-account local lock root comes from the POSIX account
database home or Windows `LocalAppData` known folder, never `TMP`/`TEMP`; local
process tests inject a separate root. This primitive is not a cross-host or
account-wide writer fence, and its Windows DACL/path-replacement properties
still require independent deployment review.
The default inventory has the read-only SimNow binding but no verified real
provider session or external-write authority. There is still no live runner.
Synthetic live registration with `--confirm-live` is also rejected
at final dispatch until production execution admission is independently verified.

`examples/007_ctp/runtime-production/` is a legacy reserved, unregistered
CTP production config location, not the planned routine operator path. Its
parser-only schema accepts a separate
`live/managed_live_direct` plus `ctp_production` contract there and seals its
private fields, including one required `md_front`/`td_front` pair or an
ordered `front_pairs` list of 1–8 pairs. Parsing only seals the candidate
list and never selects its first item; the README records
the independent production approval
boundary. The old `bt-runtime prepare-ctp-production-config` CLI command and
the internal second-file writer both reject before source reads or target
creation. The `ctp_production` parser remains for migration/audit compatibility;
it does not select a pair or register a route. This path contains no tracked
config or account values. Its
directory-local `.gitignore` names only `/config.yaml`, `/calendar/`,
`/reports/`, `/state/`, `/secrets.yaml`, `/approval-receipt.json`, and
`/deployment-receipt.json`. This path does not appear in the default inventory
and adds no provider import, network, or write route. The intended operator
flow uses the canonical `ctp:` fields in one `config.yaml` and switches
explicit `mode`/`preset` plus account/front/contract values there; the live
runner and admission for that flow are not implemented. Production receipts,
account/artifact bindings, and credential-version keys must still be bound
to the live environment and cannot inherit SimNow authority.
Syntax-valid production fronts in `config.yaml` do not authorize a connection;
the default inventory has no production registration or populated code-owned
front/account pin. `resolve_runtime_config()` still rejects the production
contract. `backtrader_runtime/ctp_production_credentials.py` can resolve the
sealed production authentication fields only under an injected registry and
exact pin, rechecking the existing platform ACL/file-identity gate before
credential release. `backtrader_runtime/ctp_production_readonly_runtime.py`
defines a seven-query/zero-write session contract and labels results as
unverified session-protocol evidence. Its unregistered composition probes
every sealed configured MD/TD pair, including a single pair, with the bounded
credential-free TCP selector before opening a session. A selected pair must
belong to that sealed candidate set; legacy code-owned exact-front fields, if
present, are validation-only and cannot select a different address. The
unregistered `backtrader_runtime/ctp_production_sdk_readonly.py` adapter
rechecks the sealed config, selected pair, account and instrument scope, then
calls the separate
`ctp_production_artifact_provenance.py` gate before resolving credentials.
Its production wheel-pin catalog is empty, so the default implementation
rejects before credential access or SDK import. With a reviewed pin it would
lazily import the SDK and perform the seven native TD reads. It checks
account identity, the SDK's generation-fenced local TD-front connection
callback state, stable connection generation, query scope, zero write
counters, and bounded client close. Unknown native request-counter names
fail closed even if their reported count is zero. The MD front is passed
unchanged from the sealed production config to the SDK and locally bound by
login, subscription, and tick callback state. This does not verify the remote
endpoint (`remote_front_identity_verified=false`).
The returned Python session still holds a private native-client reference;
private attributes are not an isolation boundary against untrusted in-process
strategy code. A future production route must keep credentials in a trusted
process/service boundary rather than handing this object to strategy plugins.
Fake-client tests do not prove SDK artifact provenance, production Windows
DACL acceptance, or a real provider session. The default registry and CLI
still have no production read route, runner, or write route.
`backtrader_runtime/ctp_production_readonly_admission.py` provides a pure,
non-authorizing check that a sealed production config and selected candidate
match an exact code-owned account/instrument registration. Its optional legacy
front pin can only narrow a config-selected pair. It is not wired into the
default registry or CLI and cannot import the SDK or open a provider session.
`backtrader_runtime/ctp_production_execution_admission.py` separately binds a
sealed production config to a code-owned production execution registration,
receipt/artifact identities, and bounded opening-order limits. Its result is
explicitly non-authorizing; no production write route, verifier, or provider
session is registered.
For canonical `ctp:` live configs, its `sealed_config` scope mode derives the
account, contract and ordered front candidates from the same sealed file; an
optional sealed effective runtime is included in its non-authorizing scope
identity. The pure binder derives scope from the sealed inputs and a supplied
exact configured pair. Pure binding remains offline-only; profile-backed production
selection, credentials, SDK access, session construction, runner, and writes
remain closed. The profile-backed TCP selector rejects before opening a socket.
`backtrader_runtime/ctp_production_approval_binding.py` now provides a separate
pure, unregistered receipt-to-scope lookup contract: it rederives the selected
scope from sealed config/effective runtime inputs and asks an injected verifier
about an externally trusted `(receipt digest, scope identity)` pair. The default
verifier rejects; fake-map tests cover stale account/front/contract scope and
receipt rotation. The external mapping avoids a receipt/scope self-hash cycle;
it is not a trusted verifier or authority source. Local fake-map results are
non-authorizing. Trusted verifier/mapping, trusted time and revocation, fresh
on-disk config identity, provider artifact/session gates, and a live writer
remain unimplemented. The default sandbox registration does not become
production authority when `config.yaml` changes mode. Legacy
`runtime-production`/`ctp_production:` remains migration compatibility, not
the intended second operator configuration.

The three AI products are not vendored and are not Git submodules. Make product
changes, packaging releases, and product-specific acceptance changes in their
respective repositories; this repository only links to them from its README.

The cross-exchange arbitrage examples use `BtApiStore.getdata()` / `BtApiFeed`
with `orderbook_as_ticks=True` and `TimeFrame.Ticks`. Native `notify_orderbook`
callbacks drive `bt.Strategy.buy/sell` and `notify_order`; `BtApiBroker` routes
demo orders through public `BtApi` methods with `normalized=True`.
The SDK owns venue schemas, request mapping and optional execution-session state
(durable intents, unique client IDs, uncertain-order reconciliation and fees).
`bt_api_py.cross_venue` owns only provider-neutral, stateless typed execution
planning: quantity lattices, executable VWAP, cost accounting, funding schedule
validation and normalized orderbook evidence. It consumes SDK contracts and
does not own a client, account, order, pair state, alpha, or compensation policy.
The store holds `BtApi` directly and only maps framework orders, references and
native market-data objects; there is no second Backtrader trading client.
`examples/strategy_candidate_approval.py` binds the two example candidates'
manifest, offline receipt and source provenance. It is example admission policy,
not a Backtrader utility or SDK protocol.
The two folder-local 012 manifests hash the raw bytes of each folder's `run.py`,
`strategy.py` and `config.yaml`; root `.gitattributes` pins those six exact paths
to LF so strict SHA-256 values match Git blobs across Windows, Linux and macOS.
The canonical manifest remains unchanged and demo approval stays `NOT_APPROVED`.
OKX endpoint selection belongs to the SDK through
`api_region=global|eea|us|tr`: REST plus public/private/business WebSockets use
one atomic region/environment profile. Global/EEA/US support production and
demo; TR currently supports only production, so `tr+demo` fails before network
I/O. OKX 50119 proves that the selected credential/domain combination was
rejected; by itself it does not distinguish region, key, secret, passphrase,
expiry, or permission causes.
Funding is a typed SDK read model. `BtApiStore` refreshes it on a separate
single-concurrency read-only lane with request coalescing, TTL/schedule-boundary
expiry, and generation fencing; strategy callbacks only read the local cache.
This snapshot supports entry reserves and settlement-window risk. The SDK does
not yet expose a unified, pagination-complete, account-bound OKX/Binance funding
cashflow ledger, so a cycle crossing settlement cannot claim complete realized
net PnL. The production status is
`PRODUCTION_BLOCKED_ACTUAL_FUNDING_CASHFLOW_LEDGER`: venue-level single-page raw
income/bills parsers do not prove pagination coverage, identity, deduplication,
aggregation, settlement latency, or a complete empty result. Idle risk also
advances without a new bar through `notify_idle` polling.
The `exchange_kwargs` and `symbol_routes`
configuration supports multiple providers in a single broker. Amounts remain native units
(OKX contracts / Binance BTC); strategy sizing uses metadata multipliers.
The examples require independently verified dual-side/hedge mode and maintain
long/short legs separately; no net-position fallback is accepted. `shadow` uses
public production books with zero orders/fills/PnL, `paper-live` uses public books
with local hypothetical fills, and only `demo` can submit exchange orders. Demo
writes additionally require a strategy-specific, hash-bound approval receipt.
Both Iteration 21 frozen candidates failed their pre-OOS calibration cost screen,
so their `paper-live` simulated-fill and `demo` order paths remain prohibited;
read-only shadow and demo preflight remain available. Any new economic attempt
requires a new candidate ID, preregistration, and untouched holdout.
Credentials are kept in each example's ignored `.env`. Deterministic `replay`
reports are formula fixtures with zero orders/fills and no PnL; the native
Store/Feed/Cerebro/Broker path is tested separately. The second candidate is
classified as event-driven and remains `HFT FAIL/NOT_ADMITTED` until end-to-end
latency, queue and real-fill evidence exists.

The Iteration 22 SA example uses one authoritative `BtApiFeed` to dispatch CTP
quote events and form watermark-closed one-minute bars. CTP trading admission
requires typed terminal account/position/order/trade/reference queries bound to
one stable connection generation and account fingerprint. `replay` is an
offline zero-write path, `shadow` is read-only, and `simnow` additionally
requires a hash-bound approval receipt plus a complete first-set observation
gate. The example never treats replay output or a single SimNow day as evidence
that the strategy is profitable.

Its imported `run.py::main()` now accepts only explicit offline replay, and
`run_network()` rejects before reading legacy `.env` or constructing a Store.
The direct script and the options SimNow operator/launcher also route through
Iteration 41 registration or reject before provider access. The options
operator's imported front probe and Store builder, and the 015 launcher lazy
session helper, reject default/real-provider use; only explicitly marked fake
test doubles are retained for local tests.

## Tests

- `tests/functional/strategies/` holds 1,286 inlined regression tests across ~30
  categories (trend_following, mean_reversion, asset_allocation,
  machine_learning, options, pairs_trading, …). Each is self-contained: inline
  strategy + data loader + `cerebro.run()` + assertions against master-baselined
  metrics.
- `tests/unit/`, `tests/integration/`, `tests/performance/`,
  `tests/original_tests/`, `tests/add_tests/` cover the framework itself.
- Config: `pytest.ini` (markers incl. `slow`, warning filters), `conftest.py`
  (temp cleanup, installed-vs-local switch, slow auto-marking).
- `python scripts/ci/smoke_iteration41_registered_offline.py` runs the
  registered offline replay/backtest CLI entries; the retired source managed
  L2 CLI routes needed local SDK source packages on `PYTHONPATH` and no longer
  exist in the default registry. It deliberately filters
  registrations before config loading and skips all private-read and live
  routes.
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

## Logging (iteration 29)

- Single entry point `backtrader/utils/log_message.py` (`get_logger`,
  `configure_logging`, throttled storm suppression). See
  `docs/LOGGING_GUIDELINES.md`; baseline catalogs are regenerable via
  `python scripts/scan_logging_baseline.py --out <dir>`.
- Default silence: nothing is emitted or written until
  `configure_logging(...)` is called (protected by tests).
- Split-file layout (opt-in): `configure_logging(level="INFO",
  log_dir="logs")` writes `logs/<script>/<YYYY_MM_DD>/{error,warning,info}.log`
  (level-exact routing, `debug.log` at DEBUG level). `<script>` auto-detects
  from `sys.argv[0]` (`xxx/run.py` -> `xxx_run`); `script_name=` overrides;
  `retention_days=30` prunes only that script's expired date dirs;
  child processes (cerebro optimize) get `.p{pid}` suffixes.
- Write backend: `backend="auto"` prefers the optional `spdlog` package
  (PyPI `spdlog` 2.0.6, sdist build — macOS/Python 3.11 verified working)
  and silently falls back to stdlib; `"spdlog"` raises ImportError if
  unavailable; `"stdlib"` forces pure stdlib. `get_logger()` always returns
  a stdlib `Logger` — spdlog is mounted as a `logging.Handler`.
- Silent-exception policy: no new `except: pass/continue` without a log
  line; bare re-raises log an ERROR first; hot-loop repeats use
  `throttled_error`/`throttled_warning`. CLI tools (`btrun`,
  `reports/reporter.py`) and public APIs (`Analyzer.print`, `Strategy.log`)
  keep `print` on purpose.
- Key lifecycle INFO (run start/finish, feed load, strategy nextstart/stop,
  order submit/fill/reject in `bbroker`) is per-run/per-order — never per
  bar; keep it that way in hot paths.

## Notifications (iteration 32)

- Single entry point `backtrader/notifications/` (`configure_notifications`,
  `send_message`, `Strategy.send_message`, `flush_notifications`,
  `reset_notifications`, `notification_stats`). See
  `docs/NOTIFICATIONS_GUIDELINES.md`.
- **Opt-in and silent until configured**: no channel, thread, queue, file or
  network until `configure_notifications(...)` runs. `send_message` before
  configuration returns `reason="not_configured"` and warns once on stderr.
- Asynchronous by default with **one worker thread and one bounded queue per
  channel instance** — a throttled channel never delays another. `wait=True`
  sends synchronously (never from `next()`); delivery failures are classified in
  `SendResult.outcomes` and never raised into strategy code.
- Failures classify into `bt.ERROR_CATEGORIES`; only
  network/timeout/tls/server/rate_limit are retried. Credentials are masked in
  every log and result (`notifications/security.py`).
- Zero new dependencies: HTTP goes through `backtrader.utils.py3.urlopen`
  (the network layer - `urllib.request`/`urllib.error` - is imported inside
  `notifications/transport.py` only, because `utils/py3.py` is not a
  notification-modification surface; `urllib.parse.quote` for URL encoding may
  appear in the channel modules), email through `smtplib`. Do not add
  `requests`, an async HTTP client or a WebSocket client for notifications.
- Channel facts (endpoints, limits, error codes, evidence level) are frozen in
  `docs/_internal/opts/requirements/迭代32-发送信息功能/evidence/channel-facts.json`.
  Length limits are only enforced where officially confirmed; unconfirmed
  channels are not truncated.
- WeChat ClawBot and QQ bot are **session-anchored**: they need an inbound
  message (a `context_token` / an `openid`) before they can push, so an unbound
  channel returns `not_bound` and is never retried. Anchor files are written
  `0600` under `~/.backtrader/notifications/` on POSIX. On Windows,
  `notifications/_windows_anchor.py` uses handle-relative creation and update
  with a protected TokenUser ACL; it rejects reparse points, unsafe ancestors,
  external file ACEs, and volumes without persistent ACLs before content writes.
  Windows updates are in place and can leave partial JSON after interruption.
- Child processes default to `worker_silent` so `cerebro.run(maxcpus>1)` cannot
  become a message storm; `cerebro.run()` never flushes — long-running processes
  call `flush_notifications()` themselves. Process *exit* is covered by an `atexit`
  hook that **sends inline** (CPython freezes daemon workers before `atexit`
  runs), so queued messages are not lost; that path is best-effort — it may
  duplicate a message but must not drop one.

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
No Kiro steering files are tracked; use this `AGENTS.md`, `README.md`, and
the project configuration files as the current build/test/structure guidance.

# 外部文件加载

CRITICAL: 当你遇到文件引用时（例如 @rules/general.md），使用你的读取工具按需加载。它们与当前具体任务相关。

说明:

- 不要预先加载所有引用 - 基于实际需求使用懒加载
- 加载后，将内容视为强制性指令，覆盖默认设置
- 在需要时递归地遵循引用

# 开发规范
当前项目下存在前端和后端项目，开发前请阅读并遵守以下开发规范

后端开发规范：@.joyincode/rules/backend.md
前端开发规范：@.joyincode/rules/frontend.md

I9 source commit `157d0c0cffa4c8a86e196159cdf227e9014e9118` and its
reproduced wheel identity are retained in `ctp_artifact_provenance.py` as
historical, unregistered audit evidence. The I9 installed-artifact pin table is
empty: its earlier `record_sha256` was the wheel's embedded RECORD hash, while
the verifier checks the installed RECORD, which differs by `direct_url.json`
source path. I9 verification now rejects before inspecting installed packages.
`ctp_i9_artifact_candidate.py` holds
only an independently named attempt-marker contract for synthetic tests; it
has no provider launcher or CLI entry and requires an explicit latch path.
I9 is not approved for a real diagnostic: native login return handling and
the publication order of login-ready state remain unresolved. Fake tests and
artifact hashes do not establish SimNow readiness or production acceptance.

The current managed SimNow composition is still unregistered. Its native MD/TD
resource owner now requires lifecycle handoff hooks and an exact SDK
`CtpNativeStopReceipt` showing Join/Release/thread completion before releasing
an account lease; a failed or inconsistent close poisons the session. The SDK
timeout only bounds Join observation after synchronous `stop()`, so this code
does not provide a hard wall-clock shutdown deadline without a supervised
worker. `backtrader_runtime.managed_execution` retains the fail-closed CTP
placeholder: a fake adapter that could invoke Store's SDK dispatch callback was
removed from runtime code and is test-only. The separate SDK v5 outbox fresh
verifier/claim helper is also unregistered and non-authorizing; it has no
trusted verifier or native dispatch. The latest local runtime suite after these
main-repo changes passed 1,465 tests with 24 skips; six related integration
files passed 7 tests. These are offline checks, not SimNow order/cancel evidence.

I10 is a separate, unregistered MD-only diagnostic candidate. Its clean SDK
source commit is `a6253a58b1ebca11f58c8836fbed757d0daf7582`; the twice
reproduced CTP wheel and the installed RECORD for a fixed wheel source are
pinned only by `verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts`.
The I2 default read-only pin and route are unchanged. A no-system-site-packages
Python 3.11.5 offline environment at `D:\temp\i10-runtime-env-20260925` passed
`pip check`, strict installed-origin SDK/native import, and the I10 provenance
gate with synthetic fronts. Its fixed wheelhouse lacks pytest, so tests inside
that specific environment are `NOT_RUN`; two separate installed-target copies
each passed 171 fake MD tests. `ctp_i10_oneshot_md_readonly.py` and
`ctp_i10_attempt_latch.py` expose no trading capabilities. A normalized path
alias of the canonical latch still goes through the registered-directory
check. The I10 supported operator entry ran once under a Windows Job, but all
five explicit config MD/TD pairs timed out in its credential-free TCP probe.
The value-free child receipt was `front_selection_rejected`; credential
resolution, native client construction, login, subscription, tick, order, and
cancel were not reached. The I10 latch is permanently consumed. Job empty
proves process containment only, not SDK orderly close. No real I10 SimNow
session has been accepted; `NO_WRITE / LIVE_NO_GO` remains. This one-shot
operator contract does not attest against deliberate same-user direct SDK or
private-Python invocation outside the supported entry.

`bt-runtime check-ctp-fronts --strategy-dir <registered-013_3-private-dir>` is a
separate credential-free TCP diagnostic for the same protected canonical
`config.yaml`. It runs only after the exact sandbox registry/binding gate and
reports pair indexes and MD/TD sample counts without addresses or credential
values. It neither uses a CTP SDK nor consumes a native diagnostic latch. A
2026-09-25 08:00 UTC check found configured pair index 3 reachable on both
MD and TD (3/3 each); the other four pairs were 0/3. At 15:40 UTC, a new
check found no eligible whole pair under the old 3/3 rule: index 3 had MD
2/3 and TD 3/3. Selection now requires a strict majority of samples on each
side (2/3 for the operator's three-sample check) and scores only successful
samples. A fresh 15:55 UTC check selected index 3 at MD/TD 3/3; the other
four pairs remained 0/3. These are time-local transport observations,
not a CTP login, account, settlement, or write acceptance.
The independent I11 MD-only supervised attempt has run once and ended `incomplete / native_join_pending`; its I11 marker is consumed and must not be reset or retried.
A subscription ACK was observed, but identity remains unverified; tick and TradingDay evidence are null, and native Join remains pending. See the I11 value-free evidence at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i11-md-diagnostic-2026-09-25.md`. Trading and settlement writes were zero. Default CTP write and live routes remain closed.

`ctp_i12_td_only_readonly.py` and `ctp_i12_td_only_latch.py` remain unregistered TD-only read candidates, not dispatchable runtimes. One supervised I12 attempt has run and consumed its independent marker: Job containment verified/empty, child exit 2, `rejected / runtime_policy_rejected` at `sdk_artifact`, login `not_observed`, all queries `unverified`, close `not_attempted`, and receipt fields `order_submission_authorized=false`, `settlement_confirmation_called=false`. Offline review found a strong, reproducible candidate defect matching the receipt: a sealed-config `Mapping` was passed to `_route`, which requires `CtpConfiguredFrontPair`. The child exception was not retained, so this is not proven as the unique cause of the real attempt; the recorded stage was before credentials, not an account diagnosis. Do not retry. Offline remediation is in progress. Its independent TD installed-artifact pin and metadata-only Job precheck reuse the exact I10 base/CTP wheel installation but do not call or inherit the I10 MD-only verifier. The candidate delays credential resolver and TD SDK/preflight imports until after fresh seal/pair and artifact checks, runs seven certified read queries, and requires positive typed native close evidence before emitting `td_readonly_complete`; Join pending and unknown close remain incomplete/fail-closed. The parent probes configured MD/TD endpoints with bounded unauthenticated TCP and selects a whole pair; the child probes only the same selected pair. These probes prove transport only. The native/API path is TD-only, with no `MdClient`, MD login, or subscription. Fake-only tests passed 14 cases with Ruff clean. No successful TD session or settlement was accepted; no order or settlement write was accepted, and no default route was added.

`ctp_managed_cancel_binding.py` adds an offline, non-authorizing structural contract that validates the v1 Backtrader cancel handoff against the full target fields used by the SDK schema-v8 candidate, including typed `ExchangeID`; the cancel action ID remains distinct from the target order IDs. Its focused fake-only tests pass 8 cases and Ruff is clean. The handoff types currently have no runtime consumers. The next insertion point is before SDK command staging inside a future async adapter replacing `CtpManagedExecutionAdapterPlaceholder.cancel_order`; wiring this into the current placeholder would only validate then reject because the generic facade still requires a synchronous provider observation. The binding does not authenticate callback source, produce a provider observation, enable an outbox/SDK dispatch path, or change the shared canonical `ctp:` config.

2026-09-25 I12 follow-up: `run_readonly_child` now accepts an optional shared
absolute `time.monotonic()` deadline. I12 starts one 90-second budget before
credential-free sealing/front selection and passes it through its metadata
and TD Jobs. Normal child exit waits within the remaining budget for natural
Job emptiness before terminating descendants; pending native Join, timeout,
and error paths still terminate immediately. The strict I12 acceptance
predicate was not relaxed. A separate real Windows Job run of only the
metadata verifier (no config, credentials, marker, SDK import, or provider)
returned `artifact_verified`, exit 0, Job empty, and no termination request.
The historical I12 one-shot marker remains consumed and its original child
exception remains unavailable; this offline check is not a TD session retry.
The latest full runtime suite at this checkpoint was 1,579 passed, 26 skipped
with one existing pytest config warning. The deadline is cooperative around
synchronous Python/Win32 operations, not a hard whole-command bound; ordinary
CTP `preflight`, SimNow writes, and the live route remain closed.

`ctp_i13_md_observability.py` is an unregistered, value-free projection of an
opt-in SDK MD diagnostic receipt. It keeps SDK callback/subscription/tick facts,
adapter acceptance, TradingDay checks, and native Join separate; contradictory
facts reject, and missing evidence remains unknown. The isolated I13 CTP SDK
candidate at commit `c68bebe8631419801e7a24e13b98c42867df0beb` has an
independently audited, byte-identical two-clone Windows wheel build (SHA-256
`c6eb83c1389b8f0e96edf9f727c20901b2411961489e19abb4ee1aef6ec2ce5d`)
and a recorded 234-pass installed-wheel fake-only run. The main projection's
13 focused tests pass. No I13 supervised real diagnostic has been accepted,
and these local results do not prove login, tick, native close, or trading.

`ctp_dispatch_read_model.py` is a pure opt-in reader/reducer for one exact
durable CTP command projection. It preserves local queue outcome separately
from provider order and cancel-action facts, including target-order state;
it never emits a Backtrader accepted/fill status or authorizes a write. The
isolated `bt_api_execution` v9 combined candidate has reviewed callback
envelope mapping plus a read-only durable projection (95 package tests), but
its callback and reconciliation verifiers still default to deny. The reviewed
CTP TraderClient source-event candidate is source-only and not bound to a
managed session. No trusted native source bridge, external account-wide
writer fence, default write route, or production admission exists.

The later I13 MD-only and I15 TD-only source-seal candidates are unregistered
and fail closed: I13 has an all-zero source pin and no manifest, and I15 has a
`None` pin and no manifest. Their child processes use `-I -S -B`, source-only
imports, and an exact fixed venv install root. A real one-shot is still
blocked because ordinary parent imports can execute runtime bytecode before
the source gate. The I13 finder also admits an unlisted `.py` sibling after
inventory, confirmed by an independent temporary-directory reproduction;
its directory lease does not prevent creation. A trusted stdlib-only parent
launcher and a manifest path/hash-bound I13 finder are required before either
candidate can use a real account or marker. The I15 child finder already
checks its manifest allowlist and hashes at each import. The latest full
runtime suite after the shared-config CLI wording check was 1,647 passed, 26 skipped,
one existing pytest configuration warning, in 71.96 seconds; this is offline
only. The current protected SimNow configuration and future production use
the same canonical `ctp:` block and physical `config.yaml`; the target is one
mode-aware managed CTP runner with distinct sandbox/live admission, while the
default registry currently has no CTP write runner or live dispatch. The
unregistered `scripts/ctp_i13_i15_sealed_import.py` is an offline, CPython
3.11.5-only source-import foundation with no supervisor or operator entry.
Its Windows file-ID lease now covers manifest seal and source-loader bytes;
external descriptor, interpreter/PyYAML pins, complete dependency closure
and independent review are still required before any real read-only use.

The Iteration 41 operator target is one protected
`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` with the
same canonical `ctp:` fields and one future managed CTP runner for SimNow and
production; mode-specific admissions remain separate. This local file exists,
is exactly Git-ignored, and is not tracked. A configuration edit alone still
cannot dispatch a CTP writer or live profile. The unregistered CTP queue-lease
source at `232a14d` produced a locally reproducible `2.0.2` native wheel and
its installed `TraderClient` plus fake API passed the two previously skipped
v9 execution bridge tests. That version is below the SDK superproject's
`bt_api_ctp>=2.0.3,<3.0` requirement, so it is not a formal integration pin.
An independent version-only candidate at `19349b8` now labels the same queue
lease/callback source `2.0.4+iteration41.i9`; two clean native wheel builds
are byte identical, installed RECORD and origins pass, and a no-system venv
passes 10 queue fake tests plus the two real-`TraderClient`/fake-API v9 bridge
tests. This candidate meets the superproject version range but is not pinned
in this repository or accepted for real CTP callbacks or writes.
The execution API-breaking cutover proof is now separately versioned as an
unregistered `0.2.0` source candidate at `60102bf`; two clean-archive wheels
are byte identical and their RECORD/source checks pass. Neither candidate
authorizes real callbacks, SimNow orders, cancels, or production. Agent/Skills/MCP
now have metadata-only private-runtime path guards with independent offline
tests, but arbitrary Python and the checkout-root `.env` are not isolated;
AI-to-CTP execution remains unavailable.

The generic config-v4 profile dispatcher now permits only trusted code-owned
offline `simulation/replay` and `backtest/local_backtest` profiles with a
runner, no secrets, network, external writes, managed execution, capabilities,
approval, or sandbox write policy. The default 013_3 CTP profile remains
read-only and has no runner. A separate non-authorizing CTP mode-scope binder
proves that synthetic sandbox/live profiles can use the same physical config
and runner identity while binding distinct account, receipt and front scopes.
A synthetic receipt-required SimNow profile can now open a fake native session
through the unregistered session composition; default deny/live unavailable
still reject. Profile-backed submit/cancel revalidate the sealed config before
reservation and native dispatch, but a final check-to-native-call TOCTOU remains
and requires a linearizable lease or trusted external per-action grant before
deployment. The latest full local runtime suite at this checkpoint was 1,793
passed and 27 skipped, with one existing pytest configuration warning; this
does not establish provider or write readiness. An isolated
test-only native I13 callback shim traverses C++ virtual to SWIG director to
Python, and its full MD one-shot file passes 107 fake tests. It did not explain
the actual vendor callback's empty identity fields.
I2/I4/I6/I7 static artifact audit found the same full 6.7.7 MD DLL/header
family in the reviewed source and wheel payloads, with no Mini 1.7.0 files.
It lacks the child processes' actual mapped-module receipts and official
archive hashes, so the callback and Join root causes remain unknown.
An isolated mapped-module identity receipt candidate `a3b3fd89` passed 16
fake tests but is unregistered and has not queried a real Windows child; its
path hash is linkable and it cannot exclude reparse-to-network or concurrent
file mutation.
The unregistered I13/I15
sealed-import slice passed nine fake tests. Its Windows source file-ID lease is
integrated into manifest seal and source loader; loader execution identity now
rejects a forged, unexecuted module in `sys.modules`. The I13/I15 parent
launcher now has an offline external-descriptor and clean import-closure gate,
with injected metadata-Job tests. An unregistered outer watchdog and Windows
Job backend candidate now cover suspended atomic Job assignment, handle
escrow, and an inert local child in 28 targeted tests; the single Windows smoke
is not provider or hard-deadline acceptance. An accepted external descriptor,
complete dependency closure, artifact pins, independently supervised whole-
command deadline, and provider worker dispatch are still absent.
An isolated local source-only snapshot `64c271bf` matched the 91 runtime
Python files in that checkpoint byte for byte and produced positive/negative I13/I15
candidate manifest checks. The runtime manifest paths and reviewed pins remain
unset, so this does not authorize diagnostic launch or close G1.
The static writer-candidate inventory also scans historical 014/015 CTP
examples; discovered calls remain review-required and unavailable, never
runner registrations.
Its default scope now includes Python sources under ordinary `examples/`
directories and root `.py` scripts, with a reviewed path baseline in
`scripts/iteration41_writer_inventory_scope.json`. New unclassified paths
At the 2026-09-28 CE04 Store route-identity checkpoint, the R2 scanner inventory was refreshed to SHA-256 `0874A81AC23BA4F659ACAAC833A976ECEC44FA892A3A97778EA3D9779DB67A67`; it retained 460 active candidates (363 writer, 97 dynamic) across 355 files, plus six historical tombstones. Candidate IDs and order were unchanged; source-linked locators reflected that snapshot. The verifier reported 460/460 rows, all active dispositions `REVIEW_REQUIRED / NOT_AVAILABLE`, and no reason codes; the R2 scanner focus passed 15 tests. The current official inventory is the later `A959A3BC…` snapshot recorded in the Iteration 41 checkpoint below. These checks prove static inventory and disposition integrity only, not writer closure or route authorization. The private CTP runtime state is summarized by path without reading its contents.

The [AC41-63 full writer review archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-writer-review-460-2026-09-27/README.md) covers the exact prior A039 Store-era inventory SHA-256 `03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456`: 460 unique positions, with no gaps or overlap, and 20/20 checksum and 14/14 link checks. It records three scoped static findings (a mutable CTP wrapper flag reaching a fake sink after same-process mutation; `create_live_broker` accepting a caller-supplied Store; and `RuntimeRegistry(trusted=True)` not being code-enforced), plus 31 stale line-only checklist locators across eight files. The verifier still passes and all official dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE` (six tombstones). This is historical review evidence: at its later 2026-09-28 refresh the inventory was `0874A81A…`; the subsequent official inventory is `A959A3BC…` with the same candidate identities. It does not establish current-source writer closure or authorize writes.

The credential-free CTP front selector now considers a pair transport-reachable
only when MD and TD each connect in a strict majority of bounded samples (2/3
for the registered diagnostic), and ranks eligible pairs by their successful-
sample median latency. The operator diagnostic rechecks the score and fastest
configured pair; native login/readiness and write admission remain separate.
At 2026-09-25 15:55 UTC the current protected config's pair index 3 had MD/TD
3/3 and was selected for transport observation only; the other four pairs
were 0/3. The same file's earlier 15:40 UTC 2/3 MD observation was rejected
under the then-current 3/3 rule and remains historical evidence.

`ctp_shared_managed_runner.py` adds an unregistered, non-authorizing common
preparation path for synthetic SimNow and production profiles using the same
canonical `ctp:` config, runner identity, and exact selected pair. It now
rechecks the issued admission object and rereads the registered `config.yaml`
before mode selection and after front probing. A stale in-memory effective
config is rejected; final-check-to-native-call linearization is not solved.
`ctp_shared_managed_runtime.py` is an unregistered common composition root:
the simulation arm delegates to the existing SimNow managed session, while
the live arm rejects before front probing, credentials, SDK import, or native
construction because production session and durable-journal authorities are
absent. Its public context rechecks route/account/front/contract changes in
the same config path and closes a just-opened session if the config changed
during the opener. Private password/AuthCode rotation is left to the
underlying per-action credential-binding gate; it grants no write route.
`ctp_f14_external_admission.py` defines only a typed external account-wide
fence/coherent-snapshot action claim; no trusted authority or dispatch binding
exists. `backtrader/stores/ctp_managed_projection_bridge.py` defines an outbox
projection port, but current SimNow session and BtApiStore queue worker do not
share one durable command authority; the bridge rejects that session. The
Store's managed `_sdk_order_request()` and `bt_api_execution` still have
different OrderRef reservation sources, so a queued Store command cannot yet
be claimed as the same execution-ledger row. A new unregistered typed v2
`CtpManagedDispatchBinding` carries complete command/session/approval/cancel
target identity. The managed Store queue can persist its exact receipt under
the worker condition lock before publishing the command; the managed worker
requires that typed binding and a single dispatcher, with no generic fallback.
The opt-in I9 bridge checks the Store receipt's reserved OrderRef,
queued/status fields, priority, and queue depth before recording it; these
local checks do not establish a shared durable worker authority.
No live caller supplies those ports yet, and the old v1 bridge records its
receipt after queue dispatch. Managed submit/cancel therefore reject before
the second OrderRef allocation or native send. A single reservation source,
v2 cutover and crash-safe no-resend proof are required before native dispatch
is allowed. The candidate Windows `ctp_config_action_linearization.py` exposes
a `ConfigPathReadLease` diagnostic only. It pins local NTFS config path handles
and rejects remote/nonfixed drives and config hard links, but is not integrated.
A focused local negative test shows
that a parallel `FILE_WRITE_ATTRIBUTES` handle can set a custom reparse tag on
the held config during a fake native-action window: the share lease is not a
final-seal-to-native-call fence. A trusted external broker owning config/path
mutation and the single native dispatch is only a type-level future contract,
not an implementation or write grant. The I9 base/CTP/execution three-wheel
artifact-set verifier is an
audit-only offline candidate with no default pin; its CTP wheel does not
include the separate bounded Join source candidate. I13/I15 parent preflight
rejects missing external source pins/manifests and remains disconnected from
provider sessions. SimNow's official 7x24 environment is API-test-only with
no settlement service, so it cannot supply the current managed TD settlement
readback needed for complete write acceptance; config front selection still
never infers environment from set labels or time.

An isolated `bt_api_ctp` I9+Join/Feed Ref synthesis has a uniquely versioned
`2.0.4+iteration41.i9.join1` Windows CPython 3.11 wheel. Independent roots
produced identical SHA-256
`8d2d845501f43939704c9e6c61610ec1747d613a4e07485245bbb006c8242fbe`;
254 fake tests passed and one checkout-relative test was excluded. A fresh
no-system venv installed exact base/CTP/execution wheels and a recorded
dependency closure; installed RECORD, origin, and `pip check` passed without
loading `_ctp`. This wheel lacks the `order_action` evidence and query-source
request-filter APIs used by the separate G5 query-target candidate. It is
incompatible with that candidate and has no default pin or native acceptance.
An I13-to-I9+Join1 ancestry audit stopped without a merged wheel: the exact
I13 branch and I9+Join1 tree have 14 `client.py` merge conflict regions across
native Join/Release, API-origin and callback queues, and order-action history.
The required `get_order_action_evidence` needs those callback/lifecycle
semantics, so copying only its DTO or query filters cannot close G5. A
separate native lifecycle/callback merge review found that Join/Release must
share one per-API state machine and source/order/action callback records must
be admitted atomically under the same API-generation lock. The isolated manual
fake-only source candidate at `D:/bt_api_ctp_i13_g5_manual_candidate_20260926`
passed 264 tests with one path-dependent test deselected; it adds the shared
Release fence, source/order/action evidence and exact query filters. It still
lacks managed-cancel identity arguments/response envelope, bounded stop,
wrapper/consumer compatibility, package export/version review, and the Store
I9 reservation-to-request handoff. No unified wheel, pin or managed artifact
is accepted.

An inert-only Windows guardian candidate now connects a sealed parent launcher
to a separate guardian and sleeping Python child. Its external descriptor
binds source hashes, the interpreter, and a fixed receipt directory; tests
terminate the parent and observe the guardian empty the child Job. The six
focused modules passed 82 tests in the compatible Windows venv after the
fixture used the actual pipe-service and owner PIDs. A blocked-service negative
test shows that caller IPC timeout leaves the service/child alive, while killing
the service closes its Job and kills the inert child. This is not a hard G1 supervisor: synchronous
`Popen/CreateProcess` and guardian Win32 calls can block beyond a deadline,
the descriptor's external trust anchor and receipt directory ACL are not
verified, and the ordinary CTP `preflight` does not use this path. No SDK,
private config, marker, network or trading write was used.

An additional unregistered, inert-only outer deadline supervisor owns a
separate Windows Job around that guardian. After the owner process dies, an
independent process reaches the same monotonic deadline, requests Job
termination and writes an UNKNOWN receipt; the service and sleeping child then
exit. Seven guardian modules passed 84 tests twice in the compatible venv,
with one existing pytest-configuration warning; a root rerun also passed 84.
This does not prove a whole-command hard deadline: receipt write can occur
after the deadline, and supervisor hangs, source trust, deployment ACL,
native lifecycle and ordinary preflight integration remain unverified.

The guardian pipe service now uses a protected current-user DACL verified by
handle readback, remote-client rejection in `dwPipeMode`, two pipe instances,
and impersonated SID checks for both the HMAC response and the actual request.
The exception path also avoids closing the pipe handle twice. The final
service file passed 11 tests in both author and independent root runs; the
root run took 24.28 seconds with one existing pytest-configuration warning.
This local current-user boundary supplies neither an external deployment
trust root nor a whole-command hard deadline. G1 remains NOT_PASSED.

The 2026-09-26 broad default-plugin regression in a compatible isolated
pytest 8.2.2 / pytest-asyncio 0.24.0 environment, covering
`tests/unit/runtime` and all eight `tests/integration/test_iteration41_*.py`
while excluding runtime one-shot files, passed with 1,639 passed, 27 skipped,
2 xfailed, 0 failed and no warnings in 93.68 seconds. This was superseded by
the latest F14/SimNow candidate run: 1,674 passed, 27 skipped, 2 xfailed,
0 failed and no warnings in 99.92 seconds. This range excludes
the separate seven-module guardian script focus described above.
Gateway's
fake provider returned once while
Router recorded `RETURNED_UNVERIFIED` and the managed client retained
`UNKNOWN`; a repeated submission did not call the provider again. This is
offline fake/inproc coverage, not a CTP session or trading acceptance.

`ctp_managed_action_authority.py` is an opt-in signed-action verifier for the
exact execution Store, issued callback owner, writer lease, and active session.
It binds the persisted command to an Ed25519 permit, sealed runtime scope,
revocation observation, external-fence observation, and trusted UTC port.
Returned authority expires no later than either trust observation's 250 ms
freshness deadline and is consumed by the Store's existing one-use ledger.
The default verifier rejects. The pinned key mapping rejects ordinary mutation;
this is not isolation from hostile code in the same Python process.
`ctp_managed_action_scope_resolver.py` revalidates the canonical config and
exact mode-specific admission on each resolve. Its account reference uses a
versioned canonical broker/user digest, and it fixes the selected configured
MD/TD pair. It performs no transport probe or default registration. These
modules do not provide a deployed permit issuer, external account fence,
active native host-pair continuity, or an atomic fence through the final
native request. Independent V18 Store review found that the first 41-test
candidate could authorize a signed request whose login account and request
account/contract fields differed from the sealed config. The frozen v2 fix
and READY-only defer passed 75 independent source tests; eight additional
signed request/session mismatches were rejected by the actual V18 Store,
with READY rows and zero native dispatches. This used SDK29/parent76 sources,
base 0.15.4, and an explicit QA execution metadata shim, not an installed
wheel bundle. The v2 test file retains one Ruff E731. Final CLAIMED-phase
expiry/revocation/fence revalidation is a separate slice: the next repair
checks the original Store binding expiry against the final trusted-clock
sample and has 98 author focus passes. An earlier independent run imported
mutable main-tree code through its CWD; its frozen-r3 attribution is invalid.
A corrected same-process origin-guarded r3 probe reproduced the expiry gap
within the allowed 250 ms wall-clock skew and called only a fake SDK Req.
The successor fix still needs independent acceptance; neither version proves
an external atomic fence through the native request.

`scripts/ctp_i13_i15_guardian_deployment_anchor.py` is an unregistered fixed
ProgramData descriptor/handle-lease candidate. It separates code integrity
permissions from the service's fixed receipt-directory writes, retains the
source and selected venv interpreter paths, and creates receipts with
CREATE_NEW. Its deployment pins remain unset. This does not yet seal the
base Python distribution: CPython loads encodings before bootstrap, and the
current local Anaconda base grants Users write access. A separate fixed
runtime manifest, protected base DLL/stdlib inventory and retained directory
leases are required before deployment. The client-safe descriptor reader
binds the fixed BacktraderCtpReadonlyGuardian service name without reading
the legacy shared-HMAC key. The new read-only pipe route uses OS service
identity and remains under integration review. The source manifest has a
narrow data-only exception for the exact read-only worker path; the child
bootstrap and dependency finder are being integrated. The frozen r5 anchor
passed 68 independent tests, including a temporary Windows retained-handle
absent/present cache-leaf test with ACL checks stubbed. Its code-derived
`disabled-bytecode-cache` path does not accept caller overrides. Guardian
route r1 has a cross-session inherited-handle deployment blocker and a
failed-RevertToSelf follow-up bug. A later pre-orchestration snapshot passed
41 independent service tests and one parent manifest-gate test; its seven
Revert/fail-stop tests are a subset of the 41. Both impersonation helpers now
use process-fatal restoration failure handling. Those tests did not execute
real process termination. A bounded named-pipe output channel and per-request
coordinator/receipt supervision remain separate follow-up slices. Caller timeout still
does not prove a whole-command service deadline. Ordinary preflight,
service deployment, real native sessions, and default write routes remain
closed.

The V18 execution Store's cancel postcondition slice was independently
verified at 155 passed / 2 skipped, including six legacy migration cases;
the skips lack the ambient SDK callback consumer lease. Local commit
33d132d6 matches that frozen source after CRLF normalization. V18 still
partitions account identity by environment, so a new mode-independent CTP
account-family owner gate is being implemented. Its old journal cannot
reconstruct raw account references from hashes; nonempty legacy history
must not be silently reassigned. A separate main-bridge regression found
that UNKNOWN cancellation recovery was scoped to one strategy. The V19 r0
Store claim gate rejected a live bridge's new order after another strategy
left UNKNOWN cancellation state; the order stayed PENDING_DISPATCH with
zero attempts, and restart reconstructed the risk freeze. Independent QA
then reproduced a writer-lease generation ABA: release deleted the row,
reacquire reused token 1, and an old lease could mutate or release the new
lease. V19 r1 retains an expired tombstone and passed 240 author package
tests with two skips. Independent r1 public-API/SQLite checks accepted the
reviewed family owner, generic/CTP unresolved-cancel claim gates, V18 migration
fence and close/reopen stale-lease rejection; root rehashed 28 source/test
files and checked nine copied synthetic databases. Clean-close ownership
handoff is still unavailable. The broader main bridge focus then reported
63 passed / 4 failed; old test doubles and actual offline replay integration
are being repaired, so this is not unified runtime acceptance. The shared
candidate's public factory opens the existing account journal filename under
its existing flow lock, rejects legacy history before schema changes, and
binds an immutable exact account identity. It does not create a second ledger
or claim cross-host/hostile-file protection. V20 r0 incorrectly accepted a
same-name trigger with an altered body. V20 r1 added full SQLite schema
comparison and precise empty legacy orders-only recognition, but independent
QA rejected public-API cross-account mutation. V20 r2 adds transactional
bound-account checks; 29 frozen source/test files matched the manifest, and
28 independent tests plus a public API probe accepted the scoped single-account
binding. The r1 snapshot remains rejected and immutable. The main shared-
account candidate independently matched 105 frozen files and reran 84 passed /
2 expected xfailed in a source-only fake bundle. The xfails retain the final
config-check-to-native-dispatch race. Separate V20r2 and R3r2 ordinary
installed-wheel consumers independently passed full offline dependency,
origin and RECORD checks (51 distributions, 9,077 hashed RECORD rows each),
but both Execution wheels are labeled 0.2.0 despite distinct hashes and need a
unique final version/pin. None proves a real-account restart or deployment.
The R3r2 cancellation claim source bundle independently matched 29 frozen
files and passed 278 package tests with two optional SDK bridge skips; those
two tests passed only in a separate QA fixture with complete fake login fields.
An integer-zero risk claim prevents any cancel provider call and freezes
UNKNOWN; an integer-zero provider result follows one cancel call and also
freezes UNKNOWN. Parent terminal-proof issuance and main runtime positive
integration remain unfinished.
The clean-handoff design audit requires
issuer-bound native-close and final callback-drain evidence before any new
owner generation; current permanent owner fences are not a usable restart path.
The claimed-action expiry r4a source bundle independently passed 100 fake-call
tests, including 100 microseconds before/after the original Store binding
expiry with a bounded 250 ms trusted-time-to-call skew. It does not supply an
external account fence, native CTP proof, or write authority. The main
cancellation bridge now obtains an exact risk dispatch claim before a fake
provider cancel call but still needs a typed terminal cancellation proof before
releasing its risk latch. G1 output-channel r3 failed independent QA because a
forged outer
result could claim Job empty while the worker was alive; r4 independently
passed 20 local helper tests and r6 passed 56 post-resume tests. The
coordinator/worker Job and subsequent receipt-writer Job still require
complete service acceptance. Default routes remain `NO_WRITE / LIVE_NO_GO`.

The G4 fake blocked-stop Job probe and an independent Windows rerun both
observed timeout, process termination and Job empty for blocking
`RegisterSpi(None)` and `Release()` child calls. This proves only host-local
fake containment. The SDK `stop_and_wait(timeout)` does not bound those
synchronous close calls before its Join timer, and the wider SDK focus retains
one historical failed concurrent-cleanup assertion. An isolated test-only
synchronization fix then passed 56 focused tests independently; e75 production
SDK source was unchanged. Real native close and the full G1 service supervisor
remain unaccepted.
A separate fake service counterexample independently reproduced a synchronous
`create_receipt` blocking after worker Job empty and beyond the request
deadline; the handler stayed alive past an external 250 ms wait and returned
`observed` only after release. No real SCM/CTP was used. The current service
therefore has no accepted whole-command hard deadline; ordinary CTP
`preflight` stays fail-closed.
The installed-wheel G5 fake chain independently reproduced a different gap:
after a post-claim synthetic admission denial, the account family and callback
owners are POISONED and new owner acquisition rejects across reopen, but the
command remains CLAIMED with native_call_inflight=1 and no explicit UNKNOWN
receipt. No native Req occurred. A narrow poisoned-generation UNKNOWN
finalizer and a full rerun are pending; this is not a replay bypass or G5 pass.
The first G5 author evidence JSON mistyped the Execution wheel SHA as 65 hex
characters; a separate v2 corrigendum verified the existing 64-character
wheel against the prior unified installed-consumer receipt and RECORD.

`ctp_simnow_operational_window.py` adds unregistered, non-authorizing G6-S
scope, one-action permit, revocation, risk-ceiling and single-query stream
contracts. Their account-wide exclusion, common snapshot, signature and write
authority flags remain false. They are separate from strict F14 and have no
trusted reviewer/verifier, Store or SDK dispatch connection. The independent
I13 MD value-free source candidate is commit `297f37e` in
`D:/source_code/bt_api_ctp_i13_md_value_free_review`; its 14-entry Windows
byte-stable manifest is SDK source-review evidence, not the complete parent
launcher source manifest/pin. It has no candidate `_ctp.pyd` or wheel, and
native/provider tests were not run. These candidates do not alter the default
`NO_WRITE / LIVE_NO_GO` route.

`ctp_simnow_signed_review.py` adds an unregistered HMAC review verifier and an
explicit host-local SQLite permit/action replay guard. On Windows the guard
checks owner/protected DACL, ancestors, database identity and SQLite sidecars,
and rejects UNC/remote/unknown volumes and untrusted generic-write ACEs. Its
two-file focused contract passed 77 tests in the compatible local venv. No
deployed key/issuer, account-wide writer fence, trusted callback, Store/SDK
dispatch, production ACL deployment or cross-host claim is supplied; the
permit stays non-authorizing and ADR-41-16 option B is still proposed.

`backtrader_runtime/ctp_f14_signed_receipt_contract.py` is an unregistered,
offline receipt-wire contract candidate. It validates canonical versioned
receipt bytes against explicitly injected issuer/key/audience pins and an
injected Ed25519 verifier, then returns only a non-authorizing shape
observation. A local `CtpF14PinnedEd25519Verifier` checks genuine signatures
against injected public keys and SHA-256 pins; no production trust pin or
account-control service is supplied. Its
replay/epoch cache is process-local; an optional explicit host-local SQLite
observation fence persists replay keys across restarts and concurrent local
processes, but its ACL/owner and cross-host exclusion are unverified. Neither
implements external account control, service-side durable dedupe, a
`CtpF14ExternalAdmissionAuthority`, or dispatch.
Signed assertions do not prove account-wide writer exclusion or snapshot
truth. G6-P remains blocked, G8-P remains unrun, and the default route stays
`NO_WRITE / LIVE_NO_GO` until a unique external account actor owns credentials,
session, snapshot and final provider dispatch.

The isolated `bt_api_execution` I9 single-worker source candidate now has
follow-up commit `b676fe6`: its SQLite queue receipt precedes claim, and any
post-claim sender `REJECTED` is persisted as `UNKNOWN` because there is no
trusted no-send/no-callback proof. Only a pre-send durable `queued=false`
receipt is locally rejected. This candidate passed 133 SDK package tests with
two skips, but has no wheel, default pin, native sender, or shared OrderRef
authority with `BtApiStore`. The main Store's broad unit suite passed 662;
ten Iteration 41 integration tests passed. None is provider acceptance.

A later Store/Broker broad local run used six fresh detached source checkouts
at exact parent/base/CTP/execution/risk/monitor commits
`5de97235/3de0fa4/9976bcbb/55798072/dce2c84/8498ca7d`. The compatible
venv run passed 1,121 tests and skipped 148, with no warnings. An audit hook
allowed 53 literal loopback socket events needed by Windows asyncio and
blocked DNS, non-loopback network, native CTP imports and private config
reads; no such blocked attempt occurred. Five initial `bt_api_py` import
failures came from the venv lacking those external sources and passed with the
exact clean source paths. An independent rerun after narrowing the audit
import guard to the exact native module leaves `_ctp` and `ctp_wrap` again
passed 1,121 tests with 148 skips in 10.37 seconds, exit 0 and no warnings;
the guard no longer mistakes the Python `bt_api_ctp` package for an extension.
It recorded the same 53 loopback events and no blocked attempts or native
CTP modules loaded. Skip review then confirmed the optional SDK helper checks
installed distribution metadata before import: the 13 CTP wrapper test
locations were skipped despite the CTP source path. This broad result does
not establish CTP Python client compatibility or installed-artifact coverage;
with explicitly labelled temporary source-only distribution metadata, the 13
CTP wrapper test locations expanded to 15 passing tests. The expanded
Store/Broker run was 1,261 passed, 11 failed, 1 skipped: nine request-DTO
signature mismatches and two rejection-message mismatches. A subsequent
six-test rerun passed after non-CTP cancellation stopped sending the CTP-only
`runtime_order_id` keyword and the same-store rejection message was unified.
The legacy Store now keeps runtime IDs in its internal mappings and omits
unsupported top-level runtime identity keywords from parent request DTOs;
the pinned normalized Store file passed all 44 tests. Managed CTP still
rejects before the separate legacy allocator. An adjacent source-only I9
queue smoke needs the new fresh same-store cancel target handle; that
compatibility check and the opt-in parent request builder remain in progress.
The expanded run blocked two optional native import attempts and loaded no
native CTP module; temporary metadata is not installed-wheel evidence.

The isolated CTP source compatibility checkpoint is now
`07012dda628c8c0d7fefa6e1b925f7f8b3f8f518`: query getter readback,
managed cancel identity, terminal login observation/certificate and a native
shutdown receipt view coexist in one source tree. Its copied five-file fake
focus passed 302 tests with one parent-layout exclusion; the actual SDK fake
receipt to main shutdown consumer focus passed 45 tests independently. No
native CTP module was loaded. A subsequent independent clean-checkout audit
of all seven files passed 347 tests with one layout exclusion and two warnings
in 57.38s; external network and protected config access were absent. The audit
allowed only numeric loopback for Windows event-loop socketpairs and is not
an OS isolation proof. When no observer thread exists, the receipt reports
`thread_alive=False`; Join completion remains a separate condition.
Synchronous `stop()` still has no whole-call hard bound.
This is not a wheel or default pin. MD/profile credential compatibility and
the 155-callback durable session ingress remain incomplete; the current
three-event source queue cannot prove complete account callback coverage.

`BtApiBroker.get_strategy_allocation(strategy_id)` now delegates through
`BtApiStore` to an attached `ManagedExecutionBridge` and the optional SDK
local risk reader. It enforces the runtime strategy and returned account
scope, and performs no SDK startup or balance refresh. The returned snapshot
is advisory local reservation information, not cash, margin, a provider
account snapshot, or order authorization. The ten main-repository forwarding
tests pass; together with the existing managed bridge focus, 73 tests pass.
The opt-in `NotionalAllocationSizer` uses a reviewed SDK instrument registry,
an explicit Decimal limit-price callback and metadata clock, and the new
reader. Its SDK helper reuses the instrument assessor and floors to the
quantity lattice; it does not infer margin or remaining position capacity.
Four source-only SQLite risk-to-Broker/sizer integration tests pass, including
an over-budget custom request rejected by the hard gate; the combined main
sizer/reader/bridge focus passed 85 tests. Independent source review verified
the immutable account-policy binding rejects widened caps, removed allocation
requirements and changed units, and the two-process distinct-strategy race
admits only one 600-unit reservation under a 1,000-unit account cap. The
six-file risk package passed 201 tests at that checkpoint. Subsequent small
changes add a snapshot arithmetic-scale bound and clarify zero-allocation
exhaustion; their final candidate result is recorded in the parallel
checkpoint. These contracts do not establish full AC41-48 or a deployed
writer. Existing `getcash/getvalue` semantics are unchanged.

The unregistered `backtrader/stores/ctp_i9_managed_dispatch.py` bridge now
rejects structural fake ports before any reservation or worker call. It
requires Python 3.11+, the exact installed `bt_api_execution==0.2.0` I9
classes, and a worker whose `_store` is the same object used for durable
readback. This is a local wiring guard, not a trusted code-origin or
in-process isolation proof; cancel still lacks typed provider-order
provenance. Four focused offline tests against isolated real I9 source and
the 667 Store unit tests passed. The source smoke establishes local submit
stage/readback and a fake sender path, not installed-wheel or provider
acceptance. The bridge refuses forged/cross-instance/cancel handles before
queue callbacks because cancel still has no trusted provider-order projection.
An additional local negative test supplies complete caller-owned cancel
target fields but still observes zero stage, queue receipt, or dispatch; the
missing I9-to-native-query scope receipt remains an explicit G5/G7 blocker.
The current managed cancel DTO requires both native target forms even though
the CTP native API permits either one; source-only negative tests keep both
single-route forms closed until a trusted tagged provider projection exists.
The isolated SDK consume-only OrderRef mirror, managed Feed/Gateway Ref
format sentinel, and I9 single-worker source candidate remain separate,
unregistered slices. Neither mirror nor sentinel grants dispatch authority;
trusted SDK request-intent binding and accepted allocator cutover remain G5 blockers.

An isolated SDK follow-up commit
`87776bf38bd9b4ac0b9b0963deb074a4996e10a8` rejects the legacy
time-based allocator for bound/managed CTP sessions and rejects exact CTP
venues in the no-session allocator facade before clock or journal effects;
independent fake review found no P1 in that narrow cutoff. The no-session
`make_order` legacy UUID path is distinct from that cutoff. An independent
offline composition smoke followed it through the real DirectBackend and a
byte-matched pinned CTP Feed: no execution capability was passed, and the
Feed rejected before OrderRef allocation, RequestID, or native submit, each
observed at zero. This is only a narrow no-capability fail-closed result.
The older Feed/Gateway Ref sentinel commit `03f0b96` is on a divergent SDK
tree and cannot be cherry-picked into the current parent: Gateway and Feed
now live in pinned `bt_api_base`/`bt_api_ctp` subpackages. The pinned CTP
Gateway adapter rejects direct writes, but a fake managed/armed CTP Feed can
still allocate a missing OrderRef locally. An isolated CTP child source
commit `0609b05afee97d0cde644dac22f5c620aa088ec9` directly on the pinned
`ce1edd60785eb4c66fefa16a994a66946a1e068f` removes that Feed fallback,
requires an exact 12-digit ASCII Ref, and passes it unchanged; 218 focused
offline tests passed and an independent review reran 190 affected-file tests.
An isolated source-only parent commit `7fe53a07981ec46c01a0a9993dae124b779435ee`
updates only its CTP Gitlink to that child; the accepted wheel and default
runtime are unchanged. Independent audit found a managed fake-transport path
that accepts a valid Ref without an I9 mirror, and ordinary Python import
selected site-packages CTP rather than the candidate Gitlink until explicit
source paths were supplied. This format check is not I9 reservation/intent
binding, a native direct-call guard, or managed
cancel provenance; no provider writes are enabled.

A newer isolated CTP child `9976bcbbbe331ee77e2d90e05da08472259a625a`
combines the Feed Ref guard with the full Join/Release source chain. The
clean parent candidate `6d24217d858bb6ac27ca46ad8a1a13123063d047`
in `D:\bt_api_py_codex_ctp_gitlink_9976_20260926` updates only its CTP
Gitlink to that child. Exact pinned-source testing passed 255 child fake
tests and 309 parent I9/execution/forwarding/normalized API tests with two
skips; Ruff, compile and diff checks passed. The default pin/wheel remains
unchanged, the execution Gitlink is still an initial commit, and the result
does not establish I9 authority, native close, or provider acceptance.
The same isolated parent branch then cherry-picked equivalent forwarding
scope patches, yielding clean HEAD `da2286911a376678c8f22bf8080090d4c4fdbfe2`.
Its exact source-path parent fake suite passed 469 with 21 async skips;
the child focus passed 255. Independent audit verified the original
forwarding SHAs are patch-equivalent, not exact ancestors, and separately
passed 18 Feed/callback, 107 Router-scope, and 29 I9-consumer fake tests
with explicit root/base/CTP import origins. The execution Gitlink is still
the package-empty initial commit and there is no installed wheel/native or
default write route.

A separate clean parent Gitlink-only candidate
`c4407b09bb4fd470a3dcb498d56fd0c6034d02c7` in
`D:\bt_api_py_codex_execution_gitlink_b676_20260926` fast-forwards only
`bt_api_execution` from its package-empty `2700cb54` to source commit
`b676fe666de5373c58ff59bc0b856b7f6d4ce7fd` (`0.2.0`).
`installable=false` and the default route remain unchanged; the SDK has no
installed I9 distribution metadata from this change. I9 source fake tests
passed 133 with two skips, CTP child tests 255. The parent expanded suite
reported 640 passes, two skips and 19 failures; all five arming fixture
binding failures and 14 risk `AccountScope`-API failures reproduce at the
previous Gitlink. Full I9 Ruff reports 38 findings. This is not an accepted
wheel, runtime authority, or provider write path.
Independent Gitlink review passed 19 I9 store/contract, 29 SDK consumer,
and 5 installer focused tests, confirmed the one-pointer diff and unchanged
installer behavior, and reproduced the 38 I9 Ruff findings; it did not
accept the expanded parent suite.
Independent risk-source review found current Gitlink `d0c18a9` lacks the
managed fake-dispatch APIs. The first `AccountScope` child `7343430` is
insufficient and would allow generic clearing of a dispatch-inflight latch.
The first source commit with typed `VerifiedDispatchResolution`, journal
authority, and generic-clear rejection is `dce2c84d3216cdb215f6db7157dda181178260af`;
at that checkpoint it was not pinned or independently tested. The parent runtime's old
generic resolver calls also need conversion to the exact proof path, so a
risk Gitlink update alone does not close the 14 fake-dispatch failures.

A later clean, isolated parent **source-only** candidate at
`D:\bt_api_py_codex_i9_integrated_20260926` HEAD `5de97235` combines the
I9 child quality-only `5579807`, risk `dce2c84`, monitor `8498ca7`,
typed parent dispatch-freeze resolution, and repaired old arming test
fixtures. With exact clean local source paths for base `3de0fa4`, CTP
`9976bcbb`, and those three children, the parent non-network contract and
fake-dispatch suite reports 1039 passed / 7 skipped. Risk child tests report
159 passed, monitor 40, I9 133 passed / 2 skipped; I9 Ruff is clean.
Independent risk review found no path in this typed composition to clear a
dispatch-inflight latch without the injected fake journal authority. The
monitor successor covers a durable outbox for local fake facts; its separate
control ledger accepts caller-asserted issuer/authorization and is **not**
an authentication boundary. The execution submodule still has
`installable=false`, newer Gitlinks have not all been published to a shared
remote, and no accepted combined wheel/RECORD/import-origin, native session,
cancel-target issuer, default write route, or real provider order/cancel exists.
G5 remains `NOT_PASSED`, `NO_WRITE / LIVE_NO_GO`.

A later unregistered `bt_api_monitor` candidate gates its control ledger
through `ControlIngress` and a domain-separated HMAC verifier with injected
key and issuer policy. The full isolated package suite passed 64 tests,
including async tests. No deployed key resolver, rotation/revocation,
trusted issuer/receipt policy, or production route is present; this remains
an offline authentication contract and does not change G5 or live status.

An isolated source-only G5 child `c10ccf5f` adds a durable pre-cancel CTP
target projection bound to one I9 reservation, a one-use same-store handle,
and monotonic freshness checks under the staging/claim transactions, including
a final staging check before return. Its full fake suite passed 141 tests with
two skips. A separate parent integration `097a98a7` pins that child and
passed 1039 non-network contract/fake journal
tests with seven skips. The verifier is still injected and has only a
rejecting default; no code-owned native query-to-reservation issuer, trusted
sender, wheel/origin proof, or registered cancel path exists. G5 stays closed.
The main runtime's unregistered query-to-target candidate now derives a
non-authorizing, at-most-two-second order observation from a candidate SDK
`TraderClient.query_orders_result` source and fake native callback. It checks
the current request filter, record digest, TradingDay, connection generation,
and precise remaining order quantity. Nine focused tests pass with the
candidate SDK source; the default installed SDK lacks `order_action` and
query-source filter metadata, so the SDK-dependent test skips there. No I9
issuer-to-durable-store readback or trusted sender is connected, and no
cancel projection or dispatch authority is issued.
ADR-41-17 proposes startup-sealed, immutable CTP run scope with no session
hot reload for the same protected config and shared runner. It is not accepted
or implemented; current action-level config mutation tests remain strict
xfail and P2 stays open.

A separate SDK source-only commit
`decd760012ad77d0c7ddab6400951a28fea16516` adds nested CTP identity
labels to `OrderRequest` and checks managed requests against the mirrored I9
account/day/scope/intent/runtime ID/Ref before journal or fake transport.
Its related contracts passed 403 with two skips; independent fake review
confirmed missing/mismatched mirrors reject and exact mirrors still face the
write gate. The consumer still accepts class-name/module-name spoofed I9
objects, so the mirror is not a trusted authority; this source commit has no
accepted wheel, Feed Gitlink, default route, or provider/native acceptance.
A separate source-only follow-up `5744d3cb98dbbf729078753417a22b6dbfac8cd7`
requires `bt_api_execution==0.2.0` metadata and exact imported I9 classes;
29 independently rerun fake tests show name/module spoofing and absent I9
reject. A temporary-metadata real-I9-source smoke is API/type compatibility,
not installed wheel/RECORD/origin trust or in-process isolation.
Independent review also found no verified forwarding/wire propagation of the
nested field and no I9 cancel-action binding; model serialization tests alone
do not close those paths. An isolated source-only forwarding branch
(`fbd08485` then `121675dbabac20dcaf30c924da827a8e1d182a5a`)
intended to reject CTP make/cancel/cancel-all before client/send and report
those capabilities unavailable; 152 author fake tests and 95 independent
focused tests passed. A later P1 whitespace alias bypass was repaired in
source-only commit `c33ce478a5f2557bdc9fc118cd852e8dcef2c187` with 15
alias negatives and 167 related fake tests. Independent review then found a
broader P1 receiver route bypass: `UNKNOWN___FUTURE` can pass the client
guard and wire to `OrderRouter.handle_command`, which dispatches by command
type to a CTP-configured adapter without checking the command venue. Direct
wire clients can bypass client guards entirely. Source-only commits
`e6cd73bbddf1875a351c8519f15ece4369fa7284` and
`2fec245ec885589edc337efb144ff86a28a8f518` close the observed
declared-scope/default-router bypass: ZMQ writes require explicit matching
exchange/market/account scope, CTP scope is disabled, and direct Router or
embedded Runtime defaults to no writes and rechecks a nonempty scope.
Author tests reported 379 synchronous passes with 18 async skips;
independent exact-commit review passed 132 focused fake tests and found no
new P1 for correctly declared adapter identity. The in-process adapter's
static exchange/account are still self-reported; a CTP-capable custom
adapter falsely reporting SIM can receive SIM-bound writes. Peer/token
authentication and client capability agreement are also absent in this
parent forwarding path. A separate unregistered local
`bt_api_transport_zmq` candidate now authenticates remote Curve clients by
ZAP public-key metadata and checks a server-owned account/strategy/kind ACL;
its 12 local tests do not integrate the gateway. Independent review found
that its grant and `GatewayPrincipal` shapes differ and no strict gateway
command decoder is wired between transport and Router. These
conditional source results are not a trusted provider identity, installed
wheel, working CTP forwarding route, or default route.

A later unregistered gateway/transport candidate has local Curve/ZAP client
key ACLs and a strict parent transport-to-gateway decoder/principal adapter.
The transport suite passed 12 tests; the parent adapter/composition focus
passed 13. The gateway SQLite account writer authority and event cursor
suite passed 69 tests after bounded WAL-lock initialization retry,
database-path identity rechecks, and a same-transaction final action/command
journal identity check. A fake provider's returned `ACKED` payload
remains `RETURNED_UNVERIFIED` in the Router and `UNKNOWN` to the client;
retries do not resubmit. This is a same-database local contract and does
not exclude other hosts or manual CTP clients, prove a common account
snapshot, install production identity/keys, or open the default write route.

The external `backtrader-mcp` candidate worker now fails closed before
approval consumption, payload loading, and process launch because no
code-owned Windows or POSIX OS network isolation backend with descendant
containment is installed. Its CTP/path four-file focus passed 115 tests with
18 isolation-dependent skips (`--no-cov`); this deliberately disables
candidate execution on the current host. Static Windows protected-path
literal checks remain, but dynamic paths and OS network isolation have not
passed AC41-84. The main repository's SimNow signed operational review is
also unregistered: two focused files passed 75 tests. An explicitly injected
local SQLite replay guard now durably claims permit and action keys together,
but injected HMAC policy, UTC and that local ledger supply no real issuer,
protected key, Windows ACL proof, account writer fence or write authorization.
ADR-41-16 remains proposed and `NO_WRITE / LIVE_NO_GO` continues.

`scripts/ctp_i13_source_manifest_candidate.py` creates only a labelled
dirty-tree artifact under `artifacts/` with the 91-file current
`backtrader_runtime` Python inventory minus two code-owned pin modules. Its
fixed output path and reparse checks have eight offline tests; the trusted
runtime manifest remains absent and the I13 pin remains zero, so the parent
launcher rejects. The offline parent launcher now also binds a returned seal
to the preflight source root and ordered standard-library paths before finder
installation or metadata Job setup; failed seal cleanup rejects explicitly,
and the three related fake files passed 42 tests. The external descriptor
source and real Windows Job setup remain
unimplemented. The isolated `bt_api_ctp` Join/Release fail-closed source
candidate is commit `df565f6debef1fccd22fe378a2ccd774b4c61a67` with
31 fake shutdown tests. A separate child source-only synthesis combines the
Feed guard and the complete five-commit Join ancestry at
`9976bcbbbe331ee77e2d90e05da08472259a625a` with 255 affected fake
tests; neither the parent Gitlink nor default runtime points to this synthesis.
There is no native build or real G4 close evidence.

The repaired G1 token/control r2 helper freeze had 60 focused tests and an
independent origin-guarded Windows rerun of 60 tests; root reverified its 73
source artifacts and 85 QA artifacts. Current-process token smoke used only
`TOKEN_QUERY`; a local named-pipe smoke exchanged one synthetic frame. Fake
tests cover bounded SID pointer parsing and requested token access masks, not
real `DuplicateTokenEx` or owner-token transfer. `_OwnerTokenControlServer`
is not yet constructed in the full command path, and the coordinator/worker
and receipt-writer two-Job chain and whole-command deadline remain unproven.
The earlier buffer-lifetime snapshot is withdrawn. Ordinary CTP `preflight`
stays fail-closed; no write or live route is enabled.

The frozen Execution R3r3 cancellation candidate adds a same-transaction
`CancelObservationCommitV1` and lease-checked `read_terminal_cancel_commit`.
Compared with R3r2, only the Store, its public exports and one new test file
changed. In an independent exact-source copy the cancellation focus passed 35
tests and the full package passed 284 with two optional SDK skips; native
imports and direct network attempts were zero. A first full collection failed
because pytest-asyncio was disabled, then passed with the compatible plugin.
The source digest is a normalized local journal fact, not authenticated
provider evidence. Parent fake proof wiring and three main-repository positive
cancellation cases remain outstanding; this does not enable CTP writes.

R3r3 cannot yet be given an installed-wheel acceptance. R3r2 and R3r3 both
declare `bt_api_execution 0.2.0`; keeping that version duplicates distribution
identity, while the frozen parent76 `_execution_session.py` and five main
runtime modules exact-pin `0.2.0` and reject a unique `0.2.1`. The audit was
verified against the exact parent archive because its outer working tree had
changed. A coordinated parent/runtime pin migration and fresh wheel RECORD,
origin and integration checks are required; the R3r3 284-test result is
source-only.

The parent76 fake cancellation-proof issuer r2 snapshot passed 23 author tests
and 28 independent combined tests against the exact frozen Execution R3r3 and
risk sources. Its 15 manifested artifacts and 43 synthetic SQLite QA files
were hash-checked and archived. It derives typed cancel-action proof only
from the lease-checked terminal journal readback; stale leases, changed target
facts and foreign account scopes reject. This applies only to the offline
`SIMULATION_JOURNAL` fake authority. The source digest does not authenticate
a provider, and parent control-release/main bridge wiring remains absent.

The later G1 whole-command supervisor review is archived at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-g1-whole-command-supervisor-no-go-2026-09-27/`.
Independent inert/fake verification passed 65 supervisor tests and one ordinary
CLI fail-closed test. The frozen source packet omitted two directly used helper
files, and the replay needed 105 then-current support files; intermediate
five-timeout runs remain unexplained. Synchronous process creation and cleanup
are not proved to complete within the current whole-command hard deadline.
The proposed prewarmed-service request-only SLA would change that requirement.
G1 remains closed and ordinary CTP `preflight` remains fail-closed.

The controlled G4 CTP wheel rebuild evidence is at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/g4-msvc-pe-timestamp-author-review-2026-09-27/`.
A strict isolated C build produced a native image the same size as the pinned
image, differing at six PE timestamp bytes; reproducible `/Brepro` A/B images
were byte-identical to each other but 512 bytes larger than the pin. The
corrected archive passed independent checksum and link recheck. The exact
pinned wheel has not been rebuilt, so G4, native acceptance, and CTP routes
remain closed. A subsequent inert linker-input audit found no supported MSVC
timestamp setter in the captured command or local `LINK /?`; plain linking
uses the current time, while `/Brepro` changed much more than the timestamp.
The archived study added no new build or native load.

An accidental shared-tree Ruff format on 2026-09-27 affected tests during an
isolated G5 validator task. Recovery preserved the immediate test snapshot,
restored 1,267 formerly clean tracked files, 24 formerly dirty tracked files,
and 67 untracked files from verified pre-incident candidate sources, and
removed three accident-created empty/docs paths. The 31 pre-existing tracked
test diff paths remain. Ruff formatting cannot be uniquely inverted, so the
recovery provenance and residual style-only uncertainty are recorded in
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-test-tree-formatter-incident-recovery-2026-09-27.md`.
Post-recovery scanner/inert-import focus passed 16 tests, and the restored
Store/Runtime baseline passed 2,725 tests with 43 skips, two xfails and zero
failures. A subsequent narrow CTP generic-queue fail-close r3 candidate was
reversed after its main broad run had 13 failures (2,724 passed); the Store
SHA-256 at that rollback checkpoint was `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`.
The failed candidate and raw results are preserved for a compatible revision;
they grant no CTP write route.
An isolated public-Store fake audit also found conditional same-process route
identity bypasses when an injected API advertises CTP under a different Store
provider or mutates its route map after Store construction. Four direct and two
manually completed async fake sink calls were observed in those two cases;
the correctly labelled CTP control made zero calls. No SDK/native/provider
write occurred. See
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-store-write-narrow-fake-bypass-audit-2026-09-27/`.
Neither route metadata nor same-process private attributes are account authority.

The compatible AC41-63 generic CTP SDK queue fail-close r4 is a historical
integration snapshot, not the current Store: it recorded Store SHA-256
`A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE`. It
rejected CTP generic submit/cancel queue and `_invoke_sdk_command` fallback
before SDK writer method lookup, while recovery exits disarmed on early
rejection; `_cancel_managed` remained byte-identical to the A028 baseline.
Independent fake-only QA passed 12 queue-contract, four recovery, three
budget/sink, and ten managed-cancel/forwarding compatibility cases. The Store/
Runtime plus queue-contract run passed 2,740 tests with 43 skips, two xfails,
zero failures and one existing pytest-configuration warning. At that checkpoint
the scanner inventory was `03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456`;
the later CE04 refresh is documented above. See the [historical r4 archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-ctp-generic-queue-failclose-r4-2026-09-27/README.md).

#### Current Store, G1, G5 and AC41-63 checkpoint (2026-09-28)

The current Store is CE04 route-identity R2 (`CE04ECBADDD3D3EA01C707313EA9B144650C47E322D0BDFC915000C0110094CA`). Its [main integration archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-store-api-route-identity-r2-main-2026-09-28/README.md) records a 28-test focus; guarded Store results of 730 passed / 13 skipped / 18 exact optional CTP node IDs deselected; and guarded Runtime results of 2,010 passed / 30 skipped / 14 exact CTP node IDs deselected / 2 xfailed / 0 failures. The first invalid harness result is preserved but excluded. Current official inventory SHA-256 is `A959A3BC6284232EA90191F13ADC71A6931F5DFCBA6DB16E7AC72B1476B9D142`, with 460/460 dispositions still `REVIEW_REQUIRED / NOT_AVAILABLE`; four locator lines changed from 491 to 495 after the CE04 snapshot, the writer-dispositions SHA-256 `B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426` is unchanged, and 15 scanner contracts passed. The custom-API `__getattribute__` residual remains; this conditional guard does not close writers or authorize CTP. `NO_WRITE / LIVE_NO_GO`.

The [G5/V21 offline ActionRef ledger audit r0](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-g5-v21-offline-actionref-ledger-audit-r0-2026-09-28/README.md) passed 10 synthetic tests and independent QA as a local offline projector. It does not establish G5 authority, ledger cutover, native ActionRef floor, an account-wide writer fence, or a write route: `NO_AUTHORITY / NO_CUTOVER / NO_WRITE / LIVE_NO_GO`.

The unregistered G5 managed-action verifier now requires a typed account-wide ActionRef snapshot for CANCEL at both READY claim verification and the final CLAIMED recheck. Its consumer contract checks declared G5/V21 sources, cutover identity/floor stability and in-process epoch/high-water/mapping monotonicity, exact CANCEL payload-to-target binding, mapping uniqueness, counter equality, snapshot freshness, and zero account `UNKNOWN` or unrelated `CLAIMED` allocations. Source digest strings are only format-checked; they are not authenticated, and in-memory monotonic state does not survive restart. There is no trusted snapshot producer or runtime registration; absent producer denies CANCEL. The offline focus exercises fake contract ports only. This does not establish G5 acceptance, trusted floor provenance, writer fencing, provider behavior, or a live route; retain `NO_AUTHORITY / NO_CUTOVER / NO_WRITE / LIVE_NO_GO`.

The [G1 overlapped-I/O custody archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-g1-overlapped-io-custody-main-2026-09-28/README.md) records a local subgate only: main guarded focus 33 passed and adjacent guarded suite 305 passed, with independent QA verdict `GO_LOCAL_SUBGATE`. Strict whole-command G1 remains `NO_GO`, ordinary CTP preflight remains closed, and this gives no live dispatch or write permission.

The AC41-63 007 support module now has three narrow fail-closed retired helpers: `create_live_broker()` (guarded focus 5/5), `add_live_feeds()` (6/6), and `run_cerebro_with_timeout()` (7/7). The [timeout-helper archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-007-timeout-helper-failclose-main-2026-09-28/README.md) records an empty guard and independent archive QA of 27/27 payloads, 28/28 sums, and 20/20 links; README SHA-256 `2024A461449239389571649B4841EE05165DEE567378C3388592FFE635AEB80C`, manifest SHA-256 `4C1CB5995691BB0CF9549950CC420171E4085973496FDDD855F1BEAAB0871DDB`. The integrated `examples/007_ctp/ctp_example_support.py` SHA-256 is `37536B9598E3EE2414DE2AF787EA1E15C8C52E42558E9679107DB4F3F34C273A`; the new timeout test SHA-256 is `C5F88209C110CABB57F71003CFF9B56C0DA4D54DB43B3675ECB7414840DE5EF3`. The prior [Feed archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ac41-63-007-live-feed-helper-failclose-main-2026-09-28/README.md) independently passed 20/20 payloads, 21/21 sums, and 18/18 links; its hashes identify the earlier feed snapshot, not the current support source. These three helpers close only their named entry points. General `Cerebro.run()`, generic Timer use, and public Store/Broker/Feed constructors remain available; overall writer closure is not established. The Feed archive has no separate main-focus exit-code sidecar.

The 013_1/013_2 `ctp_example_support` R4 is integrated with eight legacy-helper fail-close guards. Source SHA-256 values are `560B5D60DF8BFDDDDABDCB8F6EB53468498328FA1E541B5323EBFFA4F968EBAC` and `675A5E3315559C90A1D7E39AC7D3E1ED2F9555E4A27F6C8A9F5DB0D8196D40A9`; the new `tests/unit/test_iteration41_legacy_ctp_support_inert_import.py` SHA-256 is `3832B447E9606BC00D75316B0BCF29FAF87404969B9DAB520784BAE209D45069`. The valid guarded main safety focus is 32 passed / 1 private-config node deselected; isolated candidate guard passed 1 case with an empty guard. Source Ruff still reports four existing `SIM112` findings on unchanged lines. The initial 33-case run read two untracked config files, is marked `INVALID`, and is excluded; its raw log/JUnit are not archived and no private config values are recorded here. The first archive draft was returned because its candidate manifest retained an unqualified 33-pass claim. The corrected [canonical R4 archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ac41-63-013-legacy-ctp-support-r4-main-integration-2026-09-28/README.md) passed independent final QA: 32/32 payloads, 33/33 sums, three local links, and a 34-member CRC-clean evidence ZIP. README SHA-256 `71C09D95BB1C87446DBD4091A795F0D27FF06DBC4C4DB487EE195D3C9CBE9E07`, payload-manifest SHA-256 `E7110B9D59925F553A13F2807983C193131D7C192D3C0946D1FD1CD8E21FB83D`, and sums SHA-256 `6462C1E33946A8ABDF4BBDB5588C4A567815DFF3F3E28CC0D95E48A71CA50E83`. QA marked all nine unqualified 33-pass statements `INVALID / EXCLUDED`; the original 33-run logs, JUnit, and config files are absent. Current official inventory SHA-256 is `A959A3BC6284232EA90191F13ADC71A6931F5DFCBA6DB16E7AC72B1476B9D142`; only four locator lines changed (491→495), checklist SHA-256 `B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426` is unchanged, and the verifier passed 460/460 with 15 scanner contracts. G1, G4, G5, and G6-P blockers remain; `NO_WRITE / LIVE_NO_GO`.

The [hidden-route negative QA](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-hidden-route-negative-qa-2026-09-28/README.md) rejected the isolated Store candidate after a spoofed static snapshot still reached local fake submit/cancel sinks; the main CE04 Store was not changed. [ActorPort r4 exact-binding QA](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-ctp-account-actor-port-r4-exact-binding-independent-qa-2026-09-28/README.md) remains an unintegrated fake-only candidate without G6-P authority. The [registry trust-boundary static review](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/runtime-registry-trust-boundary-static-review-2026-09-28.md) finds `RuntimeRegistry(trusted=True)` is a mutable same-process cooperative assertion. These local findings do not change `NO_WRITE / LIVE_NO_GO`.

The isolated G5/V21 ActionRef cutover validator r1 is archived at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-g5-v21-offline-cutover-validator-r1-2026-09-27/`.
Its exact replay and 28 synthetic tests plus five selected adversarial tests
passed independent QA. It rejects differing state, UNKNOWN, differing supplied
snapshot boundary labels, and malformed objects that would invoke Python
callbacks. The evidence manifest's mistaken r0 commit pointer was corrected
and independently rechecked without changing code or test bytes. The boundary
label and digests remain caller-supplied and unauthenticated; no deployed
exporter, native ActionRef floor, account-wide writer fence or migration
procedure is established. Status is `LOCAL_TYPED_CONTRACT_ONLY / NO_AUTHORITY /
NOT_A_MIGRATION_TOOL / NO_WRITE / LIVE_NO_GO`; it is not integrated into the
runtime.

A static G6-P resource audit at
`docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/g6p-account-actor-resource-discovery-2026-09-27/`
found no trusted, deployed external AccountActor in the reviewed local
repositories. The older `D:/source_code/bt_api_py` gateway can own a CTP client
but its command boundary lacks authenticated account-wide authorization and
durable identity/fencing. The dirty `D:/bt_api_py` checkout has newer
transport/router/execution building blocks, but no accepted CTP provider
composition, sole credential-owning service, cross-host writer fence, or
same-version complete account snapshot. This was source-only review with no
private config, SDK/native, network, or provider contact. G6-P remains blocked;
strict SimNow and production live remain `NO_GO`.

#### SimNow 007 C01 r3 与 G1/G4 来源复核（2026-09-28）

C01 r3 的 17 个目标已主树集成。冻结候选完整套件为 482 passed；主树 `tests/unit/live_certification` 集成后实测 **488 passed、1 个既有 warning**。17 个目标 Ruff 通过，主树集成内容与冻结候选在 CRLF 归一化后逐字一致，`git diff --check` clean。独立 schema QA 对精确 r3 patch 给出 `GO for source-only integration`；独立 alias/session 复核为 197 passed。上述来源级结果不代表 C01 完成。C01 仍为 `INCOMPLETE`：可信 SDK issuer 私有 RequestID ledger verifier 与 baseline/final query receipt path 尚未接通，也没有可认证的 native callback 来源、受信账号 owner 或 provider 证据。逐目录入口复查为 33 个 `BLOCKED` / exit 2，原因均为 `managed_ctp_certification_not_registered`，network/order_write 均为 0，真实 `PASS` 为 0。不得据离线测试声称 33 个真实案例通过。详情增补在 [007 SimNow 33-case acceptance evidence](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-007-simnow-33-case-staging-acceptance-2026-09-28.md)。

独立的 issuer-side RequestID ledger 研究将完整 C01 请求序列按八个 ID 建模：auth、login，以及 baseline/final 各自的 orders、positions、funds 查询。隔离 fake-only 原型的 16 项测试通过，覆盖请求方法映射、ID/回调关联、跨客户端/API、重连、拒绝派发、终态和八 ID 区分。它没有调用真实 native API；fake 可直接调用 Python SPI，因此这些结果只验证本地关联合同，不证明 native/provider callback 来源。该原型没有接入受信 SDK ledger，也没有改变 C01 completion 状态。

新的 G1 whole-command 故障注入审查包含六项 fake 注入：backend 创建、launcher resume、Job termination、句柄释放、control escrow 和回执 `fsync`。本地 6 项测试通过，证明这些同步调用可以在配置 deadline 之后才返回；结论为 `G1_STRICT_WHOLE_COMMAND = NO_GO`。它没有测试真实 Win32 卡顿、CTP、provider 或存储设备故障，也没有开放 preflight。

G4 parent/gateway source pin provenance 审计与独立 QA 均为 `HOLD_PROVENANCE`：兼容 gateway 实现来自本地未跟踪快照，而记录的 upstream gitlink 树不含该实现。独立 QA 确认候选 wheel、安装 RECORD 与 fake consumer 结果内部一致；这不能认证上游来源，也不构成 G4 精确来源/制品准入、native lifecycle、provider 行为或写入授权。

以上为离线或 source-only 证据；保持 `NO_WRITE / LIVE_NO_GO`。

#### G1 request-level offline contracts and Gateway source drafts (2026-09-28)

The owner no longer requires a 0.8-second hard limit for the entire CTP CLI
command. The proposed replacement is a code-bounded request accepted by a
pre-started protected guardian, with a separate client wait and an UNKNOWN
result on missing or late evidence. No such guardian is deployed or registered.
`backtrader_runtime/ctp_guardian_service.py` and
`ctp_guardian_request_journal.py` are unregistered offline contracts for the
fixed read-only `ctp_readonly_preflight` operation and a 300-second server
request budget. They do not provide a Windows service, protected named pipe,
trusted peer identity, bounded native runner, Job supervision, terminal journal
wiring, or CTP provider evidence. Independent local verification passed 39
fake/contract tests with Ruff and Black clean; the ordinary private CTP
`preflight` CLI, all 33 real case entries, and every trading write route remain
closed. G1 remains `NO_GO` until the complete deployed request path and Windows
failure injection are independently accepted.

The Gateway source and MIT license are now on the draft
`cloudQuant/bt_api_gateway` PR #1, and the draft `cloudQuant/bt_api_py` PR #13
pins reviewed base, CTP, and Gateway source commits. These unmerged source
branches resolve the earlier README-only Gateway pointer for review, but do
not establish an authenticated account Actor, native binary provenance,
provider reconciliation, a trusted writer fence, or a managed CTP route.
G4/G6-P and real SimNow certification remain `NO_GO`.

#### 000 three-venue simulation preflights (2026-09-30)

The 000 Binance and OKX suites now have separate read-only direct account
preflight scripts; the 000 SimNow suite has an offline admission preflight.
These scripts do not implement the schema-v2 certification backend or produce
any of the 33 case results. One Binance USD-M demo signed account query returned
HTTP 200 with zero order/cancel requests. OKX still needs an explicit account
region before its signed query. The 000 SimNow suite is not registered and its
preflight stops before private config loading or native import. Focused offline
tests passed 28 Binance, 44 OKX, and 13 SimNow cases. The
33 separate 000 SimNow `run.py --live` entries all returned exit 2 / `BLOCKED`
with `managed_ctp_certification_not_registered`. The
three preflight suites, 000 venue entry-contract suite and explicit-topology
guard suite passed 173 tests in total. Binance/OKX now block every explicitly
selected direct or gateway/ZMQ topology, with any execution/risk/monitor
selection, before credential/backend access because no reviewed route is
registered; omitted topology is stamped `legacy_generic_bridge` in evidence.
This guard is not direct or component route acceptance. Five
optional-component wheels were independently built and installed
in an isolated Python 3.11 consumer with source/RECORD/origin and `pip check`
passing; this is installation-only evidence, not a route acceptance. The
[three-venue Iteration 41 plan](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/000三场所模拟穿透开发与验收.md)
records the distinct 99-case and optional-component acceptance gates. No real
penetration certification case has passed.

#### 000 development candidates and read-only observations (2026-10-01)

The 000 SimNow suite restores the historical typed read-only observation,
decision and completion modules alongside its offline smoke classes. Its 33
public scenario documents live under `case_contracts/`, leaving only the
strategy and runner in each case directory. All live entries still block
before private configuration access. The retained 007 runtime IDs in the
diagnostic scope binder do not register 000 or provide a runner. The restored
legacy `capture_store_snapshot` helper now rejects before touching Store/config.
Frozen full `tests/unit/live_certification` QA passed 828, skipped one Windows
symlink-privilege test, with one existing warning and zero SDK/native/network/
private-config guard attempts across eleven Python processes. This is offline
evidence; SimNow remains `NO_WRITE / LIVE_NO_GO`.

Binance and OKX each have a standalone GET-only `direct_observation.py`.
Binance's second fixed Demo capture accepted seven GETs with zero order/cancel
requests and observed hedge mode; it is limited REST observation, not C01 or
account-wide/atomic proof. OKX has no new provider run pending explicit region.
New private output paths have owner ACL checks; OKX retains private economics
outside Git, while Binance persists redacted counts/shapes/public metadata.

`backtrader_runtime/certification_direct.py`, `certification_binance.py`,
`certification_okx.py`, `certification_components.py` and
`certification_operator_control.py` are unregistered candidates, not default
runtime routes. Direct uses WAL/FULL single-action claims, schema-5 provenance/
economics/position-side binding, independent queries and UNKNOWN freezing.
The fixed Demo LIMIT ports require durable accepted provider-order ACK binding,
exact grants and bounded submit/cleanup windows; neither reads `.env` or changes
account mode. Risk/execution/control
composition currently accepts offline_fake only. Risk+execution cancellation now
binds the pre-cancel fill quantity in immutable SDK intent tags before dispatch;
quantity changes retain UNKNOWN/review across polling order and restart. Terminal
risk release, risk-only cancellation, execution without an admitted gate, live operator
services and complete certification backends remain unavailable.

The gateway SDK has a separate uncommitted dev query-resolution candidate in
`D:/bt_api_py/bt_api/bt_api_gateway`. Its candidate wheel passed 118 installed
SDK tests and six framework tests; three-process TCP/Curve completed fake
submit/query/cancel/query. Original claim history and takeover fencing remain;
the September 30 wheel was not replaced. No real query verifier, provider or
account route was accepted. See the
[current development evidence](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-000-development-2026-10-01.md).
Real penetration certification remains **0/99**; source presence and fake
component tests do not close provider or writer-inventory acceptance.

The final nine-file feature lane passed all 309 tests with unchanged source
manifests. Its strict audit launcher exited 1 for one blocked urllib3 IPv6
loopback capability probe during requests import, before OS execution; it is
not a zero-attempt audit pass. Private-config and provider-native attempts were
zero. See the separate
[feature QA archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/000-certification-feature-offline-qa-2026-10-01/README.md).

### 000 certification entry candidates (2026-10-01 later development)

`certification_binance_cli.py` and `certification_okx_cli.py` are explicit,
standalone bounded Demo LIMIT/query/owned-cancel/query entries, not registered
33-case runners. Default doctor/preview does not load credentials or connect;
OKX doctor reads its bounded private plan only. Execute requires fixed account,
order, budget and absolute grant windows. Any positive fill remains marked for
position review before UNKNOWN/terminal early returns; later zero observations
cannot clear it. No resume, write retry, account-mode change or automatic close
is supplied. The final CLI-plus-independent files passed 69 Binance tests and
55 OKX tests with one Windows symlink-privilege skip. These are offline results.

`certification_okx_setup.py` supplies the missing read-only private account
binding step. Default doctor is zero I/O. Explicit prepare performs five fixed
Demo GETs, constructs credentials only after stable UID/config observations,
stores the real UID only in an owner-protected file, computes the port's scope
and creates a disabled incomplete draft. Its 33 tests plus seven independently
authored tests passed; no real setup request was executed. Shared
`certification_private_artifacts.py` atomically creates new owner-only directories
outside Git, verifies Windows child-inheritance flags and fixed-code path errors,
and exclusively writes JSON. Independent Windows tests checked actual JSON and
SQLite DB/WAL/SHM ACLs; this is storage evidence, not provider authentication.

Binance's portable `_certification/c01_signed_rest.py` is a separate pure C01
evidence-review candidate (139 independently rerun tests). Its successful result
remains `EVIDENCE_READY_FOR_REVIEW / BLOCKED`; legacy entries are unchanged.
The adjacent V2 scope proposal corrects V1's unfiltered whole-product declaration
to explicit instrument/resource/time coverage matching actual provider APIs.
Neither version has a registered real collector or certification PASS route.

The generated `scripts/ctp_i13_i15_readonly_preflight_bootstrap.py` is now
materialized byte-for-byte from its existing generator; all-zero deployment pins
reject before protected deployment reads. New `ctp_td_only_worker.py` composes
the actual read-only factory's seven queries and strict native close contract.
Independent guarded source/fake QA passed 26 tests with zero guard attempts and
SDK imports. The bootstrap still calls the old TD+MD worker; TD-only coordinator
v3 wiring, 000 registration, pins, Job containment and actual native lifecycle
remain unaccepted. The expanded QA preserves a historical raw-hash failure due
solely to worktree CRLF vs HEAD LF; no frozen evidence was rewritten.

The later 14-file custom writer scan reports 51 writer and 14 dynamic candidates,
zero parse errors, `CANDIDATE_DISCOVERY_ONLY / CUSTOM_SCOPE_NOT_CLASSIFIED`; it
does not refresh formal R2 disposition or grant a route. See the
[entry development evidence](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-000-entry-development-2026-10-01.md).
Real certification remains **0/99**, and CTP remains **NO_WRITE / LIVE_NO_GO**.

### 000 C01 source and TD chain (2026-10-01 current development)

The later portable `c01_capture.py` collectors bind explicit signed-REST V2
instrument/resource/history scopes, preserve raw captures and real pagination,
and never grant certification from a serialized source label or local hash.
Binance's V2 pure normalization and both collector adapters passed 82 source
tests with two venue-branch skips. The C01 case entry is being connected through
a separate exact-source-byte loader and current two-process capture custody;
saved-file review remains BLOCKED. This profile does not invent a provider
session or claim a whole-account atomic snapshot or distinct administrative
trust domains. Its trusted launch requires Python `-I -S -B`; Python startup
code from an unisolated interpreter cannot be retroactively removed by a child.

A real Binance BTCUSDT collector invocation obtained only the public time GET
HTTP 200 before a clock check returned BLOCKED. Archive/ACL delay caused the
old comparison against the current time to reject a valid recorded response.
The revised collector checks the recorded request/response interval with the
same two-second tolerance and accepts only one Content-Length with no TE.
Chunked or lengthless responses are explicitly unsupported for that collector.
That source was independently re-reviewed; this observation is not a real C01
PASS or permission to write. Private raw evidence stays outside the repository.

`certification_execution_admission.py` now supplies the optional execution-only
public admission/claim path using direct cumulative budget and immutable SDK
claim readback. The independently rerun 41-test source focus passed; risk=False
does not import risk. Each effect rechecks the original provider and scope;
UNKNOWN, restart and terminal status do not release the cumulative budget.
It still accepts offline_fake only and is not a real or installed-wheel route.
One guard-blocked urllib3 IPv6 loopback bind probe during monitor import is
recorded explicitly; no outbound/provider, native or private-config event ran.

The materialized CTP bootstrap now has the complete source-level coordinator
v3 -> fixed 000 TD-only worker -> strict frame -> receipt writer wiring.
The fixed runtime is `example.000_live_certification.simnow_penetration.ctp_private`
and the strategy is `example.000_live_certification.simnow_penetration`; v2 keeps
the old 013_3 TD+MD path. Direct entry must pass actual bootstrap/source/runtime/
dependency custody before configuration, front probing or SDK access. The
81-test guarded author lane excluded three real-OS tests and one unchanged
historical CRLF/LF evidence-hash failure. Independent frozen QA passed 34 tests
with zero guard attempts; all 12 source hashes matched before and after. The
generated bootstrap is 276,191 bytes. Only its builder cap and two guardian
bootstrap-source checks changed from 256 to 512 KiB; wire/output caps and Job
deadlines did not change. Actual Windows custody, installation pins, native
login/query/close and default registry admission remain separate acceptance.

See the [current development record](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-000-c01-runtime-development-2026-10-01.md)
and [frozen SimNow source QA](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/simnow-000-source-chain-qa-2026-10-01/archive-index.json).

The subsequent actual Windows bounded harness passed seven tests in eight
guarded processes with zero private/SDK/native-CTP/provider/network attempts.
It exercised local query-only token handles, named-pipe EOF/PID and 63 KiB
frames, isolated Python, real Job completion and three timeout/termination/
Job-empty cycles. Process handle count stayed 220 -> 220. This does not test
Session 0, service identity, owner-token transfer, CreateProcessAsUser,
ProgramData receipts or the installed full 000/native chain. See the
[Windows harness archive](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/simnow-windows-bounded-platform-2026-10-01/README.md).

New `certification_close.py` and `certification_binance_close.py` provide a
separate Binance HEDGE LIMIT IOC close candidate with exact typed grants,
owned-opening-fill allocations, cumulative plan budgets, unique dispatch and
ACK, and independent order/trade/position reconciliation. Known execution is
persisted before later reads; UNKNOWN and restart retain its high-water mark.
Contradictions after convergence durably freeze the current state and same-leg
admission while retaining historical convergence and allocations. Source/fake
focus passed 64 tests, and an independent recheck passed four checks. Both live submit and live query remain closed pending actual opening
ownership admission; CONVERGED is not certification PASS. Limit-based SELL
notional is a plan budget, not an upper bound on actual execution economics.

The C01 r5 bootstrap uses the current actual CPython image on Windows to avoid
venv redirector PID mismatches. Ten author checks and eight independent checks
passed in the actual QA venv, retaining strict current PID/nonce/custody checks.
Only Binance is REVIEWED at registry SHA-256
`a34e9b39fdbc0090f1223c7ccb35856c98c738b6e0e4497e64afa1e0d2f79573`;
OKX remains PENDING. The fresh r5 real demo run returned BLOCKED: each of two
collectors completed seven GETs with HTTP 200, then income exceeded five
seconds. Both current children cleaned up completely. An earlier r4 collector
completed all nine GETs in 14.702 seconds but failed the former venv PID binding;
that historical evidence was not promoted. No order/cancel occurred and real
certification remains 0/99. Exact public source snapshots and safe summaries are
linked from the current development record; private bodies remain outside Git.

The later 2026-10-01 C01 r8 checkpoint adds the explicit Binance-only
`C01_SIGNED_REST_V3_READ10` policy; the older V2 remains at five seconds.
READ10 does not change recvWindow5000. Signing occurs after the fixed TLS
connect, within the whole request deadline, and raw evidence binds the actual
unsigned query sent. The r8 real demo attempt completed five GETs with HTTP
200, including signed reads lasting 8.239 and 5.600 seconds, then the sixth
GET exceeded ten seconds. The single owned child cleaned up completely;
the second observation did not start. Historical complete single captures or
saved manifests cannot be promoted into current double-observation PASS.
Real certification is still 0/99. Persistent TLS reuse is a separately reviewed
candidate pending its full current collector/source-closure admission.

The dedicated Binance local-validation profile captures four GETs with fixed
five-second request and thirty-second capture limits. Its complete exchange
metadata accepts bounded, exact Unicode symbol identities without normalization;
the selected USDT perpetual still uses the strict ASCII scope. It measures the
current certification runner's validation gate, not the legacy SDK's global
validator. Both real attempts are BLOCKED; rules or saved files alone grant no
case PASS. A versioned V01/V02/V03 case adapter is separate acceptance work.

The 000 SimNow OS root/SCM source checkpoint passed 208 guarded source tests
and two actual missing-root entry checks returned exit 78 before provider
startup. Its six-test deployment preparation dry-run reported twenty explicit
blockers: this host is unelevated in Session 1, the fixed service and protected
image are absent, and the pinned installed dependency closure is incomplete.
Three located wheel hashes establish candidate identity only. Later installer,
EnvRef-renderer and directory-sentinel changes supersede those frozen source
hashes and need their own review. No service or private config has been created,
and G1/G4/default pins remain closed. Keep NO_WRITE / LIVE_NO_GO.

The 000 Binance suite now has explicit `_validation_cases_v2/` and
`_validation_cases_v3/` portable closures and fixed `run_validation_cases*.py`
entrypoints. These version the V01/V02/V03 contract for the actual certification
runner's read-only dispatch gate; they do not claim the legacy SDK validator or
a persistent REST provider session. V2 has had a real current invocation:
public time returned 200, the following account config timed out, and all three
cases were BLOCKED. Current real status is five BLOCKED cases (Binance
C01/V01/V02/V03 and OKX C01), 94 NOT_RUN and 0/99 PASS. V3's fixed five-second
request/thirty-second capture connection-reuse closure is separate review work.

The r9 real Binance retry scope returned public time 200 and a following
generic network_failed. A later actual-stdlib offline repro found an actor
response-lifecycle bug: fixed-length read1 completion can leave response.fp
open, so the next getresponse raises ResponseNotReady. The historical run did
not record the exception class and is not retrospectively relabelled. r10 must
explicitly close a fully validated response while retaining the connection,
check closure and record only fixed phase/error codes; no retry-policy change
is required. The real OKX global READ5 attempt timed out on public time before
account authentication; no region or key conclusion follows.

`certification_monitor.py` supplies optional local owner/port telemetry using
the actual SDK outbox/consumer/checkpoint APIs. The independently reviewed
18-test source slice checks the original journal at both owner and port entry,
keeps observation read-only and does not load monitor when disabled. Its count
basis is local method entry, not HTTP attempts/native ACKs; missing native/raw
and claim/latch source hooks still block certification. One guard-blocked local
urllib3 IPv6 bind probe was recorded, without outbound provider access.

The fixed 000 deployment tools now include `ctp_000_deployment_cli.py`,
`ctp_000_install_admission.py`, `ctp_000_render_config.py` and an isolated
entrypoint. They implement DemandStart-only SCM creation, durable ownership
journals and identity-bound removal, and explicit process-env versus private
env-file rendering. Three code-owned admission pins remain None. The latest
49-test guarded env-file slice plus exact-source static review does not reuse
older 56/208-test authority acceptance. Actual env-file ACL suitability and
installed/native behavior have not been tested. Explicit profiles include the
lowercase SimNow-account names (canonicalized on Windows) with CTP settings;
there is no automatic selection or fallback to Hongyuan/generic CTP accounts.


### 2026-10-01 C01 explicit network source checkpoint

Both 000 Binance and OKX portable suites now include the byte-identical standard-library-only `c01_http_connect_candidate.py`. Schema-v3 C01 plans default to DIRECT; explicit `HTTP_CONNECT_ENVREF_V1` requires the paired HTTPS_PROXY or HTTP_PROXY envRef, read from the same current credential-file capture. There is no automatic proxy discovery, retry, route fallback, production target or regional switch. CONNECT supports only demo-fapi.binance.com:443 and openapi.okx.com:443, uses bounded HTTP header parsing and verified target TLS before JIT signing. Proxy endpoint fingerprints remain private to current IPC/manifests; public results use only route labels. Original request and capture deadlines remain unchanged. Binance DIRECT keeps its previous connection implementation.

The r11 source closure was independently reviewed: 15 execution sources and four entry bindings matched; final focused runs passed 30 Binance and 13 OKX checks, including inert connections in actual isolated child processes. Author focus counts were 150 and 89, with overlap; these are source tests, not account acceptance. Both registries are REVIEWED at this checkpoint. Request-stage progress is bounded and bound to the current process/request; it does not establish provider receipt. The original `.env` proxy endpoint had no listener during the read-only inventory, and no matching registered proxy client was found in the bounded standard registry search. Portable clients and other paths remain unknown. Real case totals remain 0/99 until a new actual run establishes its own result; this checkpoint does not grant other cases, component routes or CTP writes.


The subsequent current root-owned r11 DIRECT run accepted Binance C01 under the explicitly scoped READ10 profile: two nine-GET captures were complete HTTP 200, both collectors exited normally with verified receipts and cleanup. A new V3 run accepted V01/V02/V03 for the current isolated runner's actual rule gate, using four complete HTTP 200 specification/account reads and normal actor/parent cleanup, with zero provider order/cancel calls. This establishes four versioned READ cases, not the old SDK global validator, remote order rejections, whole-account atomicity, component routes or write authority. Latest real case totals are 4 PASS / 1 BLOCKED / 94 NOT_RUN.

OKX r11 reached a successful signed account-configuration read (API code zero) but rejected the third HTTP 200 instrument response because the reader did not support Transfer-Encoding. Its exact coding and body completeness were not established. OKX r12 now has an independently reviewed bounded framing helper: a single chunked coding with no Content-Length, or one Content-Length with no Transfer-Encoding, is accepted only after strict parsing, original-deadline checks and response/socket close. Other framing is rejected. Its registry is REVIEWED at SHA-256 `e8ef0d44a5f456d696d9c03369b43ddf90a2308bd4acffbd93a3ea613165f562`; Binance and V3 accepted source closures remain frozen. A new root-owned r12 actual attempt failed the first public time GET after 5,010 ms with HTTP status 0 / framing NONE. The child exited 2 with complete cleanup; no authenticated account read or second observation occurred. This does not establish provider chunked behavior. Old failed runs are not upgraded, and totals remain 4/99.

`scripts/ctp_000_paired_front_selector.py` is a credential-free, unregistered
transport diagnostic using the existing paired probe primitive. It ranks intact
MD/TD pairs by both-side success rate, worse-side median and maximum successful
latency, with three samples per side. It does not combine sides across pairs,
load credentials, import an SDK or grant native/provider authority. Author and
independent guarded source tests passed 23 checks. After the user's paired
selection request, root projected only the five existing private config front
fields outside Git and ran a single TCP diagnostic. All five pairs had 0/3 MD
and 0/3 TD success; `NO_CANDIDATE`, no selected index and no login or writes.
The command finished in 6.4 seconds; internal 30-second deadline accounting is
not a hard whole-command supervisor. Current SimNow cases remain 0/33 real
PASS and `NO_WRITE / LIVE_NO_GO`. See the paired-front source/transport archive.

The 000 Binance `_validation_log_v1` bundle and `run_validation_log.py` add an
explicit L04 current-log profile. Its fixed 13-source registry is REVIEWED at
`24bd8a08f6324db6b8d8b4d1e45843d858f6a7e7ac8b46dbe68497ffbcf64662`.
The producer logs one fresh gate evaluation; a separate network/credential/
spawn-denied inspector checks five events and returns facts only, strict=0.
Current parent custody and complete cleanup are required for the case result.
Sixteen author source tests and separate actual Windows pinned-loader synthetic
and fully rehashed adversarial-log checks passed. They do not certify accounts.
The fresh root-owned live read attempt failed the first public request within
5,010 ms; its diagnostic does not identify the startup/IPC/transport stage.
Producer cleanup was complete, actor exit confirmed but normal STOP not proved,
and no inspector or order/cancel call followed. L04 is BLOCKED. Current real
totals are 4 PASS / 2 BLOCKED / 93 NOT_RUN. Frozen C01/V3 sources are unchanged.

The standalone Binance roundtrip r1 source closure is
`7342d5e4df4879d9a5a9ad605dbf0ecb25fd9aad558ff1995f7c258f08ddf76a`.
It has a durable same-user LocalAppData one-shot ledger, exact BTCUSDT
BUY/LONG/GTC plan and 100-USDT order-notional cap, no auto close/retry, separate
ordinary/algo open-order baselines, and official filter checks. Fifty-five
author source tests and independent source/offline review passed. Actual root
preview exited 2 before provider work in 391 ms: credential input accidentally
reused the artifact-output walker, which rejects repository ancestors including
the requested checkout `.env`. A separately reviewed r2 input-path fix is being
prepared; output repository rejection stays enforced. No roundtrip order/cancel
has run. Root backed up the `.env` owner/group/DACL and applied a native
DACL-only owner-protected change after metadata-only verification; no credential
bytes, owner/group/SACL, or file identity were changed. Native ACL verification
and Git-ignore checks pass. The backup is retained privately outside Git.

The 000 renderer now has an explicit eight-EnvRef credential-only profile for
fresh paired-front selection. It admits installation and checks the destination
before probing the exact public projection, consumes a short-lived same-process,
same-thread one-use handoff, then opens the explicit credential source. No
candidate blocks before credentials/config creation. Default profiles remain
available. Ordinary mutation and altered dataclasses.replace cloning are blocked;
this is internal Python API protection, not reflection isolation or native/write
authority. The author 110-test focus and final independent 3/4-test focuses pass
with overlapping tests. The nine-file selected public archive has SHA-256
`3ca0960a53d3ab72c3992aef552425425c549d9e7793e1c021a8fa847cfebc6a`.
It is not a deployment closure. Current pairs remain unreachable; install pins,
service/dependency custody and native lifecycle acceptance remain closed.

A separate root-owned public-only diagnostic made one first-IPv4 connection
attempt to each fixed Binance Demo and OKX global time endpoint. DNS/TCP consumed
most of its eight-second transaction window, and both expired in TLS before any
GET. Both child exits were confirmed without forced termination; no credentials,
account requests or writes occurred. This is not a case result or an explanation
of an earlier actor failure. Actual case totals remain 4 PASS / 2 BLOCKED /
93 NOT_RUN. CTP remains NO_WRITE / LIVE_NO_GO.

The standalone Binance roundtrip r2 input fix received independent source/offline
GO at eight-source digest
`7f6e88ee22816d75c167cab2c14a1c37d01faa584a176fe024071a15aabd6bd6`.
The same 58-test focus passed in author and independent runs; it is not 116 unique
tests. The literal/effective Git-ignore gate holds checked input/policy/tool
handles; artifact-output repository rejection is unchanged. A fresh root preview
passed credential input checks, received complete public time HTTP200/close, then
failed to obtain the specs worker frame: 9,953 ms / exit2 / UNKNOWN. It reached no
authenticated resource and registered no submit/cancel. Later process inventory
found no parent42480 direct children; normal specs cleanup is still unproved.
The exact fourteen-file public snapshot ZIP SHA-256 is
`58c3a048b9aa18348505fadf4661b82cf7127c4ff19ad6d0d255b184db929df7`.
This is no new case PASS and no actual roundtrip acceptance.

The separate OKX V01-V03 source bundle is REVIEWED at registry SHA-256
`96e66f364e6bf45acaa443bab6dd126a6cef3a2956cb17e89ade38add1194dd4` after
independent review of 51 focused tests. It checks documented USDT balance shape,
exact SWAP rules, bounded ticker freshness, local output drives, current actor
PID/nonce/source/STOP/EOF/exit/cleanup and atomic artifacts. Pure or saved facts
remain strict=0; only the current coordinator can issue its scoped result.
Python 3.8 grammar parsing passed, runtime execution on 3.8 was not performed.
The new root-owned live invocation exited2/BLOCKED/actor_request_deadline in
25,406 ms, with one receipt and no verified actor STOP/EOF/exit/cleanup. No body
semantics or authenticated balance acceptance followed, and no order was called.
Later process inventory showed no actor3092 or parent33280 direct child; it is
not a normal-close receipt. V01/V02/V03 are BLOCKED. Latest case totals are
4 PASS / 5 BLOCKED / 90 NOT_RUN, still 4/99.

The public optional wheel consumer r2 archive has 26 metadata/audit/harness
files, ZIP SHA-256
`7fa11763e4fdb906e9c3efba939c676a9b6da006ebec31b2b7c9df3c1e11bd4c`.
A fresh isolated candidate-composite install verified 9,009 RECORD payloads
across 53 distributions and installed SDK/ZMQ origins with clean pip check.
Its runtime closure substitutes only gateway r2. The old same-version gateway
wheel lacks four query-resolution exports; the candidate interface, six local
framework fake/SQLite SDK contracts and 49 fake gateway contracts pass. These
are installed-artifact/source-at-test results, not provider/topology acceptance.
Application-level network/provider/subprocess calls were guarded; environment
setup and tests used processes. Current optional source revisions/R3 producer
still need final review and source allowlists remain empty.

The separate READ8 batch candidate has independent source GO at five-runtime-file
digest `13174c4f8df66ce04cde5ee082158890912b8717cf404f6b0aeda841abc686e1`.
Its parent requires durable capture acknowledgement before the next fixed GET,
with five-second request and thirty-second batch limits, no signed retry, and
socket/STOP/EOF/exit checks. Bounded JSON numeric parsing rejects nonfinite
overflow and nonzero underflow while accepting exact-zero exponent forms.
The same 17-test focus passed in author and independent runs; Python 3.8 grammar
passed without 3.8 runtime execution. The six-member public source archive SHA
is `db3782634945bfb148be6c5b88c4c3eb8f4402ec2b4e7c0c8e3f557361ff2445`.
It is unregistered/source-only and supplies no provider observation or case PASS;
the full standalone R3 integration remains under development.

At 2026-10-01T14:23:54Z, a new root-owned credential-free probe of the identical
five intact MD/TD pairs again found 0/3 successes on both sides of every pair.
It returned NO_CANDIDATE/exit2 in 6,406 ms; no SDK/login/native/subscription or
trading action occurred. The new safe receipt is archived alongside the intact
r1 record. This is transport-only, no new case PASS or CTP gate change.

The later optional consumer 348f source GO was revoked: `_risk_binding` still
imported ambient risk SDK during receipt mint/revalidation before the verified
owner importer. Empty default pins kept live activation closed. Its isolated
installed diagnostics verified 51 wheel URLs, 9,009 RECORD payloads and 115 loaded
SDK/pyzmq origins; tests remained incomplete due to missing R3 Finder and denied
child launches (34/1/1, then 68/1/1 deselected/6 failed). A socket.bind attempt
outside a named test was blocked. The three-file public hash-only diagnostic
records these limits; no source/policy pin promotion or live acceptance followed.
The prior accepted local artifact checks remain their original snapshot, and R4
origin/policy fixes are separate work.

The R3 all-off DIRECT_READ_ONLY_PREVIEW closure `2523beddb205c8ff27f8f4b60558c3daf57ae38f805c55cf2cf24de4771ca169`
has scoped source GO and overlapping 26-test author/reviewer focuses. Its first
root actual invocation returned exit2 in 640 ms, with only private binding.json;
no capture database/response/candidate was established. All nineteen source hashes
still match, so no drift was observed. The generic error needs an inert actual
isolated-Finder initialization reproduction before another live read. No order,
cancel or new certification PASS followed; optional and write scopes remain closed.

R3's duplicate bootstrap/Finder class bug was reproduced with synthetic inputs and
fixed by canonical registration/reuse, retaining strict class and preload checks.
The new direct-read closure is `c8a60ec8b8f0edcc202ce21afb4140a2fcef46193ce3afbbcae43685299ac326`;
author/reviewer 27-test focuses overlap. The next root real preview created its
database but returned UNKNOWN/worker_nonce_binding in 1,156 ms. Eight predeclared
capture rows have zero raw/frame observations; worker9928 diagnostics show kill
sent and wait/EOF completion, without socket-close/normal-exit proof. No candidate
or order/cancel was established. Current nonce-bound error handling is under inert
review; all actual records and old source ZIPs are preserved.

The optional consumer risk-import fix has source-only GO at ten-file digest
`9412f2399821a6f42abbb2e37c218767b971a27a4f353241fa7e8c6e7e45f320`
(76/1 source focus, 13/1 independent focus; hardlink skips). All activation pins
remain empty. Its exact source ZIP is `7eebf3ec4eb1ec9e45c6d237af45581ad7be91ed9c76eb3d73ba2c1d160c9cb7`.
External operator-policy and gateway/monitor candidates are new unregistered work;
installed Finder integration and provider component routes are not accepted.

The separate, unregistered optional-policy v1 loader has source-only review GO
as a non-authorizing typed document loader: 27 focused tests, Ruff and Black pass.
It verifies fixed-volume LocalAppData claim-directory/marker identity and SDK
module-name/PathFinder origin, RECORD and byte pins. Its two-file source closure
is `12c2e6ed7eb33bc628332bb1f10511e9646f13a59ca2963f258b54d508f26b0a`,
archived at ZIP SHA `b673c7cd6e4570e844acaad6992d07322b54af9ba7c31a131a514396874b2404`.
The expected policy digest and finite confirmation must come from the root-reviewed
operator packet; the actual owner still needs exact account/action/plan/receipt
and imported-object bindings. V1 is unwired and excludes gateway/ZMQ, monitor and
all-off selection. A new v2 integration candidate is separate work; legacy pins
remain empty, and this source result establishes no live route or provider PASS.

The later READ8 error/cleanup revision has independent source-only GO at digest
`c52283788d501fbfa93a04fc50004766aebad521ed02de49dc5feaf05c718e67`.
Its nonce-bound post-BOOT FAIL retains PID/source/request checks and fixed redacted
failure codes. `socket_created` and `socket_close_uncertain` distinguish no-socket
DNS failure, confirmed setup-failure closure, and uncertain cleanup; successful
completion still requires all eight persisted/acknowledged captures and clean
socket/STOP/EOF/exit. Independent READ8 focus passed 28; the overlapping author
READ8/R3 focus passed 37. Ruff/Black and Python 3.8 grammar passed, without a 3.8
runtime run. The six-file ZIP SHA is
`77890592f6457f73c7d7052bbed98d9da382d6f62d4820a275d5ab237ab65c3a`.
Root verified its members against current bytes. R3's matching diagnostic-schema
integration is separate review work; no real provider run or case PASS follows
from this source result.

The later R3 direct-only r3 packet has 19-file digest `cac399ac866ca178adadba869cb0f6d0cd1b08b405ae1e842a5f2fe91f70e2dc` and exact 25-member ZIP `72f656c803eb11c3141f7f39419cc392edfc4070966b6f90d3bb9d21e2610fdb`; independent focus passed 39. One root-owned actual preview returned UNKNOWN/worker_failure_connect_network_tcp_failed in 875ms, with eight planned capture rows but zero raw/frame observations, no account baseline/candidate and no order/cancel. Its safe-result SHA is `ad42aaef2266458cf89d7906cf5e04a2f96c7f245eef0e483b2c827ebdb1d7f2`. Root credential-free isolated DNS comparison found Windows env={} fails with gaierror 11003, while only SYSTEMROOT/WINDIR succeeds. The READ8 parent now preserves only those two OS variables on Windows (canonical keys, case-insensitive selection); non-Windows stays empty. Author READ8 focus passed 30; changed files passed Black/Ruff and 3.8 grammar. The new 19-file closure `1e0e57cdd48263a4c642e23f6c9e138251b7dc885a35517620c7dd4de63555f6`, READ8 closure `a630e72c8faaaa6ab0612a7a8b309fe4ddefa18c82e0d0ee04aa5cfbf8ef8e93`, and ZIP `e2419dfe70c969c163ca933dc21e4e90b3d570770f4cc1b2ca0964fde0a646a8` require separate independent review and real preview. Historical archives remain unchanged; these facts add no provider or component PASS.

The minimal Windows-environment 19-file packet `1e0e57cdd48263a4c642e23f6c9e138251b7dc885a35517620c7dd4de63555f6` received direct-only source GO. Its raw four-file focus initially had 39 passes and two stale subprocess digest failures; both literal pins were then refreshed and the unmodified on-disk focus passed 41. The corrected-test 25-member ZIP SHA is `40f59c506f15e3221f6457b73623624e88f4db85fb8903ab4b490807ce1248da`; execution bytes were unchanged. A root-owned actual preview returned UNKNOWN/worker_failure_connect_network_deadline in 6094ms: eight planned rows, zero raw/frame, no baseline/candidate or order/cancel. The authenticated failure has socket-created/close-attempt/closed true and close-uncertain false, but no normal STOP/child exit. Safe-result SHA is `f6db38a455b6b08f0140ae3d27c1608808f6abbe649b55f1f7eefcf695f6dac0`. The current tree subsequently enters separate R4 optional-owner, bounded-phase and case-native-field integration; historical 19-file source QA is not acceptance of those changes. Real case count remains 4/99.


The later V3 operator-control storage source has independent SOURCE_ONLY_GO:
source SHA `b7df12407599afa67c7074486b020bce1037339f8edb44c2b5b5043f35549364`,
test SHA `79a60f7f5c08bf3c7ec2c090bb415498b4aeb3b9e84af5ca0a06bc88a7a4fde5`.
Its isolated focus passed 15 and skipped one unavailable file-symlink fixture.
Windows private-directory ACL, identity, hardlink and active-WAL checks executed;
most owner fixtures are synthetic and do not establish the actual binding factory.
The four-member source ZIP SHA is
`ca30584cae426c8039cfe9c0d5235ab3c5c1984325990ebb66b12b8dc757efd6`.
`guard_for(bound)` shares the exact runtime/account control gate; pause blocks
submit/cancel writes while permitting read reconciliation. Monitor selection
alone does not enable operator controls. R4 provider integration and real cases
remain separate; this adds no provider PASS or native/logout/permission proof.


The later READ8 bounded-phase source has pin-review GO at closure
`fd8f962dc8de93b093818cb3b2975966ded8cbcafdb48fef441bb3dbadb1e3c4`;
independent Windows Python 3.11.5 focus passed 47 (not a 3.8 runtime run).
First connect is 15 seconds, with a post-TLS response ceiling of five seconds
and first total 20 seconds; later requests are five seconds and batch is 60.
Typed progress cannot extend deadlines; eight ACKs and normal close/STOP/EOF/exit
are required. Its source ZIP SHA is
`9fffdd3c75a5ae6a3e52b55be8d21c732c3eefecf48e310c7a6c28a215955164`.
The gateway/monitor storage candidate has independent source/fake loopback GO,
11 tests, and source ZIP SHA
`71aa078d32c057073066d3240f45d3587e3c5a30e81026a326fdecdeaa93f4aa`.
Live factories derive the exact bound private session directory; storage ACL
fixtures are mocked and OS peer authentication remains false. No component
mount or provider acceptance follows from these source results.

The OKX bounded-phase source received 61-test source GO and an exact three-file
registry/loader promotion delta review. Runtime source digest
`b8ccf1a801d72e211e3472c0de12b01434eb8141b7557db65dd254570d48a977`
and final source ZIP SHA
`d4c07fae2174a453c3141e11fe43875fd773f3b97c2582798dfda48690dad4e0`
refer to that historical 2026-10-02 checkpoint. A root actual read at
2026-10-01T21:08:15Z completed three HTTP 200 GETs and normal STOP/EOF/exit/cleanup
in 15,812ms but returned BLOCKED/current_response_validation_failed. Native
account response semantics and V01--V03 were not accepted. Failed raw responses
and a specific typed validation code were not retained by that checkpoint;
protected diagnostic preservation is subsequent work. Safe result SHA is
`3ae378e2a426392fe332e4a42dbf2dfecc8ec8a06fc9d5e4bf0689f40dfa21f2`.
The native portable case contract independently passed 16 tests, but omitted
topology still reached the generic configurable backend and remains live HOLD
pending the fixed owner registry and full account snapshot source. No order or
cancel has occurred; real cases remain 4/99.

The later 2026-10-02 checkpoint supersedes that historical case count. Fresh
OKX r4 V01--V03 current-read/local dispatch-gate acceptance adds three scoped
cases: **7 PASS / 2 BLOCKED / 90 NOT_RUN**, with 99 cases and 16 unaccepted
optional topologies. The r3 tracker JSON is
`08d9dd77fa80f2df7f7dec73e236dfda0d5858e57779d5730304fd2993e65630`.
OKX uses a separate bounded uppercase-ASCII inventory grammar for observed
underscore identifiers; the selected BTC-USDT-SWAP grammar remains strict,
and no inventory rows are dropped. Fresh GET responses, raw custody and
normal actor cleanup were verified. This is not provider order-rejection,
C01 or trading acceptance; older failed runs retain their conclusions.

Binance R4 direct/all-off r6 completed all eight current GETs and the bounded
passive candidate preview after a narrow exact POSITION_RISK_CONTROL/NONE
shape fix. Its 26-file closure is
`23d8ffc14d9c0918518e9978b810e51e7afa5cb57d5a6ed999931b4a90927a9d`.
The local L04 adapter produced facts-only validation evidence, with zero strict
cases; no order/cancel has occurred. Unknown/malformed filters remain closed.
The new SimNow transport selection found pair index 3 reachable (MD/TD each
3/3); this is time-specific TCP evidence only. The separate fixed TD C01
protocol/native adapter/Windows Job supervisor candidate uses auth/login plus
six bounded snapshot queries and explicit native stop receipts. It is being
reviewed and has no real-provider result. CTP writes remain NO_WRITE/LIVE_NO_GO.

The subsequent current 2026-10-02 checkpoint records **8 PASS / 1 BLOCKED /
90 NOT_RUN**. Fresh OKX C01 r13 uses C01_SIGNED_REST_V2, global Demo,
DIRECT and BTC-USDT-SWAP. Its two owned collectors completed 36 GET requests,
confirmed normal cleanup, and matched scoped economic snapshots; root checked
the private owner ACLs, identities and complete raw response hashes. The safe
summary is `bdeff06f18883a48e2e13916d0b70749a71e114a0a66609cd102166a6a54bc8e`.
This is scoped authenticated read acceptance, with no provider-session,
atomic-account-state, trading or optional-topology claim. Saved evidence replay
cannot issue PASS, and historical failed runs remain unchanged. No provider
order/cancel has occurred. Binance's distinct durable client-ID query recovery
and SimNow's fixed native C01 read candidate are still under review.

The immutable r4 99-case tracker JSON is
`9d477645faa38ce58e5ee107364616580bbd4d6f56d9a1750f779f3e60e0b01b`;
its generator pins the exact r3 snapshot and root-reviewed r13 summary and
changes only OKX C01. DIRECT in that record binds the network profile only;
optional components remain UNBOUND and all 16 topologies NOT_ACCEPTED.
Root separately verified the reviewed CLI's actual shared Codex ancestor and
created exact owner-ACL Backtrader/Iteration41 children. That local path check
read no credentials, created no action ledger/marker/policy, made no provider
request and supplied zero case PASS results.

The later 2026-10-02 Binance R9 actual attempt completed eight GETs and normal
actor cleanup, then stopped after its permanent reservation and before command
creation. Root held private file/SQLite custody and verified zero commands,
provider dispatch claims, POST ACKs and recovery-query rows. The original v1
grant remains consumed UNKNOWN, with missing provider ID/fill evidence; it is
not reset, released or retried. This adds no certification or topology PASS.
R10 corrects the exact native Path-type check for WindowsPath while retaining
directory/ACL/SQLite/RUNNING checks. The author module passed 22 tests with one
deselected; independent native-path and complete isolated V2/direct fixtures
each passed one test, separately recorded. The latter used fake READ8 only and
stopped before submit. Its 26-source closure is
`d2419be9ceac47f2070f1b005bc1f74aa26610c9deb320f73f565b03e9ec5b4e`;
the immutable source ZIP is
`6adbb4c458e6a6c16c934cb9ab36e52bf2294948f285e7d100816a1adc530636`.

SimNow C01 native/protocol/contract/supervisor source focus passed 119 offline
tests; root verified 359 installed hashed payload files and 322 Python sources
without importing the SDK. Two actual credential-free Windows Job inert runs
cleaned up normally but blocked before SDK/native import. R2 identified the
native guard's incorrect `_win_amd64` substring check against the actual
`.cp311-win_amd64.pyd` CPython 3.11 Windows suffix. The pre-fix source bundle is
preserved; the new ABI fix requires refreshed reviewed pins. The suite-root
ignored/untracked private config now retains the same five intact MD/TD pairs
and all values as JSON valid YAML, with owner-only ACL and an exact private
backup. A new explicit C01_NATIVE_TD_READ_V1 issuer is being implemented to
select freshly across those pairs and use only five explicit account EnvRefs
from the root .env. The frozen single-env-pair owner remains BLOCKED. No actual
SimNow account request or additional real case PASS has occurred; CTP writes
remain NO_WRITE/LIVE_NO_GO. Gateway/monitor's three independent Windows ACL,
SQLite and loopback tests passed with a synthetic provider and stubbed lineage;
all 16 real optional topologies remain NOT_ACCEPTED. The current real case
tracker remains 8 PASS / 1 BLOCKED / 90 NOT_RUN.

The later R11 Binance replacement-grant candidate is HOLD: independent source
review found that the legacy direct optional_policy=None path accepted arbitrary
syntactically valid authorization references at Plan/ledger reservation. Its
source closure and tests are preserved in a separate immutable archive. R12
restricts Plan, initialization and reservation to the exact V1/V2 set and
requires the typed verified optional policy for live V2. Its source-only focus
passed 127 tests with one clean-consumer test deselected; independent six-file
review passed 68 with one deselected and gave source-scope GO. These overlapping
suites are not additive. Neither revision creates authorization or changes the spent
real V1 UNKNOWN row.

SimNow's exact ABI fix passed independent source QA. A third actual inert run
passed SDK RECORD/import-path/ABI checks, then blocked at native_import_failed
with normal Job cleanup and zero client/request operations. A separate fixed
`backtrader_runtime/certification_simnow_c01_dependencies_v1.json` now records
seven Python dependency RECORD pins and selected package roots; setup.py ships
this public manifest as package data. Root checked 148 hashed dependency payloads
and 106 Python sources without importing them. The dependency verifier/finder
candidate passed 121 fake-only tests: source .py files are compiled from verified
bytes, canonical cache rows and two exact unused console rows are excluded, and
optional dependency native payloads remain unavailable to imports. This is not
an accepted native load or provider session.

The 000 SimNow C01 case now has an explicit source-bound
`--live --profile C01_NATIVE_TD_READ_V1` entry. It reads five pairs from the held
private suite config, selects one fresh intact pair, uses the five fixed .env
account EnvRefs, and runs only TD auth/login plus six account queries under the
Windows Job. Its current issuer recomputes private snapshot/receipt validation;
the private audit v2 retains full typed worker/lifecycle facts and cannot save a
PASS claim. Eight source/fake tests passed; final independent entry review and
actual native/account acceptance remain separate. Ordinary --live is still
closed and this profile grants no CTP order/cancel permission.

The actual credential-free R4 dependency check still blocked; R5's fixed enum
diagnostic identified `urllib3_six_moves` with normal Job cleanup and zero client
or request operations. urllib3's verified vendored six.py creates virtual
modules dynamically, so those require a narrow source-bound loader rule rather
than ambient PathFinder access. The frozen C01 entry/audit v2 independently
passed eight fake tests and source review, but its R4 worker has not passed the
actual inert import gate and no account-profile invocation has occurred.

The later R6b native/owner/inert focus passed 126 fake tests and the updated
entry pin chain passed eight. Its actual credential-free import still returned
`native_import_failed`, with normal Job cleanup and zero client/request
operations. The old 23-member source closure is archived. Exact public six.py
producer semantics require relative `_get_module` names and distinguish the
virtual urllib and parse objects from physical stdlib modules. A byte-identical
public source fixture, retaining its MIT license, is at
`tests/fixtures/iteration41/urllib3_six_source.py.txt`; its SHA-256 is
`6fd2ccd30057bfb13b4ab6c28c09b8c3037e86b1fe88dc6fd7c2e058d30c28fa`.
This fixture supports source-producer checks and provides no SDK/native,
account, trading, or case acceptance by itself.

The later R7 source/entry checks passed 124/8 overlapping fake tests, but its
actual inert import still failed. R8b adds closed exception categories and
hash-bound public relative source locations, and quarantines unknown success
metadata fields before public output; its author and independent focuses each
passed 19 tests. The actual R8b Job run failed with FileNotFoundError at verified
certifi/core.py line 41, with normal process cleanup and zero clients/requests.
The CA payload is already verified by the dependency RECORD; a narrow verified
resource-reader correction is in development. This remains zero real SimNow
case passes and grants no CTP write authority.

Binance's new T01 REST current-account/bounded-income-window candidate is in
`_certification/t01_owned_order_window_v1.py`. Its R3 source focus passed
29 tests with 29 expected venue skips, and the separate R2 collector focus
passed 16. These are source-only results; the current-owner integration remains
in development, the candidate cannot issue PASS, and the consumed real V1
UNKNOWN grant is unchanged. The new unregistered
`certification_monitor_read_case_candidate_v1.py` screens six monitor read-case
envelopes in fake-only mode and always returns BLOCKED; its 20 tests do not
establish a live monitor fact source, independent attestation, provider-session
mapping, or threshold configuration. Real counts remain 8/99 and all 16 optional
component combinations remain NOT_ACCEPTED.

At the later 2026-10-02 checkpoint, SimNow's R9 verified resource-reader focus
passed 128 overlapping source tests. Its inert child still carried an old
adapter hash; the next R9b fixed-pin focus passed 20. The actual R9b credential-
free SDK/native metadata run completed in 3,047ms with normal Windows Job
cleanup and zero clients/requests. This is import metadata acceptance only.
The C01 `C01_NATIVE_TD_READ_V1` profile was then attempted and blocked before
native worker evidence or account snapshots. A separate transport-only
diagnostic returned `no_current_transport_candidate`; the profile's nested
context managers masked that downstream error as a credential-source failure.
The R11 propagation correction separates resource-read failures from yield-body
failures and retains normal-exit ACL/directory checks. Its 13-test independent
focus passed. The latest real C01 run returned `fresh_pair_selection_unavailable`
in 6,922ms before native worker receipts or account snapshots. Its provider
operation counter was not observed. Real SimNow C01 remains BLOCKED. The final
r6 tracker is 9 PASS / 1 BLOCKED / 89 NOT_RUN: Binance 5/0/28, OKX 4/0/29,
SimNow 0/1/32. All 16 optional combinations remain NOT_ACCEPTED, and route/
component bindings remain UNBOUND. CTP writes remain NO_WRITE / LIVE_NO_GO.

Binance's R13 current-owner candidate now uses four sealed case modules under
`backtrader_runtime._binance_t01_case_contract`, the PRECLAIM REST window,
immutable native journal captures, one typed V2 direct owner, and the actual
terminal claim row. Its 34-source closure and overlapping 140-test/5-scenario
reviews are archived under `binance-t01-current-owner-r13-source-2026-10-02`.
The candidate remains BLOCKED; a current typed parent issuer is separate work.
OKX's T01 worker R2 passed 77 source tests after binding cancellation to its
own submit and independent reader invocation. Its stable durable journal and
current parent admission are separate work. Neither path adds a real T01 PASS
or creates a replacement grant.

The new Binance `_validation_log_v2` closure and `run_validation_log_v2.py`
use a Windows Job for the producer and networkless inspector. The original
handle-close/setup-deadline HOLD snapshot is preserved; the revised independent
24-test focus passed and the registry was mechanically promoted to REVIEWED.
The real V2 read run completed four HTTP 200 GETs in 4,469ms, with five validation
log events, one local validation, zero dispatch boundaries, and normal producer/
inspector/HTTP actor/parent Job closure. L04 is PASS only for this fresh local
logged gate instance; it does not prove a remote rejection, global SDK validator
count, provider session, or optional topology. The fixed case entry supports
the explicit V2 profile before ambient imports; its independent 29-test focus
passed. A new actual invocation through `cases/L04/run.py` completed in 5,078ms,
with four complete GETs and the same scoped log/normal-close facts independently
rechecked by root. It is the same L04 case, not a tenth PASS.

The separate Binance T01 parent issuer can return only BLOCKED or an ephemeral
same-session typed proof. R14's descriptor-reader HOLD is archived; R15 now
verifies the child ACL and handle facts under a protected lease through parsing,
then reopens the fixed pathname to verify identity. Its 10-test independent
focus passed and its 38-member source archive is frozen. Actual KnownFolder
descriptor production remains separate. The current owner proof lacks the
generic T01 case's distinct attested event source and full before-cleanup
account snapshot; a fixed execution entry must not upgrade these narrower
facts to a 99-case PASS. The old V1 consumed UNKNOWN grant is immutable, and no
real V2 grant or claim has been created. OKX's new current issuer is fake-only pending
trusted admission: the R2 candidate rejects live source-pinned executors before
collector creation and refuses database reconstruction after a persistent
bootstrap marker. Independent R2 review then found zero-byte database replacement
could still recreate schema. The R3 correction restricts initialization to the
same constructor's exclusive marker-plus-database bootstrap; its 19-test source/
fake focus passed independent review. Empty/schema-less reopen cannot reserve
again, and real dispatch remains unavailable. Neither T01 path has a real PASS
or account write.

At the later 2026-10-02 checkpoint, the fixed `cases/L04/run.py` Binance entry
completed one root-owned V2 validation-log run in 5,078ms. It is the same L04
case as the earlier V2 read, so it adds no case count; at that checkpoint the
r6 tracker was 9 PASS / 1 BLOCKED / 89 NOT_RUN, with all 16 optional combinations
NOT_ACCEPTED. SimNow C01 R11 remains BLOCKED at
`fresh_pair_selection_unavailable`; its provider operation counter was not
observed. Binance R15 parent-issuer source review is GO, while the 39-source
R16 execution closure and its fixed entry remain under independent review, with
no actual invocation or V2 grant. The first OKX auxiliary read attempt's
`public_preflight_validation_blocked` reason had no verified underlying error.
The newer public-only R2 attempt completed three HTTP 200 captures in 2,562ms,
then blocked at `ticker_market_invalid`; it did not derive intent, load
credentials, or issue an order/cancel, and adds no case PASS. OKX R5's
isolated-module framing HOLD is preserved; R6's Content-Length/chunked framing
correction received independent 30-test source GO, while R7 is correcting the
overstrict ticker check. No R7
actual auxiliary run or case acceptance exists. These statuses do not add
account-route or optional topology acceptance.

At the r7 checkpoint on 2026-10-02, the tracker was **9 PASS / 1 BLOCKED / 89 NOT_RUN**
with 16 optional topologies `NOT_ACCEPTED`. Binance L04 remains one scoped
local-gate PASS. SimNow C01 R12 is BLOCKED at
`fresh_pair_selection_unavailable` after 6,265ms; no valid current selection
was obtained, and the reason subtype was not recorded, so this does not show
that all five pairs were unreachable. No native worker receipt or account
snapshots exist, and the provider operation counter is unobserved.
Binance R16 retained eight complete HTTP 200 read captures but ended UNKNOWN;
its legacy L04 owner-slot diagnostic is 18 expected versus 24 current, while
the T01 case remains NOT_RUN. OKX R3 validated three Demo-marked public
metadata GETs in 1,656ms; no credentials, SDK, intent or writes were used, and
T01 remains NOT_RUN. These reads add no case PASS or optional-topology binding.
See the [r7 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r7-2026-10-02.md).

At the 2026-10-02 r8 checkpoint, the tracker was **9 PASS / 1 BLOCKED / 89 NOT_RUN**
with 16 optional topologies `NOT_ACCEPTED`. Binance R17 was a complete
read-only preview diagnostic (8 HTTP 200 GETs, 3,437ms, normal read cleanup),
but Binance T01 remains `NOT_RUN` with zero strict cases. SimNow C01 R13 is
`BLOCKED` (`worker_process_incomplete`, 6,328ms); root verification found
`AUDIT_PROCESS_MISBINDING` between launch PID 34,452 and audited case PID
37,460. A pair index was selected, but the worker exited 2 and was force-killed;
no worker receipt or account snapshots exist, and the provider operation
counter is unobserved. No normal containment or verified PID binding is claimed.
OKX R3 remains public metadata context only. The installed-risk-SDK consumer
test passed one import/RECORD gate, which grants no route, case, topology, or
release acceptance. The WebSocket observer remains HOLD, and the current
control inventory does not prove a deployed principal or receipt. See the
[r8 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r8-2026-10-02.md).

At the current r9 checkpoint on 2026-10-02, the 99-case tracker remains
**9 PASS / 1 BLOCKED / 89 NOT_RUN**; all 16 optional topologies remain
`NOT_ACCEPTED`. Binance T01 remains `NOT_RUN`: observer V2 R2 saw a bounded
ready/quiet read-only stream with zero events and normal local cleanup, but it
was not a T01 case execution; the fixed controller/read closure is on
`HOLD_SOURCE` because the active R3 source map rejects its four new module
names and synthetic `__file__` roots do not resolve. SimNow C01 R15 attempt 2
is `BLOCKED` at `native_close_unknown`
after 95,297ms and forced termination. Pair index 3 was selected, but no worker
receipt survived and provider auth/login/query progress is unobserved. The
separate credential-free TCP probe is transport-only. Gateway installed
consumer R4 is `BLOCKED` at `verified_import_gate` on `_uuid` from
`BASE_RUNTIME_DLLS`; the narrow source correction and independent review are
pending. The optional source-registry R2 review is source-candidate-only and
does not admit a route or case. See the [r9 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r9-2026-10-02.md).

At the current r10 checkpoint through 2026-10-02 12:09:29 UTC, the three-venue
tracker remains **9 PASS / 1 BLOCKED / 89 NOT_RUN**, with 16 optional
topologies `NOT_ACCEPTED`. This checkpoint adds no write, account-native, or
optional route/component binding; the existing per-case `DIRECT`/`OFF` labels
are preserved. SimNow
C01 R17 is `BLOCKED` at `native_close_unknown` after 95,579ms; its durable
progress ends at `client_start/begin`, with no final worker receipt or account
snapshots, and auth/login/query progress unobserved. A separate TCP R2 probe
observed pair 3 at MD 3/3 and TD 2/3 at its own time only. Gateway installed
consumer R8 remains blocked on unresolved `org` during the bounded optional
import gate; zero provider requests, state constructors, and case passes were
recorded. The optional Windows stdlib review is source-only, and the OKX T01
observer remains `HOLD_SOURCE` / `DISABLED`. See the [r10 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r10-2026-10-02.md).

At the historical r11 checkpoint through 2026-10-02 13:57:28 UTC, the tracker was
**9 PASS / 1 BLOCKED / 89 NOT_RUN**, with 16 optional topologies
`NOT_ACCEPTED`. Binance T01 remains `NOT_RUN`; independent profile review R1
is `HOLD_SOURCE_ONLY` for server-clock query-window bounds and a legacy V2
pre-claim bypass. SimNow C01 R19 is `BLOCKED` at `native_close_unknown`; the
final worker receipt and actual provider request counters are unavailable.
OKX T01 remains `NOT_RUN`: the R7 WebSocket attempt acknowledged login but the
first subscription failed with `60033 Parameter id error`; READY, root replay,
protocol drain and successful observer close were not verified. The root
observed Job and handle cleanup, with zero order/cancel attempts and no case
PASS. No new write, account-native, or optional route/component binding was
added, and existing per-case route labels are preserved. See the [r11
tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r11-2026-10-02.md).

The R12 three-venue tracker is a historical cutoff snapshot through
`2026-10-02T18:25:38Z`: **9 PASS / 1 BLOCKED / 89 NOT_RUN** across 99 unique
cases; Binance 5/0/28, OKX 4/0/29, SimNow 0/1/32. No new unique PASS was
added, and all 16 optional topologies remain `NOT_ACCEPTED`. Existing case
statuses and route bindings were preserved, including SimNow C01's `UNBOUND`
route. The [R12 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r12-2026-10-02.md)
has JSON SHA-256 `174759dfea66d026cfecb202611aa7a78fe600fe7818cd9c6e8055e52533eb0c`,
Markdown SHA-256 `0662c45e5a254ca44c686a6774f2d9caeb1d8c22b119e058200bcf9821eb87c`,
and generator SHA-256 `472f95bab54f72516d44bd18d31867720e95776f5d3cfc5a00bd11797363bb1d`.
The R11 JSON and Markdown remain byte-identical.

At that cutoff, SimNow C01 R20 was blocked at `native_close_unknown` after
98,094ms (exit 2). The 11-record issuer projection failed root validation;
root validation matched a 12-record typed/durable prefix ending at
`client_start_native_module_check/begin`. Forced Job cleanup reached active
count zero with EOF and closed handles, but no final worker receipt or provider
counters were observed. R21 was a source/fake-only 20-source correction; its
pre-cutoff README reported 247 focused checks, with independent review pending
and no native C01/inert-harness execution. The frozen ZIP SHA-256 is
`daa12c7a81bb2fd6ce89139cbd801ad3a47cc041ce286caf50e873ec06e7f3e8`. Its
README/index/checkpoint were edited in place after cutoff; the original bytes
could not be recovered from Git or the ZIP. R12 keeps their captured pre-cutoff
hashes under metadata-integrity `HOLD` and excludes later metadata/review state.

OKX T01 remained `NOT_RUN`: R11 reached READY, replayed six journal events and
matched one data UID to REST, then failed quietness; R12 reached READY and
replayed five events but received no data UID before `quiet_ack_deadline`.
Root-replayed R12 terminal detail reports `partial_websocket_frame`; the socket
closed, but normal WebSocket close and control-thread join were not verified.
Forced Job termination left active count zero and handles closed. Both runs had
zero order/cancel attempts and added zero case passes. Binance T01 remained
`NOT_RUN` with R1 `HOLD_SOURCE_ONLY` and R2 ongoing. Optional16 interop R1 timed
out without a final child receipt or observable cleanup; R2 was held for
source/report consistency; R3 had eight source/fake checks and independent
review pending. The composition source/test candidate had no immutable author
result packet and remained unregistered. No optional topology was admitted.
These are historical public-evidence findings; R12 did not inspect private
configuration or `.env`, import SDK/provider modules, or make network calls.

The R16 three-venue tracker is a fixed-cutoff snapshot through
`2026-10-03T02:00:24Z`: **9 PASS / 4 BLOCKED / 86 NOT_RUN** across 99 unique
cases (Binance 5/0/28, OKX 4/3/26, SimNow 0/1/32). It adds zero unique PASS;
all 16 optional topologies remain `NOT_ACCEPTED`. Only OKX L03 and L04 change
from `NOT_RUN` to `BLOCKED` on one fixed read-only CLI attempt each, both
`readonly_lease_verification`; order and cancel caps are zero. The L03
posthoc read confirms an existing complete GET capture and decodable log but
finds missing reopened-store digest attributes. Static `_l03` access to those
attributes is a source defect after the reads, but does not prove the complete
actual failure path; L04's phase is unknown. The separate inert Windows Job
probe is credential-free and makes no provider call. SimNow C01 remains
`BLOCKED / UNBOUND`; its V2 R1 source/fake packet is independently held for
unbound SDK `QueryResult` provenance/records. OKX M01 remains BLOCKED; V4 is
held for missing PyYAML RECORD/module-origin closure. Binance T01 R2 amendment
review verifies package integrity only. Optional16 R11 actual import-only
diagnostic timed out after 122,922ms; cleanup for the direct child completed,
but there is no final child JSON, constructor success, provider session, case
PASS or accepted topology. The [R16 final tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r16-final-2026-10-03.md)
has JSON SHA-256 `622e4c73ce41da6425558f9cb01605935229efbc446a5f62a3406e00f494d90d`,
Markdown SHA-256 `bb79b4a422314ebac158c270b3273c3174d0492403da3da0d5c5e5e24803ae95`,
and generator SHA-256 `01c58ae613c89f05f52c006960bd9d3c14c54b67dbac700eb80075bb96518208`. R15 remains
byte-identical at JSON `766255c31a290f4e481d6a6c108edd88b7df48617e893f193ad8399d5971093c`
and Markdown `2544bf83f02d8d214aa6f2cccebc70ff38437e0490c234f6baeaf2b2d622cdda`.
The [R16 draft erratum](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r16-draft-erratum-2026-10-03.md)
records a corrected initial JSON association; generic `r16` filenames are retained as non-authoritative drafts. R16 final directly verifies all 291 unique public evidence paths against their
SHA-256 pins; the generator reads public pinned evidence only and makes no
private-config, `.env`, SDK/provider import, or network calls.

The R15 three-venue tracker is a fixed-cutoff snapshot through
`2026-10-03T00:59:42Z`: **9 PASS / 2 BLOCKED / 88 NOT_RUN** across 99 unique
cases (Binance 5/0/28, OKX 4/1/28, SimNow 0/1/32). It adds zero unique PASS;
all 16 optional topologies remain `NOT_ACCEPTED`. Only OKX M01 changes from
`NOT_RUN` to `BLOCKED`, bound to one fixed case CLI result that lacks current
read proof; its earlier registration correction is source-pin-only and grants
no runtime admission. No route or optional-component binding changes. SimNow
C01 remains `BLOCKED / UNBOUND`; its V2 R6 result has no current worker receipt
and leaves request/callback/order/cancel counts unobserved. Optional interop R10
source/fake reviews are `GO_SOURCE_FAKE_ONLY`; the actual import-only R10 run
is `BLOCKED` with an unsafe child result and exact Windows access-violation
exit `0xC0000005`. The child was reaped and output pipes drained/closed. No
provider session, registry admission, constructor success, or case PASS was
established; sanitized fatal-only follow-up does not establish module origin
or root cause. The [R15 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r15-2026-10-03.md)
has JSON SHA-256 `766255c31a290f4e481d6a6c108edd88b7df48617e893f193ad8399d5971093c`,
Markdown SHA-256 `2544bf83f02d8d214aa6f2cccebc70ff38437e0490c234f6baeaf2b2d622cdda`,
and generator SHA-256 `52d91c2ee26ce526c42b38df8b5bdb63a2c5571afa64f270e6763a02fb6a80a4`.
R11–R14 tracker files remain byte-identical. R15 canonicalizes R14's 130 repeated
`docs/` evidence prefixes and verifies all 231 serialized public evidence paths
resolve and match their SHA-256 pins. Its generator reads only pinned public
source/evidence; it does not read private configuration or `.env`, import
SDK/provider modules, or make network calls.

The R14 three-venue tracker is a fixed-cutoff snapshot through
`2026-10-02T23:16:21Z`: **9 PASS / 1 BLOCKED / 89 NOT_RUN** across 99 unique
cases (Binance 5/0/28, OKX 4/0/29, SimNow 0/1/32). No unique PASS was added;
all 16 optional topologies remain `NOT_ACCEPTED`. Case status, case-evidence
IDs, route bindings, and optional-component bindings remain identical to R13,
including Binance C01 `DIRECT` and SimNow C01 `BLOCKED` / `UNBOUND`. See the
[R14 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r14-2026-10-03.md).
Its JSON SHA-256 is `68917e7eade8f2be1cd6f955cc33807507c625136807dc3d291ecb0177770cd6`,
Markdown SHA-256 is `e58315fed14c5310da85588169addee3b899d2910c3d89cc217617d6f7c15b48`,
and generator SHA-256 is `194dbb8fc1344f80ec4b9c4892844d9bad7ff799adf60a80a8c41ea0c5af4eb4`.
R11, R12, and R13 tracker files remain byte-identical.

SimNow C01 continues to bind the R20 `native_close_unknown` result. A separate
R3 root-wrapper actual invocation ran once for 22,063ms and returned
`candidate_internal_error`; retry was false, and worker/request/callback/order/
cancel counts remain unobserved without current worker proof. A public audit
verified the protected registration and consumed claim but found no current
worker proof. Static source order shows the wrapper permits only the `.env`
Git check while the candidate checks its fixed `config.yaml` before the
credential lease. This is a static failure explanation, not a measured
worker-zero result. Binance T01 remains `NOT_RUN`: R5's protected read-only
audit records eight completed GETs and no orders/cancels, but the stream
snapshot has one journal entry and zero events; R2 stopped before observer
startup, while R3 drained normally with zero baseline GETs/events and remains
diagnostic only. Optional16 remains 0/16 accepted. R6/R7 SDK import attempts
did not establish a constructor or provider session; R8 review is held for
unbounded pre-persistence child capture; R9 is frozen source/fake only with
review pending and no actual child/SDK run. M01 readonly-monitor V3 has
source/fake-only GO and no runtime/provider admission. R14 reads pinned public
evidence only; it does not read private configuration or `.env`, import
SDK/provider modules, or make network calls.

The R13 three-venue tracker is a fixed-cutoff snapshot through
`2026-10-02T19:35:24Z`: **9 PASS / 1 BLOCKED / 89 NOT_RUN** across 99 unique
cases (Binance 5/0/28, OKX 4/0/29, SimNow 0/1/32). No unique PASS was added;
all 16 optional topologies remain `NOT_ACCEPTED`. Case status, case-evidence
IDs, route bindings, and optional-component bindings are copied unchanged from
R12, including Binance C01 `DIRECT` and SimNow C01 `BLOCKED` / `UNBOUND`. See
the [R13 tracker](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r13-2026-10-03.md).
Its JSON SHA-256 is `541d2e7980241b4ca7cf45034de968328ff3cd5c63c1471161000ce49f12af66`,
Markdown SHA-256 is `87a6a4dc6fcf9c011a469bb9e791320624ae46c11c94c323193778eab2dc7015`,
and generator SHA-256 is `4d926576a3a6a21c139da7c39def9aa09b53b91d4fcb89338115dff58265bbd2`.
R11 and R12 trackers remain byte-identical.

OKX T01 remains `NOT_RUN`. R17's read-only WebSocket diagnostic reached READY,
quiet, drain, complete six-event journal replay, one matching UID frame, and
normal close; the Windows Job was assigned before resume and the process exited
0 with active count zero, EOF, and closed handles. It made zero order/cancel
attempts and added zero case passes. The R13 transport fixture review (58
passed, 1 skipped) and R17 fixed Git/Python/shell launch-audit review are
`GO_SOURCE_FAKE_ONLY`; neither admits a route or accepts T01. The earlier R15
stub stopped at Git audit before provider launch.

SimNow C01 remains blocked on R20's `native_close_unknown` attempt with the
same direct evidence ID and `UNBOUND` route. The R21 schema replay validates
the 12-record typed/durable R20 prefix while leaving the invalid 11-record
issuer projection, absent worker receipt, and unobserved provider counters
explicit. R21's independent `GO_SOURCE_FAKE_ONLY` is limited to its pinned ZIP
and fake source slice (247 passed); it adds no SDK/native/account/provider/C01
acceptance. The public metadata-drift amendment says its pointers were added
after that review and records `2026-10-02T18:37:14Z`; review-before-that-time
is an inference from the amendment, not filesystem mtime. R12's original
README/index/checkpoint pins remain under `HOLD`; later bytes do not replace
them. A separate credential-free native getter diagnostic ended with
`worker_frame_invalid`, no final worker receipt, and `NOT_A_CASE_RESULT`, so
it does not unblock C01.

Binance T01 remains `NOT_RUN`: the independent R2 source review is
`HOLD_SOURCE_BOUNDARY`, and the R3 39-base/49-combined frozen source profile
remains source-only with its combined review pending at cutoff. The R3 scope
addendum defines one fixed listenKey POST, no PUT/DELETE, and separate order
submit POST/cancel DELETE. Optional16 interop R4 is blocked at
`installed_public_record_closure`; it created no provider session and admitted
no case. Its separate R3 cleanup summary reports 4,473 observed handles, zero
exit waits outstanding, and 395 denied Job assignments, but does not prove
that every process was contained. Composition V2 remains held; V3 is an
unregistered fake/source candidate with independent review pending.

At the R13 cutoff, OKX L03 had source/fake-only GO but no runtime admission;
L04 remained an unadmitted 33-test source candidate with review pending. M01
had no immutable source archive, SimNow R22 source was still being written,
and optional interop R5 remained an un-frozen source draft without an actual
run. None changes case counts or the 16-topology acceptance state. The R13
generator consumes the pinned R12 tracker and public evidence only; it does
not inspect `.env`/private configuration, import SDK/provider modules, or make
network requests. Evidence after the fixed cutoff is excluded.

R17 was the fixed authoritative snapshot at
`2026-10-03T08:45:39Z`. Its final [JSON](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r17-final-2026-10-03.json), [Markdown](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r17-final-2026-10-03.md), and [generator](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/generate_iteration41_three_venue_99case_tracking_r17_final.py) are additive; R16 and earlier snapshots remain immutable. R17 contains **9 PASS / 4 BLOCKED / 86 NOT_RUN**, zero new unique PASS, and **0/16 optional topologies accepted**. All 99 case rows, their evidence bindings, the direct Binance/OKX C01 route bindings, and the unbound SimNow C01 route remain unchanged from R16. The generator verifies 461 unique public evidence paths and hashes, including 170 new non-case context references.

R17 final JSON/Markdown/generator SHA-256 values are `9305970fe6092169ccfe683be6bfce81c665e0fb84da2b57194f02f3b2ffedb7`, `fd6505b8d5a1238b1c8e8b4d9759b015bf0536319a53fffb99bd90f56e59c709`, and `19e84a637a55277b484afe60b7b3585292901a0d4ef3f82fd7db3a1be032261a`.

R17 adds public context for Binance T01 and V2 diagnostics, SimNow C01 and paired-front transport observations, the unregistered Binance/OKX L02 source/fake correlator, OKX M01 and Optional16 diagnostics, and L03/L04 R4. Diagnostic worker counts are not account-wide proof; unknown provider activity remains `UNOBSERVED`. The L03/L04 R4 sanitized report records one registered installation and one blocked attempt per case. Both are blocked at outer `run_namespace_create_new`, with child summaries `source_bootstrap_blocked` / exit 2; normal reap, both pipe EOFs, stream closure, Job active count zero, and no forced termination are reported. Tree-zero is not certified, and provider requests/account activity remain `UNOBSERVED`. The separate inert source diagnosis reproduces `project_modules_preloaded` from the fixed main/worker files missing in the child manifest, but does not prove the exact captured failure stage. These are non-case contexts and do not add PASS.

SimNow paired-front TCP observations are host/time-specific transport evidence only; they do not establish login, provider readiness, future reachability, or case acceptance. The L02 correlator is source/fake only, unregistered, and has no producer or route. Its Binance listenKey cleanup never deletes a potentially shared provider key; its OKX session identity uses provider-issued login `connId`, while local run nonces bind evidence windows only.

The root-wrapper source/fake review gate uses real frozen helper code and full archive metadata with inert API fixtures. It verifies upstream review pins, each new wrapper template pin, matching outer/inner activation filenames, and a single child-bootstrap call through the real `__main__` guard. The five-second Job settle is one total budget that may complete after pipe EOF drain. Every blocked actual should retain a safe projection of its capture interval; unknown provider counters remain `UNOBSERVED`.

## Iteration 41 current acceptance snapshot: R19 FINAL (2026-10-03)

R19 FINAL is the current read-only authoritative 99-case snapshot at cutoff `2026-10-03T14:21:30.935297Z`: **11 PASS / 4 BLOCKED / 84 NOT_RUN**. Venue totals are Binance USDⓈ-M `6/0/27`, OKX SWAP `5/3/25`, and SimNow `0/1/32`. The snapshot binds 673 case-evidence references and 13 publication-metadata context records; metadata contributes zero case-status delta. All **16 optional topologies remain NOT_ACCEPTED**. See the final [JSON](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r19-final-2026-10-03.json) (SHA-256 `fef21f09380231f9fdada87d319e6896a8160257075a5e50f110c2fba72640a3`) and [Markdown](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r19-final-2026-10-03.md) (SHA-256 `57b31408950124ef5f270fd709afc94fe9ab0a0beb9b0f2e52b5c6fa9fe26230`).

The only two case changes from R18 are Binance L02 and OKX L02, scoped to each current-session read receipt plus producer-authored session-log correlation. This is not server-log or generic-workflow acceptance. The root decision sets publication cutoff only; it does not mint case/provider evidence. Account-write authorization is false, order/cancel activity remains `UNOBSERVED`, and no optional component or venue route is newly bound. R17 remains an unchanged historical snapshot, superseded by R19; R18 remains unchanged as the draft parent.

Additional diagnostic/source context does not alter R19:

- Later source clarification of M01 R9 confirms the child frame ended in CRLF; the nested C01 helper returned `c01_unavailable`. M01 remains blocked; provider order/cancel counts are `UNOBSERVED`. See the [R9 safe summary](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v6-r9-root-actual-safe-summary-resume-r1-2026-10-03/root-observation.json) and [framing observation](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v6-r9-root-helper-framing-readonly-r2-2026-10-03/root-observation.json).
- OKX L03/L04 V7 R4 remains blocked (`worker_result_blocked` / `candidate_rejected` at the source-closure/name-length gate); provider write counts remain `UNOBSERVED`. See the [R4 safe summary](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-l03-l04-v7-r4-root-actual-safe-summary-isolated-resume-r1-2026-10-03/root-observation.json).
- Binance T01 V4 R2 is GO_SOURCE_FAKE_ONLY, but actual continuation is held pending the 49-source profile activation repair. It adds no case PASS. See the [source/fake packet](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-binance-t01-v4-continuation-source-fake-r2-2026-10-03/README.md) and [independent review](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-binance-t01-v4-continuation-source-review-r2-2026-10-03/README.md).
- Optional16 R19 R4 timed out after 60,219 ms; cleanup was forced and the Job active count reached zero. The public stack sample was in `R9_DEPENDENCY_CLOSURE` at `_requirement_is_active` (line 409), before SDK import/guard completion. Optional acceptance remains 0/16. See the [safe summary](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r19-root-stack-r4-actual-safe-summary-r1-2026-10-03/root-observation.json) and [phase/stack projection](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r19-root-stack-r4-safe-projection-r1-2026-10-03/root-observation.json).

## Historical pre-R19 post-cutoff operational context (non-authoritative)

At the time of the following earlier reports, R17 was the latest fixed snapshot and R18 remained an immutable draft; R19 FINAL above supersedes that tracker status. These summaries remain historical context only:

- Binance CID R2 at 12:38 UTC completed two read-only GETs, reaped cleanly with Job active count zero, and reported the original ledger unchanged. It issued no budget authority or PASS. See [safe summary](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-binance-v1-cid-r2-root-actual-safe-summary-r3-2026-10-03/root-observation.json).
- OKX L03/L04 V7 R3 at 12:49 UTC returned `internal_error` for both cases. The source diagnosis confirmed missing R3 failure diagnostics; provider order/cancel counts remain `UNOBSERVED`, with no case promotion. See [safe summary](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-l03-l04-v7-r3-root-actual-safe-summary-resume-r1-2026-10-03/root-observation.json).
- Binance/OKX L02 R6 at 12:52 UTC both returned `l02_case_issuer_failed`; both Jobs reaped with active count zero, and the original template was restored. No case was added. See [safe summary](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-l02-r6-root-actual-safe-summary-r1-2026-10-03/root-observation.json).
- Optional16 R19 timed out after 180,594 ms and was force-stopped; the Job was empty after cleanup, stdout/stderr were each zero bytes, and the bounded raw capture was saved. The last public phase was entry into `R9_MODULE_RECORD_SCAN`, with 1s and 2s checkpoints; the underlying cause remains `UNOBSERVED`. See the [safe result](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r19-root-actual-safe-summary-r3-2026-10-03/root-observation.json) and [phase projection](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-r19-root-phase-safe-projection-r1-2026-10-03/root-observation.json).

These reports are historical non-case context. Source/fake `GO` decisions remain limited to their reviewed source and fixtures; they do not establish provider acceptance. Do not attempt SimNow login until password rotation is confirmed.

## Iteration 41 current acceptance snapshot: R20 Final R2

R20 Final R2 is the current canonical 99-case snapshot at cutoff `2026-10-03T22:51:51.578780Z`: **12 PASS / 3 BLOCKED / 84 NOT_RUN**; Optional16 remains **0/16 accepted**. This supersedes the R19 section above as current status; R19's bytes and evidence remain historical and unchanged. See the final [tracker JSON](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r20-final-r2-2026-10-04.json) (SHA-256 `16b98128cc9b975756febb0e544e944f592f5d34c34b8213e72ef222c0050b0c`), [tracker Markdown](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r20-final-r2-2026-10-04.md) (SHA-256 `771c22de4a589500ae681e3b7d423494cad5d63623e6c51010589159e6e5247b`), and [publication manifest](docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-three-venue-99-case-acceptance-tracking-r20-final-r2-2026-10-04-manifest.json) (SHA-256 `c1a0fe983fc1df138b81b7954dd2d67bc1bc618f3de90729b687de0bf1664f8b`).

The accepted Monitor V3 and Optional16 R31 R2 records are scoped local SDK diagnostics, not provider/account certification or Optional16 acceptance. SimNow environment-filter and TH application-monitor candidates remain disabled, unregistered source/fake designs; they do not change the live selector, schema, registry, or venue evidence. Keep whole MD/TD pair selection, `NO_WRITE / LIVE_NO_GO`, and the existing requirement to confirm password rotation before any SimNow login.

## Iteration 41 SimNow front selection clarification (2026-10-07)

The current `scripts/ctp_000_paired_front_selector.py` and its same-call
`ctp_000_front_handoff.py` accept one to eight complete MD/TD pairs. A pair is
eligible when both endpoints have at least one successful connection among
three bounded attempts. If no pair is eligible, selection fails. Eligible
pairs are ranked by the larger of their MD and TD successful-sample median
latencies, with configuration order breaking ties. Stability and failed
attempt counts are diagnostics, not additional eligibility or ranking gates.
The focused independent selector/handoff suite passed 45 tests. The additive
C01 V3 source closure now binds the current selector, handoff, and probe, and
its five independent synthetic checks exercise the actual typed handoff into
the original pre-admission validator. The combined author suite passed 50
tests; Root read back all 29 source members and the independent review bundle.
The validator remains `BLOCKED` pending protected native admission. Historical
C01 V1/V2 closures are unchanged and still pin their older sources. These
source checks add no real-account PASS and do not authorize login or trading.

## Iteration 41 Root startup findings (2026-10-07)

The current canonical account snapshot remains R20 Final R2: 12 PASS,
3 BLOCKED, 84 NOT_RUN; Optional16 remains 0/16 accepted. Later local startup
and source-fake work adds no account PASS.

The L04 R2 actual Root admission reached the reviewed source gate but returned
`root_route_root_invocation_uncertain`. Its owner process exited; retained
source post-verification and native/provider cleanup were not established.
The consumed namespace must not be reused. The R3 successor is limited to
finite diagnostics for the existing invocation, frame, consumer, and lease
boundaries; the R2 sources and attempt remain frozen.

Optional16 R19's actual whole call returned `CHILD_RETURNED` with child status
`ROOT_UNCERTAIN_RETAINED_NO_PARSE` and exit 2. Root's separate 591-public/
5-software outer custody was post-verified and released before process exit.
The child uncertainty is not a component or G1 acceptance. R20 development
preserves the 100+5 limit and adds only strictly validated child diagnostics
to the existing one-frame parser path; private or late captures stay closed.

Binance T01 R3 failed at `root_capsule_changed` before its OUTER/INNER
invocation. Public source shows that the synchronous capsule handle was read
twice without rewinding; the activation grant and markers have the same
reread pattern. R4 development uses a bounded seek-to-zero reread helper and
a fresh protected capsule namespace. Do not overwrite the R3 capsule or use
its failed admission as acceptance. Original V1 remains UNKNOWN; no original
CID lookup or retrospective allocation is authorized by these successors.

M01 R29's 118-public/36-software source maps and metadata scope fix passed
source-fake review, but its physical startup recipe is blocked: it requires
deployment absence while holding and executing a wrapper inside deployment,
and the attempt claim has no writer. R30 development must bind a protected
predeployment by identity, ACL, and exact source hash, and create/flush/verify
an exclusive claim before fresh capture. The 180+5 and 405+5 diagnostic budgets
remain unchanged; an external parent 100+5 envelope remains unestablished.


### Iteration 41 actual constructor follow-up (2026-10-07)

Binance R4 passed 12 source-fake tests but its activation directory suffix
differs from the frozen R13 writer. Its independent verdict is integrated
production path BLOCKED; Root did not run it. R5 is an additive repair and
must test the real producer-to-consumer constructor, keep the frozen R13
protocol suffix, and bind the public CLI dependency before loading.

Optional16 R20 R2 passed five independent source-fake tests. Its Root actual
local diagnostic returned CHILD_RETURNED with child ROOT_UNCERTAIN_RETAINED_NO_PARSE
and finite RuntimeError/r2_invocation/review_pin_shape diagnostics. Root held
604 public and five software paths, postverified and released the outer
custody, then explicitly exited the owner process with code zero. No private
capture or late parse occurred. R19 passes a five-key review map to the
frozen R2 constructor, which requires four keys plus a separate README slot.
R21 must adapt this bridge and test the real constructor; R19/R20 stay frozen.

M01 R30's six source-fake tests passed, but independent review is HOLD:
the real pinned bounded reader advances a synchronous file handle and does
not seek before wrapper/claim rereads. Path.read_bytes fakes concealed EOF.
R31 must use offset-aware fakes and an explicit bounded seek-to-zero adapter.
No complete 154-entry physical acceptance or external 100+5 supervisor is
established. A packet declared frozen must never be overwritten; successors
use a new packet namespace and retain each older byte set and QA limitation.

R6's 28-field ZMQ map has validation but no actual Root collector. R5 derives
bootstrap metadata from a supplied complete map; static pins do not supply
installed-source/cache/native/dependency/module/DLL observations. Formal
acceptance remains 12 PASS / 3 BLOCKED / 84 NOT_RUN and Optional16 0/16.


### Iteration 41 physical-source follow-up (2026-10-08)

The SimNow selector accepts one through eight complete MD/TD pairs, filters for both endpoints reachable, fails if none qualify, and ranks qualifying pairs by the maximum of their successful latency medians, then configuration order. The accepted correction remains source/fake evidence only; password-rotation confirmation is still pending before SimNow login.

Root independently verified restored M01 R31 R1 bytes and reviewed R31 R2 (5 source/fake tests), then actually held the 118-public/36-software physical closure and passed the generated runner's 154-entry held-map gate with a fresh NON_ACTUAL_PLAN. Both source holds were post-verified and released. No readiness validator, coordinator, SDK/account input, provider operation or attempt claim ran. This does not establish M01 acceptance or its external 100+5 supervisor; see the 2026-10-08 root-physical-source-precheck and owner-exit archives.

Optional16 R21 R2 independently passed 6 source/fake tests with the real binder/R2 constructor path up to a fake CUv2 read leaf. Root's later actual local diagnostic held 605 public and 5 software paths and returned ROOT_UNCERTAIN_RETAINED_NO_PARSE / outer_stderr_not_empty (exit 2, one retained group). Root did not read private captures or late results or claim source postverification/native cleanup; the owner then explicitly exited 0. R22 finite diagnostics are separate pending work. Formal results remain 12/3/84 and Optional16 0/16; these checks add zero real-account PASS results. Frozen packets must remain immutable and later changes use new source and packet names.


### Iteration 41 single-pair and finite-diagnostic follow-up (2026-10-08)

The generic SimNow managed-case endpoint median now accepts at least one successful sample out of three, matching the shared selector. Independent public synthetic coverage passed 44 focused checks, including one complete pair through selector/receipt/case binding/validation and no eligible pair producing no receipt. The new additive C01 V5 candidate bounds configured pairs to 1..8 and matches current config count and digest before credential resolution or selection; author and independent focused runs each passed 5 tests. Root verified all five public reviewed/current sources and five review members. V5 remains unregistered and default-closed, without native/provider acceptance. The frozen V3 five-pair scope is historical, not the generic config contract.

One separate author audit violated private-input policy by including an ignored SimNow config sensitive line in a broad search. Its original capture is excluded from public review and evidence; do not reopen, quote, hash, or use it for account operations. The independent V5 review did not reread that input and does not assert zero private reads for the whole author audit. SimNow login still requires pending password-rotation confirmation.

Binance R6 independently passed 14 public source/fake tests, with a held-loader supplement and combined 15-test focus. R7 adds a separate owner-child/300+5 guard candidate; its 9 author tests are source/fake only and independent review is pending. Callback deadlines are cooperative. M01 R32's abstract 100+5 coordinator independently passed 7 source/fake tests; a concrete R33 adapter/bootstrap and actual READY plan remain separate work.

A fresh L04 R3 draft and three ACL-bound run materials led to one actual local startup diagnostic using 98 public and 2 software holds. It returned BLOCKED with the finite r19_consumer/r16_route_exit/outer_lifecycle_uncertain diagnostic, retained its uncertain holders, and the owner then explicitly exited 0. The generic r16_route_exit code does not prove R16 ran. Its UUID is consumed; no private capture was read and no cleanup/source-postverification/provider PASS was inferred.

Optional16 R22 independently passed 8 source/fake tests. Root's actual local diagnostic held 618 public and 5 software paths and completed outer cleanup and full Root custody postverification/release, then owner exit 0. The child still blocked at activation binding with finite RootEnvelopeError classification; this does not establish G1 or components. Formal account results remain 12 PASS / 3 BLOCKED / 84 NOT_RUN and Optional16 0/16.


### Iteration 41 Root count correction and bootstrap scope (2026-10-08)

The Optional16 R22 Root caller incorrectly filled INERT_PUBLIC_PATH_COUNT with the 495-item default-closed derived closure. The child payload contract requires the 379-item base public_paths_sha256 map; active public/software/alias counts remain 575/5/19. A public synthetic production-binder probe reproduces driver_r5_active_map_shape with 495 and completes binding with 379. The previous actual frame only observed RootEnvelopeError at the binding phase; do not relabel its unseen private capture with the synthetic specific code. Future Root fill must derive the base count from map.base_inert_public_paths. R22 historical observations remain immutable; R23 is a separate finite-code candidate under independent review.

Binance R7 independent review is HOLD for unbounded in-child StringIO and unproven false provider-call status on BLOCKED. The additive R8 uses bounded TextIO/buffer capture and null when activity is unobserved; its 14 author source/fake tests and concrete coordinator integration await independent review. No R8 account operation has run.

The M01 R33 default-disabled bootstrap constructs CUv2's lazy contextmanager but R31 returns before entering it; the preliminary review claim that this test necessarily invokes native/private scope operations was withdrawn. All 6 source/fake tests passed. Its actual READY activation interface and full pending-write/no-release test remain separate R3 work. R34's 21-key plan draft is pure source/fake preparation, not authority or an actual protected READY plan. Formal results remain 12/3/84 and Optional16 0/16.


### Iteration 41 owner outcomes and instance isolation (2026-10-08)

Binance R8 independently passed 14 source/fake tests. Root's one-shot actual R6-capsule invocation held 33 public and 2 software paths and returned PARENT_TIMEOUT / active_deadline at the external 300+5 boundary. The child lifecycle and capture completed; parent source custody was post-verified and released with no retained groups. No typed child frame or case result exists. Provider activity remains UNOBSERVED, private captures and late results were not parsed, the capsule is not reusable, and original V1 UNKNOWN is unchanged. The owner explicitly exited 0; see the R8 actual-observation and host-exit archives. Static R13 retention behavior is a possible no-frame path, not evidence that it occurred.

Optional16 R24 independently passed 13 source/fake tests and verifies 53 fixed inputs. R23's parser HOLD is pinned only as historical provenance. Root corrected the inert-count field to the base-map count 379, prepared a 623-entry fresh closure, held 620 public and 5 software paths and made one 100+5 local diagnostic call. The clean parent returned CHILD_RETURNED / exit 2; the finite child diagnostic is RootEnvelopeError / source_custody_entered / UNOBSERVED with ROOT_UNCERTAIN_RETAINED_NO_PARSE. Parent custody was post-verified and released; child cleanup or source postproof was not inferred. No private capture or late-result parsing occurred, and the owner exited 0. Optional16 remains 0/16.

M01 R34 plan-draft construction independently passed 8 source/fake tests and Root verified its public packet; it grants no authority. M01 R33 R3 independently passed 5 tests but remains HOLD / NOT_ADMITTED because its temporary shared R2 module-global gate can admit an unrelated adapter instance. A separate R4 instance/private-module successor is in progress; frozen source and packets are unchanged. L04 R4 has 18 author source/fake tests and awaits independent review and fresh concrete Root scope. The SimNow one-through-eight-pair correction is accepted source/fake behavior; real login remains pending password-rotation confirmation. Formal venue counts remain 12 PASS / 3 BLOCKED / 84 NOT_RUN; all new work above adds zero real-account PASS results.


### Iteration 41 post-image actual diagnostics (2026-10-08)

M01 R33 R4 independently passed 8 source/fake tests but its fresh actual parent stopped before resume at target_verification_failed, with clean parent cleanup and source release. R5 independently passed 12 tests and Root checked the public packet, 14 dependencies and ten historical review files. R5's fresh READY namespace 1157a2e7d1c04b84bc746f22920ebcb7 held 156 parent paths and 55 extra context paths; the actual 100+5 parent returned CHILD_EXITED / exit 2 in 7.235 seconds with zero stdout/stderr bytes. Parent capture, cleanup, source postchecks and release completed. The child 154-source gate, plan validation and provider state remain unobserved; no case payload or private capture was parsed. The owner explicitly exited 0. Finite child-stage diagnostics are the next source-only task.

L04 R4 independently passed 18 source/fake tests. Its fresh concrete source review covers 102 public plus two software rows and the 21 extra exact context pins required to bind its template test. Root physically held and authenticated that context, created three protected material files, and invoked namespace 083501985f504dc9adcdb26ab082b806 once. The actual result remains BLOCKED / root_route_root_invocation_uncertain. The finite R14 lifecycle diagnostic has eight failed gates: parse_allowed, disposition_clean, reason_none, process_reaped, job_empty, job_closed, raw_capture_complete and source_postverified; ten other gates are true. No R16 execution or provider state is inferred from the generic r16_route_exit label. No private capture, late result, cleanup or source postproof was claimed. Two retained Root groups ended at explicit host exit 0; the namespace is consumed.

Optional16 R25 has nine passing source/fake tests but remains SOURCE_FAKE_HOLD / NO_ACTUAL_G1: production fixed-input verification fails on one mistyped R24 source-pins.json digest. R26 will retain frozen predecessors and verify the actual public fixed closure. Binance's candidate for a new read-only lease over an existing R6 allocation grants no trading reuse, deadline extension, allocation issuance, recovery or original V1 query. No existing CID or provider query has yet been established. Formal counts remain 12 PASS / 3 BLOCKED / 84 NOT_RUN, Optional16 0/16, with zero new real-account passes.


### Iteration 41 original-allocation inventory and namespace regression (2026-10-08)

Root's bounded protected R6 metadata inventory found no matching run directories or allocations.sqlite3 in the existing t01-runs scope. No credentials, SQLite contents, private captures or provider request were used; the historical capsule metadata read did not reactivate trading or extend deadlines. Source custody was post-verified and released and the owner exited 0. This absence is not a provider-activity proof; original V1 UNKNOWN remains unchanged. The Binance R6 read-only source R1 / documentation packet R2 independently passed eight fake tests but is SOURCE_FAKE_REVIEWED_HOLD: its public transport can bypass the proof gate with arbitrary query text, exposes raw response bytes and stores a general POST/DELETE-capable request method. A separate source R2 successor is narrowing the operation inside the proof-validated observer. No actual GET occurred.

Optional16 R26 independently passed ten tests and verified all 62 public fixed inputs through the production reader. Root public readback passed, but metadata map preparation stopped at driver_r5_control_pin_mismatch before active-copy, protected-control, physical-custody or process creation. R26 incorrectly aliases the frozen R19 baseline CONTROL/SCRATCH to fresh r26 paths. Root did not override those pinned baseline values; R27 will preserve explicit frozen R19 baselines and test the real namespace/rebinding path. Source/fake GO does not establish namespace execution or G1. L04 and M01 finite diagnostic successors remain in development; original passing conditions are preserved. Formal counts remain 12 PASS / 3 BLOCKED / 84 NOT_RUN and Optional16 0/16.


### Iteration 41 single-pair policy and finite child-stage diagnostics (2026-10-08)

The corrected 000 SimNow selector accepts 1..8 complete MD/TD pairs, filters both-endpoint reachability, fails with no candidates, then ranks max(successful MD median, successful TD median) with configuration-order ties. At least one of three bounded probes per endpoint suffices; stability is diagnostic and cannot override latency. Selector/handoff/generic consumer/C01 V5 constraints align. The independent focus passed 44 checks; no new TCP, provider login or case acceptance occurred.

Optional16 R27 independently passed 13 source/fake tests and all 62 production fixed-input reads. Its Root map has 632 rows. One actual local diagnostic held 629 public + 5 software files: the parent returned CHILD_RETURNED/exit 2 with complete Root postverify/release and zero retained groups; the child reported RootEnvelopeError at source_custody_entered with held_path_missing and retained its own uncertain scope. Parent cleanup is not child postproof or G1. M01 R6 independently passed eight fake tests; one fresh READY-plan actual parent run held 156 main and 170 extra rows, exited 2 in 6.656 seconds with clean capture/cleanup and released source scopes. Its only finite child phase was RUNNER_RESULT_UNSAFE/UNVERIFIED, the shared validator-None or validated-UNCERTAIN branch. Provider activity remains UNOBSERVED and raw child streams are not returned. Both owners explicitly exited 0.

The L04 R5 additive observer independently passed 14 fake checks and Root public readback verified 26 source ZIP entries/42 review entries. It preserves cleanup result/exception, restores temporary hooks, freezes pending observations, and does not change the R4 lifecycle gates; actual diagnostic use is still separate. The final Binance read-only source R3/candidate R3 independently passed 11 fake checks; no original allocation database exists, so no account GET or trading retry was made and original V1 UNKNOWN remains unchanged. Formal counts stay 12 PASS / 3 BLOCKED / 84 NOT_RUN, Optional16 0/16.


### Iteration 41 actual L04 cleanup boundary and composed-entry coverage (2026-10-08)

Fresh concrete L04 namespace 23eeffe289744f1586c7fcdd877744ae obtained metadata-only source review with 49 indexed members. Root created three protected public-content control files. Its first caller stopped before authorization/invocation on an obsolete review cross-pins field; the corrected caller verified the current field and still-fresh leaves, then actually invoked with 104 main and 65 extra rows. The original eight lifecycle gates still failed. The R5 observer reported one returned cleanup_uncertain, unknown count/null returncode, clean/capture/job_closed false and streams_closed true; all temporary hooks restored. Uncertain source refs stayed until explicit host exit 0, not child cleanup/postproof. The actual observation SHA-256 is 039ad8913fad3dd0fb987311b0dd3559594e780e1e2579e0db8ffcd1edd0aa6b; an earlier 65-character PTY transcription was rejected by the exact host-record pin check and corrected.

Actual R14 ports R5 uses R10CleanupAdapter(bundle.r12_module), whose broad cleanup catch collapses reader/process/Job/pipe/close exceptions into the observed tuple. The separately published R25 helper function is a different R3 lineage path, not this actual adapter call. No specific failed step or gate relaxation is justified. Optional16's 64 review paths all appear in the exact derived 577-key child map; same-process validation also reveals fixed dynamic-module alias reuse, so separate validator checks do not establish the production chain. M01 R7 first composition placed observer definitions after the __main__ guard; import-only fake tests missed the actual entry ordering. It is frozen HOLD and not used by Root; a successor must test exact composed __main__ execution. Formal counts remain 12 PASS / 3 BLOCKED / 84 NOT_RUN and Optional16 0/16.


### Iteration 41 M01 composed-entry and finite result checkpoint (2026-10-08)

The additive M01 R7 R2 observer (`scripts/iteration41_okx_m01_r33_runner_result_observer_r7_r2.py`) passed eight independent source/fake checks, including actual composed `__main__` ordering and a fake post-launch timeout that suppresses late parsing after cleanup/release. The original R7 R1 remains frozen and was not activated. R2's nested supersedes canonical-source/bundle metadata repeats R2; preserved R1 bytes were verified from R1's own pinned index instead.

Root created a fresh current READY plan and five protected files in namespace `28f4128fa82b48bdac8227621be524fa`, held 156 main and 186 context rows, and ran the 100+5 parent once. It returned CHILD_EXITED / exit 2 in about 6.984 seconds with complete parent capture, cleanup, both source postverification/release, and no retained scope. Its finite result is VALIDATOR_APPROVED_UNCERTAIN with reason ordinal 12 and diagnostic-pair ordinal 1; source-review-bound is reported true, provider/native fields UNSET, and route count null. These are unverified reported categories, not provider or case evidence. Actual observation SHA-256 is `628358eff0a4940a5a25eab066f0f835ed2aa663f8660adf008422b75c711f58`; explicit host exit 0 observation is `23266cf3e7c0cdd5caa44a21a83a5380894f6143842f0a7065fc3ec55e75dad4`. No private captures or late results were read. Formal account results remain 12 PASS / 3 BLOCKED / 84 NOT_RUN and optional topology acceptance 0/16.


### Iteration 41 cleanup adapter and initial custody map checkpoint (2026-10-08)

L04 R6 cleanup-stage observer passed fourteen independent source/fake checks; Root verified its 16-member packet and 31-member review. A fresh concrete namespace `d6a92ec369914ae790ccafd2c512eab2` was independently reviewed and materialized, then invoked under 104 main + 82 context rows. Actual result remains BLOCKED with the same eight R14 gate failures and one R5 cleanup_uncertain return. R6 bound its own sources and R10 cleanup, but runtime adapter_source_bound=false; stage/outcome stayed UNOBSERVED, with no adapter patch. Direct canonical R14 fake tests do not establish actual transformed adapter binding. Two Root scopes remained until explicit host exit 0; no child cleanup/source postproof was established. Actual observation SHA-256 `5ba4c5515d36ade7b3193486f1a1992334a79702cb81a950abd788e9d370d44a`; host exit SHA-256 `eb3734c52cf17f3d7c384f7aee1250f8f2405259c1b7f0ad618e4c283f80d501`.

Complete same-process Optional16 R27 sourcefake exposes the activated-map/request distinction: binder validates 575 public + 5 software, whereas real R2 delegate/adapted_hold initially requests 518 public + 5 software. Sixty-four activated keys and 49 review-closure keys are unrequested; the second R17 helper lookup is deterministically absent. The union is 582 public plus the same five software paths. The earlier 577 static projection is not this first request. External/temp/software fake omissions are not actual missing-file evidence. R28 exact merging and fixed-alias lifecycle repair remain candidates pending full composition and independent QA. No G1/provider/case acceptance follows. M01 ordinal 12/1 maps to the shared outer-response/parse catch, not an attributed native/provider cause. Formal totals remain 12 PASS / 3 BLOCKED / 84 NOT_RUN and optional 0/16.


### Iteration 41 source-review boundary incident (2026-10-08)

An Optional16 R28 author reported an ad hoc exists/read_bytes loop over 575 declared public pin keys, including at least two prohibited external temporary sources. External totals and native/credential/config/secrets/capture/authority categories were not recorded and are UNOBSERVED. The final self-report says counts only were emitted and no bytes copied, written or reused; Root did not inspect the prohibited contents. The check and 575-hit result are excluded, and blanket no-external-read / whole-turn private_inputs_read=false claims are withdrawn. The original agent was stopped; original unsealed R28 files remain HOLD. A separate agent is rebuilding R28_r2 from frozen public R27 and whitelisted indexed public snapshots, without filesystem reads through external pin keys. See `evidence/iteration41-optional16-source-review-boundary-incident-r1-2026-10-08/observation.json`. No provider, G1 or account PASS follows; formal totals remain 12/3/84 and optional 0/16.


### 2026-10-08 current local diagnostic checkpoint

The SimNow selector accepts one to eight complete MD/TD pairs, filters both-side reachability first, then chooses the lowest maximum of the two successful-median latencies; tie order is configuration order. The sealed ranking/handoff independent review records 45 focused checks; the earlier 44-count statement is withdrawn. Public documentation now includes single-pair and multiple-pair placeholder JSON. No current private front projection or real probe/login was read/run in this checkpoint.

M01 R8 independently passed 11 source/fake checks. Root actual startup returned CLEANUP_UNCERTAIN / launch_failed / session_unavailable in 0.016s, without a child frame or cleanup/postverify proof. Its 38,867-byte bootstrap makes a quoted Windows command of 40,005 Python characters, above the documented CreateProcessW limit; this is a launch-blocker inference, not actual exception disclosure. Main156/extra199 holders remained until Root host87043 exited0. The R8 review's inherited167/164 label describes the full index; Root separately verifies dependency164/162 and both packet-relative ZIP aliases. Frozen R7 R1 preservation is derived from its original pinned index. R9 sidecar transport is unfinished source work.

L04 R7 independently passed16 source/fake checks. A fresh concrete review and Root protected material preparation preceded actual invocation. Main104/extra244 custody and observer bindings succeeded; R10 returned cleanup_uncertain at JOB_ACCOUNTING, with source/code/class patches restored. The eight lifecycle failures remain; actual Job count and exception type are unobserved. Root host16742 exited0 with holders retained; child cleanup/source postverify is unproven. Public actual record is f238c1b8aedb652303efdbb06782857e9c32a95eee681ab22590a3b1dee9110c. Optional clean R28_r2 remains unfinished; only a Root-verified whitelist of six public wheel blobs and six public RECORD blobs permits opaque byte/hash transport in its fake, without extraction/import/native behavior. External software uses synthetic bytes. The earlier source-read boundary incident remains recorded and its original R28 excluded. Formal acceptance stays12 PASS /3 BLOCKED /84 NOT_RUN, optional0/16; no added real-case PASS.

Root also produced an exact-hash public opaque snapshot of three fixed CPython stdlib profiler caches for clean Optional source/fake transport only (index9916da11d480bfbaee1a5c741240abe186b3a0ec920e7ba75a2e3580e43aecf0); reviewers must not probe their external metadata paths or unmarshal/import them. The 000 renderer emits version4 with legacy ctp.front_pairs, accepted by the simulation/sandbox compatibility schema; selector docs now state conditional admission and the correct shape. No actual deployment or private config creation is established.

M01 R9 later independently passed13 source/fake checks and Root actual short-command transport ran in freshnamespace2f39647cd1204655b85192c856aa33c7. Protected sidecar used the Root publisher, six CREATE_NEW files, main157/extra213 custody. The actual command was1296 UTF16 units includingNUL, stdin1787 bytes, sidecar38867 bytes. Parent CHILD_EXITED2 in7.656s with complete outer capture/cleanup, both holder postverifications/releases, no retention; host31344 exit0. Finite R8 phase reports OUTER_RESPONSE/RAISED/VALUE_ERROR and parserNOT_REACHED; R7 result remains VALIDATOR_APPROVED_UNCERTAIN ordinal12/pair1, provider/nativeUNSET, no casePASS. Public actual SHA0aa95af0acdbac2305193ffb694b68af3e355bdba3e802ab318d18fbedb397ab. No exception text/args/locals or private/late capture was read; inner/provider lifecycle and formal acceptance remain unestablished.


### Iteration 41 predeployment contract and accounting observer readback (2026-10-08)

Independent public static reviews confirm a frozen R28 production once conflict: different active/fixed namespaces fail path binding; identical namespaces fail its absent-directory guard because R30/R9 require protected predeployment. The exact once remains dd3da5e4678b4758e83006f635f88fbff01520cbbed43f103bbd317955e430a5. Actual R8 finite OUTER_RESPONSE/ValueError is consistent but does not locate the actual failed check. A new explicit R10 handoff is source work; frozen inputs and complete custody/claim/cleanup gates remain required.

L04 R8 independently passed12 source/fake checks. Root public readback verifies29 archive/28 indexed/16 repository/39 review members and rechecks inherited201 public context/62 PREP rows, merging216 context. Prior-R7 ZIP snapshots match the original public physical packet; no nonexistent unpacked snapshot is claimed. Readback SHA dfec17279e1b51075c5f9cc0da3e4ce2c6dea844d0568a852c77dcea0aa4420f is public consistency only. Formal acceptance remains12/3/84 and optional0/16; no added real-case PASS.


L04 R8 actual in fresh namespace0a77cbbccb1444ce9df8de75939c0484 used main104/extra259 rows after concrete source review and three protected material files. Root authentication bound36 R5,216 R8 and21 template context rows. One cleanup returned cleanup_uncertain with stage/exception_stage JOB_ACCOUNTING_CHECK; the query call returned, but actual count/was_forced remain unobserved. Source/code/class/module hooks restored. The same8 gate failures remain, without cleanup callback or source postverification/release; two holder refs remained until explicit Root session42367 exit0. Actual SHA5b084ab8acd8e8a1b8b98eb5dc0a42d63999762d65bd20f11018cc842f343eeb, host SHA746d43c73fdb8e51c59aa7f7c938cc7ea2dfad7cca8605cfef6451e2abd8fad0. Host exit is not child cleanup proof; namespace is consumed. Concrete review preserves its unrecomputed observer member-index digest caveat; Root separately verified all39 observer archive members by size/hash. No private/raw/late capture was opened or real case PASS added; formal12/3/84 and optional0/16 remain.


### Iteration 41 local Windows handle-order diagnostic (2026-10-08)

Public V4 accounting ABI/type checks show no mismatch. R10 retains the Popen handle across wait/EOF into Job query; Microsoft documents ActiveProcesses decrement after process-reference release, and CPython3.11.5 wait does not close that handle. This is a source-order risk, not actual L04 attribution. Root isolated empty-env pass-child labs used exact V4/software pins and no account/SDK/provider: R1 key normalization failed before Job/child, postverified then host58879 exit0; R2 reaped0/pipes closed but count POSITIVE before/immediately after Close, retained without job-close/postverify until host62897 exit0; R3 added a separate bounded ten-sample/planned50ms window, observed ZERO on its first sample, normally closed the unforced Job, postverified/released five public/two software rows, then host95000 exit0. R3 SHA1f9e141f4aff09bfab9d75ad5c06215ebe8e132f3b50acdefdba79f615e15bf2 is local mechanism evidence only, not actual-case values/provider/native acceptance or100+5 proof. R9 observation and a cleanup successor design remain in progress; frozen code is unchanged.

Clean Optional sourcefake now derives the actual first cold request as515 plus14 extra minus11 overlaps equals518. Inert495 is a different stage; the earlier495+23 cold split is withdrawn. Active575/5software/19alias,64 active-only,7 outer-only and582 public union are unchanged, pending sealed independent QA. Profiler equivalence is an explicit bottom fake because external software rows stay synthetic; opaque public cache bytes are not parsed/unmarshaled/imported and confer no actual-equivalence authority. Original R28 boundary-incident exclusion and formal12/3/84, optional0/16 remain.

Root current subprocess public source snapshot index is a57ad270adb62afa1f9136d3005357329af4b7495a45f1ec297005edf08f44cd; blob2ff641d58f8696496e8718538cd96cd7afcd503ae271fb23da22422b3aee9fc7/88448B. Agents may inspect/compile that public copy only, never probe its external origin or execute native/module-top-level/process behavior. It is not runtime/custody authority.

### Iteration 41 current SimNow selection verification (2026-10-08)

Root reran the selector, independent selector, handoff, and managed-consumer partial-success public suites: 49 passed, one existing pytest configuration warning, exit 0. Single configured pairs are accepted; no eligible pair fails; one eligible pair is selected; multiple eligible pairs rank only by max(MD successful-sample median, TD successful-sample median), then configuration order. Stability is diagnostic only, and MD/TD are never mixed across groups. The managed positive case uses the real probe, receipt, and invocation validator with inert socket leaves. Evidence `iteration41-000-simnow-pair-correction-current-root-source-qa-r1-2026-10-08/observation.json` SHA-256 is `28940e2d841584c944efabd660ba2c60fe71245d778c0a08565ae1284724757a`. This is source/fake evidence; frozen C01 old source pins, native/provider admission and actual account acceptance remain closed. Formal 12/3/84 and optional 0/16 are unchanged.

L04 R9 finite accounting-value observer independently passed 13 source/fake checks. Root public readback verifies 30 archive/29 indexed/18 repository/40 review members and inherited 216 context rows, producing 232 context; a separate additive readback recomputes the exact 40-member review-index recipe and produces 233 context. R2 readback SHA-256 is `fdd1873e25d38b25eb7ef5aedeb836a0e55ee501961e46ca6bda6d61f6360129`. Canonical source-pins SHA-256 is `bddf3393c5fbe608ced379d29477723fb18522f8b06ce7bd4916751133505822`; the earlier author message's f8f06 spelling is withdrawn. No actual L04 count/forced category follows from source/fake or public readback. New cleanup successor implementation and a fresh concrete diagnostic review remain separate work.

Root supplies one further named opaque software sample for the M01 R10 sourcefake closure: `iteration41-m01-public-python-image-opaque-snapshot-r1-2026-10-08/index.json` SHA-256 `a7b7d8cce24046baaa069635b5c1332871f36dc75da087e0cb983e8133740559`, with sole `python-image.bin.blob` SHA-256 `c98caee82c66433f0e89d4abbf152b39a7dc2e99979b28dcb021598b4e3f5642`, 92,160 bytes. Root performed a stable bounded 256KiB exact hash/size read. Agents may use only that public index/blob for opaque byte/hash transport into fake files; PE parsing, execution, native import and origin-path probing remain forbidden. This narrow sample is not authority for the complete 36-software map, actual custody, process behavior or provider acceptance.

The next explicitly identified M01 sourcefake software gap has a separate public opaque sample: `iteration41-m01-public-python-dll-opaque-snapshot-r1-2026-10-08/index.json` SHA-256 `1d83ee3ae0309eb878ff20b2fff6f77d4be9f91e103345bd894f2482bded3f90`, sole `python-dll.bin.blob` SHA-256 `162e8557fbed5f39ae24983ee62b2d435b4796c937d9c1a34371888c7e43af00`, 5,991,424 bytes, from a Root stable bounded 8MiB exact hash/size read. The same opaque-only restrictions apply; this does not permit reading metadata origin paths or other software keys, and does not establish native or full-map acceptance.

### Iteration 41 latest L04 and Optional source checkpoint (2026-10-08)

The fresh L04 R9 namespace `be5eb6196bab47f4ba6bc355cbda57b3` is consumed. Main104/extra276 custody and R5/R8/R9/template context authentication succeeded. The original cleanup returned clean with count ZERO and forced FALSE; all18 inner lifecycle gates passed, including capture, normal Job closure and inner source postverification. The actual result remains BLOCKED at `r19_consumer / r16_route_exit / child_frame_stdout_digest`. This is one observed clean run, not a permanent cleanup fix or provider acceptance. Outer Root cleanup/postverification/release did not run; two holder refs remained until explicit host27165 exit0. Actual observation SHA-256 `c0e9c735fb8edc8e6f38627a05212f9c70bcbbe0da48e97accd5b169cf66fd8e`; host record `3cb9bf0842aef3f73ac2b8801da526f4feadd6e999ee6465006f51d44f97008f`. No raw/private/late capture was opened, and provider behavior remains UNOBSERVED.

Material R1 refused the exact public21.6MiB review ZIP at its16MiB reader limit before custody/protected creation/native dispatch. Additive R2 used a32MiB public bound, below CUv2's64MiB bound, verified140 review members and the exact member-index recipe, and created three protected files with source postverification/release; host99612 exit0. Material record `c59721ca74793cc9ec9f680b9f2378c97213a12172d8fc84175043fb78958179`; host `afc0442fe1850bbc7e4ba72a2936ab29723cab6669cd5f823afd7e84500696a5`. The independent concrete review preserves its inherited R3 source-packet prefix/index mismatch caveat; its cross-pins do not establish verification of every inherited R3 member.

Static source/fake review identifies an R19 adapter branch that emits an empty stdout payload for code2/INNER_BLOCKED, whereas its consumer requires nonempty decoded stdout and reports the combined `child_frame_stdout_digest` reason. This reproduces a source branch only; the actual R9 predicate/adapter branch is unknown. No deterministic successful-path LF/CRLF conflict was found. An additive finite diagnostic is pending; validation, retention and success gates remain unchanged. The separately sealed cleanup robustness successor passed12 source/fake checks and awaits independent review; it is optional robustness after the observed R9 clean run.

Optional16 R28_r2 independent review is HOLD_SOURCE_FAKE_IDENTITY/ACTUAL_ROOT_BLOCKED. Function code/origin binding accepted three sourcefake mutations to defaults, globals and closure cells. It did not prove an actual exploit or full-chain mutation. An additive R28_r3 is being developed to bind those runtime fields and compare every production map row to the independently derived map. R28_r2 stays frozen and cannot be activated. Formal acceptance remains12 PASS/3 BLOCKED/84 NOT_RUN and optional0/16.

M01's third named opaque sample is `iteration41-m01-public-git-image-opaque-snapshot-r1-2026-10-08/index.json` SHA-256 `2e3206f529050e7fbb82523f4e4cd2e9f9fc05dd9d3b70c642d53e7acc24b981`, sole `git-image.bin.blob` SHA-256 `134a3923dadcb35e4a017ea27cdeb3aa017c29e012a5566180866f37f9fbdf5f`,45,048 bytes. Root used a stable bounded2MiB exact size/hash read. Agents may use only this public index/blob as opaque fake bytes, never inspect/parse/execute/probe the external origin. R10 full public composition reaches the unavailable pinned C01 helper payload and fails closed; its36-software closure is not proven by these three samples or the18 public PyYAML payloads. No additional private/installed metadata/native payload read is authorized by that limitation.

The cleanup R2 author reports pytest used a newly created external `D:/temp` basetemp despite the prescribed repository basetemp. Its frozen README and sanitized QA summary record that location, without an exact unredacted author command artifact. This author run is not approved scope evidence; the independent reviewer separately observed12 passing tests using the prescribed repository basetemp. No external basetemp was inspected by Root/reviewer, and the author's claims of no other external reads/deletes remain self-report. Future candidate QA must use a fresh repository `.codex-tmp` directory, without revisiting that external directory. Source review is separately HOLD for restarted cleanup deadline and insufficient wait/poll callable binding; no actual activation follows.

Current SimNow C01 V5 public source review also matches19 manifest members and passes5 isolated sourcefake tests, including1/8-pair bounds, same-call one-success-per-side selection, eight-pair latency selection, no candidate and default-closed entry. Its issuer and owner both bind current selector/handoff pins; the reviewer withdrew an erroneous owner-absence claim after the exact existing owner hash was verified. V5 is the existing additive corrected-pair candidate, so no duplicate binder was created. The49-test focus includes a separate007 typed managed binder; that binder does not consume the000 SelectedFrontPair type and must not be presented as000 C01 integration. V5 remains unregistered/default closed with no issuer/native/login/provider invocation. Formal12/3/84 and optional0/16 are unchanged.

The V5 source-order review then found credentials/private-run precede selection and credentials use pair0 metadata; the private packet has no endpoint fields and worker uses separate pair_binding, so no native misroute is claimed. Additive unregistered V6 selects/revalidates first and constructs credentials from its exact selected pair. Its unchanged R1 plus R2 companion passed14 isolated tests independently, including real `_run_candidate` through real `_credential_lease` with inert EnvRef/private/worker leaves. Independent review36ba5d4d97568cf977f67cb8b35e312387a1687c0030e7fb65b7a9aaf3bf91c8 is GO_SOURCE_FAKE_ONLY. Root bounded public readback26 unique rows/19 manifest rows matches, SHA0580653fd25aea616ade365022404b033cfc388e0d89103527bba411cd577378. The companion imports its listed R1 helper by path; SHA is externally pinned/reviewed, not asserted by that loader. Front-match metadata refers to credentials used by fake packet construction plus separate worker binding, not serialized endpoint fields. No source custody/native/registration/account acceptance follows; login remains closed pending rotation confirmation.

M01 R10 source candidate is sealed at96a8edc31f7dc2dc88158f1d9ccd5142bbe1d405d8f2c57ee3deed38aec69226. Its author19-test run used ordinary `python -m pytest`, not prescribed -I/-S/-B, with PYTHONPATH status unobserved and repository `.pytest-r10-finalfocus-06` basetemp. The author withdrew an isolated-QA claim; this result is distinct from the prescribed independent isolated rerun. No frozen packet was rewritten. Source design preserves118/36/154 plus18 parent additions, regenerates exact R31 wrapper lineage from held stdlib-only helpers, and has no plan/self hash cycle because R34 plan binds wrapper, not outer. Full main fake still stops at missing public C01 bytes; direct real closure stops later at pyyaml_record_payload. Independent review and actual activation remain separate.

R20 diagnostics independently passed16 sourcefake checks, but review is NO_GO_AS_CURRENT_R4_ROUTE: outputs alone are not consumed by current R16/R14 loaders and their R4 pin contracts. A coherent new R21 assembler/loader/route source chain is being built without swapping modules after validation; baseline102+2 remains a separate immutable lineage. Optional R28_r3 source candidate passed5 focused checks and awaits independent review of all runtime-function fields and full production-map rows. Formal12/3/84 and optional0/16 remain unchanged.


### 2026-10-08 public checkpoint after paired selection correction

SimNow permits one or multiple complete MD/TD groups. Each group is eligible when both ends have a successful bounded connection probe; no eligible group fails, one is selected directly, and multiple eligible groups use the lowest whole-pair latency score. Current selector/handoff and the unregistered 000 C01 V6 source cover single-group and non-first-group behavior. Independent V6 R1/R2 source-fake QA passed 14 tests; no real login occurred and password-rotation confirmation is still required.

M01 R10 independent R2 is GO_SOURCE_FUNCTIONAL_QA_ONLY / ACTUAL_HOLD. Its third, isolated unique-basetemp run passed 19 tests; static review confines writes to tmp_path. Run 1 completion remains UNOBSERVED and the shared-basetemp run 2 is excluded. Root bounded readback matched five review artifacts and two candidate sources; observation SHA-256 9c6ef26949ff199742e0bd12145fbd903641b65c364249b659516872b498ccf8. This is public pin readback, not physical custody, actual activation, deadline, native/provider or case acceptance.

Optional16 R28_r3 independent review is HOLD_SOURCE_FAKE_IDENTITY / ACTUAL_ROOT_BLOCKED: code-referenced module-global content can still change in memory despite the same code and globals-owner identity. The new r4 must bind those values; do not activate r3. L04 R20 diagnostics passed 16 source-fake tests but require a separately reviewed coherent R21 Root route. Historical 102-row maps contain namespace-specific material and cannot be a universal successor digest; new runtime sources must be explicit new held rows. Formal results stay 12 PASS / 3 BLOCKED / 84 NOT_RUN and Optional16 0/16.


### 2026-10-08 M01 R10 actual parent diagnostic and observation gap

Root consumed fresh namespace f016f69ea797499e9831955335502c1f for one authorized zero-write local diagnostic. The canonical child map remains154; 18 parent additions overlap one baseline row, yielding171 held main rows plus237 public context rows. Seven protected files were CREATE_NEW; current R10 once/outer/map bindings were checked in the same hold. The actual parent returned after22.609s with childexit0, capturecomplete, cleancleanup, both source scopes postverified/released, and no retained Root refs. Owner93630 then explicitly exited0. Actual observation7a2b8534ed6326530228c8902f6696d79957516c727fc856ac71761e50c9997a; host observation22db96ab75407e6c1711fe438594c5f8df01f5ee0f19f358c27549b51ed629ef. Hostexit is not provider or case proof.

R8 reported COMPLETED/RETURNED for outer and parsed response; R7 remained UNOBSERVED. Its default route_invocations0 is not an actual business counter. Root did not open raw/private captures; child account/provider activity remains unobserved. Static review found no deterministic R10/R7 namespace or runner-pin mismatch. The current R7 emitter has no frame for normal approved OUTER_CAPTURED results, and R8 only accepts its result frames with RUNNER_RESULT_UNSAFE. An additive R11 finite returned-result protocol is being developed at the existing _safe_result boundary, preserving capture/cleanup/postverify/release gates and zero case/provider authority.

The Root-driver public snapshot index54c3ceb29e20101487d067284c90b511965ec703dd4f9a685ef62aa62581abee permits inspection/compilation only, never agent execution. R10 author index four groups contain27 rows/17 unique paths; the10 activation and13 parent-source entries repeat dependencies and are not23 unique sources.

Optional R28_r4 independently passed6 source-fake checks but is HOLD_SOURCE_FAKE_BUILTINS / ACTUAL_ROOT_BLOCKED (reviewe74edd7d8c8550088dd4bd452ec6b08731feba5751b81d6bd1765a51e7d5c9d2). A source-bound function accepted a custom effective builtin len returning999. This is an identity/behavior gap, not a normal-chain bypass or actual exploit. New r5 must bind effective builtin resolution to a trusted pre-execution baseline; do not activate r4. L04 R21 whole-route composition remains separate work. Formal results stay12/3/84 andOptional0/16.


### 2026-10-08 Optional16 R28_r5 fixed-closure review

R28_r5 independent focus passed8 tests and verified28 bundle members. Decision GO_CURRENT_PINNED_SOURCE_FAKE_ONLY / ACTUAL_NOT_ESTABLISHED; review4cbd6811972a6f0afbe259e6bc79d9f75cf36f5a9709b42c555f65a4eb17a43b. Root bounded readback matched five review artifacts and anchored checkpoint crosspins only, without candidate execution or custody. Two message README/bundle hashes were transcription errors; actual files match the anchored checkpoint, with no frozen-file rewrite. Baseline builtin identity is the adapter-import trusted-host mapping, not proof of pristine host state. The synthetic dynamic getattr(builtins,'chr') edge remains an unsupported generic form absent from this indexed closure; the author README's blanket unsupported-forms-failclosed statement is not approved. No general verifier/isolation or G1 authority follows.

There is no independent000/C01 front-only entry. V6's protected reader avoids.env/credential resolution but boundedly parses a private config containing credential fields; do not claim credential bytes are unread. A separate unregistered transport-only candidate is being developed: preserve protected ACL/locked lease, select/reverify whole pairs, no semantic credential use,.env/private-run/worker/provider dispatch, account/config digest or value output, or case authority. Root's OS-native ACL protection remains required. This does not remove the pending rotation confirmation for login.


### 2026-10-08 000 front transport and M01 R11 actual diagnostics

The additive unregistered `certification_simnow_c01_front_transport_v1.py` defaults disabled. Its ten isolated fake contracts and independent review passed; review9000d5d3e4fdf9a8d698c4a12db34a0926a0aa86f48c01e5273cc14341f9ceac is sourcefake only. It uses V6's protected config lease and current000 selector/handoff. One to eight complete pairs are supported, eligibility requires at least one successful sample on each endpoint, and eligible groups rank by the maximum of MD/TD successful medians, then config order. The30s accepted-result selection budget is not a hard whole-call cap.

Root actually ran one transport-only check through protected bounded config/Win32 ACL/locks and real TCP. Five configured pairs selected index0, degraded=true, after4.484s; context returned and public source pins reverified. The full config containing credential fields is parsed in memory, without credential resolution/use,.env, admission/private-run/worker, SDK/login, registration or order writes. Actual evidenceb8a400f6cae4c0c4f95b6c485e4d97989eba39100d9b83d2d065259ccbbce62c and owner3307 exit0 evidencea55424e3f83dbb6f576a3669e3a7e742baf11e79315cd555469ad99d32d0d374 establish current transport only; login remains closed pending rotation confirmation. No endpoint/account/config/credential values or hashes are public output.

M01 R11 independent focus passed8 with18 unique indexed rows and7 source ZIP members; review50a9c0de34eea771c8af264cda713a479887324e0da513a11a2661f9cf5fcf50 is GO_SOURCE_FUNCTIONAL_QA_ONLY / ACTUAL_HOLD. Root driverR1 stopped before plan creation or parent start; actual exception cause is unobserved. Its alias violates the frozen R11 canonical module-name contract, so the prior static no-blocker conclusion was withdrawn. Extra custody then postverified/released and owner33422 exited0; failed observation54856d25fdad541747e07ed3e835d34037e1b0a3a963dd47b2fbb65cd7f0b723 and cleanup/hostb627e0b04a1e7a800836d6dacd89f914da3915c9d4223526448ef708bdd0638d stay immutable.

New Root R2 snapshot indexd8e7aa34f5a94aac4e29257e9b248faf5a811a20de75648560edd40bc631b857 permits agent inspect/compile only. Root namespace525de48278a948cfad71b66eb7516a31 created8 protected files, keeping old and new sidecars. Canonical child154 plus24 additions with one overlap yield177 main rows; extra250. Actual parent21.735s returned childexit0, complete capture/clean cleanup, both scopes postverified/released and no Root refs retained. R6 postverify and R8 COMPLETED/RETURNED/RETURNED/NONE gate a finite R11 OUTER_CAPTURED observation: outerBLOCKED, both route counts0, nativeUNSET, providerNO_REQUEST_REPORTED, sourceboundtrue, reasonordinal3. Only the prepared public manifest table decoded3 to r28_outer_candidate_captured; outer_reason staysUNREPORTED. These reported fields are unverified diagnostic categories, not independent provider or case proof. Actual98d83cc3173c72fac4c9ef17ec6b0838caa6e1f6a81c8569ceb07a5011db7f5b; owner42598 exit0 ae22a7d762851ef83600b42acadd79cd167b81ce7d1185003ea80a0cabbf8c6c. Raw/private captures were not opened or parsed late. Source-bound finite outer-reason mapping remains separate work.

Optional R5's fixed sourcefake GO has no actual-mode handoff from frozen R27 whole.main; its reader is test-only. A separately versioned retained-handle bounded source session is required, without carrying source_fake_mode/test_fake_active_main into actual. L04 R21 composition is still source work, including explicit R20 template/R19 generated launcher receipt bindings and cold-before-CU order. Formal results remain12 PASS/3 BLOCKED/84 NOT_RUN andOptional0/16. New transport/process diagnostics add zero real case passes. SimNow write/default native account lifecycle remains closed.


### 2026-10-08 rotation authorization and installed software check

The user subsequently confirmed SimNow password rotation and local protected-config synchronization, authorizing continued login acceptance. The earlier pending-rotation condition is removed; do not ask again. The next C01 simulation scope is TD auth/login and orders/positions/funds baseline/final only; order/cancel, nativeJoin and MD SDK/session/subscription remain closed. V6 must freshly select and bind a complete pair before its credential lease.

Root verified the fixed interpreter and470 installed SDK payload rows in1.204s, hashing native payloads without loading them. No SDK import, provider login, config/.env read or admission creation/consumption occurred. Observationc51b1c3280d61a3c71501724e73ec626351a689adf99905288039ada94ac05e7 and owner40945 explicit exit0 record77371b2b7dc948c769fe397ebd303cddf3ed9456e9947dcadec68d37c1f8514d are installed-byte evidence only. V3 Root activation is profile-hardwired; a separate V6 entry and fixed Windows Job CLI supervision are being authored, without mutating frozen V3 globals.

RootHeldSourceV1 R1's aggregate-cap test claim was inaccurate, so review93169ba253793e954af9ce85ebecd499551f943e8e133b3df4b2dbc1fb814e60 is HOLD_PACKET_QA_CLAIM_ACCURACY / SOURCE_FUNCTIONAL_ONLY. R1 stays frozen. AdditiveR2 corrects it and exercises the real counter with8/7-byte fake caps, equal-limit success and over-limit failure before payload reads with both handles closed; this is not a production2GB run. Combined independent focus passed11; review244cd19c6a3f22cca78f0a15be21eaea576cefb19dfa27b8af791501ff7810b7 is GO_CURRENT_PINNED_SOURCE_FAKE_ONLY. Root matched five review files only (0eca151a3853a0706a6075cf375b513a8729affba8bb613120905171ea78c3a3), without producer execution/custody. Caller map provenance, opaque root policy, builtin baseline, wrong-thread close and actual Windows/ACL remain limitations; no R27/R5 integration, Root-ready or G1 follows. Formal12/3/84 andOptional0/16 remain unchanged; login authorization and installed checks now exist, with the concrete V6 entry still required.


### 2026-10-08：SimNow V6 实际准入失败与整链复核修正

SimNow 新 V6 Root activation 及其独立聚焦检查各通过14项隔离 sourcefake tests；独立 review `253c061f3c166788a5bf4418ff17e1f4d4b8df98689573df1aca993e7f19c6e4` 仅 GO_SOURCE_FAKE_ONLY。Root有界核对29个unique公开行、19个V6 manifest行及2个ZIP成员（读回记录 `bf8901a15d2ba1129bd82dc00d0b3d284152611a11765c789e68ba0f0c15e76d`）。初次ZIP member前缀假设错误的assert发生在输出目录/actual之前，按包中exact basename修正后通过；它不是原生或账户运行。

密码轮换确认和只读登录授权持续有效。Root随后实际调用新入口一次，4.750秒返回 `C01_NATIVE_TD_READ_V6 / BLOCKED / admission_lease_failed / writes=0`。公开wrapper事后SHA一致，未确认Job引用组为0；owner59416显式exit0。实际记录 `evidence/iteration41-simnow-v6-root-activation-root-actual-r1-2026-10-08/observation.json` SHA-256 `efdef33e5f162e1679b16ac200a740ab95f63c84a67874fd4306219ec0ae5d4e`，host记录 `7c980365c6e97c88ced92230637bf17e204bacb5033492734de097aa5cd8ecf3`。没有打开raw/private/late capture，没有输出配置、账号、凭据值或相关摘要。实际provider/native业务是否触达保持UNOBSERVED，不声称登录成功或SDK未加载；host退出不建立内层账户/认证证明。本轮一次性状态保留，不能删除或重用V6 claim/Root marker。

公开静态对照未找到V6 Root admission producer与consumer必然冲突：schema、scope、17个绑定、配置组数、canonical JSON、TTL和命名空间一致。`admission_lease_failed`封装未知异常，不能由源码推断本次原因。下一步为独立V7 source generation、独立私有namespace及同call有限stage/class观测；不得读旧失败捕获、复用旧准入或修改V6冻结字节。V6的`read_only_candidate_complete`即使实际出现也只是readonly profile证据：原contract仍待protected actor验证source/native identity、snapshot custody与回调归档，不能直接计为正式33-case C01 PASS。

L04 R21 R1的6项sourcefake测试使用`_test_prepare_action`，跳过production review gate；其包缺少production gate要求的checkpoint.json/qa.json。原README整链声明撤回，独立结论 `HOLD_SOURCE_FAKE_ROUTE_GATE`（review `74e11ceb4ae75465d31564d492fe921fbc74126d50d6429c0d6f9a4b3dc7fb50`）；不执行R1实际准入。R2 successor另出现路径复用事件：作者覆盖了既有untracked `_r2.py`，旧partial字节尚未恢复，不能声称旧文件全保留。当前R2 bytes已在公开包保存，R2停止GO/实际运行；其独立6项测试只记录为sourcefake元数据。后续必须使用未存在的新source/output路径并保留已封存版本。

M01 R12 R1独立7项sourcefake通过但封为 `HOLD_DIAGNOSTIC_METADATA / ACTUAL_HOLD`（review `69ce3f02fbb62439800ab5ad00abaeb744d11b37fbe8406fedc348e13fd69145`）：向R11传前三帧时丢弃13-byte R12 frame，却未恢复stderr_bytes总计数。新R2只修复总字节计数并增加四帧断言；尚未Root实际执行或得知R11真实outer reason。

Optional16独立静态桥接检查为 `BLOCKED_API_AND_PATH_POLICY_MISMATCH_NO_ROOT_ACTIVATION`：379-row公开map有189个D:/temp逻辑origin，全部被R1 policy拒绝；R5/R12仍有直接Path.read_bytes且未使用该session API。518/575/582是sourcefake组合计数，不是当前物理custody。新的固定ROOT_PUBLIC_PINS公开snapshot reader独立3项sourcefake通过（严格-I-S-B-Xutf8），但没有R5/R12调用集成，379个child origin未解决，NO_ROOTREADY/NO_AUTHORITY；原不含-S的作者QA排除，另有严格调用修正包。

用户要求的运营控制先完成公开盘点：`evidence/iteration41-three-venue-operational-controls-public-inventory-source-only-2026-10-08-r1/`封存135 source pins。Binance/OKX固定owner route仍为空；公开材料未建立独立控制回执endpoint。TradeLogger为本地事件/计数实现，operator service/latch是本地控制；服务端权限变更、终止、断连恢复及独立monitor回执来源未由公开材料认证。历史跟踪中的M02/M03、EM01–EM03、TH01–TH06共33槽均NOT_RUN；这不是一次新的私有配置/服务可用性探测，不推断本机一定未配置外部服务。

正式三场所结果仍12 PASS /3 BLOCKED /84 NOT_RUN，Optional16为0/16。本轮没有新增正式PASS，SimNow登录未通过；用户的密码轮换确认不再是阻塞条件。


### 2026-10-08：V8 实际 worker 阻断与 M01 部署副本校验定位

SimNow V7 的有限诊断实际返回 `admission_lease_failed / consumed_marker_create / type_value`，耗时5.157秒，wrapper后验一致、未确认Job引用组0，owner92596显式exit0。实际记录 `evidence/iteration41-simnow-v7-root-activation-root-actual-r1-2026-10-08/observation.json` SHA-256 `b583e7d1b08dfaf28e9c5fc2c5348b215ceaa72bf1d6c8028ceb07e29d529f29`。随后作者和独立公开源码复核均确认V6/V7 admission重建遗漏必填 `configured_front_pair_count`，会在该位置产生TypeError；该确定源码缺陷与V7有限观测一致，但未读取私有捕获来归因V6/V7实际运行。此前“未找到必然冲突”的表述仅代表早先检查点。V6/V7及其一次性状态保留。

新V8只传递遗漏字段，并使用新profile/准入命名空间/runner/Root entry/frontV3/manifest/schema。作者与独立隔离focus各通过8项；新增测试调用真实 `_profile_admission_lease`，用合成文件及假保护叶走重建、yield及三文件二次读取。独立review `4dfb9206d4d6bebfa73157a0ef9d91ca80058a7050618a804c832a44c3deafe4` 为GO_SOURCE_FAKE_ONLY。Root有界核对27个unique公开source、19个manifest row、5份review文件，读回记录 `0081435325f802a0406daa02c4f66cee19b9139f79383ec113acdc5c180fda96`；这些检查未建立账户或native证明。

在持续有效的密码轮换确认和TD只读登录授权下，Root固定字节入口实际执行V8一次，23.937秒返回 `BLOCKED / worker_process_incomplete / admission_failure_stage=none / admission_failure_class=none / writes=0`。wrapper后验一致、未确认Job引用组0，owner48090显式exit0。记录 `evidence/iteration41-simnow-v8-root-activation-root-actual-r1-2026-10-08/observation.json` SHA-256 `32ee30e41db1927044ad017cc909f0cd74d5c81d0d0516ffa42cf699170a1045`；Root driver固定SHA `cd9e4620cb1501d81f9e43483b3f1ac4d86c70390a03b84681020797eb85a189`。外层未打开private/raw/late captures，没有配置、账号、凭据值或摘要输出。这个reason来自candidate阶段的worker-result/lifecycle组合检查，不证明native Init、authenticate/login请求或回调已发生；不能据耗时或none/none诊断推断具体worker条件。旧准入/claim/marker不删除、不重用，V8冻结。

正式C01仍需独立protected actor、同调用source/native/snapshot/callback custody及脱敏归档。source-only设计盘点 `evidence/iteration41-simnow-c01-protected-actor-design-inventory-r1-2026-10-08.md` SHA `9edf361f56808fa4869a42bb268746d89eb45ff9f0e44a6588e79dae5290c3dc` 不提供actor。普通布尔、同进程callback、候选digest/MAC或事后打开issuer-audit不能代替provider真实性和独立权威。V8 profile即使未来出现read_only_candidate_complete，也不能直接记正式C01 PASS。

M01 R12 R2纠正四帧总stderr字节计数，独立7项sourcefake通过；review `5bc1f1d5c78a43fde04d70a6be0e085f9b716afc74be480a50a2fa69c645bdd8`。新Root driver静态复核为STATIC_STRUCTURE_CONSISTENT / ACTUAL_HOLD；其外部源码pin、实际物理持有和授权由Root另行承担。Root核对51个indexed record、36个unique source、14个bundle成员，使用外部固定字节pin及额外CU driver lease执行一次namespace `86f54cdaa04f4d208f2b534f7d0be4db`。创建9份互异保护文件，child map154（118+36），parent union179、extra275；父过程20.625秒，childexit0、capturecomplete、cleanupclean、main/extra及额外driver lease后验和释放成功，owner52094显式exit0。实际记录 `evidence/iteration41-m01-r33-r12-r2-root-actual-parent-diagnostic-r1-2026-10-08/observation.json` SHA `9d7832fdb7c824cff05c080fed051d876b805014de22bb98f9568ca1239e8fd8`。

M01有限返回outer BLOCKED、route0、native UNSET、provider NO_REQUEST_REPORTED；R12 ordinal33绑定171项当前prepared公开源码literal table（SHA `fd34f03bdf56b5cfdcf9f97e8a4725677565a61c4da97fc3af2bf49019f4a092`）。同调用Root从已保留的公开table投影为 `driver_activation_copy`，没有打开raw/late/private捕获；投影记录 `8f74a7aff68078403542a3bf032bca5db4138d6c4260946d72822289830f126a5`。公开源码确认R28旧normalizer只处理R28常量，而R31/R10已生成新的outer；R10替换wrapper gate却保留driver gate，导致模板相等契约与预期生成源码不兼容。观测定位这个组合门，不归因其内部字节/哈希/类型子条件。后续只修复该确定契约，保持原模板pin/lineage、plan/claim/custody和预算，不放宽normalizer去剥离任意源码。

L04新R21 R3已在fresh `_r4_r2.py` 与v7输出命名空间通过独立6项sourcefake；production `load_plan/prepare_action/run_prepared_action` 路由在合成Rootreview和显式fake leaves下得到typed code2拒绝。review `ef76ebd6a421c0f82248ac8d5e57f65822ce1aa8c75b3f031ab8b196fe2587c1` 为GO_SOURCE_FAKE_ONLY / ACTUAL_ROOT_BLOCKED。它不恢复此前被覆盖的R2旧字节，不提供actual Root批准/物理holder接口或code0认证。

Optional16新的fixed JSON同会话consumer独立4项sourcefake通过，review index `81d51f05d24b68eb48d3d2b13b758eb53a77728e0a00cfb5abf41dcf65d31c7f`；379行全部UNRESOLVED，190个repo label与189个temp logical label，C01 helper命中0。R5/R12仍在持有之前读取并验证path，consumer没有生产callsite。`evidence/iteration41-optional16-r5-r12-held-source-callsite-gap-r1-2026-10-08/README.md` SHA `f93e72bddb5eb2a0fa31541e806d5a085208cead653b4d201cfbd04633ba5677` 记录两阶段初始化迁移、CU前置path load和postverify路径复读缺口；未新增无callsite helper或扩大测试，不提供0/16之外的新验收。

运营控制进一步源码分类：EM02本机暂停策略可实现但需provider查询，SimNow EM01交易权限修改/恢复需要管理员控制，EM03服务端强制退出需要服务端/运维控制；M02/M03本机监督器可发起故障恢复，但不能替代真实provider回调。已询问用户测试管理接口/权限范围，登录和可独立开发继续。无新增私有服务可用性探测。正式总结果仍12 PASS /3 BLOCKED /84 NOT_RUN、Optional16 0/16，SimNow C01登录未验收，所有未获准写操作继续关闭。


### 2026-10-08：V9 R2 同调用只读观测及清理结果

用户已确认 SimNow 密码轮换并同步，本次继续授权范围内的只读 TD 登录诊断。
V9 R2 的独立 source-fake focus 通过 16 项；Root 校验 29 项当前公开来源，
并在外层加入 schema-consistency addendum 要求的未观测 lifecycle 交叉检查。
R1 的旧 packet 文件仍在，但旧 source payload 未单独保存，已明确撤回其对
当前源码和实际激活的证明资格；实际使用的是 R2 的固定来源。

Root V9 R2 实际调用耗时 17.437 秒，返回 BLOCKED / worker_process_incomplete。
同调用有限观测为 Windows Job、assignment/stdin/两路 EOF/退出观察/句柄关闭均
为 true，退出码 TWO、Job 活跃数类别 ZERO，未超时、未强杀。Root 未解决 Job
引用为 0，并完成 live assertions 后主进程 exit 0。认证和登录各记录一组
attempt/first/terminal；查询记录三组。progress 为 71 条合法前缀，末尾为
native_stop/end；receipt 为 none，因此 request return-code 字段保持 null。
这些是候选进程诊断，不能认证 provider 活动或确立正式 C01 PASS。

独立静态定位确认：三组查询对应基线 orders/positions/funds 的开始与回调标记；
第三次查询的返回值/来源校验、基线快照、首次 final 查询之前的步骤仍可能失败。
native_stop/end 仅表示 stop_and_wait 调用正常返回，不证明其返回了有效 native
close receipt；progress verified 仅表示前缀结构有效。现有公开有限字段无法唯一
确定失败原因。Root 没有晚读本次私有 failure/capture/audit，后续诊断须在新 run
同调用且保护句柄仍有效时仅投影固定类别。writes=0 是 NO_WRITE 政策字段，
不是独立测得的 native 发送计数。

公开实际 observation SHA-256：
59f3372eb9c7c2ac3a8e788fca6777b5cbce2399c00b357549fb9098dadaca45。
Root host-exit observation SHA-256：
f29620fad5a44b73aac6e4190dfd7c177b738d6c277d1a03f11101801cf9a55f。
归档分别位于 evidence/iteration41-simnow-v9-r2-root-activation-root-actual-r1-2026-10-08
及 evidence/iteration41-simnow-v9-r2-root-activation-root-host-exit-r1-2026-10-08。

正式三场所仍为 12 PASS / 3 BLOCKED / 84 NOT_RUN，Optional 仍为 0/16；
本次进程观测和 source-fake QA 新增正式 PASS 为 0。


### 2026-10-08：dev 逐轮提交原则、历史工作区核对及 V10/M01 实际诊断

用户明确要求相关代码直接在对应 dev 工作区修改，每轮按约定范围验收成功后提交，再进行下一轮修复或优化，避免遗留工作区导致重复开发。该原则已写入全局长期指令、Backtrader 顶部 AGENTS.md 和 SDK 本机 AGENTS.md；SDK 的 AGENTS.md 按其既有 .gitignore 保留为本机指令，未强制入库。Backtrader 已以 857d5531bbbb1e188dfab7d27737eb61e346e281 提交仅新增的九行开发原则。其他既有修改未纳入该提交。

当前实际开发路径为 D:/source_code/backtrader 和 D:/bt_api_py；两者及 SDK 的 Base、Binance、OKX、CTP、Execution、Risk、Monitor、Gateway、ZMQ 九个子仓库均为 dev。D:/source_code/bt_api_py 是另一个 code-optimization 旧副本，本次未修改。历史已记录的 Sep29/30 集成提交均为当前相应 dev 的祖先；不能据此宣称历史工作区的所有未提交修改已归并。

Root 对十个历史 Backtrader 工作区的 135 个改动 Python 路径进行了有界源码比较，仅归一 CRLF：103 个已与当前 dev 已提交源码一致，26 个不同，6 个在当前 dev 缺失。32 个差异/缺失的公开源码静态复核未发现可整批复制的已验收产品逻辑：缺失文件是候选探测、未验证回调证据、测试或未注册的离线 guardian；多处历史行为已由当前更强的关闭/来源校验取代。源码存在和静态比较不建立真实账户验收。归档为 evidence/iteration41-dev-delivery-inventory-2026-10-08 和 evidence/iteration41-historical-worktree-public-source-comparison-r1-2026-10-08。SimNow 仍使用用户已确认的 1–8 组完整 MD/TD 规则，每端至少 1/3 成功，不恢复历史多数或 3/3 门槛。

Root V10 SimNow 同调用实际只读诊断返回 BLOCKED / worker_process_incomplete，固定失败序号 119 对应 position_text_invalid。同调用受保护失败诊断记录 5 requests、5 callbacks、2 auth/login rows、3 baseline query callbacks、0 final、0 snapshots，native-close present；这是候选进程有限诊断，不是 provider 身份或正式 C01 证明。Windows Job 归零、两路 EOF、退出观察、句柄关闭均完成，worker exit TWO，未超时/强杀；Root 未解决 Job 引用为 0，host exit 0。外层未晚读失败捕获。实际 observation SHA-256 为 084aa1720c027f43811c43384b1074c0294c82b7770d819307761d5a2f164178；host-exit SHA-256 为 05373dd4003f117eaeaba0dbdf9c39ad3aab95f20d9f1e631d6a2be5436c0491。随后 V11 仅新增同调用固定字段/类型/失败类别投影，保持 native V2 不变；author 与 independent source-fake QA 均为 23 passed。V11 实际调用尚未执行，其 Root driver 的优化模式检查仍在修复，不能将源码 QA 视为正式通过。

正式 C01 dispatcher V1 因未解决引用可能丢失而 HOLD；V2 保留准确模块及稳定引用，并拒绝同进程重入，其独立 source-fake focus 为 7 passed。该 dispatcher 尚未进入本次 Root 实际路径，正式 C01 PASS 仍为 0。

M01 R14 helper 的独立真实构造源码 focus 为 3 passed，R14 Root-driver R2 清理 focus 为 3 passed。Root 实际生成九个受保护文件后，在 parent 完整来源 custody 进入阶段关闭：main scope 未进入、其 generator 已关闭，extra scope 已 postverify，parent/child/provider 均未启动。Root 同调用有界保护读核对 181 行，全部存在，仅序号 141 的 root_public_source_map_r33.json 与序号 142 的 root_runner_template_r31.py 与声明的 pin 不符。静态定位发现最终 R13 runner/map 写入同一路径，但 parent hold addition 仍继承旧 R10 字节 pin；R15 正针对这两个绑定修复，不能绕过校验。Root 未对未进入的 scope 重试 __exit__，保守引用保持至 host exit；bootstrap 完成 postverify，工具确认 Root session 19561 exit 0。实际 observation SHA-256 为 683087775ae8b55caef32a1e9ddd2df641a7f22c90580c7f65486af0bc72f27d，同调用有限 pincheck/host-exit 请求 observation SHA-256 为 a982ec3e7b83c3c17fa5a9cc70d39acbc22ac255573fd1a1aa47bad45a337f8c；最终工具 host-exit 另存独立归档。

Root-held scope V3/V4 的合计 source-fake focus 为 23 passed；V4 为固定消费者增加同保护句柄的私有软件/support 借用。OKX Root identity R1 的整体超时未涵盖 DNS，R2 新增固定域名的有界解析和同一绝对 deadline，合计 source-fake focus 为 26 passed。二者的源码 QA 均不是实际组件或账户验收；L04 的跨进程私有身份交付、可选组件的固定 worker view 仍在完成接线。子代理并发配置已由 10 改为 30，并读回确认；模型上下文配置未改。

正式三场所仍为 12 PASS / 3 BLOCKED / 84 NOT_RUN，Optional 仍为 0/16；本轮新增正式 PASS 为 0。默认 CTP 写入仍为 NO_WRITE / LIVE_NO_GO。每轮后续提交应记录明确验收范围及证据层级，不能将源码或诊断通过升级为真实账户通过。


### 2026-10-08：V11 R3 与 M01 R15 实际诊断、继续当前失败轮

- 长期开发原则已保存于全局和两仓库 AGENTS：现有 dev 修改，每轮约定验收后显式提交，再进入下一轮；Backtrader 规则提交为 `857d5531bbbb1e188dfab7d27737eb61e346e281`。SDK 子包先提交，再更新父 gitlink；保留已有无关改动。
- SimNow V11 R3 的独立 8-test source focus 通过后，Root 实际 session 35585 运行 21.453 秒，返回 `BLOCKED / worker_process_incomplete`。内部 lifecycle 的 forced_kill=true，使 failure/字段形状读取保持 UNOBSERVED；不能认定本次重现了 V10 ordinal119。两个外层 Job 最终 zero/EOF/reader joined/handles closed，不替代内部生命周期。Root 外层公开文件 postverify/close，宿主工具退出 0，未解析 Job 引用组 0，无晚读取私人 artifacts。实际观察 SHA-256 `b35c0b8e3e07806c8ecfccdd86fc8cd05a520958acb44bc1d52a9b86408f47bd`。
- 公开监督器源码在非零进程退出且 Job 计数正数时立即 terminate；外层已有 Job 计数延迟归零的公开测试模式，但不能据此归因本次内部终止。V12 当前轮修复是在原清理期限内给予短暂 reconciliation，持续非零/未知仍保守终止，不放宽最终生命周期或私人诊断门禁；源修复/测试进行中，未再实际运行。
- M01 R15 的两处最终 runner/source-map hold 修复通过 1-test source focus 和独立静态 GO。Root 实际 session 74920 在 `root_current_plan_prepare` 返回失败，未创建受保护 plan/启动 parent/调用 authenticator/读取账户。prepared R13/R14/R15、hold addition、active source 均已完成赋值；原错误代码没有保留，不能归因。返回后同内存 plan 的有效期已过，仅是后续类别观察。该轮尚未达到实际 parent-map 门禁，未通过 M01。
- M01 调用过程中 Root 一次采样观察 elapsed 465.90 秒、CPU 368.28 秒、直接子进程数 0；这不是阶段 profile 或性能验收。extra 和外层公开文件持有已 postverify/close，prestart cleanup complete，宿主工具退出 0。实际观察 SHA-256 `09f041d09f563225fe72eeb0d2850952c11f4c45244ee26c4d23dbe7d248461f`。R16 当前轮准备优化将使用同一次操作中的私有不可变事实，避免重复重建，保留独立入口的新鲜验证和原时限；实现与 source QA 进行中。
- L04 caller 的公开 map/identity-proof/CREATE_NEW 授权记录 focus 当前 6 passed；R22 child seam/composer 尚未封存，未实际运行。可选组件 TOP R28 入口与 owner-held/worker immutable view 正在集成测试，未实际运行。
- 两个当前失败轮继续修复，代码尚未作为已验收账户功能提交。显式源码/fixture whitelist 已记录，避免广泛暂存未验收代码。正式结果仍为 **12 PASS / 3 BLOCKED / 84 NOT_RUN，可选组件 0/16**；本段所有新增源码/进程/诊断结果增加零个正式 PASS。


### 2026-10-08：V12 R2 明确资金字段失败、R16 实际启动准备与父持有推进

- 当前所有修改继续直接发生在现有 dev；没有新建开发 worktree。长期小轮次原则的规则提交仍为 `857d5531bbbb1e188dfab7d27737eb61e346e281`。单独提交新入口而缺失未提交依赖不能满足可复现交付；V12/R16 的显式前置源码和测试 whitelist 已盘点，不能广泛暂存无关修改。
- V12 首个 candidate 的 Root→V6→V12 函数接线及 runner issuer pin 不一致，已保留 HOLD 公共快照，未实际运行。修正 R2 的 25 个 payload（含 manifest）通过 Root hash/size/ZIP member 核对，作者隔离 QA 8 passed，独立静态 source-only PASS。独立 reviewer 没有重跑 pytest。
- Root 使用精确 V12 wrapper 的 `_parse_activation_args`、`_run_production`、`_validate_v12_payload`，外层持有全部 25 个公共 payload、固定 runtime 及独立 review。实际 session 27686 运行 23.438 秒：仍 `BLOCKED / worker_process_incomplete`，同调用脱敏诊断明确为 funds.BizType、field ordinal 4、str、NUL_ONLY；failure ordinal 119 为 pinned `position_text_invalid`。auth/login 共两回调，三个 baseline 查询共三回调，final 查询/基线和最终快照均为零。worker 诊断的 insert/cancel 请求为零；这是实际 worker 观察，不是独立 provider 签名。
- V12 R2 内部 forced_kill=false，进程 exit2、Job ZERO、EOF/handles closed；两个外部 Job 同样清理完成、读线程结束、无 forced termination，未解析 Job 引用组零。Root 外层 physical hold postverify/close，宿主工具 exit0。公开 actual observation SHA-256 `b005ea4aa824f359d8d817fd20e88730544c5a0a98addd72e71623402ec6e19a`；未晚读取私人 captures。
- 具名公共 CTP 6.7.7 header 将 BizType 声明为 char，Future='1'/Stock='2'；NUL 不能推断为 Future。当前请求只绑定 BrokerID/InvestorID。下一修复为 funds-only tagged unknown/observed representation，并同步 worker/protocol/独立 contract 的 account schema；保持其它四个维度、身份/交易日、所有金额和完整 baseline/final equality 检查。只比较实际观察到的单个 account-currency row，不声明全币种账户汇总或明确业务类型。
- 当前 C01 case plan 没有要求第三方/provider 签名。真实 native auth/login callback、RequestID/ErrorID、本地到达顺序、login 的 FrontID/SessionID/TradingDay 和零写入是验收事项；本地时间不能冒称 provider-issued。缺失的 production Root observation/request-ledger verifier 是实现接线工作，不是新增外部授权前提。正式 C01 bridge 将绑定同调用的 source/native/artifact custody、账号 scope、真实 callback/ledger 与清理；普通 JSON/profile bool 仍不能产生正式 PASS。当前 V13 funds candidate 与该 bridge 尚未封存或实际验收。
- R16 composite 的隔离 fake focus 1 passed（41.64 秒，一条既有 pytest config warning），独立静态 review 记录了 constructor stub，因此不宣称端到端成本。Root 全公共依赖与精确三文件 pins 核对后实际执行 session 1011：plan draft 2.703 秒、composite 29.875 秒、plan contract slice 0.859 秒；这些是一次实际阶段测量，不是性能矩阵。
- R16 实际创建九个受保护文件、进入 parent physical source hold、调用 authenticator/release，并验证 final runner/map 与 R16 helper 双持有。parent 运行 22.094 秒，child exit0、capture complete、cleanup clean、scope released、无 retained refs。Root 外层 postverify/close、宿主工具 exit0，未解析晚期私人结果。actual observation SHA-256 `f8a6e0b474d21734ddf14a946b4e4298ea914f1d1a5bed9f11e5830def2b780a`。
- 该 child 的 outer result 仍为 BLOCKED，198-literal 表 ordinal155=`r13_source_map_binding`，route invocations=0、provider UNOBSERVED、正式 PASS=0。Root 返回后的同内存 runtime-map 校验三条件为真，不能代表 child 状态。源码追踪随后明确 R13 gate 使用了 R28 的 34-row case-source map 参数，而非 R9/R4 的 154-row runtime map；下一修复从同调用 held entry 读取 descriptor 绑定的确切 runtime map，不 origin fallback，不放宽原校验。
- L04 R22 完整 child runner/R11 successor/registration closure 正在实现；必要新增公共行将以最终固定 source-bound 数量封存，不为保持临时 135 行而遗漏依赖。注册限定于同一 fresh Root handoff 目录的受保护 registration child。V5/caller 的现有 focused QA 分别 7/8 passed，完整实际路径尚未验收。
- 可选组件 Root entry 正在跑真实固定 source transform 的 fake focus。Root 额外提供 cProfile.py/profile.py/pstats.py 三个固定软件 opaque hash/size 快照；不是 runtime/provider 验收，子代理禁止解析或执行这些 opaque bytes。组件实际矩阵未运行。
- 正式结果仍 **12 PASS / 3 BLOCKED / 84 NOT_RUN，可选组件 0/16**。以上诊断与启动准备增加零个正式 PASS；保持每轮代码验收范围与账户案例验收结果分开记录，失败案例继续当前修复轮。


### 2026-10-08：前置选择轮已提交，V13 资金快照真实验收仍失败

- 现有 `dev` 完成一个独立 accepted round：`79560db367196678ba558b3c969db8c85ff03259`（parent `857d5531bbbb1e188dfab7d27737eb61e346e281`）。精确七文件为 runtime front probe、000 paired selector、三个相应测试、`.gitattributes` 五个指定路径 eol 规则以及本轮公共记录。指定 SourceQA 三文件 64 passed/0.96 秒，一条既有 pytest config warning；暂存后逐文件核对 Git checkout filters 输出等于已验收原始 working bytes。提交后五个源码/测试和 attributes clean、index 空。该轮只接受一组/多组完整 MD/TD 的 reachability/latency 选择契约，不能作为 C01/provider PASS。记录见 evidence/iteration41-simnow-paired-front-dev-round-2026-10-08.md。
- V13 funds-only tagged BizType 25-file closure、ZIP/pins 均核对；作者和独立 SourceQA 均 35 passed。独立 review SHA-256 `4a627459c07165df1e21ee297be39f73b209d1f6d55d364313f5969329412047`，未放宽其它维度/身份/金额和 baseline-final full-funds equality。
- Root 原 profile 真实 session 34535 耗时 21.344 秒，仍 BLOCKED/worker_process_incomplete。认证/登录两回调，三个基线查询三回调，没有接受快照/最终查询。failure ordinal=0（unclassified）、position-text projection=UNOBSERVED，不能宣布 BizType 已通过账户验收或推定 exception cause。actual SHA-256 `11e7ff6a4486e3426b924aee939624e189c402154543b0ed399c8de3c2f723b1`。内部 exit2、Job ZERO、无 timeout/forced kill、EOF/handles closed；两个外部 Job clean，未解析引用零。Root physical outer hold postverify/close 后宿主 exit0，host evidence SHA-256 `b370ed9823ac90eee014ee2d24fc53cd40a6ee36f6817b1a43a35299c6daaa1e`。未晚读私人 captures。
- 后续公共 synthetic fixture 调用实际 `worker._private_snapshot -> protocol.encode_private_snapshot_artifact`，明确复现 worker 持仓 schema v1 与 protocol 要求 v2 不一致，产生 `private_snapshot_position_schema_invalid`。这是确定的源码错误；尚不能认定为上述真实 ordinal0 的唯一原因。下一同一资金快照修复轮仅对齐该 schema 与重绑必要 successor closure，必须用完整快照管线门槛，不能只重复 projector 局部测试。
- 资金轮未接受，不提交为账户功能。正式 Root C01 bridge 保持下一独立接线工作，不与本次 schema 修复混合。正式总数保持 **12 PASS / 3 BLOCKED / 84 NOT_RUN，可选组件 0/16**。


### 2026-10-08：两轮闭包已交付 dev，V14 worker 完成而父层仍阻断

- 只读策略源闭包轮提交 `d283ec9d9d059846a0845705b2d45f0de57f1cce`（parent `79560db367196678ba558b3c969db8c85ff03259`）：六策略、六 common 模块、共享测试的单个 suite-root hunk、指定 eol 规则和本轮记录，共十五文件。十三源文件与既有公共 828 passed/1 skipped fake/offline checkpoint 完全一致；本轮指定 isolated SourceQA 最短 C01 typed-plan 节点 1 passed/0.17s，synthetic complete plan 仍不许可 dispatch/certification PASS。记录 evidence/iteration41-simnow-readonly-strategy-dev-round-2026-10-08.md。
- V12 R2 监督诊断闭包轮提交 `5bcd3b6170a0792d5375f28649b85b48020291ac`（parent `d283ec9d…`）：剩余二十 pinned source prerequisites/R2 files、四份公共 evidence、指定 eol rules、round record，共二十六文件。所有二十五 payload size/hash 均匹配；源和四份 evidence 暂存后的 Git checkout-filter bytes 匹配验收 raw bytes。指定 isolated SourceQA supervisor 文件加 C01 typed-plan 节点 **7 passed/0.76s**，一条既有 pytest warning。独立静态复核 PASS，Root 实际诊断 isolated funds.BizType/NUL_ONLY，完整清理。接受诊断设施及有限失败投影，不接受账户/C01 功能。源内既有混合 eol、Markdown hard-break 和 EOF blank-line 在普通 `git diff --check` 下产生 whitespace 提示；保留精确已验收 raw bytes，没有把该输出记为通过。记录 evidence/iteration41-simnow-v12-r2-diagnostic-dev-round-2026-10-08.md。
- V14 完整 snapshot producer 管线修复只接受 SOURCE_FAKE_ONLY（作者/独立复核 3/3）；Root 真只读 session18175 耗时19.829秒。inner worker exit0、typed receipt、candidate_transport_complete；auth1/login1/queries6（均终结 callback/return0），progress94/end，receipt reported order/cancel0。父 profile 仍 BLOCKED/candidate_internal_error，未知具体 owner/contract gate；不能认定资金语义或 C01 正式通过。actual SHA `2dd68629a9e5e351443000a5b1edc9f428bd3007ace568bda63df70d3e347500`。两 outer Jobs active0/readersjoined/EOF/closed，无 forced termination；Root outer physical hold postverify/close后宿主exit0，无 retained refs，无晚读私人 captures。host SHA `eeb2747dd42d34de71ca21756fe4ac07fa8a4ca0d92810d28e9b39ecab1f14ea`。
- 公共复核发现 issuer 直接调用 owner 的 tree/artifact API，owner._OwnerError 与 issuer._IssuerError 不同，预期有限 owner failure 会落入 generic candidate_internal_error；这是确定的错误映射缺口，但本次真实具体 owner gate 未观测，不能据此推定原因。下一 successor 必须覆盖真实 parent postworker sourcefake 并同调用投影有限阶段/代码，不放宽 ACL/tree/contract。
- OKX M01 R17 session27502 在构造真实 R14 adapter 时抛 ActiveOuterActivationBlocked，authenticator 未调用、业务 parent 未启动；samecall未投影有限 code。main/extra/outer source holds均清理、宿主exit0。actual SHA `b52c7121f3c8ea6dc058f0d4d3ebaf2af1a0cbb74dda1b4700262ef03852b5ca`。公共追踪指出 R17 prepare 临时变换已恢复，而 R14 constructor 重新 compose 使用旧源；R18 正在覆盖真实 constructor 并复核，同样不能作为 M01 账户 PASS。
- 现有 dev、无新工作区；每轮接受之后明确白名单提交，再继续下一轮。SDK/package 本时段无新增提交，原 unrelated dirt 保留。正式累计 **12 PASS / 3 BLOCKED / 84 NOT_RUN，可选组合0/16**。


### 2026-10-08：M01 R18 实际构造成功，内层持有作用域仍缺少两项支持源

- R18 helper/test/Root draft frozen pins 分别 `f9dd76909adeff5b0f6e76a9664c427b213e10a2915109e1f7dda32b1ea47902`、`307d02b624aa158f81241fb64ac4fdb9dc25155d2a903a860352441773e791cf`、`7333976ea4cb34ed94edb160b775a587aee8e2e227821b6da1747e7e4bd1e719`；作者指定 isolated SourceQA **3/3，97.21s**，既有 warning；独立静态复核 clear with limits，review SHA `bb2eb49b4e1926d95876e367b4abf5c0e43d04bb58560c0437eb2da37b91b683`。源 fixture覆盖真实 R14 constructor/R13 recompose，未覆盖完整 R31 preparation。
- Root实际 session75457 真实 R14 constructor在本轮变换下成功19.016s；parent随后23.422s完成，protected CREATE_NEW9、auth/release调用、parent185rows/extra294rows，R18 helper与154 runtimeMap等绑定检查true。inner返回 exit0/cleanup clean，但 outer ordinal132 exact `r13_held_missing`、route0、provider UNOBSERVED、strict cases0。actual SHA `12e80748fa9536e56c3c3cf3be86fdd74f0ec31231c836933e6d71d2d0e938cc`。
- main/extra custody均postverify/close、scope released、没有 retained refs；Root额外物理hold postverify/close后宿主exit0。host SHA `11aff570a7e7b2229739e93354b20624e3f831b49774a314e73979fdf8c490f3`。未读私人 captures、未晚解析结果。仅证明真实构造接线和监督诊断清理，不是 M01 账户验收。
- 公共独立追踪确认内层 R28 run_prelaunch 的 CUV2 held map独立从154 canonical child pins（118public+36software）构造，不含 R17 runtime source-map file和R17 helper；Root parent持有这些项不能自动流入内层。generated verifier先查runtimeMap，后查helper，两处均可能映射相同 r13_held_missing；本次ordinal不能独立指出具体callsite。下一R19仅添加这两项精确、单独pin的inner physical support rows，保持154 canonical admission map/count，必须用完整generatedouter/run_prelaunch/selectedmapdispatch sourcefake检查正向、缺项和篡改。
- 运营控制盘点 evidence/iteration41-operational-controls-inventory-r1-2026-10-08.md 已落盘：M02需受控真实disconnect/reconnect事实；EM02本地可控但当前operator模块仅offline_fake；EM01账户admin disable/restore和EM03服务端logout回执仍需已询问的控制入口。已有monitor/risk/execution/gateway local APIs不自动证明账户/提供者事实。现有optional矩阵仍为synthetic0/16，需完成实际绑定；没有新增用户信息问题。
- dev HEAD保持 `5bcd3b6170a0792d5375f28649b85b48020291ac`，index空，未新增工作区。M01 precursor/R18小轮交付闭包见 evidence/iteration41-m01-r33-r18-dev-delivery-closure-r1-2026-10-08.md；尚未新增M01 source commit。正式总数 **12 PASS / 3 BLOCKED / 84 NOT_RUN，可选0/16**。


### 2026-10-08：V15 真实运行定位到 owner 树 ACL 契约不一致

- 上一goal turn是progress：交付三轮dev代码、真实V14/M01R18证据改变下一修复动作。本轮保持全部99case+optional16原目标，dev HEAD `5bcd3b6170a0792d5375f28649b85b48020291ac`、index空、无新worktree。
- V15 owner exception边界修复作者/独立SourceQA均**4/4**，一条既有warning；完整fixture真实调用 `_run_candidate -> owner._verify_tree/_read_snapshot_artifacts -> contract recompute`，只fake底层文件/API/账户/transport。25file/19manifest+ZIP全部match。pins SHA `52a59d0bd8533b7e03bb1bd5f0ba89d4e7c9081913d6d003dc7bcf20ec74f5b3`，review SHA `4e6f4ebf5f5cc7d95e62251f231f48363d6a65fc67a0f1baaed216b53897d45c`。
- Root session62210本次真实readonly运行20.969s：worker typedreceipt/exit0/candidate_transport_complete、auth1/login1/queries6/progress94/end、reported writes0；父层BLOCKED/candidate_owner_validation_failed，finite stage=`verify_tree`，code=`private_tree_acl_or_identity_invalid`。actual SHA `cd87d7fc2d60fc1e4d4c2dbb19bb74307fe6f1a5302a49457ed78eee7de74772`。两外层Jobsactive0/readersjoined/EOF/handlesclosed、无forcedkill，Rootouterphysicalhold postverify/close后hostexit0；无 retained refs、无晚读私人capture。host SHA `6a8d241b03d71ddbc808934e77b37fab45390f95c7a4a59677c6c326ced24a56`。
- 公共源码明确workerNativeV4 `_PrivateAcl`生成 `D:P` protected evidence进度/快照，而ownerV6递归walk对evidence所有child要求inherited=True；sharedprivate.verify_acl严格检查protected flag与inherited相反和exactACEflags，因此已知protected evidence的消费规则不一致。这是source契约缺陷；本次具体失败文件/ACL子条件未投影，不作路径归因、不读capture。下一独立owner/issuer successor拟标V17（保留V16Rootbridge槽位），用实际ACL判断代码的synthetic描述符复现，并只对齐protected evidence与SDK-inherited nativeFlow。严格SID/oneACE/fullcontrol/reparse/identity不放宽，sharedprivate/CLI保持冻结。
- V16Rootbridge仍是source plumbing：ContextVar一次stage、typedpending/nonce、native八请求ledger和commonprojection检查；物理postverify/Rootaccount-witness producer及issuerhook未实现，producerhash空，不能mint正式PASS。其最终Rootentry需在执行issuer的同一进程完成stage/context与custodypostverify，不能假设ContextVar跨subprocess传播。不存在第三方监管签章/外部ledger要求。
- L04R22root十输出transform in-memory已完成，childclosure/pins未freeze所以fixedfiles0/10；caller十项sourcefake通过、V5/nonce suffix-b/九源identityview准备，仍未接真实链。optional582map已通过scope构造，下一R27review validator scope-entry gate，未Rootactual，不能accept16组合。
- 后续dev交付盘点已派发：V15test依赖未tracked的 `tests/unit/runtime/test_certification_simnow_c01_v2_contract.py`，必须纳入已验收fixture闭包；不能孤立提交新test。正式总数保持**12 PASS / 3 BLOCKED / 84 NOT_RUN，optional0/16**。


### 2026-10-08：V17 真实只读流程推进到收尾 admission 句柄复读缺陷

- 本轮是progress：真实V17证据将下一动作定位为三项同句柄复读EOF，而非继续修改ACL。dev HEAD仍为5bcd3b61，index空，未新增worktree。当前轮失败继续修复，未将未通过profile作为accepted提交。
- V17 R2核心25及support5全部pin/ZIP一致；作者及独立focus各2/2、一条既有warning。R2 pins655415d924935837353f1b0395546f08f78aa5dd44f2048284fbd670d121e9b5；独立review b6d616884ec62b5a13e650fa23e8e7a194e29c3e2d19e1a627e1a63b2b10494b。clean-dev最小名单21项，旧V15项仅为回归测试依赖，未重新接受旧失败profile。
- Root session96903实际27.75s：auth/login+六查询完成、typedreceipt/worker0/end94；parent BLOCKED/admission_source_changed，post-worker stage/code均none。actual SHA736f94e8f92d4efb2abeaba4399730650fcd0ab35368107f21d4023d96dd5578。两Jobs0/EOF/joined/closed/noKill，Rootouterhold postverify/close成功，host0/no retained refs/no late private read；host SHA0e09ddc6832e84431d01bb3ffc809c09525b82737f68fdcd1b31955db73faaf4。
- 公共源profile admission lease1298正常yield返回后1304再次ReadFile同admission handle，未seek0；marker/claim同样需要复读。冻结CLI bounded reader按当前cursor读，因此EOF会被误判为source changed。这个source-defined分支在candidate body正常返回后执行；不晚读private audit、不把该inference当正式C01 PASS。新V19专门修复三handle checked rewind/ACL/identity/bounded reread，sharedCLI/private/NativeV4不改，完成真实验收后提交本轮。
- V18正式Root接线draft并行实现：原ExitStack内fixedcustodyhook、同进程scope/ledger/postverify、producer真实retained source/runtime/artifact handles。V18也需同窄rewind修复；producer pin尚未最终冻结，当前无formalPASS。
- L04 R22 child10+Root10已落盘，fullcaller/V5仍在接线并修复原R21review与activeR22coord混用；原review只针对原源，activeR22必须独立绑定held composition，随后独立review及actual。optional entry正在修真实原main attestation和worker snapshot闭包，不把testfakehook或prefix拒绝当实际入口完成。
- 正式总数保持12 PASS / 3 BLOCKED / 84 NOT_RUN，optional0/16。完整99case+16组合目标保持active。


### 2026-10-08：V19 只读修复验收通过并已提交 dev

- Repository/branch: D:/source_code/backtrader / dev. Accepted commit: f46234e338c774d017eb58853f32cfd7310ff9d5; parent 5bcd3b6170a0792d5375f28649b85b48020291ac. Exact 23-file whitelist delivered; index empty. Fifteen new source/test files include only three V17 EOF regression baseline files. No SDK/package commit or new worktree.
- Acceptance: independent source focus 8/8; clean non-Git HEAD snapshot + exact current closure 8/8 (0.72s; one existing pytest config warning). All 28 payload/support pins and all 25 committed filtered checkout payloads matched. Two tracked watchdog helpers use explicit CRLF checkout rules; new source/records preserve raw bytes.
- Root actual V19: PASS/read_only_candidate_complete,23.328s,auth1/login1/query6,worker0/typedreceipt/end94. Jobs2zero/EOF/joined/closed/noKill; outerCUv2 postverified+closed; tool session1311 host0; no retained references or late private capture. Actual SHA66988070dbc9dbf75373a18c245cf1af2634c8be87938eeaa41ec9a6bf0021f2; host SHA1e2a27c3d45c4790d7af5fe2cc937c61db7c728461473f54d9a70a3d14b73107.
- This accepts the bounded readonly repair round, not formal SimNow C01. Formal totals remain12PASS/3BLOCKED/84NOT_RUN; optional0/16. Next round is V18 same-process Root custody/ledger/entry: producer571036d79815f7791bc6917f7afbf87ff8acd9806dc0556a80b9b39d34553f26, bridgec703e509a73aeb5e4b1e37fd911a8a3ccd4211fe1ce9cf2cdcf65edffe586cef. Combinedsourcefake30 passed; final packet and independent review still pending. Keep officialC01PASS0 until actual receipt/cleanup acceptance.
- Existing dev checkout workflow remains: implement current fix, finish agreed acceptance, stage only accepted explicit paths/hunks, commit, then next round; package commits before parent gitlinks. Preserve unrelated dirt and reconcile verified historical worktree changes.


### 2026-10-08：M01 R19 actual 定位运行映射绑定失败，V18 正式启动包装待补齐

- 上轮是progress：只读V19真实PASS及clean-source8/8已经提交devf46234e338c774d017eb58853f32cfd7310ff9d5，本轮从该提交继续；index空，未新增worktree。
- Root M01 R19 session96967：parent14.187s，真实constructor15.969s；canonical154/parent186/extra295。返回固定ordinal167/r19_runtime_map_binding、reportedroute0/providerUNOBSERVED；actual SHA06fd3e3badaa43e8a9d0867063d337d7c48863b843f8b91ff345da42fe07d605。两source/runtime scopes已postverify+closed，child0/cleanupclean，Roothost0/ref0；host SHA78670d6321347d7096bcdc2ef799b4db13ea6c66cc69f311f1293f9c7f84b5ff。无lateprivatecapture。M01未验收，不提交失败入口；新R20检查公共源中的map/self/plan绑定，必要时增加有限分组错误码，保留所有校验。
- V18 R1 publicentry packet已经冻结：27map+entryself=28源，三个focus文件31/31；独立匹配及复跑31/31。它尚无Rootactivationwrapper，不能直接宣称actualready。author现补additiveV18wrapper：freshprotectedregistration、boundedouterJob、同进程entry、opaqueCaseReceipt在所有contextclose后序列化；R2完整closure完成及独立GO后Root实际运行。核心entry/producer/bridge保持当前pin，正式C01仍0PASS。
- L04 end-to-end仍缺typed sourcefake hold view；source validator不改，caller/seam通过显式testtoken绑定typedfakeview，使全链到真实validator/fakebottom。optionalentry只完成map prefix2tests并在profiler gate前拒绝；profiler/cache opaque bytes未在该成功run解析。active-only64rows已定位为publicrepo44docs/16scripts/4tests，下一步冻结入口及具体Rootactual接口，不能将prefix测试计为G1/16组合验收。
- 正式总数仍12PASS/3BLOCKED/84NOT_RUN，optional0/16；全99case+16组合goal保持active。当前turn是progress，实际证据改变下一动作。

### Iteration 41 V18 R2 source review and M01 R20 finite actual observation (2026-10-08)

The accepted dev checkpoint remains f46234e338c774d017eb58853f32cfd7310ff9d5. The additive V18 activation R2 wrapper closure (29 source rows, four focused tests) independently passed 42 source/fake tests; actual formal C01 remains pending. Its independent review is iteration41-c01-v18-root-entry-activation-independent-review-r2-2026-10-08.md under the Iteration 41 evidence directory. Root's external custody driver and clean-source closure checks are separate pending work. No formal PASS was added.

M01 R20 was invoked once by Root. The actual returned finite diagnosis changed from R19 ordinal 167 to ordinal 164, r19_canonical_map_shape, with zero route invocations and no provider request reported. Both Root custody exit calls returned after postverification and their retained flags were false. The public recorder then failed because its failure-record assignment was outside the exception handler; a recovery assertion also failed before writing the original complete observation. Child return code and parent cleanup fields remain UNOBSERVED and must not be reconstructed by opening private captures or late results. Root host session 23012 explicitly exited 0, as observed by the tool. The bounded public observation is iteration41-m01-r33-r20-root-actual-parent-diagnostic-r1-2026-10-08/observation.json, SHA-256 bb917da586265e7b7fc53b336339f52fc96804d987076f2e553947f2a85ec268. R20 remains frozen and unaccepted; continue the actual main map-contract and recorder fix in a fresh source namespace, without rerunning or committing the failed R20 profile.

### 2026-10-09：000 三场所穿透认证三件套化完成（96/99 PASS + 16/16 拓扑）

本条记录当前实际交付形态。每个用例目录只有 `config.yaml + <ID>_strategy.py + run.py`，命令
`C:/anaconda3/python.exe cases/<ID>/run.py`（干跑自检）/ `--live [--allow-write] [--allow-dangerous]`；
退出码 0/1/2/3 = PASS/FAIL/BLOCKED/UNKNOWN；证据写入 `cases/<ID>/evidence/*.json`（git-ignored）。
公共层为每场所一份 `certlib/`（约 500–900 行：envfile/context/runner + binance_client/okx_client/ctp_client
+ monitor/validation），替代此前逐案例 Bespoke 候选管线；旧候选代码（binance `_certification/` 等）仍在树中
但不再被新流程引用。

**真实结果**：三场所 98 PASS / 1 BLOCKED / 0 FAIL / 0 NOT_RUN。**用户于 2026-10-09 明确接受 98/99 作为
最终交付**（最终交付记录：evidence/iteration41-000-three-venue-certification-final-delivery-2026-10-09.md）；
EM01 受限密钥路径保留为将来可选翻转。r21 快照
（docs/.../evidence/iteration41-three-venue-99-case-acceptance-tracking-r21-2026-10-09.{json,md}，每例证据
SHA-256 + r21-case-evidence/ 归档）绑定 commits: backtrader dev `1048cdd4`、bt_api_ctp dev `a497bab`
（另含 SDK 父仓 gitlink `7312e718`）。仅余 1 处 BLOCKED：Binance EM01（Demo 密钥具备持仓模式权限；加入
`.env` 的 `BINANCE_DEMO_RESTRICTED_*` 受限密钥即翻 PASS，代码路径已就绪）。EM03 已通过"操作员授权场方
登出"（ReqUserLogout→连接终止→幽灵会话查询失败→新会话恢复）实跑翻为 PASS；E01 已通过**标准引擎**在夜盘
时段实跑翻为 PASS（真实 CTP 资金拒绝 error 31，合约缺少资金 2035244.51；前三笔驻留冻结保证金）。运维要点：
SimNow 标准前置（3000x）仅在交易时段（如夜盘 21:00–23:00 北京时间）TCP 可达，7x24 前置常时可达，用例
自动落到先可达的完整 pair。

**可选组件 16 拓扑全通过**：`examples/000_live_certification/optional16/`（spec/gateway_server/gateway_client/
components/run_matrix + README）。真实矩阵 binance C01+T03 × 16 组合全 PASS（`acceptance-matrix.json`）；
网关能力验收 `gateway-capability.json` PASS（双客户端同会话同 pid、订单归属、坏 token 拒、停服写请求抛
GatewayCommandUncertain 且场侧确认零订单、命令 journal 入档）。组件走真实 dev SDK 入口（DurableRiskGate /
ManagedExecutionFacade+SqliteExecutionStore / DurableOutbox），未启用组件不导入（imports_observed 佐证）。
诚实缺口：无请求去重/防重放；仅 localhost+per-run token；`bt_api_gateway` 的 router/receipt 链未接线；
组件接线为 binance 参考，okx/simnow 保持直连认证。

**场所引擎实测要点**：SimNow 7x24 前置持续撮合、挂单即队列、回报(OnRspOrderInsert)可能缺失→以场内侧订单
查询为受理判定、OrderRef 需时间戳唯一（跨会话查询保留历史行）、查询偶发超时与 -2 流控（读重试、参数化
attempts/backoff）；OKX Demo 价格带实测仅约 ±0.5%（用 /public/price-limit 取带）、下单端点存在 50013
Systems busy 时段（同 clOrdId 幂等重试、51016 即已受理）、错误需透出 data[0].sCode/sMsg；Binance Demo 本机
时钟慢约 8.8s（服务器时偏补偿必需）、双向持仓模式。

**提交链**（dev）：SDK `a497bab`；主仓 `285aac68`（v2 方案）、`8f668fca`/`595daa04`/`8f721384`（SimNow）、
`3bf6a37d`（Binance）、`b8d492f5`（OKX）、`fadcfb81`（optional16）、`d3ebad4b`/`3f017017`（r21 快照与记录）、
`b89539a5`（EM01 受限密钥就绪）、`9ce049ea`（EM03 场方登出）；SDK 父仓 gitlink `7312e718`。遗留旧代码清理
（用例目录版本碎片被旧测试按字节断言引用，属历史证据工件，移动会破坏历史可验证性）与 okx/simnow 的网关
泛化为后续独立轮次事项。

## Iteration 42 — examples 012–015 four-file standard and simulation penetration (2026-10-10, in progress)

Plan and evidence live under `docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/`
(迭代计划.md + evidence/). Every example directory converges to the standard four-file form
(`README.md` + `config.yaml` + `<name>_strategy.py` + `run.py`) with `run.py` supporting
dry / `--replay` / `--live` and exit codes 0/1/2/3; evidence JSON is written to each directory's
git-ignored `evidence/`. The all-eight dry/replay sweep and the registered offline smoke are green
(report/evidence: `evidence/r9-offline-sweep-2026-10-10.md`).

Commit chain on `dev`: `eb3da84f3` (R1 013_3 + SimNow registered-sim chain; `backtrader/stores/btapistore.py`
gains the additive `allow_zero_login_response` passthrough, default off), `7cfad68bc` (R2 012_1),
`90cf8914a` (R3 012_2), `0150641a3` (R4 013_1), `e91e3638b` (R5 013_2), `8c067982b` (R6 014_1 strict
feed-sealed live adapter) + `8c5414496` (bounded feed quote capture) + `a7d2cfc52` (R7/R8 observation-tier
amendment), `adb1fb7a9` (R7 014_2 observation tier + live-entry hardening), `c13177459` (R8 015 tick
observation tier + watchdog stop-loss fix), `972a183b2`/`7b68e19be`/`41929f556`/`92d5a3378` (R9 offline:
sweep record, tracker refresh, Monday argv pre-flight, first-run rehearsal records).

- SimNow execution for this iteration goes exclusively through the direct registered-sim narrow admission
  (`simnow_direct.py`, vendored byte-identical in five example copies with drift guards; the Store/
  managed/production write routes stay closed per plan §5.1). One SDK admission authorizes one instrument;
  cross-leg strategies switch the arm (disarm → arm) strictly between writes and record `arm_history`.
- Live entry hardening (R7/R8): canonical checkout `sys.path` fence, Python 3.11 interpreter guard
  (`live_tier_requires_python_3_11`), dev-SDK source preload before any `bt_api_ctp` binding (importing
  `simnow_direct` eagerly builds the CTP wrapper class), evidence scope-fault classification
  (`BLOCKED / live_event_clock_outside_run_mapping` instead of an UNKNOWN crash), and the R8 watchdog
  stop-loss fix (persistent `cerebro.runstop` press plus the pre-run budget check
  `observation_window_exhausted_before_run`).
- R4 registered the §4 defect fixes for 013_1/013_2: exchange-metadata close offsets (`close_offsets`
  param), refusal instead of blind close-price pricing when the one-book is missing, and a monotonic
  `deadline_clock` for live order/holding deadlines. `run_runtime.py`/launchers of 012_x/013_x/014_x/015
  were rebound to `legacy_runner` so the registered LOCAL_REPLAY_ONLY routes keep working after the renames.
- Options live tiers (R6–R8): 014_1 is a strict feed-sealed **write** drill (run-scoped non-synthetic
  `ClockMapping`, sealed `BarEvidence` + bounded quote capture, per-leg arm switching, one-shot drill);
  its first real pre-write chain ran 2026-10-10 05:44 Beijing on 7x24 and was cleanly BLOCKED at the
  exchange-limits gate with zero write. 014_2 and 015 are decision-only **observation** tiers per the
  R7/R8 amendment (014_2 seals real minute bars with captured quote windows; 015 streams real ticks into
  the cohort strategy); `--allow-write` is explicitly BLOCKED on both. The 015 observation PASSed for
  real (ticks on all three FG legs, zero write; cohort admission stays `FAIL/NOT_ADMITTED` because the
  direct CTP lane carries no `ctp.quote.v2` attestation, which this iteration never fabricates). 014_2's
  real chain reached sealed bars but the 7x24 environment's event clock is ~47.9h stale →
  `live_event_clock_outside_run_mapping`; the standard-front session window is its acceptance path.
- Pre-Monday fix round (2026-10-10, commits `1477ad469`→`71089e7c6`, docs through `c93b5a5f6`): the
  consecutive bounded 7x24 rehearsals cleared the pre-order gate stack end to end and produced the
  first-ever native fills for 013_2 (both legs filled; the run then died on the dual-side close
  mapping, fixed at both the strategy layer and the core `position_modes` validator with harness
  regressions). Also: sealed-bar provenance wiring for 013_3, the store's typed query-evidence
  projection for the broker gate, GFD + `field.RequestID` on the direct lane, front-selection failure
  details persisted on all six live entries, the session-aware selector ranking corrected in docs
  (standard inside CZCE day windows, 7x24 outside — six-copy design since `eb3da84f3`), and a missing
  `notify_idle` pump added to 013_3's entry (every earlier live run stalled in
  `RECOVERING/drain_reconciliation_required` because the drain reconciliation retry loop was never
  driven). A bounded watcher re-ran the 013_2 drill plus a 013_3 drain rehearsal when the SimNow
  fronts returned (results in the Demo-side closure bullet above); all eight directories' dry/replay
  were re-run green at the current HEAD.
- Demo-side closure (2026-10-10 evening; main-repo `ac9b76ea3`/`91c7e63bf`/`906ffe57b`, SDK
  `636addc5`/`5163cbb7`): both crypto gates are closed. 012_1's reissued qualification window plus
  the submit-race/fee-flag SDK fixes produced `MECHANICAL_DEMO_SMOKE_PASS` (`447e9a10`; regression
  `82a55b70`). 012_2 got an operator-acknowledged bounded mechanical-smoke lane (real-book-priced
  single pair; the research path-model gate stays fail-closed) and passed for real (`f28557f7`);
  its defect chain (Decimal/float submit boundary, transient-stale risk read latching the kill
  switch, refresh-lane/placement conflicts at the SDK risk-freshness gate, stop reconcile racing a
  just-closed order — now a bounded retry) is fixed with regressions. The returned SimNow fronts
  let the watcher capture the 013_2 drill completing a full round trip on 7x24 (`3583ad31`: both
  legs opened and flattened; the close-mapping fix is validated on the real path). Same-HEAD
  re-verification: 8/8 dry+replay, registered smoke 12/2(iteration-41 baseline)/3,
  runtime+stores 1462 passed / 36 skipped / 0 failed.
- Acceptance status: 015 observation PASS recorded and both crypto Demo round trips closed
  (012_1/012_2, above); 013_3/013_1/013_2/014_1 (write drills) and 014_2 (observation) await the
  Monday 2026-10-12 session windows per the committed `evidence/monday-live-run-plan-2026-10-12.md`
  (six serial steps, each command argv-pre-flighted; 013_2's 7x24 rehearsal already passed end to
  end). R9 finalization (tracker regeneration, record appends, close-out commit) follows the
  Monday runs; two recorded leftovers: the six pinned 012_x files' manifest hashes are
  working-tree-byte (CRLF) based and need an LF normalization pass, and a handful of
  `test_btapibroker_iteration22.py` CTP-direct-write tests stay red by the iteration-41
  write-closure design (verified pre-existing via stash diff).
- Operational traps recorded during the iteration: the 7x24 SimNow front streams real quotes with a
  ~47.9h-stale event clock and has no daily price limits (write drills reject there); the front selector
  ranks standard-kind pairs first and falls back to 7x24 only when every standard pair is unreachable;
  SimNow standard fronts are TCP-reachable only inside trading sessions; the live tier requires the
  reviewed `C:/anaconda3/python.exe` (3.11) plus the dev-SDK preload; every example's dry/replay works
  on a core interpreter except 012_x, whose dry/replay also need the 3.11 dev environment (documented
  in its README).
- Component boundary: `tests/unit/test_iteration42_component_boundaries.py` pins that no standard entry
  imports `bt_api_gateway/bt_api_risk/bt_api_monitor/bt_api_execution` and that component-mount-shaped flags
  are rejected; the optional16 dry matrix re-runs green (32/32 DRY) and all four component packages import
  cleanly from the dev tree. The component-positive acceptance remains the iteration-41 optional16 real
  matrix (binance C01+T03 × 16).

### Iteration 43 — examples three-class layout, config-selected tier, portable folders (2026-10-11)

Plan and per-round evidence live under
`docs/_internal/opts/requirements/迭代43-examples目录三类重构与config选层/` (迭代计划.md + evidence/).

- `examples/` is now `backtest/`, `live/`, `unified/` plus non-example `_support/`, `data/`, and rebuildable
  output. `examples/README.md` is the index: class definitions, the per-leaf capability register, the
  small-data-versus-big-data boundary, the old→new path map, and the registered leftovers.
  `tests/unit/test_iteration43_example_layout_boundaries.py` pins that shape (root whitelist, live suite
  topology, `entry_tier` helper copies, no leaf importing `examples._support`, no tracked credential file).
  Historical evidence under `docs/_internal/**` keeps its old paths and is read as retired.
- Unified entries resolve their channel from `config.entry.tier` (`dry | replay | live`, with `backtest` as a
  documented alias) through a folder-local byte copy of `examples/_support/entry_tier.py`. A mode flag may keep
  or **lower** a declared tier and can never raise it; an escalation or a malformed declaration is `BLOCKED`
  before any handler or provider effect. Absent declaration reproduces iteration-42 commands exactly, and the
  repository ships no declaration, so `--live`, `--live --allow-write` and `--replay` keep working unchanged.
  **Any order still needs `--allow-write` plus each example's own admission, receipt and bounded conditions.**
- Evidence keys: `entry_tier` is the channel decision; the pre-existing `tier` field in a live summary stays the
  outcome label (`fill_round_trip`, `observation_only_tick_arrival`, …) that iteration-42 evidence records.
  `013_1/013_2/013_3/014_1` gained an independent `run_live_observe()` zero-write session (front selection,
  native login, account/position/order/trade reads, store write counters, orderly close) used when the live tier
  is selected without a grant; `012_1/012_2` answer `live_observation_unavailable` instead of implying an
  observation path exists. SimNow writes are still only ever via the direct registered-sim narrow admission and
  the Store/managed/production write routes stay closed (`NO_WRITE / LIVE_NO_GO`).
- Portability is guarded by `tests/unit/test_iteration43_copy_out_runnable.py`: each leaf is staged from git's
  tracked-plus-added list (so an ignored private config cannot travel), `PYTHONPATH` is cleared, and the offline
  entry must either exit zero or fail non-zero **naming the missing input** (big data, an optional dependency,
  or the deliberate checkout-only `backtrader` fence in 012_1). Small fixtures now ship inside their folder under
  `data/` with a byte-drift guard; big data stays external. `011`'s missing-data branch previously printed and
  returned exit 0 — a fake success — and was changed to `SystemExit(2)`.
- Commit chain on `dev`: `75080cbea` (R0 baselines) → `a290dc459` (R1 backtest) → `db5ad2b21` (R2 unified) →
  `021663e1d` (R3 live suite) → `f6074acd7` (R4 _support/data) → `28767cc27` → `f2c048a5b` (R5a-1 template) →
  `02bf6fc13` (R5a-2 all eight entries) → `35353e960` (R5b-1) → `81c85efe9` (R5b-2) → `ca09d7d7e` (R7).
  Frozen gates still hold: `tests/unit/runtime` 746 passed / 23 skipped / 0 failed, registered offline smoke
  8 / 0 / 2, `ruff check examples` 176 with no increment, self-contained focus 3 pre-existing reds
  (000 optional16 imports two component packages; two `ctp_example_support.py` CRLF drifts).
- Deliberately not in this close-out: the seven loose root scripts' four-file promotion, relocating or
  re-binding the root `examples/strategy-candidate-manifest.json` (its row fingerprint includes
  `resolved_example_path`, so a move needs a controlled re-issue decision), a uniform `--data-dir` CLI for big
  data, 006's ASCII console output, 001's stale `log_data` parameter name, and 002's `KeyError: 'orderbook'`.
