# P0 implementation report

Date: 2026-07-31
Product version: 0.1.0
Scope root: `backtrader-agent/`

## Implemented

- Python `src/backtrader_agent` distribution and typed CLI/doctor/payload.
- Opaque controlled root registry with traversal and symlink confinement.
- Six offline adapter paths (`generic_csv`, `backtrader_csv`, `yahoo_csv`,
  `mt5_csv`, `pandas`, and `pandas_custom_lines`), deterministic canonical
  text materialization, immutable SHA-256 CAS, registration, preview, TOCTOU
  check, quality diagnostics, typed resample/replay, and canonical
  DatasetManifest. Pandas inputs are materialized text only; pickle/object
  deserialization is rejected.
- Canonical StrategySpec with legacy input alias migration.
- Package-owned 1,155-record full metadata snapshot, deterministic search and
  provenance, plus a separate 14-entry current-fork template catalog.
- Seven archetypes × `single_test`/`python_bundle` deterministic renderer.
- Import-free AST/current-fork/security validator. Direct `bt.Strategy`
  subclasses do not receive a false missing-`super()` failure.
- Private renderer-owned signed artifact records plus locally signed,
  short-lived validation/change/run tokens with distinct kinds and continuous
  session/spec/dataset/artifact/provenance hash bindings.
- Two-phase expected-hash prepare/apply, atomic target writes, postimage check,
  create/update conflict protection, and idempotency records.
- Fixed child-process runner with exact entrypoint, `shell=False`, minimal
  environment, timeout, POSIX quota attempts, output limit, source/data
  re-hashing, eleven metrics, immutable JSON/Markdown/HTML reports. A registered
  read-only engine root is content-bound during validation; the child proves
  that `backtrader.__file__` and version resolve from that root and records the
  relative import path in `RunManifest`.
- AgentSessionManifest, strictly ordered append-only event hash chain, atomic
  checkpoint, corrupt suffix isolation, legal transitions, cancel/archive, and
  interrupted-run pause recovery.
- Independence audit for forbidden sibling imports/reads and dynamic execution.
- Create-only, idempotent, manifest-driven native adapter install/uninstall for
  Claude Code, Codex, OpenCode, and an OpenClaw workspace. OpenClaw registration
  remains an explicit user-run official CLI step and is not falsely represented
  by a project-local `agent.json`.
- Seven named public JSON Schemas, AgentSessionManifest with `$defs/AgentEvent`,
  ComparisonProfile, corpus manifest, agent payload, and wheel-content test.
- Structured 14-cell acceptance evidence. Every archetype/profile cell performs
  separate real `runonce` and `runnext` executions and a normalized metric
  comparison; six adapters and specialized multi-feed, multi-timeframe, and
  custom-line data are required. The fixed acceptance builds and clean-installs
  a wheel, runs outside the source checkout, and records wheel hash, installed
  origin, clean import path, and source-absence evidence. Crash/resume and
  failure/repair are separate gates against that same clean install.

## Public contract migration impact

The initial local draft used short internal names. Before P0 handoff it was
migrated to the cross-product canonical surface:

- StrategySpec emits `spec_version`, `output_profile`, and `run_modes`.
- Archetypes emit `single_data_indicator`, `multi_indicator_system`, and
  `multi_asset_allocation` instead of their earlier short names.
- Dataset IDs changed from a 20-character display prefix to
  `ds_` plus the complete 64-hex semantic hash.
- ComparisonProfile and RunResult now use the shared six integer metrics
(`bar_num`, buy/sell/win/loss counts, `trade_num`) and five float metrics
(`final_value`, `sharpe_ratio`, `annual_return`, `max_drawdown`,
  `return_rate`); Sharpe and annual return are nullable.
- DatasetManifest emits the canonical top-level core; Agent CAS/policy details
  live in `extensions.backtrader_agent`.
- Corpus, Artifact, Validation, RunManifest, and RunResult schemas and runtime
  output use their canonical core fields; product-specific evidence lives under
  `extensions`.

Legacy StrategySpec field/archetype aliases remain accepted on input only.
Previously emitted short dataset IDs cannot be migrated safely because they do
not contain the full semantic hash; re-register the original DataSpec.

## Security properties actually enforced

- No candidate import in the host process and no dynamic execution API.
- No raw command/shell/callable/pytest-target action.
- Separate apply and execute capability kinds.
- Authenticated product-generation evidence; external drafts, forged
  manifests, cross-session reuse, and tampered provenance records fail closed.
- Session, spec, source, dataset, artifact, provenance record, validation,
  environment, engine, preimage, and mode bindings.
- Confined relative target paths and immutable private CAS.
- Fixed child argv and cwd; no `shell=True`.
- Stable `BTAG-*` errors intended for redacted user display.

## Known limits and deferred work

- P0 child-process controls are not a full sandbox and do not prove network
  isolation.
- Pandas/custom-line workflows must first materialize trusted tabular text;
  pickle/object deserialization is absent. The controlled Pandas run paths use
  the Pandas dependency installed with Backtrader.
- Snapshot search is lexical. Source-attached full-corpus rebuild is implemented
  for explicitly registered read-only roots; embedding search is deferred.
- Automated fresh master/dev worktree orchestration, cancellation signals, and
  container runner are deferred. The runtime can execute separately approved
  engine profiles but does not create worktrees.
- Renderer repairs are new immutable draft revisions; an autonomous patch
  synthesizer is not included.
- Report HTML is intentionally minimal and contains no plotting dependency.

## Acceptance evidence

The authoritative evidence is produced by:

```bash
python -m pytest tests -q -p no:cacheprovider
python scripts/doctor.py
python scripts/audit_independence.py
python scripts/run_acceptance.py
```

Final observed results on 2026-07-31:

- product tests: `59 passed`;
- Ruff: passed;
- Black check: passed;
- doctor: `ready`;
- independence audit: all six checks passed;
- acceptance: passed, with 7 archetypes × 2 output profiles = 14 real
  source-bound backtest cells, two execution modes per cell, six data adapters,
  clean-wheel execution, mandatory MCP/Skills absence, and independent
  crash/resume and repair gates;
- repository contract/catalog/distribution audit: passed;
- repository `make test-fast`: `2,474 passed, 1 skipped`.

The four adapter layouts are covered by installer tests. OpenClaw was not
installed on this machine, so its external registration command remains an
explicit user-side verification rather than a claimed live-host result.
