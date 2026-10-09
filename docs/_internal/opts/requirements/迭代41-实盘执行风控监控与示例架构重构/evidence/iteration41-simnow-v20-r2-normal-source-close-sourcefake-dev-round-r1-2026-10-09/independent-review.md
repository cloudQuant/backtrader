# Independent review: SimNow R2 normal source close

**Date:** 2026-10-09  
**Decision:** `GO_SOURCE_FAKE_ONLY` for the frozen helper, its three source-fake cases, and the Root QA harness design. This is a static review; no tests or QA harness were run.

## Frozen bytes reviewed

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| R2 close helper | 35,246 | `a42726bab6052e537e27df3349b1ac562138368190ebcf0646e15989c37a109e` |
| R2 close tests | 26,165 | `7978e86158ef8443915556dc0fa9b93d6b737e23ecb1f33115515aec0ba0e959` |
| Root focused QA R1 | 39,370 | `a0c762bd73343af49e180c5ee88889c61999c7455f8b22d495860bc0617d36fc` |
| Adaptation base: accepted SimNow R3 Root QA | 38,964 | `e06f529a7d5237180e0aee2ddb6bf1fbc1e7696e2bd6d7f6faf819827d68e029` |

The reviewed public execution chain includes caller R2 (24,722 / `359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0`), preparation entry R6 (24,159 / `02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f`), launch R2 (5,782 / `9af785b32f1a807867789f70268c2580b43c032bcf2f7857ef4231a6a5ec7429`), and the R3 driver (158,926 / `4f05194dea1a029a0950dba69e3644ce5e518253aa0d8a727687d707fed0b963`). The QA harness pins these alongside the bounded precheck, credential-free caller, runtime manifest, and all 26 public manifest rows: 34 public inputs total.

## Review findings

- The helper validates the exact failed R2 launch, caller source/function/code/global bindings, retained exception and summary, single attempt, preparation host, source-module aliases, driver/precheck bindings, and the lease's held public bytes. It checks the 26 public rows against both their hashes and the same byte objects held by the host lease. The three software rows are checked as synthetic held-map identities; the test's oversized DLL fixture is synthetic. No real software bytes are read.
- The only close operation is the captured `contextlib._GeneratorContextManager.__exit__(manager, None, None, None)`. Success requires the literal result `False`, an exhausted generator, the driver's lease checks and byte postverification, and unchanged retained state. The helper removes only its own keepalive tuple after those checks. Exceptions or uncertain postverification return blocked while retaining the reference. It does not create a parent-process receipt, invoke the Gate, release native state manually, or exit a host.
- The three cases cover normal close with original R2 objects preserved, precheck rejection without calling exit, and post-close uncertainty that retains the one-shot reference. They use the pinned R2 launch, caller, R6 preparation, bounded precheck, and driver sources against synthetic CUv2/software leaves.
- The QA harness adaptation selects exactly those three named methods in one unittest suite and changes the case/source/schema/count bindings for the R2 close. Its 14 outer guard self-checks, canonical-origin checks, preopened bounded input snapshot, post-run source-pin checks, and existing stdlib module/attribute identity checks remain. The removed `ThreadPoolExecutor` assertion was specific to the R3 test: the R3 fixture imports that attribute, while the R2 source/test chain has no `ThreadPoolExecutor` import or attribute access. R2's test setup contains only string names for preloading `concurrent.futures` modules. No reached lazy `ThreadPoolExecutor` attribute is left unchecked; the general attribute snapshot and late-module identity check remain in force.

## Evidence boundary

This review establishes source-fake design only. Neither the helper nor Root QA was executed here. It does not establish a close in retained hosts 1497 or 65851, preparation, Gate, provider/account behavior, or formal C01 acceptance. No retained host, private input, or real software payload was accessed. Historical R1/R2 HOLD evidence remains unchanged.
