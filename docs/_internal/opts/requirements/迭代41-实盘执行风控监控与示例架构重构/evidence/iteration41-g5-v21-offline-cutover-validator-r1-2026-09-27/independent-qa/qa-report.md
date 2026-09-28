# G5–V21 offline ActionRef cutover validator r1 — independent QA

**Disposition: `PASS_LOCAL_TYPED_CONTRACT_ONLY_WITH_PROVENANCE_NOTE`.** The isolated byte-level replay and fake/synthetic tests pass. This validates only a pure in-memory consistency checker over caller-supplied typed projections. It is not a database exporter, migration tool, authorization, account authority, or production acceptance. `NO_WRITE / NO_AUTHORITY / NOT_A_MIGRATION_TOOL / LIVE_NO_GO` remain mandatory.

No candidate or main-tree files were edited. Replay and tests were performed only under `D:\temp\iteration41-g5-v21-offline-cutover-validator-r1-independent-qa-20260927`; no SDK/native/provider, private config/credentials, network, account, database, or runtime command was accessed. `PYTHONDONTWRITEBYTECODE=1`, `-B`, plugin autoload disabled, and pytest cache disabled.

## Frozen identities and exact patch replay

- Candidate root: `D:\temp\iteration41-g5-v21-offline-cutover-validator-r1-20260927`.
- Candidate manifest `CANDIDATE-MANIFEST-r1.json` SHA-256: `ff9b2ac5e8e688c10fb22d95328b923d8f4c7dc972db2068c1a6106d5254f7ef`.
- Patch `OFFLINE-ACTIONREF-CUTOVER-CONSISTENCY-r1.patch` SHA-256: `339c8450722f18c9061d4960377ca0939032c2dc7f0453592d05674f18f093a4` (24,590 bytes).
- Referenced r0 final manifest SHA-256: `9252f88150efafe055dbaf4a134bfa056a651150d785b8cc1c2490669a60f2df`.
- Strict `git -c core.autocrlf=false apply --check` and apply both returned 0 in the separate QA copy. All four preimage hashes matched the r1 manifest and the applied four outputs exactly matched `target_sha256` and `replay_sha256`:

| Path | r0 preimage SHA-256 | r1 replay/target SHA-256 |
|---|---|---|
| `src/offline_cutover_validator.py` | `2760a43ede16b8bfc680a75ce16f4c83c5a75fad42db27729fdf3beaba86a4bf` | `ce13d2ca96c028e7bbe304082ef693d28caaf89fc65ad3086a0074584285b95a` |
| `tests/test_offline_cutover_validator.py` | `7515ab2e78d61aaf15dd918e240e324d43ef7784d540825e10a231f7067ddddc` | `1a49521e7387de6a0ed634685ef0c94c683255cc6bc5e12da7b7630bdc2b61bd` |
| `docs/CANDIDATE.md` | `62f0d33cc88295ba623073a4993e88de5dc561497338413d6cc7ec17981a6428` | `a21998d6c73ec42db5ebcf86ffa45c36c0d1f11677de9402c993006b1d4b2b6d` |
| `docs/LIMITATIONS.md` | `e4323bd0221e01786b3abfd3103fb1d8392d62f3bebbb51474e97cb40305754d` | `ea7404497a6bf7c7804346ac14d832a14926e68a85effc6b32e9bbe00f87113f` |

Pristine preimage copies, patched outputs, patch, and both manifests are retained separately in this QA directory. See [`replay-and-test-record.txt`](replay-and-test-record.txt).

**Manifest provenance note:** r1 declares the referenced r0 Git commit as `213574e`. In the referenced r0 directory, `git rev-parse --short HEAD` is `103facd`, and `git cat-file -e '213574e^{commit}'` exits 128 (object absent). The exact r0 final manifest SHA and all four payload preimages are independently verified, so byte replay is reproducible; the short Git-commit field is not corroborated and should be corrected or explicitly footnoted before treating that metadata as authoritative.

## Test verification

Author JUnit SHA-256 `79fe3a868619062271fbbd8c0c0d02f4d8a0bcee9b704a4261c8404630a5cc27` matches the candidate manifest. The author report says 28 passed. Independent replay run:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='src'
D:\source_code\backtrader\.venv\Scripts\python.exe -B -m pytest -p no:asyncio -p no:cacheprovider tests/test_offline_cutover_validator.py -q --tb=short --junitxml=<qa-root>\independent.junit.xml
```

Result: **28 passed, 0 failed, 0 skipped, 0.48 s**. Independent JUnit and raw stdout are retained here.

A separately selected adversarial subset passed **5/5** (0.46 s): same-boundary state mismatch; distinct `snapshot_boundary_id`; hostile schema comparison dunder; hostile row `to_payload`; and a nonprimitive field equality callback. The callback counters remain empty in the test assertions. The selected JUnit/raw stdout are retained here too.

## Static contract review

- `src/offline_cutover_validator.py:111-124`: `_safe_row_payload` first requires exact `ActionRefEvidence` and exact primitive field types, using `object.__getattribute__` after the exact-type check. It does not call caller row serialization methods.
- `:207-275`: snapshots require exact type, readable/complete flags, tuple rows, exact field types, declared count and digest consistency, valid high-water, and unique action/ref identities. Unsupported, empty, and `UNKNOWN` states reject.
- `:314-357`: both snapshots must use the same nonempty boundary ID; V21 high-water cannot trail legacy; each action's state and complete shared identity tuple must match. Mismatch rejects.
- `:94-98`: report defaults make `authority=False` and `write_enabled=False`.
- The test module imports only `dataclasses.replace`, `pytest`, and the local candidate module. The candidate module imports only standard-library hashing/JSON/regex/dataclass/typing modules. No database, filesystem, runtime, SDK, provider, or network adapter exists in this patch.

## Acceptance limit

The implementation can say: “these two caller-provided normalized snapshots are internally consistent under the stated typed contract.” It cannot say that either snapshot is complete, authentic, simultaneous, account-bound by an authority, or even sourced from the claimed deployment. In particular:

- `snapshot_boundary_id`, `complete`, state, digest, row content, and high-water are caller-provided unauthenticated values; matching boundary labels do not prove a shared capture barrier.
- Candidate historical G5 rows lack command ID/state; a separately validated join is required. V21 allocation rows require a command/correlation join for the shared identity fields.
- No authenticated native `MaxOrderActionRef` floor, old-writer fence, account-wide exclusive epoch, deployed old schema/exporter, or real account migration evidence is supplied.

Therefore this candidate is not safe to wire into runtime or use to migrate/authorize. It remains only a local typed comparison contract. The Git-commit metadata discrepancy is separate from the content/test result and is retained as an explicit provenance note.
