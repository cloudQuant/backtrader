# G6 main-integration candidate r4 independent QA

Date: 2026-09-27

## Scope and verdict

**Narrow pass: local fake protocol integration only.** This QA does not approve G6-P/F14, a CTP session, SimNow or production execution, or any real writer route. No main-tree files were edited by this QA. The 10-file candidate is additions-only and remains absent from the main checkout; applying it still passes `git apply --check`.

## Frozen identity and replay

- Candidate: `D:\temp\iteration41-account-actor-runtime-main-integration-r2-candidate-20260927`
- Manifest SHA-256: `8bfcfb67c5d8de21d56e3d03d63478f81375e65f86b0f8c98e144a197b7f994f`
- Patch SHA-256: `e9c3996cc836c2d7628ba92c569060cfa78c140768cf612db7f395f66cf2ca22`
- Manifest sidecar SHA-256: `e8c91dfa3ec4d80534dc14980da0d93b36ae5c3837f47f2bb87a2941b91625ce`
- Verified main preimages: 11/11 match; includes Store SHA-256 `b9e1bcd3efa6cf57bf8d3029d60ae89a7158d5332b313ee8dfe12a4a0ca557ff`.
- Exact isolated replay payloads: 10/10 target hashes match the r4 manifest. The manifest repository HEAD equals current HEAD `ad2c142b9a8b42cede85886528c681abdfcb8096`.
- `git apply --stat`: 10 files, 4,914 insertions, zero deletions. `git apply --check` passed on main; all new targets were absent there during the check.
- Verification JSON: `exact-hash-verification.json`, SHA-256 `d09fd15d0f767a4c790fe895042216414620bec51866c0aca6b2dae897f23de3`.

## Test, import and inventory checks

- Fresh isolated replay: `D:\temp\iteration41-account-actor-runtime-r4-independent-qa-20260927`.
- Focused pytest under a `sitecustomize` guard blocking provider/native imports and socket operations: **65 passed in 7.55s**. Test log SHA-256 `1c554c9ca422fa78ead3c2f0b52a1c408bc5e51b6ce01d486c593ebc3e2b3d74`.
- Ruff on candidate package and three focused test files: **All checks passed**. Log SHA-256 `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0`.
- Guard event logs for tests, Ruff and imports are all `[]`; each has SHA-256 `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. Guard source `sitecustomize.py` SHA-256 `238b50b85568e81afe9d7c5c6196bb52a881a7e26da4f00d726c2048c771ca32`.
- Default package/registry import probe: 16 registrations; candidate not loaded or registered; `backtrader.stores.btapistore` not imported. Explicitly importing the candidate modules made zero `Popen` attempts. Provider/native modules loaded: none. Probe JSON SHA-256 `84068471578c97c0d45bf21be02f5b9960c4e67fff661ac96df4728774627bd9`.
- Independent official collector scan of the exact replay package: 6 files, 20 writer candidates, 1 dynamic `subprocess.Popen` candidate, 0 parse errors. Writer/dynamic candidate records and files-scanned list exactly match the frozen r4 delta inventory. Scanner output SHA-256 `6fb440c1bee0a58b99a011b6f1dc92ab36b7e87f90f978e7ca15c923382e58b3` (the full JSON also has run-specific metadata, so comparison was on the candidate arrays).
- Supplemental proposed 21-ID crosswalk SHA-256 `45ac3621456e49426d491c3f0d01d616d5c35c149b4446062d1e2e8c8d1743e9`: IDs/AST records and source hashes all match r4, ID digest recomputes to `e26be8d85edacdfaac78a77cc6f3b7ac109e6f9bf21c5906bc672b419fe24866`, zero overlap with the frozen 445 or tombstones. All 21 remain `REVIEW_REQUIRED / NOT_AVAILABLE`.

## Process boundary and limits

The client starts only the code-owned sibling `fake_actor_service.py` via an argument list (`sys.executable`, no shell) when a caller explicitly constructs it. Its child is a local SQLite ledger/fake sink and uses stdio JSON-lines; it does not import the runtime root or a provider. Default runtime imports and registration do not expose it. The candidate tests exercised queue line/byte limits, 64 KiB request and response-line caps, oversize rejection before write, bounded blocked-write and response waits, stderr draining with an 8 KiB retained tail, abrupt child exit, pipe closure, and forced-termination uncertainty.

This remains a same-user fake process, not a security boundary: child inherits the parent environment, the caller chooses its SQLite path, and there is no Windows Job Object/process-group supervisor. Forced termination reports cleanup uncertainty, but descendant cleanup is not established. Explicit direct import/construction can start the fake child. No provider/native/network/credential access was performed or authorized, and the candidate supplies no authenticated account snapshot, external writer fence, or real authority.

The 445-item official checklist was not changed or rebaselined by this candidate. The supplemental crosswalk preserves unresolved dispositions; scanner counts and these fake tests do not close any writer candidate or authorize a route.
