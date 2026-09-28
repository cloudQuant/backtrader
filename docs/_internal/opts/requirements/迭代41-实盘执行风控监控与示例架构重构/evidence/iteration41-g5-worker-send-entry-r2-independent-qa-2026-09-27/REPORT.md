# G5 send-entry R2 candidate — independent QA

**Verdict: `G5 NOT_ACCEPTED`.** The frozen R2 candidate closes the public caller-supplied sender API and its default native port rejects without required trust inputs. It does not implement an accepted SDK/native send path. All checks below used isolated source copies, fake SQLite state, and no network, credentials, private configuration, real SDK/native module, provider, account, or order.

## Frozen input integrity

- R2 ZIP: `D:\temp\iteration41-g5-worker-projection-r2-boundary-20260927\r2-candidate.zip`, SHA-256 `1ce285ed3e90f778ad05f55ded4263e522a54e04c7a20e3a5c30009bb298e283`.
- R2 candidate output manifest: SHA-256 `2b92b0a4d777221714f6b13f93eb9b39388993b4d0a585b35113d1eb4d6ed5e3`; its sidecar matched.
- Independent verification checked all 138 manifest payloads against ZIP bytes and the supplied extracted candidate, ZIP CRC, the exact 140-member set, and a fresh isolated extraction. Result: zero mismatches.
- R1 base ZIP: SHA-256 `c75cba6adcf7db95e420d0d4cfafac39e7179eb6db985cce5096a4c49237d268`; its 116-output manifest SHA-256 `5ddb3ca53bff3d61d287846a5feeaa8814fa9d211da109dd05f527c534351fbf` matched the independent R1 source copy.
- R2 patch SHA-256 `48aa0096432bcb4e46ee93c886d659b67a0ad402522898db01e58a32926d4f48`. In an isolated R1 clone, `git apply --check` and `git apply` both exited 0. The resulting README, worker, worker test support, and new R2 test file matched the R2 output manifest byte-for-byte; the old R1 worker test was removed as recorded. No frozen source was changed.

## Independent test results

All tests ran with CPython 3.11.5 from `C:\anaconda3\python.exe`; plugin autoload and pytest cache were disabled, bytecode was disabled, and each run used a separate temp directory.

- R2 implementation tests: **18 passed**.
- Frozen SDK tests against frozen SDK source: **57 passed**.
- The same 57 tests against R2 candidate SDK source: **53 passed, 4 failed**. Three legacy tests assert schema version 5 while the candidate migrates to version 6. One old direct CANCEL fixture omits the exact typed target projection required by the candidate. These failures remain visible and are not waived.
- The three archived R1 red regressions reproduced against a separately copied R1 baseline: **3 failed**, as intended. They reproduce (1) a caller `sender` parameter, (2) a synchronous wrapper side effect before an awaitable result is detected, and (3) TTL expiry inside the callback after which fake native entry still occurs and the command is marked `COMPLETED`.
- An extra fake CANCEL test passed. It observed the final projection check through the exact same Store after durable status became `CLAIMED`; when monotonic time moved from `expires_at_ns - 1` at claim to `expires_at_ns` at the final read, the worker returned `REJECTED`, `native_call_entered=False`, and the handoff remained `REJECTED`.
- The candidate's missing-trust-input test passed: absent connection/process generations, trusted time, and reviewed SDK pin cause a local rejection with no native entry.
- The claim-crash/reopen test passed: after a durable claim and simulated process close, recovery changes the command to `UNKNOWN`; retry does not re-enter a native port.

## Boundary findings

The normal R2 path removes `sender` from `dispatch_managed_command(command_id, binding)`. Passing a third-argument wrapper is rejected by Python before its body runs. The code-owned `_CtpSynchronousNativeSendPort` performs the same-Store fresh target read for CANCEL, then rejects because the trusted time and reviewed SDK port are unavailable (`ctp_single_worker_candidate.py`, port at lines 281–320; worker attribute initialized around line 357 and dispatched around line 759). Consequently, the tests prove a local post-claim TTL rejection, not expiry enforcement at a real SDK `Req*` call: **this R2 port never makes such a call**.

A further same-process adversarial probe replaced the worker's private `_native_send_port` attribute with a fake object. The fake side effect ran after claim; normal dispatch then persisted the unavailable-port rejection. The returned `native_call_entered=False` did not describe that monkeypatched Python side effect. No real native method was present or called. This only applies if code already holding the worker object can mutate its private Python attribute; it is not the default code-owned port path, but it shows that this in-process object is not an OS or hostile-Python integrity boundary.

`COMPLETED` in these results is **only the Store command status after a local rejection receipt was persisted**. The worker result and receipt outcome are `REJECTED`; it is not evidence that a provider completed or accepted a command.

## Acceptance boundary

R2 is a fail-closed local worker candidate with useful API, final-read, and no-replay regression coverage. Trusted target-projection production/readback, trusted native time, complete session/connection/process-generation binding, reviewed SDK pinning, and a real synchronous send port remain absent. The main Backtrader bridge is not adapted to R2. The candidate therefore remains **`G5 NOT_ACCEPTED`**; no write route is enabled.

## Reproduction commands

From the isolated R2 source copy, the implementation run used:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='<isolated-r2>\implementation\sdk\src;<isolated-r2>\implementation'
C:\anaconda3\python.exe -m pytest -p no:cacheprovider --basetemp <outside-source> <isolated-r2>\implementation\tests -q --tb=short
```

The SDK baseline/candidate runs used the same frozen `inputs\sdk\tests` path, switching `PYTHONPATH` between `<isolated-r2>\inputs\sdk\src` and the two candidate source roots. The R1 red test copy changed only its hard-coded source root to the separate verified R1 baseline copy; its assertions were not changed.
