# Iteration 41 CTP private runtime

This registered runtime uses one protected, Git-ignored file:
`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`. The file
uses the canonical top-level `ctp:` block for the CTP account, contract,
HedgeFlag, and explicitly configured MD/TD addresses. The registry declares
only a `simulation/sandbox` private read-only profile. Ordinary CLI
`preflight` is currently disabled pending a bounded Windows Job supervisor.
Preparing the file grants no provider admission or execution authority.

## Prepare the shared config

Use the official `bt-runtime prepare-ctp-config` command with one or two
explicit owner-only local sources:

```powershell
bt-runtime prepare-ctp-config --source-env "D:\private\simnow.env"
bt-runtime prepare-ctp-config --source-yaml "D:\private\simnow-source.yaml"
bt-runtime prepare-ctp-config --source-env "D:\private\simnow.env" --source-yaml "D:\private\simnow-scope.yaml"
```

The YAML source uses a canonical `ctp:` mapping. For a single configured
address pair, its shape is:

```yaml
ctp:
  md_front: "<explicit MD address>"
  td_front: "<explicit TD address>"
  instrument_id: "<contract>"
  exchange_id: "<exchange>"
  hedge_flag: "1"
  broker_id: "<account value>"
  user_id: "<account value>"
  password: "<secret>"
  app_id: "<account value>"
  auth_code: "<secret>"
```

This is a schema sketch, not a usable source file. The setup command writes the
single target `config.yaml` with `runtime.mode: simulation` and
`runtime.preset: sandbox`; it does not copy mode or preset values from a source.

For multiple candidates, list exact MD/TD pairs in operator order. Do not add
backend, group, or set labels: the runtime measures only these configured pairs,
uses list order only to break equal scores, and never selects by time, calendar,
TradingDay, or session schedule. Use this instead of the single-pair fields:

```yaml
ctp:
  front_pairs:
    - md_front: "tcp://<md-host-1>:<port>"
      td_front: "tcp://<td-host-1>:<port>"
    - md_front: "tcp://<md-host-2>:<port>"
      td_front: "tcp://<td-host-2>:<port>"
```


An explicit `front_pairs` list is also supported when several exact MD/TD pairs
are intentionally configured; the registered route can measure only those
configured pairs with a bounded credential-free TCP probe. A set name, clock,
calendar, or session schedule does not choose a pair, and a later login failure
does not trigger endpoint fallback. The legacy `ctp_simnow:` source spelling remains
accepted for migration, but new sources should use `ctp:` and the output is
always canonical.

An existing collector YAML may supply the account and address fields; the
instrument, exchange, and HedgeFlag must then come from a second explicit YAML
source:

```powershell
bt-runtime prepare-ctp-config --source-collector-yaml "D:\bt_api_py\ctp_data\collector.yaml" --source-yaml "D:\private\simnow-scope.yaml"
```

The collector's `ctp.env` label and timeout are ignored. Its `md_front` and
`td_front` values are copied exactly. Both files must pass the owner-only ACL
check before either is read. If a field appears in both sources, the values
must agree. The command does not search the current directory, read process
environment variables, overwrite an existing config, or print account or
authentication values. A missing field leaves the target file absent. The
older `prepare-ctp-simnow-config` name remains as an alias; use
`prepare-ctp-config` for new operator instructions.

## Check the same file

For subsequent account, contract, or front changes, edit this same protected
`config.yaml`, save it, then run `doctor` and (when a network check is useful)
`check-ctp-fronts`. The check tests only the configured MD/TD TCP pairs without
an SDK, login, or one-shot diagnostic marker. The ordinary CLI `preflight`
command is currently disabled for this registered runtime:

```powershell
# Optional: validate config offline; this does not access a provider.
bt-runtime doctor --strategy-dir examples/013_3_sa_midfreq_simnow/runtime-ctp-private
# Optional: bounded, credential-free TCP reachability check for configured pairs.
bt-runtime check-ctp-fronts --strategy-dir examples/013_3_sa_midfreq_simnow/runtime-ctp-private
```

`doctor` validates the config without provider or network I/O. The front check
reports zero-based candidate indexes and MD/TD success counts, never addresses
or authentication values. With the current three samples per endpoint, a pair
is eligible when MD and TD each succeed at least twice. The selector compares
the median successful connection latency of MD and TD for each eligible pair,
scores it by the slower median, and chooses the lowest score; config order
breaks ties. TCP reachability does not prove login, trading, or settlement
readiness. The 013_3 `doctor` result includes an `operator_actions` summary:
offline configuration check, TCP-only front check, disabled native preflight,
unavailable run, and unavailable live route. If this same file requests live,
`doctor` reports the request and `authorization: not_granted`; editing the
config alone does not enable production trading. The CLI rejects `preflight` with
`ctp_simnow_preflight_supervisor_required` before loading this private config,
resolving credentials, importing the CTP SDK, or starting provider/network I/O.
Native SDK startup and shutdown can outlive their observation timeout, so this
route needs a hard process supervisor before the ordinary command can be
re-enabled. I2 TD completed seven queries, but native Join did not complete;
its separate MD-only diagnostic also lacked an accepted login, subscription
acknowledgement, matching tick, and complete native close. See the
[historical I2 evidence](../../../docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/validation-summary-2026-09-24.md).

The latest supervised, separate I11 MD-only diagnostic ended
`incomplete / native_join_pending`. A subscription ACK was observed, but login
identity remains unverified; no matching tick or same-trading-day evidence was
confirmed, and native close did not complete. The Windows Job contained and
then terminated the child; the I11 one-shot marker is consumed and must not be
reset or retried. See the [I11 evidence](../../../docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i11-md-diagnostic-2026-09-25.md).
The prior I8 result remains historical ([I8 evidence](../../../docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/ctp-i8-md-diagnostic-2026-09-25.md)).
An ACK does not prove identity, a tick, orderly close, account readiness, or
order acceptance. The ordinary CLI gate does not alter the independent
supervised one-shot diagnostic policies or the credential-free front check.
This runtime has no runner, so `bt-runtime run` is not a SimNow or production
execution path. Keep `NO_WRITE / LIVE_NO_GO`.

## Production remains unavailable

Future production uses this same physical protected file, canonical `ctp:`
block, CLI entry, and managed CTP execution implementation. Once the shared
write runner and both modes' admission have been implemented and independently
accepted, the intended operator change is to edit this file's mode/preset and
replace its account and authentication, MD/TD fronts, and contract fields.
The preparation command is not rerun; no second CTP config or separate
production runner is created. This is a target workflow, not current
capability: the shared write runner and live admission are not wired. Field
changes alone remain fail-closed; the production account, approvals, artifact
pins, risk controls, and provider evidence require separate acceptance. A
SimNow receipt or approval cannot be reused after changing the account or mode.

The old `bt-runtime prepare-ctp-production-config` command and its
`runtime-production/` location are legacy/deferred migration evidence, not an
operator path. Do not create a second CTP operator config for this runtime.

Do not put real account values in this README or any tracked template. The
tracked `../config.yaml` is an Iteration 22 strategy parameter file, not the
Iteration 41 runtime config.
