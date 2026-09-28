# Iteration 41 G5 send-entry R2 follow-on

**Status: `R2_FAIL_CLOSED / G5 NOT ACCEPTED`.** This is an isolated candidate under `D:\temp`; it does not change the main repository, production/default route, protected configuration, credentials, or a real account. It imports no provider module and performs no network or native SDK call.

R2 removes the caller-supplied `sender` from `CtpManagedSingleWorkerCandidate.dispatch_managed_command`. The signature is now `(command_id, binding)`. Passing a callback raises Python `TypeError` before the callback body can run. After a durable claim, the worker enters one code-owned synchronous port. That port has no callable injection and always rejects because this candidate lacks a reviewed SDK pin, trusted time authority, and complete session/connection/process generation binding. The worker persists a local `REJECTED` receipt and the handoff state stays `REJECTED`; the Store command's `COMPLETED` status only means that the local rejection receipt was durably recorded. A duplicate dispatch returns the same rejection and cannot enter a native call.

For cancellation, the code-owned port performs a fresh same-Store durable projection-row read after claim. A deterministic test clock proves a projection that is fresh at claim but expires at this final read rejects with zero native entry. The Store's local monotonic clock is useful for the row TTL check, but it is not a trusted native-query/time authority. This port makes no actual native send and therefore does not claim a successful send-entry implementation. If the claim is lost to process death, restart recovery fences it to `UNKNOWN`; dispatch will not replay it.

## Evidence and exact commands

R2 focus is the four cases in `implementation/tests/test_g5_worker_send_entry_r2.py`: sender-parameter removal and pre-body rejection; final projection expiry check; missing generation/time/SDK authority default rejection; and claim-crash/reopen `UNKNOWN` with no replay. The complete isolated implementation tests passed **18/18**. The frozen SDK test comparison against candidate source reports **53 passed / 4 failed**; the same **57 tests passed** against untouched frozen SDK source. The four candidate failures are recorded in `evidence/r2-sdk-tests-candidate-source.log`: three legacy schema-version-5 assertions see schema 6, and one legacy direct CANCEL fixture omits the required typed projection. These are not suppressed or represented as accepted tests.

The original three red R1 cases remain under the parent research tree's `tests/test_r2_sender_entry_boundary.py`. The source, log, JUnit, and exit marker are copied into this candidate as `evidence/r1-send-entry-regressions.*`; `evidence/r1-send-entry-regressions-copy-verification.json` records matching before/after SHA-256 for all four. The cases showed (1) R1 exposed a caller sender, (2) a synchronous wrapper entered before returning an awaitable, and (3) R1 could cross TTL inside that arbitrary callback before fake native-entry. The original R1 worker focus test file is preserved verbatim as `evidence/r1-worker-focus-original.py`; R2 focus remains separate.

From PowerShell, rerun the R2 checks:

```powershell
$candidate = 'D:\temp\iteration41-g5-worker-projection-r2-boundary-20260927\r2-candidate'
$env:PYTHONPATH = "$candidate\implementation\sdk\src;$candidate\implementation"
python -m pytest "$candidate\implementation\tests" -q --tb=short
python -m ruff check --config "$candidate\inputs\sdk\pyproject.toml" '--select=E4,E7,E9,F,I' `
  "$candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py" `
  "$candidate\implementation\tests\test_g5_worker_send_entry_r2.py" `
  "$candidate\implementation\tests\_g5_worker_test_support.py"
python -m py_compile `
  "$candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py" `
  "$candidate\implementation\tests\test_g5_worker_send_entry_r2.py" `
  "$candidate\implementation\tests\_g5_worker_test_support.py"
```

The SDK comparison commands use the frozen `inputs\sdk\tests` folder and are recorded in `evidence/r2-sdk-tests-*.log`; `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider` were set. The exact R2 delta from the frozen R1 author candidate is `implementation/sdk_patch/G5_SEND_ENTRY_FAIL_CLOSED_R2.patch`.

## Frozen artifacts

The file-level SHA-256 manifest and its checksum are `candidate-output-manifest.json` and `candidate-output-manifest.sha256`. The frozen package ZIP is `D:\temp\iteration41-g5-worker-projection-r2-boundary-20260927\r2-candidate.zip`; its CRC/SHA verification receipt is stored in the parent research evidence directory.

## Blocking limits

- **G5 remains NOT ACCEPTED.** There is no trusted native target-projection producer or native query/readback port. The default V21-shaped verifier remains Reject; the test-only synthetic verifier proves persistence/readback mechanics only and is not native provenance.
- Caller-supplied seed assertions remain non-authorizing. The isolated worker ActionRef allocator is its sole candidate allocator; V21 has a separate allocator beginning at 1. They must not be combined. There is no trusted `MaxOrderActionRef` snapshot/cutover.
- `session_generation_id` does not prove OS process generation. The durable projection lacks a trusted current connection/process generation source. The prepared binding currently contains session generation and dispatch FrontID/SessionID, but no connection/process generations.
- There is no trusted current-time authority. Store-local monotonic expiry is not enough to authorize a native call.
- The existing Backtrader caller bridge/main-repository patch still reflects the R1 sender-taking API and is not adapted or integrated in this R2 slice. A mismatch fails closed with `TypeError`; no default route is changed.
- There is no real SDK pin, account/session, network, native send, order, or cancel. R2 supplies a safe disabled boundary, not a G5 acceptance or trading authorization.
