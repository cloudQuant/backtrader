---
name: backtrader-strategy-test
description: Run approved Backtrader Skills candidates in fixed isolated child processes and compare runonce with runnext. Use for smoke backtests, parity checks, the 11 standard metrics, event-sequence comparison, reproducible JSON and Markdown reports, or investigating a failed generated strategy run.
---

# Backtrader Strategy Test

Execute only an applied, product-generated candidate with a valid DatasetManifest and a separately
approved `run_execution` token.

## Workflow

1. Run `run prepare --candidate /path/to/strategy.py --dataset-id 'ds_<64hex>'`.
2. Inspect the RunManifest hashes and static validation evidence.
3. Ask the user to approve the returned execution token, then run `approval approve`.
4. Run `run execute --run-id ... --token-id ...`.
5. Read the JSON and Markdown reports under `<target>/.backtrader-skills/runs/<run_id>/`.
6. Treat parity as passing only when integer metrics and normalized events match exactly, floating
   metrics satisfy the frozen tolerance profile, and null occurs only where declared.
7. Diagnose a failure from structured diagnostics. Change the StrategySpec/IR, create a new draft,
   and obtain fresh write and run approvals before retrying.

The fixed runner invokes the distribution's active Python interpreter in two separate `python -I`
children. Candidate code is never imported by the controlling process. This is process isolation
with AST, path, import, hash, and offline-data gates; it is not a complete operating-system sandbox.

Read [metric-contract.md](references/metric-contract.md) for all 11 units and nullable rules.
