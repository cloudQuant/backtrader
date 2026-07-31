# backtrader-agent

`backtrader-agent` is an independently installable, offline-first Backtrader
strategy-authoring agent runtime. It registers local data into immutable
content-addressed storage, validates canonical strategy specifications, renders
14 current-fork scaffolds, statically reviews candidates without importing
them, gates writes and runs with separate hash-bound approvals, executes only a
fixed child-process profile, and records recoverable session provenance. Its
acceptance matrix executes every scaffold in both `runonce` and `runnext` mode
and compares the normalized metrics.

It does not import, start, inspect, or depend on another Backtrader AI product.
It also does not embed a model SDK or require a model API key.

## Adapter, payload, and runtime are different layers

- A **native host adapter** is a tiny discovery/activation file in the host's
  own format. It contains no validation, data, state, or runner implementation.
- The packaged **agent payload** (`backtrader-agent payload`) provides persona,
  routing, lifecycle, and safety instructions.
- The installed **Python runtime** (`backtrader_agent`) implements typed actions,
  contracts, CAS, validator, approvals, writer, child runner, reports, and
  journal recovery.

The installer never presents one generic `.agents/skills` directory as four
different hosts. Each host receives its own native adapter.

## Install the Python distribution

From this directory, using any supported Python 3.8+ virtual environment:

```bash
python -m pip install .
backtrader-agent doctor --json
backtrader-agent payload
```

The runtime has no mandatory third-party dependency. A controlled backtest
requires Backtrader in the same Python environment; generated `single_test`
profiles also require pytest in the child environment.

The examples below assume the environment containing `backtrader-agent` is
active. Conda, `venv`, and equivalent isolated Python environments are all
supported.

## Install one native host adapter

All installs are preview-first, create-only, hash recorded, and idempotent.
An existing modified adapter is never overwritten. Replace
`/path/to/project` with the host project/workspace root.

### Claude Code

```bash
backtrader-agent install --target /path/to/project --host claude --preview
backtrader-agent install --target /path/to/project --host claude --apply
```

Creates `.claude/agents/backtrader-agent.md`.

Verify and invoke:

```text
1. Start a new Claude Code session in /path/to/project and open /agents.
2. Confirm backtrader-agent is listed.
3. First request:
   Use the backtrader-agent subagent to inspect my offline CSV, clarify a
   StrategySpec, generate a strategy, and stop at each apply/run approval.
```

### Codex

```bash
backtrader-agent install --target /path/to/project --host codex --preview
backtrader-agent install --target /path/to/project --host codex --apply
```

Creates `.codex/agents/backtrader-agent.toml`.

Verify and invoke:

```text
1. Start a new Codex task rooted at /path/to/project.
2. Ask Codex to list or spawn the project agent named backtrader-agent.
3. First request:
   Spawn the backtrader-agent for my offline CSV, clarify a StrategySpec,
   generate a strategy, and stop at each apply/run approval.
```

### OpenCode

```bash
backtrader-agent install --target /path/to/project --host opencode --preview
backtrader-agent install --target /path/to/project --host opencode --apply
```

Creates `.opencode/agents/backtrader-agent.md`.

Verify and invoke:

```bash
cd /path/to/project
opencode agent list
opencode run --agent backtrader-agent \
  'Inspect my offline CSV, clarify a StrategySpec, generate a strategy, and stop at each apply/run approval.'
```

### OpenClaw

```bash
backtrader-agent install --target /path/to/project --host openclaw --preview
backtrader-agent install --target /path/to/project --host openclaw --apply
```

Creates an independent `.openclaw/workspaces/backtrader-agent/` workspace with
`AGENTS.md`, `IDENTITY.md`, a payload guide, and a registration manifest. It
does **not** claim that a project-local `agent.json` is discoverable and it does
not invoke the external OpenClaw CLI.

After reviewing the generated absolute workspace path, the user must explicitly
register and verify it with the official native commands printed by the
installer:

