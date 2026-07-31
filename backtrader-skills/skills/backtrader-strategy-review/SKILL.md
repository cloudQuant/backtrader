---
name: backtrader-strategy-review
description: Review Backtrader StrategySpec and generated Python artifacts without importing candidate code. Use for fork-construction checks, AST/security review, look-ahead detection, import and path policy validation, stable diagnostics, or deterministic repair by re-rendering approved typed IR.
---

# Backtrader Strategy Review

Review candidate source statically and return the structured `ValidationReport v1`. Do not import or
execute a candidate during review.

## Workflow

1. Run `review --file /path/to/generated.py` for an applied candidate, or
   `render validate --draft-id ...`
   for a product draft.
2. Report diagnostics by stable code, severity, file, line, rule, explanation, and remediation.
3. Classify initialization correctly:
   - Accept a direct `bt.Strategy` subclass without `super().__init__()`.
   - Warn when a direct strategy redundantly calls `super().__init__()`.
   - Require cooperative custom parents and Indicator/Analyzer/Feed components to call
     `super().__init__()` before framework state access.
4. Reject `exec`, `eval`, `compile`, `__import__`, dynamic import, subprocess, sockets, network
   clients, live stores, absolute paths, directory traversal, and positive line offsets.
5. For repairable product-generated drafts, run `repair --draft-id ...`. Repair returns to the
   stored StrategySpec and re-renders; never patch arbitrary third-party source.
6. Repeat validation and require a fresh write approval before applying a repaired draft.

Use `backtrader-skills --target /path/to/backtrader ...` from the environment selected during setup.
Read [review-rules.md](references/review-rules.md) for diagnostic categories and trust boundaries.
