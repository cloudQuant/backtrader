# Independent source lease reconciliation review (R7)

**Decision: GO_SOURCE_LEASE_ONLY.** R7 fixes the Root preflight's third software-pin key spelling and the frozen production-loaded fake suite passes. The software pin dictionary uses the exact `str(Path(CUV2_RUNTIME_ORIGIN))` key parsed from the pinned Root runner; no alias or dictionary-key coercion was added.

## Exact reviewed candidate inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_okx_m01_local_source_lease_reconciliation_r7.py` | 67,503 | `8e7e3fb7e9b0e51968e6d8a3bdc47793c7ca276e55eb9cfd60367270aa8ebef5` |
| `tests/unit/scripts/test_iteration41_okx_m01_local_source_lease_reconciliation_r7.py` | 38,022 | `25ae3dd5bc34b0180e270ab6dc9985bbbaa008617cadc16ebd881c18aade4a88` |

Both candidate pins matched at review time. R1–R6 source, test, and review-record pins also matched their earlier reviewed values. The only behavioral helper change from R6 is the runtime software-pin key expression; R7 also adds the Root runner path constant and advances the result schema version.

## Verification

Ran only the supplied canonical isolated command from the existing `dev` checkout:

```powershell
& 'D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe' -m pytest -p no:asyncio -c NUL tests/unit/scripts/test_iteration41_okx_m01_local_source_lease_reconciliation_r7.py -q --tb=short
```

Result: **17 passed, 0 failed, exit 0**, in 13.56 seconds. Two `PytestCacheWarning` notices came from the `-c NUL` cache path. No other test command ran.

## Review findings

- The test reads the exact SHA-pinned Root public runner and its pinned source index as data. It parses the Root runner's `CU`, `CU_SHA`, `SOFTWARE`, and `SUPPORT` assignment shapes without executing the runner.
- It derives all 27 public pins from the Root runner's 20-row source index, six support pins, and the runner's own pin. It derives all three software pins from the literal executable/DLL keys and the exact `str(CU)` expression, then compares the maps with the candidate constants.
- Executable and DLL contents remain synthetic. The CUv2 runtime bytes come from the public SHA-pinned source snapshot. The test does not read the external executable/DLL payloads or private inputs.
- `_verify_scope` requires exact equality for the public and software pin dictionaries, including the Windows backslash spelling produced by `str(Path(CUV2_RUNTIME_ORIGIN))`; it does not normalize or add aliases to those dictionaries. The fake fixture separately asserts that the yielded raw-byte map has exactly that runtime key spelling. Raw-byte path matching inside `_verify_scope` continues to use normalized Windows path keys so equivalent `Path` spellings resolve consistently.
- The existing R6 checks remain: exact typed GateR1 context/result source binding, separate original projection dictionary retention, registry tuple identity, before/after finite projection, canonical contextmanager binding snapshots, one normal source-scope exit, and failure retention. No Job/process cleanup claim is made.

## Scope limits

This is source-and-fake evidence only. Tests exercise production-loaded Python modules with fake file APIs; they do not invoke the Root runner or close the live Root scope. No actual/native/WinAPI/process operation or account/provider read occurred. Root must still use the exact frozen R7 source and its original held scope/maps/evidence in same-call checks. A failed postverify may unwind file leases; retained Python references do not prove OS handles remain open.

No candidate edits, staging, or commits were made.