```bash
openclaw agents add backtrader-agent \
  --workspace '/absolute/path/to/openclaw-workspace' \
  --non-interactive
openclaw agents list
openclaw agent --agent backtrader-agent \
  --message 'Inspect my offline CSV, clarify a StrategySpec, generate a strategy, and stop at each apply/run approval.'
```

The generated registration manifest uses shell-safe quoting for the exact
workspace path; review and run its `registration_command` and
`invocation_command` instead of manually reconstructing them.

Install this Python distribution into that workspace's Python environment; the
workspace adapter does not duplicate product logic.

For exact manifest-driven removal, run:

```bash
backtrader-agent install --target /path/to/project --host codex --uninstall
```

Removal stops if an installed adapter was modified. For OpenClaw, filesystem
uninstall does not claim to unregister an already registered external agent;
manage that registration explicitly with the installed OpenClaw version.

## P0 workflow

Use a dedicated state root, normally `<workspace>/.backtrader-agent`, and add
only that narrow runtime directory to the target repository's ignore file.

```bash
backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  roots register --id workspace --kind workspace --writable --path /path/to/workspace

backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  roots register --id prices --kind dataset --path /path/to/offline-data

backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  roots register --id engine --kind engine --path /path/to/backtrader-source

backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  engine --root-id engine

backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  session create --session-id session-001

backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  data inspect --spec data-spec.json

backtrader-agent --state-root /path/to/workspace/.backtrader-agent \
  data register --session-id session-001 --spec data-spec.json
```

DataSpec names a registered `root_id` and a relative path. The resolver rejects
absolute paths, `..`, symlink escape, devices, unsupported formats, changing
files, invalid timestamps, non-finite numbers, invalid OHLC, and quota
violations. Registration writes a canonical UTF-8 CSV to
`data/sha256/<prefix>/<normalized-hash>.csv` and emits a canonical
`DatasetManifest` with:

```text
schema_version, dataset_id=ds_<64 hex semantic hash>, spec_hash,
semantic_hash, manifest_hash, feeds, master_feed, alignment, status,
diagnostics, transforms, provenance, extensions
```

The six declared offline adapters are `generic_csv`, `backtrader_csv`,
`yahoo_csv`, `mt5_csv`, `pandas`, and `pandas_custom_lines`. Registration parses
each adapter's native offline text shape into the immutable canonical CAS.
Controlled execution then uses the corresponding `GenericCSVData`,
`BacktraderCSVData`, offline `YahooFinanceCSVData`, controlled MT5,
`PandasData`, or product-owned extended `PandasData` assembly path. The two
Pandas adapters accept only already materialized tabular text—not pickle or
arbitrary Python objects. `resample` and `replay` are typed transforms with an
explicit feed, target timeframe, and compression; the runner routes them only
through `Cerebro.resampledata` or `Cerebro.replaydata`.

Validate a canonical StrategySpec, search the package-owned snapshot, and
render a private draft:

```bash
backtrader-agent --state-root /path/to/state spec \
  --session-id session-001 --approve --file strategy-spec.json
backtrader-agent catalog search --query "multi timeframe clock" --top-k 3
backtrader-agent --state-root /path/to/state draft \
  --session-id session-001 \
  --spec strategy-spec.json \
  --dataset-manifest dataset-manifest.json
```

The installed catalog owns two separate assets:

- `corpus-v1.jsonl` contains 1,155 immutable metadata records covering the
  verified 1,152 functional tests, 1,035 three-file packages, and 1,032
  mappings. These records contain hashes and relative provenance, not strategy
  source; every bundled record therefore has `source_available=false`.
- `snapshot.jsonl` contains the 14 current-fork template entries: seven
  archetypes by `single_test` and `python_bundle`. Template selection remains
  available independently of corpus search.

When the original two corpora are explicitly mounted read-only, the runtime
can rebuild a source-attached snapshot without importing, executing, or
modifying them:

