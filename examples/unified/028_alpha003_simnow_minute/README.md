# Alpha003 SimNow minute example

`run.py` is the single entry for dry validation, offline research, causal local
replay, and SimNow live shadow/write modes. It binds the registered
`get_alpha(3)` class through `make_alpha003_factor_spec`; it does not contain a
second Alpha003 formula or scheduler. Research uses `ResearchSpec`,
`align_to_grid`, `FactorStrategy`, and ordinary Cerebro. Replay and live use the
ordinary `Alpha003TargetStrategy` and Cerebro-owned `BtApiFeed` cohort path.
Replay uses `CausalReplayBroker`, a local `BackBroker` subclass, and never
creates a provider Store. Live uses `BtApiBroker` and `RegisteredSimStore`.

The public [`config.yaml`](config.yaml) starts in `dry` with `entry.tier: dry`,
no write grant, and every monetary, freshness, holding, and order budget set to
`null`. Null budgets block order planning; they are not replaced by permissive
defaults. The copied [`entry_tier.py`](entry_tier.py) is byte-identical to the
unified-example helper and lets this folder run without importing a sibling
example. Install Backtrader and run from this folder or a copied folder:

```text
python run.py
python run.py --mode dry --config config.yaml
python run.py --mode research --config config.yaml
python run.py --mode replay --config config.yaml
python run.py --mode live --config config.yaml
python run.py --mode live --allow-write --config config.yaml
```

`--mode` can keep or lower the configured `entry.tier`; it cannot raise it.
Research maps to the read-only `dry` tier. Thus the template rejects replay
until its tier is deliberately changed to `replay`, and rejects live until the
tier is deliberately changed to `live`. `--factor-mode native|build` overrides
`factor.mode`; absent both, the production native mode is used. Fincore is only
loaded for an explicit offline evaluation request.

Set `selection.source: bundle` to use an explicit point-in-time selection
bundle at `selection.bundle`. Bundles use
`backtrader.futures_selection_bundle.v1`; the runner calls
`load_selection_bundle` and recomputes the selection. A serialized
`selection_claim` is audit context only. The bundle's complete exchange
session-calendar documents drive `build_common_minute_grid`; the runner never
infers planned times from the bars that happened to arrive. The default
authorized set is every product in the selected pool. An explicit
`authorized_products` list narrows who may receive targets, while the complete
pool remains present for cross-sectional ranking.

The public template defaults to `selection.source: ctp_query` for live mode.
After the single `RegisteredSimStore` is connected and read-only ready, the
runner calls its `registered_sim_collect_futures_snapshot()` bridge on that
same client. The collector issues empty-filter full catalog and current-depth
queries, preserving all CTP-visible contract rows and requiring complete
depth coverage. This describes the connected CTP session's visible catalog;
it does not claim exchange-wide universe coverage. Unknown contract
classification or a missing eligible quote blocks selection; non-futures and
known ineligible contracts remain explicit selector exclusions. The
`ctp_query_snapshot_equal_weight_v1` policy selects
the maximum exact `0.5 * open_interest + 0.5 * current_day_volume` score for
each product, with deterministic tie-breaking. No EOD snapshot fallback is
used. Catalog/depth collection and freshness are checked when an epoch is
admitted; its selected mapping stays frozen for that epoch. A later query
epoch gets a fresh Store only after the old Strategy, engine, refresh loop,
Broker and Store have completed their shutdown checks.

Query selection is a live-only path. Research and replay require
`selection.source: bundle` and an explicit saved bundle; a query source never
falls back to one. Query mode uses `selection.max_epochs` as its finite live
epoch count and does not accept `selection.daily_bundles`. Its session grid is
created by the local `expected_rule_derived` daytime calendar profile, which
retains the rule-manifest digest and source references and is not presented as
a newly fetched exchange calendar.

The saved minute source is a JSON object with schema
`backtrader.alpha003.minute_tape.v1`, a non-empty `snapshot_id`, explicit
`source_timezone` and `price_basis`, and a `bars` array. Every row names its
`target` (`EXCHANGE.PRODUCT`), exact selected `instrument` and `exchange`, and
includes `bucket_start`, `bucket_end`, `available_at`, `trading_day`,
`session_segment`, `timezone_id`, `clock_domain_id`, `connection_generation`,
positive increasing `bar_sequence`, `bar_id`, OHLCV plus `openinterest`,
`present: true`, `complete: true`, and `quality: GOOD`. Times are ISO-8601
offset-aware values; `available_at` cannot precede `bucket_end`. Replay
preserves each row as an immutable source event and marks it history-role.
Incomplete or missing planned legs remain a cohort gap; the runner will not
shrink the target pool to the intersection of observed bars.
The root `source_ref` identifies the immutable saved tape and is copied onto
each source event. The recomputed selection bundle supplies each planned
member's exact session and trading-day evidence; mismatched rows are rejected.

