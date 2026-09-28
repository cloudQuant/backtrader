# Independent QA — AC41-63 direct-dispatch fail-close candidate r1

Date: 2026-09-27. Scope is limited to the frozen local candidate. No main-tree files were changed; no credentials/private runtime config, CTP native module, live provider, or order route was used.

## Frozen input and exact-base replay

- Candidate root: `D:\temp\ac41-63-injected-broker-failclose-20260927\frozen-candidate-r1`
- Final manifest SHA-256: `d0fbc2c38f6bad8a8778a447fad4c8f0d5c7c7f34d9348d558da8b7791749dda`
- Patch SHA-256: `cc755c12522397c9980968f07655df0bbf90375ca03647d9f5b7e24d79bab0dc`
- Changed paths: two mechanical fixture modules, the direct SimNow live-runner module, and its two unit-test files (five total).
- I checked all five manifest preimage raw hashes against the main working tree, ran `git -c core.autocrlf=false apply --check --whitespace=error-all`, applied only in `D:\temp\ac41-63-direct-dispatch-qa-20260927\isolated-candidate-r1`, and verified all five target hashes against the final manifest. Main remained untouched.
- Baseline exact command: `python -m pytest -p no:asyncio tests/unit/test_ctp_options_simnow_mechanical_cycle.py tests/unit/test_ctp_options_simnow_live_runner.py tests/integration/test_iteration41_ctp_mechanical_managed_replay_l2.py -q --tb=short -rs`.
  Candidate result: **52 passed, 1 skipped**, one existing pytest config warning. The skip is the optional source-root condition (`bt_api_execution` unavailable), before the integration child launches.
- Candidate `py_compile` passed for all changed files; Ruff 0.16.2 passed for all changed files.

## Adversarial local probes

`candidate-r1-forged-descriptor-probe.py` used property descriptors for `buy`, `sell`, and `cancel` and forged caller mappings/signature-like strings.

- `SimNowLiveRunner` constructor and forged authorization path rejected with `TRUSTED_EXECUTION_AUTHORIZATION_VERIFIER_UNAVAILABLE`; descriptor lookups and calls: zero.
- Generic `MechanicalCycle` constructor kept the broker opaque. `arm`, buy submit, sell submit, and cancel rejected with `TRUSTED_MECHANICAL_DISPATCH_UNAVAILABLE`; descriptor lookups and calls: zero.
- Native CTP modules loaded: zero. Execution SDK modules loaded: zero. Network/provider calls: zero.

This supports a narrow fail-closed claim for the shipped generic `MechanicalCycle` and direct `SimNowLiveRunner` API paths. It does not sandbox arbitrary same-process Python code: a caller who deliberately writes a subclass/monkeypatch or directly invokes its own broker remains outside this boundary.

## Registered fake L2 positive: baseline-blocked, not verified

I ran the registered P1B integration in both candidate and pristine-base isolated copies with the same historical fake/local source map (`source-roots.json`, SHA-256 `5cf8b8f596ab5f2cd8bc89c52ed62f5421240ba93fe7b6ae7ba346496d21fa3e`) and its socket-denial guard. The map contributes the parent/base/execution/risk/monitor source roots only; it is not a release pin or native provider.

- Candidate failed in the staged `unknown` case: `_unknown` raised `RuntimeError("ambiguous fake-provider response was not marked UNKNOWN")` (`mechanical_p1b.py:697` in the candidate copy). Public CLI surfaced `runner_execution_failed` and `provider_io_may_have_started: true`.
- For the control, I copied the candidate isolation tree, restored the five exact main preimage files, and verified their raw hashes in `isolated-base-r1\baseline-restore-verification.json`. The same integration then failed at the same unknown-state assertion (`mechanical_p1b.py:640` in the base copy), with the same `RuntimeError` and CLI diagnostic.
- Both direct debug runs recorded `SOCKET_ATTEMPTS []`. This is a local fake-source failure, not a live/provider attempt. It establishes that the failure is also present on the exact base with these source artifacts; it does **not** establish the requested 9 fake submissions / 1 cancellation / 0 external writes output for either version.

Therefore the registered L2 positive remains **NOT VERIFIED** under the available historical roots. I did not attribute this failure to the candidate because the exact-base control reproduces it.

## Disposition

**SAFE_TO_APPLY_DIRECT_FAILCLOSE_ONLY**: exact-base replay, focused tests, descriptor traps, static boundary review, Ruff, and compilation support applying the generic/direct-runner fail-close portion only. Keep the disposition narrow: it does not accept the registered fake L2 positive, prove its 9/1/0 totals, authorize any CTP/native route, or close other writer inventory items. Treat the L2 integration as a baseline compatibility/source-artifact blocker until a source-root combination passes on both the exact base and candidate.

## Frozen QA outputs

Raw logs and their SHA-256 values are listed in `independent-qa-SHA256SUMS.txt` in this directory. Key logs:

- `candidate-exact-tests.log`
- `candidate-r1-forged-descriptor-probe.log`
- `candidate-l2-integration-historical-roots.log`
- `candidate-l2-direct-debug.log`
- `baseline-l2-integration-historical-roots.log`
- `baseline-l2-direct-debug-with-roots.log`
- `candidate-ruff.log`, `candidate-pycompile.log`