```bash
backtrader-agent --state-root /path/to/state roots register \
  --id functional --kind dataset \
  --path /absolute/backtrader/tests/functional/strategies
backtrader-agent --state-root /path/to/state roots register \
  --id packages --kind dataset \
  --path /absolute/back_trader/strategies
backtrader-agent --state-root /path/to/state catalog refresh \
  --functional-root-id functional --package-root-id packages
```

The default baseline gate requires exactly 1,152/1,035/1,032. Use
`--allow-count-drift` only for an intentionally different corpus. The generated
snapshot stays in private Agent state, outside both source roots; the
package-owned snapshot remains unchanged.

Canonical StrategySpec output uses:

```text
spec_version='strategy-spec-v1', name, slug, category, archetype,
output_profile, dataset_id, feeds, parameters, entry, exit, sizing, risk,
run_modes, allowed_imports
```

The seven archetypes are `single_data_indicator`,
`multi_indicator_system`, `multi_asset_allocation`, `multi_timeframe`,
`pairs_spread`, `order_risk`, and `precomputed_ml`; both `single_test` and
`python_bundle` profiles are renderable. Legacy input aliases
`single_indicator`, `multi_indicator`, `multi_asset`, `schema_version`,
`profile`, and `execution_modes` are accepted but never emitted.

Validation uses Python AST only. It never imports a candidate into the host
process. Imports, `os` access, Backtrader APIs, local strategy symbols, and
environment keys use exact capability allowlists. It rejects dynamic execution,
reflection, filesystem access, process/network libraries, product-runtime
transduction, live stores, path traversal, and non-allowlisted dependencies. A
direct `bt.Strategy` subclass is intentionally **not** required to call
`super().__init__()` on this fork; a custom parent or cooperative mixin must
still satisfy its MRO.

The write/run sequence is deliberately two-stage:

1. Rendering creates a private, locally signed provenance record bound to the
   exact session, approved spec, registered dataset manifest, draft directory,
   artifact manifest, and generated bytes. `validate --engine-root-id engine`
   accepts executable artifacts only when that renderer-owned record and the
   session checkpoint agree, then emits a validation report and token bound to
   the provenance record, artifact, dataset, environment, exact engine hash,
   and engine root ID.
2. `changes prepare` records exact source/target bytes, diff, expected preimage
   hash, renderer-owned draft path, artifact provenance, and the complete
   validation-token hash in an immutable locally signed prepared-change record.
   It does not write the target.
3. `approval request` persists a `PENDING` change request; a distinct local
   `approval grant --confirm` re-authenticates that signed record and the current
   session checkpoint before it persists and issues a one-time `change` token.
   `changes apply` ignores caller-supplied draft paths, loads the signed draft,
   consumes the token, checks every preimage, and uses a staged transaction
   journal with verified rollback.
4. A successful apply creates an immutable locally signed applied-artifact
   record. A separate request and local grant re-authenticates that record and
   issues a one-time `run` token bound to the applied/artifact/change records,
   full validation token, dataset, mode, environment, and engine.
5. `run` re-hashes all inputs and launches only `run.py` or the generated test
   through a fixed argv with `shell=False`, a minimal environment with no
   forwarded `HOME`, timeout, resource limits, and output quota. Before strategy
   execution, the same child environment imports `backtrader` and proves its
   resolved `__init__.py` and version belong to the approved engine root; the
   relative import path is recorded in `RunManifest`.

Reusing the same idempotency key returns its recorded result. A different key
is a different effect and cannot replay a consumed token.

After a run, reports and comparisons are addressed only by private immutable
run IDs:

```bash
backtrader-agent --state-root /path/to/state report \
  --run-id run-0123456789abcdef0123 --format markdown
backtrader-agent --state-root /path/to/state compare \
  --left-run-id run-0123456789abcdef0123 \
  --right-run-id run-fedcba9876543210fedc
```

The repair action never accepts a source patch. It requires a structured failed
ValidationReport/RunResult plus a revised StrategySpec, transitions the failed
session through `REPAIRING`, and deterministically re-renders a new owned draft.
The old artifact and action approvals cannot authorize the new bytes:

```bash
backtrader-agent --state-root /path/to/state repair \
  --session-id session-001 \
  --spec revised-strategy-spec.json \
  --dataset-manifest dataset-manifest.json \
  --failure-report failed-run-result.json
```

Use `backtrader-agent --help` and each subcommand's `--help` for exact typed
arguments. There is no `--command`, `--shell`, arbitrary callable, arbitrary
pytest target, or arbitrary output action.

## Sessions and recovery

```bash
backtrader-agent --state-root /path/to/state session create --session-id session-001
backtrader-agent --state-root /path/to/state session status --session-id session-001
backtrader-agent --state-root /path/to/state session recover --session-id session-001
```

Every transition has a strictly increasing sequence, previous-event hash, event
hash, normalized input hashes, action, state pair, token/effect references, and
timestamp. Data registration, spec approval, draft, validation, prepare/apply,
run approval, execution, reporting, and completion all advance this state
machine; they are not isolated from `session` commands. Checkpoints are atomic.
Recovery accepts only a verified journal
prefix, isolates a malformed suffix, and moves an interrupted `RUNNING` session
to `PAUSED`. Terminal sessions do not silently reactivate.

## Reports and provenance

Each successful bundle run writes immutable `RunManifest`, `RunResult`,
Markdown, and HTML artifacts under the private run root. Metrics are:

`bar_num`, `buy_count`, `sell_count`, `win_count`, `loss_count`, `trade_num`,
`final_value`, `sharpe_ratio`, `annual_return`, `max_drawdown`, and
`return_rate`.

`sharpe_ratio` and `annual_return` may be `null`; NaN, Infinity, and any other
missing metric fail. Comparison uses exact integer/status/hash semantics and
`rel_tol=1e-7`, `abs_tol=1e-9` for floats.

## Verification

```bash
python -m pytest tests -q -p no:cacheprovider

python scripts/audit_independence.py

python scripts/run_acceptance.py
```

The tests build a wheel in a temporary copy and prove that the seven public
schemas, AgentSessionManifest/AgentEvent schema, ComparisonProfile, snapshot,
corpus manifest, and agent payload are present in the wheel. They also verify
the exact full-snapshot SHA-256 and import/search it from a clean temporary
site outside this repository, without either sibling AI product.

`run_acceptance.py` writes and checks structured evidence for all 14
archetype/profile cells. Each cell contains separate `runonce` and `runnext`
result/manifest hashes, their normalized comparison, source provenance, and
the data shape used. Before running the fixed tests, it builds a wheel from a
temporary source copy, installs that wheel into a clean target, and executes
from a separate working directory whose import path excludes the source
checkout. The report records the wheel SHA-256, installed package origin, clean
`sys.path`, and `source_checkout_absent` attestation. The gate requires exact
coverage of all six adapters, multi-feed scenarios, typed multi-timeframe
transformation, and precomputed custom lines. Crash/resume and failure/repair
run against the same clean installation as independent gates rather than being
inferred from a successful matrix run.

Sibling absence is mandatory in the default command: acceptance fails if either
`backtrader_mcp` or `backtrader_skills` is importable in the clean runtime.

## Honest P0 limits

- Offline local files only: no download, database, WebSocket, API key, live
  broker/store, or real order.
- The controlled child process is defense in depth, not a container or OS
  sandbox. Network isolation is not claimed as OS-verified.
- Only candidates with an authenticated renderer-owned provenance record and
  matching session/spec/dataset/artifact approvals may run. Unknown third-party
  strategies are static-review-only.
- Snapshot search is lexical and deterministic over all 1,155 packaged metadata
  records. No embeddings, original corpus source, or hidden sibling checkout
  is required.
- The renderer provides functional scaffolds, not automatic optimization or
  profitability claims.
- Fresh master/dev orchestration is not automated in this compact P0; register
  and run each engine as a separately approved profile before comparison.
- Pandas inputs must be materialized to canonical CSV outside this runtime;
  arbitrary DataFrame objects and pickle are rejected by design.

See [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md) for implemented scope,
verification evidence, migration impact, and deferred items.