Replay additionally requires `inputs.execution_quotes`, a separate JSON quote
tape with schema `backtrader.alpha003.execution_quote_tape.v1` and a `quotes`
array. Each row has the same target/instrument/exchange identity plus
`event_time`, `available_at`, positive `bid`/`ask`, `source_ref`, and `quote_id`.
It also requires `inputs.instrument_metadata` with explicit point-in-time
permission, multiplier, long/short margin, tick size, and price limits for every
selected contract. Replay orders are matched only by the shared
`CausalReplayBroker`; an order carries the decision's source `available_at`,
and a bar whose start precedes that cutoff cannot fill it. Missing or stale
quotes and metadata block planning. This is a local simulation result, not
SimNow execution evidence.

Replay and live also require an explicit, new
`output.decision_tape_path` and a positive finite
`output.decision_tape_max_bytes`. The runner opens the JSONL destination
exclusively, writes a header and one immutable record for every complete
planned batch (including warmup batches), and flushes each record to disk
before strategy execution can dispatch an opening order. Records retain each
member's original bar fields and source receipt, factor values/status/reasons,
target decision and order plan. The tape contains no account facts or raw
provider responses. A write, fsync, byte-budget, or readback failure makes the
run fail closed; replay never claims a complete tape after dropping a row.
The readback checks each record digest and exact planned-grid coverage.

For live shadow, provide the protected CTP/SimNow Store configuration as JSON
in the environment variable named by `live.store_config_env` (default
`BT_SIMNOW_CONFIG_JSON`). The runner reads it only after an explicit live mode
is selected; it does not read `.env` or any private repository config file.
Trusted in-process embedders may instead pass the private
`_live_store_config_override` to `run.py` in live mode. It goes through the
same schema, injection, and profile validation as the environment value; when
no override is supplied, the existing environment-variable fallback remains
the default. This hook does not modify the process environment or grant write
authorization, and it is not a CLI or public-config option.
Shadow mode keeps `RegisteredSimStore(allow_writes=False)` and the ordinary
`BtApiBroker` chain. Shadow mode still opens the same durable
`ExecutionDecisionJournal` used by the live coordinator and records each
eligible grid decision, including empty-intent NOOPs and the batch/snapshot,
target-plan outcome, and source provenance. It does not arm instruments or
dispatch orders. Set `live.journal_path`, `account_scope`, `strategy_scope`,
and `logical_run_id` for either shadow or write mode; use a new logical run ID
when starting a distinct run because the journal's run budget is durable.

To resume the same live run from its saved bars, set
`inputs.history_decision_tape` to that run's previous decision tape, retain
the same journal and account/strategy/logical-run scopes, increase
`cohort.epoch_id`, and choose a new output tape path. For the default
`ctp_query` source, resume with the automatic query path (`plan=None`) so the
runner opens a fresh Store, verifies login/session readiness, and collects a
new catalog/depth snapshot before it reads the prior history. Passing an old
in-memory plan with history is rejected. Each query tape retains its original
snapshot ID, source generations, raw catalog/quote digests, grid digest, and
calendar collection timestamps as provenance. Across runs, the runner compares
the normalized semantic catalog (sorted by exchange/product/instrument and
including asset type, trading status, expiry, and product class), selected
routes and authorized targets, policy/coverage, calendar semantics, and grid
slots/members/sessions. Per-query IDs, generation/timing facts, raw digest
fields, and raw quote observations remain in each saved manifest as provenance
and are not cross-run equality keys. A semantic change, including a different
selected route or calendar/grid meaning, blocks reuse. The original selection
evidence hash is recorded in each decision row, and each new row is also bound
to its tape header; query history requires both bindings. Legacy
bundle tapes without the header binding remain readable for compatibility,
but their old header identity is not authenticated by that binding. Daily
bundle rotation remains unsupported with a history input.

The first resumed query epoch consumes the history tape; later epochs within
the same finite `selection.max_epochs` call do not reuse it. The saved history
supplies numerical warmup only: old decisions and historical factor signals
are not replayed or dispatched, and history never authorizes a new opening
order. This local runner support does not establish an OS-process restart or
real-account acceptance.

