# Iteration 17 P0 implementation report

## Delivered

- One independently installable Python distribution and unified CLI under
  `src/backtrader_skills/`.
- Three canonical skills: author, review, and test. Their scripts only forward to the unified
  runtime.
- Seven named JSON Schemas, with `DataSpec` defined at
  `dataset-manifest-v1.schema.json#/$defs/DataSpec`, plus the shared
  `comparison-profile-v1.json`.
- Full offline metadata catalog: 1,152 functional tests, 1,035 strategy packages, 1,032 mapped
  identities, and 1,155 union entries.
- Opaque read-only roots, CSV inspection, deterministic normalization, content-addressed dataset
  objects, full semantic-hash dataset IDs, immutable manifests, bounded preview, quality gates, and
  multi-feed overlap validation.
- Canonical StrategySpec input/output with compatibility aliases and restricted
  Expression/Action/StateRule IR.
- Seven archetypes and both `single_test` and `python_bundle` renderers from the same IR.
- AST/security validation with fork-aware direct Strategy, cooperative parent, and framework
  component initialization rules.
- Generated candidates can import only top-level `backtrader`; controller-package, filesystem,
  process, and network imports are rejected. Execution additionally proves candidate bytes came
  from an approved deterministic render/apply.
- Separate hash-bound write and execution approvals use 256-bit capabilities, digest-only
  persistence, TTL, explicit approval, and terminal `CONSUMED/REVOKED/EXPIRED` states.
- Multi-file artifact apply preflights and stages all bytes, records a journal, and rolls back
  already committed targets if a later target write fails.
- Fixed active-environment `python -I` child execution for runonce and runnext; under the required
  Anaconda base invocation this resolves to that environment's interpreter, and the controller
  never imports candidate code.
- The 11 standard metrics, explicit units/nullability, frozen comparison tolerances, normalized
  event comparison, JSON/Markdown reports, and typed-IR repair/re-render.
- Manifest-driven preview/apply and protected uninstall for Claude Code, Codex, OpenCode, and
  OpenClaw native skill directories.

## Shared-contract migration

The implementation originally used a truncated `ds_<24hex>` ID during local construction. Before
release it was migrated to canonical `ds_<64hex semantic hash>`. StrategySpec output now always uses
the shared top-level fields (`feeds`, `entry`, `exit`, `sizing`, `risk`) and carries the restricted
IR under `ir`. Dataset, corpus, artifact, validation, run-manifest, and run-result exports include
the agreed shared core fields; Skills-specific evidence is additive.

This is a pre-release migration. There are no published old IDs to preserve. Any local exploratory
runtime made before the migration must re-register its dataset and regenerate its draft; old
truncated IDs are intentionally rejected rather than guessed.

## Acceptance evidence

Commands use `/Users/yunjinqi/opt/anaconda3/bin/conda run -n base`.

| Gate | Result |
| --- | --- |
| Product pytest suite | 25 passed |
| Black (source and tests) | Pass |
| Ruff | All checks passed |
| Catalog snapshot count/hash check | Pass |
| Wheel content check for schemas, policy, snapshot, adapters, skills | Pass |
| Built-wheel clean-install acceptance | Pass; source checkout absent from `sys.path` |
| MCP/Agent sibling absence in isolated install/repository | Pass |
| 7 archetypes × 2 profiles acceptance | 14/14 pass; `evidence/acceptance-7x2.json` |
| Acceptance data profiles | Seven distinct manifests; all six adapters; real multi-feed/resample/custom-line cases |
| Structured repair gate | Multi-data, multi-timeframe, and ML failure → repair → revalidation → dual-mode run pass |
| Every acceptance cell runonce/runnext metric parity | Pass |
| Every acceptance cell normalized event parity | Pass |
| Clean fixture with no sibling MCP/Agent import | Pass |

The acceptance evidence records per-cell data provenance, mode hashes, comparison hashes, repair
diagnostics, and the built-wheel hash. It is included in the distribution manifest and packaged
wheel. Repository maintainers ran the commands through the Anaconda `base` environment, while the
public installation and usage commands remain environment-agnostic.

The repository-wide `make test-fast` result recorded before this focused Skills acceptance change
was `2,474 passed, 1 skipped`. It is historical integration evidence, not silently presented as a
fresh result of the current product-only verification.

## Honest P0 limits

- Child-process isolation plus AST/path/import gates is not a complete OS sandbox. There is no
  container, network namespace, seccomp, or cgroup.
- Pandas adapters accept safely materialized tabular CSV; pickle, arbitrary DataFrame constructors,
  and user callables are rejected.
- The catalog snapshot is complete metadata with deterministic lexical search. It does not bundle
  all corpus source or provide embedding search.
- Repair is deterministic IR revision/re-render. It does not guess a semantic strategy fix or patch
  arbitrary third-party source.
- The automated runner proves local runonce/runnext parity. A master/dev financial baseline still
  requires an isolated checkout and human-approved expected values.
- JSON and Markdown reports are implemented. HTML rendering and container execution remain P1.
- Tests verify four native host layouts and skill metadata; actual client UI discovery needs the
  corresponding host binary and is not simulated.
