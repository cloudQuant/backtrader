# Backtrader MCP P0 Implementation Report

Date: 2026-07-31

## Outcome

`backtrader-mcp` is implemented as an independent Python package and local
stdio MCP server. It does not import sibling Skills or Agent products and
treats Backtrader as a separately registered subprocess runtime.

The P0 flow is operational:

1. Run a read-only `doctor` from either the trusted CLI or MCP tool to verify
   the installed package, dependency versions, configured roots, and the
   actual Backtrader import/version/commit/capabilities.
2. Inspect and register a confined CSV into immutable, canonical CAS storage.
3. Derive a bounded tabular dataset with a fixed transform.
4. Search or refresh the AST-only strategy catalog.
5. Validate canonical strategy intent and create one of fourteen scaffolds
   (seven archetypes times two output profiles).
6. Update a private draft with revision and file-hash concurrency checks.
7. Validate candidate AST without importing it in the server.
8. Prepare an exact target-tree change, approve it using the trusted local CLI,
   and apply it through a journaled replacement.
9. Prepare a hash-bound run plan, create a distinct local execution approval,
   and launch a bounded durable subprocess job.
10. Poll, cancel, recover, compare, and render canonical results.

Typed execution now covers `generic_csv`, `backtrader_csv`, `yahoo_csv`,
`mt5_csv`, `pandas`, and `pandas_custom_lines`. Every input is normalized to
an immutable canonical CSV first, after which the controlled child constructs
the declared Backtrader adapter. Typed resample/replay operations are applied
through Cerebro and recorded with adapter, operation, source-row, and
output-bar evidence.

## Delivered Contracts and Controls

- Seven bundled JSON Schema 2020-12 contracts:
  `StrategySpec`, `DatasetManifest`, `CorpusManifest`, `ArtifactManifest`,
  `ValidationReport`, `RunManifest`, and `RunResult`.
- `DataSpec` is a required typed definition under
  `dataset-manifest.schema.json#/$defs/DataSpec`; it includes source-root,
  relative-path, format, feed mapping, timeframe, timezone, transform, and
  alignment fields.
- `comparison-profile-v1` fixes six integer and five floating-point metrics,
  tolerances, null behavior, and failure behavior. `sharpe_ratio` and
  `annual_return` may be null.
- Canonical dataset IDs are semantic hashes; physical CAS facts remain in
  manifest extensions.
- HMAC-SHA256 capabilities bind random nonces and expirations to exact
  validation, change, and run hashes.
- Change and execution approvals are distinct, private, expiring, one-use
  records created only through the trusted local CLI.
- SQLite WAL state, filesystem locks, idempotency records, private file modes,
  transaction journals, process-group cancellation, timeouts, captured logs,
  and startup recovery cover the local durability boundary.
- The MCP surface includes the canonical tools, resources, and prompts,
  including source-attached catalog refresh/inspection, draft repair,
  prepare/apply, prepare/start run, comparison, and report rendering.
- `doctor` is a real read-only CLI command and typed MCP tool. It reports the
  installed product origin, Python/MCP/Pandas versions, configured root health,
  supported adapters/profiles, and an isolated probe of each registered
  Backtrader runtime's module file, version, Git commit/branch, and required
  capabilities. Registering the typed server and invoking `doctor` do not
  initialize state, SQLite, secrets, locks, or recovery; the runtime probe uses
  `-B` plus `PYTHONDONTWRITEBYTECODE=1`.
- Host examples are included for Claude, Codex, OpenCode v2, and OpenClaw.

## Canonical Migration Notes

The P0 public output is canonical-only. A narrow inbound adapter accepts these
legacy intent fields:

- `multi_indicator` becomes `multi_indicator_system`.
- `multi_asset` becomes `multi_asset_allocation`.
- `dataset_ids[0]` becomes the single canonical `dataset_id`.
- `class_name` may supply a missing human-readable name; the generated Python
  class name is derived from canonical `slug`.

The canonical `DatasetManifest` moves physical content and CAS details into
`extensions`. Existing pre-P0 drafts, tokens, approvals, dataset IDs, or state
records are not migrated; version `0.1.0` expects a fresh product state root.

## Acceptance Evidence

All commands used the user's Anaconda base environment.

```text
PYTHONPATH=src conda run -n base python -m pytest -q
67 passed, 3 skipped in 112.34s
```

