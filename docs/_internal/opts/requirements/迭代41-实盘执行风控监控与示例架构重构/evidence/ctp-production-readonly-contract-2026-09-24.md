# CTP production read-only contract checkpoint (2026-09-24)

> **Historical legacy/deferred migration evidence; not the operator contract.** This checkpoint describes the old independent `ctp_production` parser/path and injected read-only contract. The current target is one physical registered runtime `config.yaml` with the shared canonical `ctp:` shape for SimNow and future production. SimNow comes first; production account/front values are not prefilled. No production runner/admission is registered or accepted, and these tests do not establish production readiness.

This checkpoint adds two production-specific contracts. The protected
credential resolver in `backtrader_runtime/ctp_production_credentials.py`
constructs an exact `RuntimeCredentialScope` from the sealed production
config/pin, rechecks the existing platform ACL and file-identity gate before
resolving values and before each value is released, and emits only a redacted
provenance-sealed credential source. The read-only orchestrator in
`backtrader_runtime/ctp_production_readonly_runtime.py` composes the same
production config pin with an injected seven-query session, checks stable
production account/session identity, requires the complete
account/position/order/trade/instrument/margin/commission digest set, verifies
the three CTP write counters remain zero, bounds the session lifetime, and
closes the session on both success and failure. Both contracts have all
provider, execution, and external-write authority fields fixed to false.

The read-only module has no SDK import or built-in provider factory. The
credential source is reachable only through its production-specific resolver;
it does not use `.env`, environment variables, or `resolve_runtime_config`.
Neither module has a default-registry entry, runtime registration, SDK pin, or
CLI route. Read-only output is classified as `INJECTED_SESSION_PROTOCOL`, and
`provider_session_verified` is always false. The credential tests replace the
OS ACL verifier with a fake gate, so they test check ordering and sealed-source
provenance without claiming that this Windows host's production ACL passes.
All fake tests therefore prove only local contracts; they do not prove an SDK
connection, production account identity, or a live provider observation.

Focused verification:

```powershell
C:\anaconda3\python.exe -m pytest -p no:asyncio `
  tests/unit/runtime/test_ctp_production_readonly_admission.py `
  tests/unit/runtime/test_ctp_production_credentials.py `
  tests/unit/runtime/test_ctp_production_readonly_runtime.py -q --tb=short
```

Result: 31 passed. Disabling the installed `pytest-asyncio` plugin is required
on this host because its version fails collection with the repository's newer
pytest configuration (`Package` has no `obj`). Ruff passed for the new module
and tests. Black passed after formatting with `--target-version py38`.

## Historical gaps in the legacy production parser path (not a second-config requirement)

1. The default inventory still has no CTP production registration. The
   production directory remains private and unregistered, and
   `load_runtime_config` refuses to read its config until a registration exists.
2. `resolve_runtime_config` still rejects `ctp_production` with
   `ctp_production_admission_unavailable`; no effective production config can
   reach the normal credential resolver.
3. The new production credential resolver reuses the current private-config
   Windows/POSIX ACL checks, but real Windows DACL acceptance for the reserved
   production directory has not been run. The current host's fake ACL tests do
   not replace this acceptance evidence.
4. The installed CTP artifact pin catalog is empty. There is no production
   SDK-backed read-only session factory or market-data adapter, and the shared
   SDK scope intentionally restricts itself to reviewed SimNow fronts.
5. No real production account/session or independent provider observation was
   performed. No SimNow or production network call was attempted in this
   checkpoint.
6. The production writer, account-wide risk/monitor/freeze/drain/reconcile
   lifecycle, independent approval receipt, operator controls, incident-stop
   exercise, and source-system order/fill/cancel acceptance remain unbuilt.

These injected contracts are historical prerequisites for testing the retired separate-parser path; they do not authorize or require maintaining a second operator config. The current production direction reuses `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` and its canonical `ctp:` field shape. After the production runner, admission, artifact/account/session controls and risk gates are independently implemented and accepted, the operator may edit that same file’s mode/preset and replace account/front/contract parameters. This historical module and its tests do not provide the runner, route, or live authority. Keep the default live route fail-closed and `LIVE_NO_GO`.
