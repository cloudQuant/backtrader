# P1-B mechanical fake-provider L2 runtime

This isolated runtime proves the Iteration 41 P1-B mechanical rail through a
local, in-process fake provider. It uses the existing three-leg
`MechanicalCycle` path with the real Backtrader CLI, Cerebro, Broker, Store,
and local execution/risk/monitor journals.

It does **not** connect to CTP or SimNow, accept credentials, submit an
external order, report an actual fill, or admit real trading. Do not use this
directory as a production or SimNow startup entrypoint.

Create the required local configuration, inspect it, then run the reviewed
fixture:

```powershell
bt-runtime bootstrap --strategy-dir examples/ctp_options_simnow_managed_replay_runtime
bt-runtime doctor --strategy-dir examples/ctp_options_simnow_managed_replay_runtime
bt-runtime run --strategy-dir examples/ctp_options_simnow_managed_replay_runtime
```

`config.yaml` is intentionally ignored and must be generated with
`bootstrap`. The fixed fake instrument metadata, fake account identity, and
fake provider exist only in the code-owned runner; neither `config.yaml` nor
command-line flags can convert this replay route to a CTP, SimNow, or live
route.

The local report deliberately separates six synthetic `MechanicalCycle`
callback fills from `sdk_confirmed_fills=0` and `actual_fills=0`. A cancelled
child only proves `RECOVERY_REQUIRED`; the three-leg compensation sequence is
a separate clean cycle, not recovery of the cancelled exposure. An unresolved
UNKNOWN survives restart as a durable risk freeze and blocks the next opening
before it reaches the fake provider. Use `--full-report` only when a developer
or tester needs those local diagnostics.
