# Authoring contract

Canonical StrategySpec output uses `spec_version=strategy-spec-v1`, name, slug, category, one of the
seven archetypes, output profile, full DatasetManifest ID, feeds, typed parameters, entry/exit
StateRule references, sizing, risk, run modes, allowed imports, and a restricted `strategy-ir-v1`.

`render preview` stores candidate bytes and a hash manifest under the runtime root. `render
validate` creates a hash-bound, expiring issued capability. Only an explicitly approved,
unconsumed token can apply those exact bytes. The persisted record contains only the token digest.
Existing targets require an expected hash; create-only is the default. Multi-file apply stages all
bytes first and uses a journal plus rollback.

The `single_test` renderer targets `tests/functional/strategies/generated/<archetype>/`. The
`python_bundle` renderer writes three files under
`strategies/generated/<archetype>/<artifact_id>_<slug>/`.
