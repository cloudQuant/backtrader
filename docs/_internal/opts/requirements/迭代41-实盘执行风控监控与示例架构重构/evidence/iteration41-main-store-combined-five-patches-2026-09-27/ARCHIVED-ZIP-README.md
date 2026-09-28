# Iteration 41 isolated patch-composition evidence

Status: **ISOLATED INTEGRATION EVIDENCE ONLY / NOT ACCEPTED.** No main-tree production files or private runtime config were edited. The copied tree excludes `.env` and the protected `runtime-ctp-private` subtree. No real SDK, account, network, or provider write was used.

## Reproduction

The exact-source baseline was copied from the r2c QA copy manifest and checked against its source hashes. Baseline and candidate started from the same Git tree `f2ebf8c0b48fdb878911be34bd4050e3b79840f5`. The copied base Store SHA-256 is `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`. The copy manifest is `BASE-COPY-MANIFEST.json` (3905 files; each listed source/destination hash matched); `.env` and the private runtime subtree are explicitly excluded.

The five original patches are preserved in `../inputs/` and applied in order. Patch 1, patch 2, and patch 3 required `git apply --check --ignore-whitespace --whitespace=nowarn` because mixed CRLF/LF caused strict check failures; all applied without manual hunk resolution. Patch 4 and the formal 013_3 patch 5 passed strict check/apply. The query seam source file was found at the package root, not under `isolated/`. Patch 1+2 Store content is byte-different only by line endings from the r2c author candidate: after CRLF/CR to LF normalization both SHA-256 values are `53CD937A7202990DF883FA071C210D31573F11DF83937C05880ABB3CBC50E90B`, with no normalized line diff. Patch 3 does not change Store.

`combined-five-patch-delta.patch` (SHA-256 `51182BAC574C27B5E22F2E289232E2ABE21EFE7833EAB8A4714586B0E7F2ABAD`) is the combined candidate delta from the exact-source baseline. It passes `git apply --check --ignore-whitespace --whitespace=nowarn` against that baseline. `git diff --check` reports mixed-EOL carriage returns as trailing whitespace; no line-ending normalization was applied.

## Test evidence

- Same-source baseline `tests/unit/stores tests/unit/runtime`: console summary `14 failed, 2472 passed, 189 skipped, 2 xfailed` (188.46s). Exact nodeids are in `failure-nodeid-diff.json`.
- Four-patch candidate broad suite (patches 1–4, before patch 5): console summary `253 failed, 2300 passed, 188 skipped, 2 xfailed` (280.03s). Its JUnit instead records 252 failures / 2301 passes; this one-test console/JUnit discrepancy is preserved. The precise JUnit nodeid set comparison shows 238 candidate-only failures, 0 baseline-only failures, and 14 retained failures. All 238 candidate-only failures report `BtApiStoreError: external account actor unavailable`; this remains an unresolved integration failure, not acceptance.
- After patch 5, the three formal 013_3 focus nodes were rerun under the startup import guard: **3 passed** in 15.59s with one existing pytest unknown-config warning. `backtrader` resolved from the isolated candidate; `bt_api_py` and `_ctp` loaded-module lists were empty; guard recorded no blocked SDK import attempts; no `D:\bt_api_py` path was present in `sys.path`. The candidate broad suite was not rerun after patch 5.

The broad Store/Runtime run environment skips optional SDK/dependency/platform tests; the import guard also recorded 95 denied optional SDK import attempts in baseline and 44 in candidate, with no SDK module loaded. Raw totals are not comparable to the current main tree. See the exact baseline/candidate JUnit files and complete nodeid difference in this directory.

The exact runner is `guarded_pytest.py`, Python `C:\Users\yunji\AppData\Local\Temp\bt-pytest-asyncio-compat-20260926\Scripts\python.exe`, with `PYTHONPATH=D:\temp\i41-store-merge\guard` and a per-run `I41_SDK_IMPORT_GUARD_LOG`; full args and environment notes are in `integration-report.json`.

## Interpretation and limits

This is an isolated composition diagnostic, not a merge candidate. The candidate still fails integration because existing Store consumers/tests encounter an unavailable external account actor. The five retained baseline failures include guard-blocked optional SDK tests and host/runtime environment failures. Patch5's replay-only 3/3 focus is local fake composition evidence and does not establish Store acceptance. I22 stable runtime-ID migration was not applied; its r1 independent QA was `PARTIAL / NEEDS_REVISION` and is not counted. Real native SDK/provider evidence, account lifecycle, default route, and CTP writes remain unaccepted and closed.

See `integration-report.json` for hashes, exact patch sources, guards, and counts; `failure-nodeid-diff.json` for every failed nodeid. Raw pytest/JUnit/environment/guard artifacts are kept alongside this README.
