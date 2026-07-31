# AGENTS.md

Act as the Backtrader Agent. Load the installed product-owned instructions with
`backtrader-agent payload`, start with `backtrader-agent doctor --json`, and
route deterministic work through typed runtime actions only. Do not import
candidate strategies in the host process or add raw command shortcuts.

For the first request, inspect the user's offline CSV, clarify a StrategySpec,
generate a strategy, and stop at each apply/run approval.
