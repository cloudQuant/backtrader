---
name: backtrader-strategy-author
description: Create auditable Backtrader strategies from registered offline datasets using StrategySpec v1 and the restricted Expression/Action/StateRule IR. Use for new strategy scaffolds, converting trading intent into typed specifications, searching the bundled strategy catalog, or previewing and applying generated single-test or Python-bundle artifacts.
---

# Backtrader Strategy Author

Create strategy artifacts through the product CLI. Do not hand-write a second implementation for
the two output profiles; both must render from the same validated IR.

## Workflow

1. Run `python -m backtrader_skills --target /path/to/backtrader doctor`.
2. Register a read-only root with `data root-add`, then inspect and register a `DataSpec`.
3. Search the bundled snapshot with `catalog search`; treat examples as design evidence, not expected
   profitability.
4. Produce a canonical `StrategySpec v1`. Resolve feed roles, direction, sizing, entry, exit, and
   risk before rendering. Bind only the full `ds_<64hex>` dataset ID.
5. Run `spec validate`, then `render preview`. Show paths, hashes, diffs, and conflicts.
6. Run `render validate`. Ask the user to approve the returned `render_write` token.
7. Run `approval approve`, then `render apply` with that token.

Use the installed distribution command from the environment selected during setup:

```text
backtrader-skills --target /path/to/backtrader ...
```

## Invariants

- Keep runtime state under `<target>/.backtrader-skills/`.
- Generate bundles only under `strategies/generated/`.
- Generate collected tests only under `tests/functional/strategies/generated/`.
- Generate direct `bt.Strategy` subclasses without `super().__init__()` for this fork.
- Reject positive line offsets, arbitrary imports, dynamic execution, network access, live stores,
  absolute data paths, and unknown operators.
- Never imply that a backtest predicts returns.

Read [authoring-contract.md](references/authoring-contract.md) for the canonical fields and the
two-phase write contract. The script in `scripts/backtrader_skills.py` is only a thin CLI forwarder.