A controlled application stop with confirmed reconciliation, thread joins,
and resource closure returns `LIVE_EPOCH_SEQUENCE_STOPPED`. It does not start
another query epoch even when `selection.max_epochs` is larger than one.
Automatic daily rollover still requires normal epoch retirement.

Replay UTC follows the published complete cohort batch and its planned quote
availability; repeated monotonic budget samples do not advance simulated
minutes. The ordinary BackBroker keeps the existing causal fill rules.

The final `factor.preheat_bars` records must be contiguous, complete,
live-role `LIVE_READY` batches ending at the latest eligible planned minute.
Each reused record must match the tape reference persisted in the original
journal. Missing minutes, altered prices, a changed route/profile, or a
missing journal decision prevent startup. The loader reads the bounded file
through EOF and retains only this warmup window.

The normal Feed/cohort path restores those bars with their original source
generation and sequence before accepting new live bars. Historical factor
signals do not create opening orders, and old grid decisions are not
dispatched again. Independently authorized cancellation or risk reduction
still uses current query and quote evidence. A further restart can consume a
tape containing a history prefix followed by a live suffix, provided its
final eligible window meets the same checks. A controlled application stop
preserves the engine's unfinished-grid status and requires the Strategy's
reconciliation, refresh-thread join, and resource-cleanup proofs; it does not
retire an automatic daily epoch.

During live `prenext`, complete warmup grids are recorded in the decision tape.
Warmup does not dispatch factor-driven target decisions or opening orders.
Independent risk maintenance uses fresh execution facts and may cancel an
owned order even if the tape write fails; the tape error remains recorded.
Replay warmup remains tape-only.

Journal decision storage is finite per database: defaults allow 100,000 BASE
decisions (including NOOPs) and 512 MiB of canonical decision JSON, plus a
separate settlement reserve of 4,096 CLOSE/CANCEL-only decisions and 64 MiB.
Exact decision replay consumes no additional capacity. When the BASE high-water
is reached, new eligible-grid NOOPs and opening/mixed decisions stop; the
reserved settlement capacity remains available for close/cancel decisions and
callback, reconciliation, and acknowledgement writes use their own bounded
tables. Keep the same journal database and capacity settings across restarts;
deleting or replacing it to get more capacity bypasses durable deduplication and
recovery. This is a finite-session contract, not an unlimited-running journal.
The journal can report canonical decision bytes and sampled SQLite/WAL file
sizes; the configured byte caps apply to canonical decision payloads, not the
entire database file.

Set `live.quote_max_age_seconds` and `live.query_max_age_seconds` to explicit
positive bounds before either live mode. One bounded serialized control loop
refreshes account/order/trade/instrument evidence and one target margin query
at a time; it stops and joins before Broker/Store shutdown. If the refresh
cannot join, Store and journal closure are reported as skipped instead of
closing resources beneath a running query. The runner returns a finite
`resource_shutdown` record with Broker, Store, journal, and query-loop outcomes;
these are local shutdown observations, not proof of a flat account.

Live mode also requires a positive `live.shutdown_grace_seconds`. SIGINT,
SIGTERM, and SIGBREAK where available request a bounded winddown. The control
thread passes that request to the Strategy and wakes an active cohort wait via
the public `Cerebro.wake_live_bar_cohort()` API. The Strategy consumes it on the
engine thread, where it can cancel its owned orders and apply the configured
`risk.run_end_policy` using refreshed facts and current quotes. The refresh
loop remains active until the Strategy reports its target-scope shutdown
ready, or the grace deadline expires. A timeout returns an explicit blocked
result and does not claim that positions are flat. Account-wide Broker
flattening is disabled. A finite replay also reports `REPLAY_INCOMPLETE` and
exit code 2 when local positions or orders remain unresolved at the final
source bar; a causal close order placed after that bar cannot be filled by
backdating its open.

At finite live-cohort EOF, the current engine performs its final idle check and
the runner accepts completion only if the Strategy already reports shutdown
ready. If a cancel or close still needs later Broker polling or a later market
bar, the run is reported blocked; the example does not treat process teardown
as proof of a settled position or order.

