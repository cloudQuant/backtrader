# Historical CTP sample: configuration-first migration boundary

`../sample.py` used to import `ctpbeebt.CTPStore`, read `params_01.json` from
the current working directory, and call `beeapi.action` directly. That legacy
path has no Iteration 41 execution admission. It is now a fail-closed,
configuration-first migration shell.

The only registered profile is a pure local `simulation/replay` no-action
check. It does not import Backtrader or CTP, read credentials or
`params_01.json`, connect to CTP/SimNow, submit an order, simulate a fill, or
claim trading evidence. Sandbox and live execution are `NOT_SUPPORTED` until a
separate managed SDK/execution implementation and acceptance package exists.

## First run

Create the ignored local contract once:

```bash
bt-runtime bootstrap --strategy-dir examples/sample/runtime
```

Then run the same registered directory:

```bash
bt-runtime run --strategy-dir examples/sample/runtime
```

The generated `runtime/config.yaml` is required and is never replaced by
`config.example.yaml`, `params_01.json`, the current directory, environment
variables, or CLI flags. If it is missing, the command returns
`CONFIG_REQUIRED`; rerunning bootstrap on an existing file returns
`CONFIG_EXISTS` without overwriting it.

The report has `LOCAL_REPLAY_ONLY` scope and records zero network and order
write counts. `LOCAL_REPLAY_PASS` proves only that the v4 gate and no-action
probe ran. It is not a CTP, SimNow, sandbox, live, provider, fill, PnL, or
profitability result.

## Legacy boundary

The historical direct action method names remain as deterministic disabled
compatibility shells in `sample.py`; every `buy`, `short`, `cover`, or `sell`
attempt raises before dereferencing a `beeapi.action` object. The old `run.py`
style direct-launch workflow is retired: `sample.py` accepts only
`--runtime-dir`, and it validates the registry and required configuration
before any framework or provider import.
