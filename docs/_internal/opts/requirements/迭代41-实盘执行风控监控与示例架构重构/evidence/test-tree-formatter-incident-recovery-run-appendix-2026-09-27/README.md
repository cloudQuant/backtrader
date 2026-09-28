# Test-tree formatter incident recovery: raw-run appendix

This directory preserves the two raw Store/Runtime broad-run sidecar sets and compact recovery provenance for the 2026-09-27 test-tree formatter incident. The incident narrative and limits are in [the parent recovery report](../iteration41-test-tree-formatter-incident-recovery-2026-09-27.md).

## Test runs

- `runs/post-recovery-a028-baseline/`: after recovery, the Store/Runtime run recorded 2,725 passed, 43 skipped, 2 xfailed, 0 failed (exit 0). This is the A028 baseline.
- `runs/rejected-r3-broad/`: the attempted r3 broad run recorded 2,724 passed, 43 skipped, 2 xfailed, 13 failed (exit 1). That r3 patch was reversed; it is not the current Store state.

Each run includes the original JUnit XML, pytest log, and exit-code sidecar copied byte-for-byte from its `D:\temp` source. The current `backtrader/stores/btapistore.py` SHA recorded in `ARTIFACT-MANIFEST.json` is A028 (`a028a68df87abe84a1d38f4020d81af56e0dfb860ded43d36c3830933106696d`).

## Recovery provenance

`provenance/tracked-24-recovery/` contains the 24-file recovery manifest and package receipt. `provenance/untracked-49-runtime/` and `provenance/untracked-16-recovery/` contain the compact 49-file audit conclusion and 16-file recovery plan. The large full-tree snapshot and 24-file recovery ZIP are intentionally not copied here; their original paths and hashes remain in the linked incident report and recovery receipt.

The matching Ruff 0.16.2 formatter output is evidence for the recovered candidate, not a unique inverse: formatting is many-to-one and unarchived source edits cannot be ruled out by these byte matches alone. This appendix makes no source correctness, CTP, G1, G4, G5, SimNow, or production acceptance claim.

## Integrity

`ARTIFACT-MANIFEST.json` lists each copied payload's source path, size, and SHA-256. `SHA256SUMS.txt` covers the manifest, this README, and every copied payload; it does not hash itself.