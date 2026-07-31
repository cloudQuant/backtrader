# Backtrader Agent OpenClaw workspace

This is an OpenClaw-native workspace adapter. It contains no product logic and
is not automatically registered. Install the `backtrader_agent` Python
distribution into the workspace Python environment; the runtime supplies
contracts, data CAS, validation, runner, reporting, and session recovery.

After replacing the template path with the generated absolute workspace path,
the user explicitly runs:

```bash
openclaw agents add backtrader-agent \
  --workspace '/absolute/workspace/path' \
  --non-interactive
openclaw agents list
openclaw agent --agent backtrader-agent \
  --message 'Inspect my offline CSV, clarify a StrategySpec, generate a strategy, and stop at each apply/run approval.'
```

The generated `registration-manifest.json` contains the exact shell-quoted
workspace path. Use that command rather than copying the placeholder above.
