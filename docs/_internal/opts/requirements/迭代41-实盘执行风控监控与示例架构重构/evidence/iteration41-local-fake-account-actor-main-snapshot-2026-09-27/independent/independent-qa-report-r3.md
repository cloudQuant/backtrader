# Independent QA — G6 main integration candidate manifest r3

## Verdict

**Behavioral and boundary checks pass for the isolated local fake candidate, but exact hash attestation fails. Do not accept this frozen r3 artifact as an exact hash-bound patch.** A rebuild is in progress to normalize three payloads to patch-replay bytes and bind the current `BtApiStore` preimage.

## Source and patch integrity

- Candidate root: `D:\temp\iteration41-account-actor-runtime-main-integration-r2-candidate-20260927`
- Manifest r3 SHA-256: `f88704de06de6fc479cc5d69b554ca612ccd333e7bd87ed5fd2e710417e84882`
- Manifest sidecar matches that hash.
- Patch SHA-256: `e9c3996cc836c2d7628ba92c569060cfa78c140768cf612db7f395f66cf2ca22`
- Patch is additions-only: 10 files, 4,914 added lines, no existing-file changes or deletions. `git apply --check` passed on current main; all ten target paths remain absent from main.
- At the replay snapshot, all listed base-file hashes matched r3, including `backtrader/stores/btapistore.py` at `40f776e783388dfa0a5499501e5886744ffd1d74d259e17d3adecd9a20a5c457`. Root subsequently integrated Gateway R2; current Store hash is `b9e1bcd3efa6cf57bf8d3029d60ae89a7158d5332b313ee8dfe12a4a0ca557ff`, so r3 is now stale against current main. The patch itself remains additions-only and still passes check.
- Fresh replay: `D:\temp\iteration41-account-actor-runtime-main-integration-r2-independent-qa-20260927`, built from current-main runtime sources and the captured Store preimage before applying the candidate patch. `git apply --check` and `git apply` succeeded.
- Seven of ten replay target hashes match r3 payload hashes. Three differ only by a single CRLF byte: replacing the one payload CRLF with LF yields the replay bytes exactly.

| Path | Manifest payload SHA-256 | Replay SHA-256 | Bytes |
|---|---|---|---:|
| `backtrader_runtime/_local_fake_account_actor_candidate/account_actor_port.py` | `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48` | `1cb3cfa6534da6974e7ec656ac54c413445401c819b3efd48e57c6be54cb7409` | 25739 → 25738 |
| `backtrader_runtime/_local_fake_account_actor_candidate/store_boundary_harness.py` | `fdd4219850b87816a44a8bf3a70911f2445afe40f9e32cc24fe65421b8067ff9` | `291eda0a2f0a31fde9b66304161bdf86285abe6a959405add6ec04473084d5d1` | 5115 → 5114 |
| `tests/unit/runtime/test_local_fake_account_actor_store_boundary_candidate.py` | `ac4575c9fe6a7cff436d1068af4bfca577c82ace4bef13323d503d7d2f2163d6` | `31ba27d73fdfad55ba0dafcb1c22d08fc851d29863ecfc62bf30689dad4c001b` | 31332 → 31331 |

The supplemental 21-ID inventory binds `store_boundary_harness.py` to the payload hash `FDD421...`; the replay source hash is `291EDA...`. Its candidate ID is stable, but that source hash must be updated when the artifact is rebuilt.

## Tests and runtime boundary

- On the fresh replay: `python -B -m unittest discover -s tests/unit/runtime -p 'test_local_fake_account_actor*' -v` — **65 passed**. Transcript SHA-256: `b46830fa1ecd34d321012e60d7a8343b045ea37e890bc131126c6d7fefd9a62e`.
- Ruff: `python -B -m ruff check backtrader_runtime/_local_fake_account_actor_candidate tests/unit/runtime/test_local_fake_account_actor_candidate.py tests/unit/runtime/test_local_fake_account_actor_server_core_candidate.py tests/unit/runtime/test_local_fake_account_actor_store_boundary_candidate.py` — all checks passed. Transcript SHA-256: `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0`.
- SDK/native import and network guards were inherited by the test process and child service. Guard log was absent; no guarded attempts occurred.
- A separate guarded import probe with `subprocess.Popen` trapped found 16 default runtime registrations, no candidate module loaded or registered, no `BtApiStore` import, and no process started by explicit candidate module imports.
- The official collector run against the six new source files found **20 writer candidates and 1 dynamic `subprocess.Popen` candidate**, 0 parse errors. It exactly matched the frozen candidate-delta inventory. Sorted candidate-ID digest: `E26BE8D85EDACDFAAC78A77CC6F3B7AC109E6F9BF21C5906BC672B419FE24866`.
- Dynamic consolidation cross-check: proposed inventory SHA-256 `142E8BACF6DABD6320C18A458CFD23858C671D42FB57020EE0C3E97EF3D06C43`; all 21 IDs match the patch manifest, all remain `REVIEW_REQUIRED / NOT_AVAILABLE`, and the set has zero overlap with the frozen 445 or current dropped-candidate tombstones. The candidate records a pre-existing main-tree inventory mismatch: the current collector reports 441 candidates while the checked-in disposition inventory has 445 entries, including four dropped-candidate tombstones. The main patch does not add these 21 rows to the checked-in disposition checklist, so reconcile that baseline and add all 21 rows as REVIEW_REQUIRED / NOT_AVAILABLE before merge.

## Process and safety assessment

The candidate is isolated from the default runtime/Store path. Its client launches a fixed sibling `fake_actor_service.py` using `sys.executable` and an argv list (no shell), with stdin/stdout/stderr pipes. Request bytes are capped at 64 KiB; response lines and queued line/byte counts are bounded; stderr retention is capped at 8 KiB; request/response waits use deadlines. The fake tests cover oversize, queue overflow, stalls, abrupt exit, and blocked writes.

Residual process limits remain: parent and child share one OS principal and inherited environment; the caller-supplied SQLite path is not confined by this package; the child is not supervised by a Windows Job Object/process group; termination marks cleanup uncertain and does not prove descendant closure. The port exposes `close()` but no context-manager or destructor helper, so callers must close it explicitly. No provider/native SDK, credentials, or network was used. This remains `LOCAL_FAKE_ONLY`; it establishes no G6-P, F14, SimNow, production, or write authority.

