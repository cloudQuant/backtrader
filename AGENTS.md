# AGENTS.md

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
override skips transitive analysis of the separate `backtrader_runtime` package;
the runtime package is not yet covered by a dedicated mypy gate.

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

## Repository layout

```
backtrader/            core library
  cerebro.py (facade) + _cerebro/ (private engine mixins) strategy.py
  indicator.py analyzer.py observer.py broker.py feed.py
  metabase.py parameters.py
  lineroot.py linebuffer.py lineseries.py lineiterator.py dataseries.py
  indicators/ analyzers/ observers/ feeds/ brokers/ filters/ sizers/ signals/
  commissions/ stores/ channels/ mixins/ plot/ bokeh/ reports/ configs/ utils/
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
examples/012_1_midfreq_cross_exchange/  mid-frequency OKX/Binance perpetual example
examples/012_2_event_driven_cross_exchange/ event-driven OKX/Binance perpetual candidate
examples/013_3_sa_midfreq_simnow/ controlled CTP/SimNow SA mid-frequency example
examples/strategy-candidate-manifest.json  hash-bound research/demo admission manifest
examples/strategy_candidate_approval.py  candidate-specific receipt/provenance policy
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

The Iteration 41 inventory currently has 17 registrations, including a 007 suite-root zero-write `simulation/sandbox` runtime/front-check route. Its protected, Git-ignored config and directory ACL are aligned with 013_3; the schema-v4 config is rebound to `example.007_ctp.simnow_penetration` and contains five configured MD/TD pairs. Offline `doctor` exited 0 with `provider_preflight_started=false`, five pairs, and `preflight_available=false`; ordinary `preflight` remains fail-closed pending a bounded Windows Job supervisor and independent acceptance. On 2026-09-28, one explicit credential-free `check-ctp-fronts` TCP probe selected pair index 3 (MD and TD each 3/3 reachable); indexes 0/1/2/4 each had 0/3. This is a host-and-time-specific transport observation only: no SDK import, provider login, market-data subscription, order, or cancel occurred, and it does not establish future reachability. `bt-runtime run` on the suite root returns `profile_dispatch_unavailable`/exit 2 with `provider_preflight_started=false`; this route has no runner. The 007 route has no certification case runner, trading runner, or write permission. All 33 case directories are staged at `examples/007_ctp/live_certification/simnow_penetration/cases/<ID>/{config.yaml,<ID>_strategy.py,run.py}`; per-case configs contain scenario parameters only and must not duplicate account credentials. Their strategy files describe planned real actions and evidence, not executable provider strategies. Historical flat `cases/*.py` remain closed source. `managed_case_entry` returns `BLOCKED`/exit 2 for the cases; that unavailable-case-runner result is never real SimNow `PASS`. The latest six-file fake/offline runtime focus passed 176 tests, skipped 13, with one existing pytest-configuration warning; it does not establish TCP, provider, account, or trading behavior. Keep `NO_WRITE / LIVE_NO_GO`.

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

The current default registry has 17 registrations: 11 nonmanaged
`simulation/replay` paths (eight ordinary strategy examples, the no-action
legacy profiles for `examples/007_ctp` and `examples/010_live_examples`, and
the separate `examples/sample.py` no-action migration profile), two zero-write
CTP SimNow `simulation/sandbox` RuntimeProfiles with read-only bindings: the
013_3 private runtime and the 007 certification-suite root runtime/front-check
route. Offline `doctor` and credential-free `check-ctp-fronts` are available
for both. Ordinary CTP `preflight` for 013_3 and 007 remains fail-closed
pending a bounded hard Windows Job supervisor and independent acceptance. The
registry also has one `examples/010_live_examples` public-market-only
`simulation/shadow` runtime
(fixed OKX public instruments, bounded duration and requested five-level depth), two
local fake-provider managed L2 replay paths, and one package-owned
`backtest/local_backtest` fixture. The fixture executes four packaged CSV bars
through Cerebro with zero network, external writes, orders, fills, or provider
submissions; it is an acceptance fixture, not a general deployment route.
The public shadow passes validated books to the historical
`LiveMultiSymbolStrategy.notify_orderbook` callback on a brokerless observer;
it does not construct Cerebro, run `next()`, or expose an order route.
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
  registered offline replay/backtest CLI entries; managed L2 replay requires
  the local SDK source packages on `PYTHONPATH`. It deliberately skips the
  public-network shadow and all private/live routes.
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
  `0600` under `~/.backtrader/notifications/`.
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
