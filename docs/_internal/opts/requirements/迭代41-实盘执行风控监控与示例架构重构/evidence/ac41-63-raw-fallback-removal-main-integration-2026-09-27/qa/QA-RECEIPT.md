# AC41-63 writer slice2 r2 rev2 independent QA receipt

**Verdict:** `SAFE_TO_APPLY_RAW_FALLBACK_REMOVAL_ONLY`

This verdict covers only removal of the `CtpClientWrapper` raw `ReqOrderInsert` / `ReqOrderAction` fallback in the two candidate helper methods. It does not authorize CTP writes, establish a trusted actor, or certify the typed SDK path. The private `_execution_gate_capability` is mutable same-process Python state and can be forged by caller code. A real external admission/actor authority remains unproven; keep CTP production and live execution closed.

## Frozen input identity

- Author package: `D:\temp\ac41-63-writer-slice2-r2-rev2-20260927\R2-REV2-PACKAGE.zip`
- ZIP SHA-256: `c9a2456d6fff2a1d5743f2402d423eb783720dff90cbe02164e83d27216e3e0b`
- Manifest SHA-256: `ad48e4dd52404bcb97180aa7fd49f7312bc39dce1cabf3194d0288f39658226a`
- 44/44 manifest payloads matched path, byte count, and SHA-256. ZIP has 46 expected members (44 payloads plus manifest and SHA256SUMS); `ZipFile.testzip()` returned clean.
- Store patch SHA-256: `2182f12a729afc39dfa6ba4c23bb4accd557f4dcda3138ef238cb039e52de291`
- Test migration patch SHA-256: `43217ec36a412d68e91133ff9c2b640a47dc0ae49c1eac64abc0cb0b3bc39d7b`
- Frozen candidate status remains `ISOLATED_PATCH_CANDIDATE_AWAITING_INDEPENDENT_QA_NO_WRITE_LIVE_NO_GO`; manifest says `write_authorized=false` and `capability_trust_established=false`.

## Exact-base and byte identity checks

At isolated replay start, the main preimage hashes matched the specified base: Store `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`; migrated test input `E7E7B985130F010DEED84B920FD0F91712BFE54AC24B5EF8BF1C8FC687BCA6B1`. I copied these files into separate QA baseline/candidate trees and applied patches with `git -c core.autocrlf=false apply --check` and `apply`.

- Candidate Store output exactly matched `05268b4953a20fa0699639f7e05ee354a4bcafc4b47915dd4ba352b26276e0d9`.
- Migrated test output exactly matched `649137b29e68f231451c61144ffdc01a0ef80176f7005b0cb9c45e3b72b7a3a1`.
- Independent reconstruction from `BYTE-REPLACEMENTS.json` verified both replacement block hashes, offsets, lengths, byte-identical unchanged prefix/interstitial/suffix, and target SHA. CRLF count changed 15,583 → 15,593; bare LF remained 1,462 → 1,462. No whole-file EOL normalization occurred.

The test migration preserves the positive typed submit contract and assertions for `InstrumentID=IF2506`, `ExchangeID=CFFEX`, `OrderRef=bt-77`, volume, limit price, request id, capability object identity, and zero raw API calls. It adds an insert raw-only rejection and parameterized cancel raw-action rejections for both missing capability and missing typed method.

## Independent tests and probes

All execution used isolated QA copies and fake CTP modules. Guards blocked `bt_api_py` / `bt_api_risk`, unexpected CTP imports, external socket connects/name resolution, and CTP-related DLL loads. Guard JSON for candidate/base reports 0 external network attempts, 0 CTP native loads, and no real optional SDK modules.

- Guarded focus: candidate 4 passed; exact-base control with the same migration 1 passed / 3 failed. The 3 base failures are exactly the new insert rejection and the two cancel rejection cases, demonstrating the old fallback/descriptor access.
- Two-file current-source suite: candidate 342 passed / 2 failed; exact-base control with the same migrated test file 339 passed / 5 failed. Both sides executed the same 344 nodeids; candidate-only failures: 0. The three failures removed by the patch are exactly the insert rejection plus two cancel cases. Two remaining shared failures are inert-shim limitations: missing `_MdSpi.OnRspQryInvestorPositionDetail`, and the intentionally blocked optional `bt_api_ctp.containers.ctp.ctp_order.CtpOrderData` import.
- The full-run count differs from the author package's 341 cases because the current shared `test_btapistore_iteration22.py` input has SHA-256 `30eeaa2c9816e6d0792e801a6ea2a8960cc1bcaa3728679111318e5178afa49d`; compared with the frozen author JUnit, it contains four newer nodeids and no longer contains one earlier nodeid. Candidate/base in this QA use the same current file, so this does not alter the 3-case failure delta.
- Independent direct helper probe: candidate 8/8 predicates passed; the exact-base control reproduced six unsafe cases (descriptor read before absent-capability check, or raw fallback reached) and two typed-fake positives.
- `py_compile`: passed. Ruff on candidate Store and migrated test: passed.

The full suite's two shared shim failures are retained in the logs; they are not treated as passing tests or candidate regressions. No real SDK/provider/native/network/order action was run.

## Main-tree timing note

A final read-only recheck after the isolated QA runs found that the main Store/test files had concurrently changed from the exact preimage to the candidate output hashes (`05268b…e0d9` and `649137…a3a1`). This QA agent did not edit the main tree. The independent apply/tests were performed in copies made from the preimage before this observed drift. The hashes indicate the main files now match the candidate payload; this receipt is still an independent candidate review, not a replacement for post-application main-tree regression results.

An extra inspection helper moved from an older pre-rev2 package directory is recorded at `extra-script-identity.json` with its SHA-256. It is not part of the formal rev2 ZIP or its 44 manifest payloads. Formal rev2 manifest, ZIP, source, and patch hashes above remain the authoritative inputs.

## Reproduction commands

From each isolated tree root (Python executable: `D:\source_code\backtrader\.venv\Scripts\python.exe`):

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONPATH = '<QA root>\suite-candidate' # use suite-baseline for exact-base control
python -B -m pytest -p no:asyncio tests/unit/stores/test_btapistore.py `
  -k 'raw_only_client_before_api_access or cancel_rejects_without_raw_action_access or submit_order_supports_exchange_prefixed_symbol' `
  -q --tb=short --junitxml <QA root>\candidate-focus.junit.xml

python -B -m pytest -p no:asyncio tests/unit/stores/test_btapistore.py `
  tests/unit/stores/test_btapistore_iteration22.py -q --tb=short `
  --junitxml <QA root>\candidate-two-files.junit.xml
```

Use the separately archived `probe-boundary.py` for the eight inert direct-helper cases, passing the isolated tree and JSON output path. `verify-package.py` and `verify-byte-identity.py` reproduce payload and mixed-EOL checks.

## QA artifact location

This receipt and its hash-bound manifest/log archive are under `D:\temp\ac41-63-writer-slice2-r2-rev2-independent-qa-20260927\qa-package`. The author candidate remains separate and unchanged.

### Post-application result reported by root

After I sent the limited verdict, root applied the exact source/test patches. Root reports final main hashes matching the isolated outputs and a main-tree rerun of `test_btapistore.py` at 138/138 plus the full Store/Runtime lane at 2,641 passed, 43 skipped, 2 xfailed, 0 failed (113.22s). This is a root-reported integration result, separate from my isolated candidate/base runs above.