The skips are intentional environment partitions, including the MCP v2 protocol
test, which requires an isolated SDK target, and wheel/clean-install checks that
require explicit temporary artifact paths.

The normal suite includes a structured 14-cell acceptance test. It covers all
seven archetypes and both output profiles, all six typed adapters,
multi-data/multi-timeframe/precomputed-custom-line inputs, resample and replay,
and the inspect/register/preview, draft/validate, prepare/apply, fixed
runonce/runnext, and compare stages.

The suite also includes exact negative regression tests for detached restricted
callables, detached `write_text`, late-bound closure rebinding, lexical
capability leakage, non-worker `Path` factories, invalid doctor configuration,
missing runtimes, and CLI/typed-doctor read-only runtime probes. A stable
single-binding closure scaffold is retained as a positive regression.

```text
conda run -n base python -m build --wheel --outdir <temporary-directory>
Successfully built backtrader_mcp-0.1.0-py3-none-any.whl

BACKTRADER_MCP_WHEEL=<wheel> PYTHONPATH=src \
  conda run -n base python -m pytest -q tests/test_wheel_distribution.py
2 passed in 0.66s
```

The wheel test verifies all seven schemas, the comparison policy, the MCP
`>=2.0.0,<2.1` dependency, the clean catalog import, LICENSE, and NOTICE. The
runtime dependency set also declares Pandas for the two controlled DataFrame
adapters.

The final wheel and its dependencies were installed into an isolated
`--target` directory with `mcp==2.0.0`, then the SDK-level in-process protocol
test was run against that installed wheel:

```text
PYTHONPATH=<isolated-target> \
  conda run -n base python -m pytest -q tests/test_protocol_v2.py
2 passed in 2.89s
```

The base environment remained on `mcp==1.20.0`.

The installed wheel's doctor was then run from outside the repository with
`mcp==2.0.0`, configured source/target/state roots, and the current Backtrader
runtime:

```text
doctor.status=passed
product.module_file=<isolated-target>/backtrader_mcp/__init__.py
runtime.module_file=/Users/yunjinqi/Documents/new_projects/backtrader/backtrader/__init__.py
runtime.version=1.3.0
runtime.commit=0e812ef7d8c250d61e092536d2a1b61e712193fb
runtime.branch=dev
runtime.status=passed
issues=[]
```

```text
conda run -n base python -m ruff check src tests scripts
All checks passed!

conda run -n base python -m black --check --line-length 100 src tests scripts
All files would be left unchanged.

PYTHONPATH=src conda run -n base python -m backtrader_mcp audit-independence
status=passed, files_checked=24, findings=[]

conda run -n base python -m compileall -q src tests scripts
exit status 0
```

The fixed acceptance entrypoint independently consumed its structured JSON
artifact and reported `executed_cells=14`, `passed_cells=14`,
`independence=passed`, and both sibling-absence checks passed. It does not
infer cell success from pytest progress dots.

The final distribution-backed run built
`backtrader_mcp-0.1.0-py3-none-any.whl`, clean-installed it into a temporary
`--target`, and executed the matrix from a separate directory outside the
checkout. Its evidence reported:

```text
wheel_sha256=00b5fab1ead034e4d6447372ef14d92caea97e8ce22d6a59f6608baaffc24f7d
origin_is_installed_target=true
source_checkout_on_sys_path=false
matrix_source_checkout_on_sys_path=false
executed_cells=14
passed_cells=14
skills_absent=true
agent_absent=true
independence=passed
```

The installed origin was under the ephemeral acceptance target's
`installed/backtrader_mcp/__init__.py`, not `backtrader-mcp/src`.

## Honest P0 Limits

- AST validation plus a controlled subprocess is not an operating-system
  sandbox. Reviewed code runs with the local user's filesystem permissions.
- The product is offline and backtest-only; it exposes no network transport,
  broker credentials, live orders, or arbitrary executable selection.
- SQLite/WAL and filesystem journals are single-host mechanisms, not a
  distributed transaction system.
- Cancellation is product-owned process cancellation, not an MCP Tasks
  extension.
- Catalog refresh examines only configured target roots and uses AST/source
  hashes; it intentionally does not import strategy modules.
- Applying a change replaces the complete managed target directory and
  therefore requires exact preimage hashes for every existing file.
- A failed apply or start after consuming an approval requires a new prepared
  approval flow; authorization fails closed.
