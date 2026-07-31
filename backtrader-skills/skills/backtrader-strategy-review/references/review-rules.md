# Review rules

Validation layers are specification, Python AST, current-fork API, security/path/dependency,
import/collection, smoke, runonce/runnext, target tests, baseline, and artifact integrity.

Static review never imports candidate code. P0 execution accepts only product-generated candidates.
Unknown third-party candidates may be reviewed with `--allow-third-party`, but cannot obtain a run
approval. Stable `SEC_*` codes identify trust-boundary failures; `BT_*` codes identify fork API,
construction, or look-ahead failures.

Repair changes typed IR or re-renders it. It does not use textual `exec`, `eval`, `compile`, dynamic
imports, or guessed source edits.
