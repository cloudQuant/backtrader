# Historical CTP examples: configuration-first migration boundary

The scripts below `007_ctp` contain historical direct CTP/SimNow behavior,
including local order/cancel flows and certification cases. They are retained
for review and regression source history, but they are **not** Iteration 41
execution entrypoints.

The only registered profile is a local, zero-I/O `simulation/replay` migration
report. It does not import Backtrader, CTP, an SDK provider, legacy YAML files,
or credentials. It does not open a network connection, send or cancel an
order, simulate a fill, or claim CTP/SimNow/trading acceptance.

```bash
bt-runtime bootstrap --strategy-dir examples/007_ctp/runtime
bt-runtime run --strategy-dir examples/007_ctp/runtime
```

Use `bootstrap` for first-time setup. It creates the ignored, mandatory
schema-v4 `runtime/config.yaml` from the code-owned safe defaults; the tracked
`runtime/config.example.yaml` is for review and is not a manual setup step. A
missing file returns `CONFIG_REQUIRED`, and bootstrap preserves an existing
file by rejecting with `CONFIG_EXISTS`.

To inspect the config without running the local probe, use the offline doctor:

```bash
bt-runtime doctor --strategy-dir examples/007_ctp/runtime
```

`doctor` performs no provider or network I/O. The `LOCAL_REPLAY_ONLY` report
from `run` proves only the configuration gate and no-action probe.

`runtime-production/` is a legacy, unregistered schema-only location, not a
second operator configuration. The planned CTP production switch edits the
same protected `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`
and its canonical `ctp:` block used for SimNow, then selects the reviewed live
mode/preset on the same CTP execution runner. Today that switch still rejects:
shared-runner live dispatch and production-specific admission are not registered, so the default live route remains fail closed. See the [legacy-path README](runtime-production/README.md).

For compatibility, a no-argument invocation of a retired direct `run.py` runner routes
to this same registered runtime. Every historical flag, including `--config`,
`--dry-run`, `--mode`, `--all`, and child-process flags, is rejected before a
framework or provider import. The historical CTP/SimNow routes, penetration
cases, sandbox writes, and live writes are `NOT_SUPPORTED` until a separately
reviewed managed execution migration has its own admission evidence.