For saved-bundle live compatibility across trading days, keep the first day's
bundle in `selection.bundle` and list later public bundles, in order, in
`selection.daily_bundles`. The runner keeps the selected product pool fixed and
requires every later point-in-time decision and exchange TradingDay to advance.
Each epoch gets a new cohort, feeds, Cerebro, Strategy, factor graph, and
decision tape, while the durable execution journal keeps the same logical run
and its intent budget. Daily rollover requires `risk.run_end_policy:
CLOSE_ALL`. The next bundle is read only after the old Strategy proves its
target scope settled, Cerebro reports `STOPPED`, the serialized query loop
joins, and the old Broker, Store, journal, and tape close successfully. A
timeout, unknown order, or incomplete local cleanup blocks the sequence and
does not load the next bundle. Remote account uncertainty is reported
separately from local resource closure; it is never presented as a flat
account. This finite sequence uses the existing cohort and winddown lifecycle,
not a second scheduler, and remains source/fake example evidence rather than
real-account rollover acceptance.

For the query-default path, set `selection.max_epochs` to the desired finite
count instead. Each epoch queries its own newly connected Store only after the
prior epoch has retired and closed. The old mapping is not reranked mid-epoch,
and a failed or unresolved epoch prevents creation of the next Store and query.

Set `cohort.max_live_bar_age_seconds` and
`cohort.max_future_skew_seconds` to the accepted source-clock profile before
starting live mode. The runner refuses live startup while the shared cohort
does not expose its source-age gate. Its injected host UTC clock controls only
the scheduler and freshness checks; it never fills missing ActionDay or
rewrites exchange timestamps, TradingDay, source clock domain, or generation.
Provider events must remain source-valid and within the configured age and
future-skew limits to produce a live-ready batch.

Live writes require all of these independent conditions: `--mode live`,
`entry.tier: live`, `live.allow_writes: true`, the explicit `--allow-write`
flag, complete non-null `risk` budgets including a finite fee upper bound, a
durable `live.journal_path`, fixed account/strategy/logical-run scopes, and exact per-instrument native arm
templates. The adapter must issue the scoped capability; a boolean or a
configuration template alone cannot grant one. No real provider/account call
is made by the example's tests. Real SimNow shadow and account acceptance are
separate acceptance levels and must be reported separately from source/fake
tests.

Run the focused runner tests from the repository root:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 C:/anaconda3/python.exe -m pytest tests/unit/test_alpha003_simnow_runner.py -q
```

The tests exercise parsing, tier/write-gate failures, point-in-time selection,
research construction, history-only cohort replay, causal order timing, and a
copied-folder dry invocation. They also verify durable bounded tape
readback/tamper detection, interrupting the real runner clock through the
public Cerebro wake API, and resource cleanup after readiness, query-refresh,
or arm-template setup failures. They do not establish live market, account,
provider, or native-write acceptance.


### 受保护配置的进程内移交（2026-10-27）

`protected_simnow.protected_simnow_store_config(selected_config_index=...)` 供主调用方读取现有 013_3 注册的受保护配置，索引从零开始且必须显式指定。它只将现有零写入策略的目录定位到此示例的 013_3 相邻目录；不修改 I41 注册或 artifact pin 表。必须先通过有界读取、配置/路由/凭据密封及本次固定安装 SDK 校验，再验证官方 SimNow TD/MD 配对。它不探测网络、不创建客户端或 Store，也不授予交易权限。

在上下文内调用 `handoff.for_runner()` 可得到用于 `run(..., _live_store_config_override=...)` 的只读映射。每次取得映射都复核凭据密封；句柄和映射的 repr 隐去内容，退出后共享映射清空且句柄不可复用。调用方必须在上下文结束前正常关闭使用它的全部 Store，单独保持 shadow 配置及已有写入许可门槛。禁止把映射转换为日志、文件、环境变量、子进程参数或验收回执；只允许向本进程 Store 移交。安装来源不符合固定 pin 时直接拒绝，不回退到其他 SDK。

本地最终 13 项合成配置测试及独立静态审阅通过；真实隔离消费者的公开 SDK artifact 校验通过。该组件本轮未执行新 helper 的真实受保护凭据移交、provider 或账户验收。


### 只读发现连接的正常关闭

`discovery_lifecycle.close_discovery_store(store, timeout=...)` 只用于尚未启动 Feed/Broker/Cerebro 的零写入 `RegisteredSimStore` 发现连接。它核对 Store 静默状态及同一 MD/trader 客户端的 SDK 回执；成功才可结束受保护配置上下文。关闭未确认时抛出脱敏 `DiscoveryStoreCloseError`，其 custody 保留原对象，禁止把异常对象或 custody 序列化。不得重复 stop、手动 Release 或以退出进程替代关闭证明。MD generation 0 普通回执不足以证明启动资源处置，保持未完成。该组件的本地测试不构成实际账户或原生关闭验收。
