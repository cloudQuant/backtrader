# Backtrader AI Strategy Public Contracts v1

This directory is the only authoritative source for the seven public JSON
Schemas and `comparison-profile-v1`. Product packages vendor byte-identical
copies; run `scripts/sync_ai_strategy_contracts.py` after changing a contract.

Canonical hashes use SHA-256 over UTF-8 JSON with recursively sorted object
keys, compact separators, Unicode NFC normalization, `-0.0` normalized to
`0.0`, and non-finite numbers rejected. A contract's named hash field is
excluded while calculating that hash.

Public wire rules:

- `StrategySpec` uses kebab-case slugs, parameter descriptors, typed feed
  descriptors, `RuleReferences`, exactly `["runonce", "runnext"]`, and exactly
  `["backtrader"]`. Product-specific IR belongs in the optional `ir` or
  `extensions` fields.
- `DataSpec` is `$defs.DataSpec` in `DatasetManifest`; it uses
  `schema_version=data-spec-v1`, a `spec_hash`, typed feeds, an alignment object,
  and typed transform objects.
- `ArtifactManifest.files` and `RunResult.artifacts` use
  `{path, role, bytes, sha256}`.
- `RunResult.metrics` is one flat vector of 11 metrics. Detailed run-mode
  results and comparisons may be retained under `extensions`.
- `annual_return` is a ratio. `return_rate` and `max_drawdown` are percentages.
  `annual_return` and `sharpe_ratio` may be null.
