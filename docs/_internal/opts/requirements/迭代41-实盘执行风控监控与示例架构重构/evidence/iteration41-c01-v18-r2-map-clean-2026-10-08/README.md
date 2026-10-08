# Iteration 41 C01 R2 map and cleanup evidence

This directory records the frozen R2 Root-driver map/cleanup round and its clean-source regression run. It is based on `dev` at `f46234e338c774d017eb58853f32cfd7310ff9d5`.

## R2 result

The frozen driver is 40,248 bytes with SHA-256 `4165e23f8f9ebb429df7cac4f26482d4a68383fb1c898661bcf8a21b0eaf2b4a`; its `pins.json` is 10,696 bytes with SHA-256 `20b5bca15b9b4d3f6e8f6ef8bb253d3ce7fae7fffa9f06a08c5bca5845b1d359`. The actual wrapper returned `BLOCKED/root_entry_blocked`. Job and outer-CU cleanup both completed, retained references were zero, and the host exit code was zero. The official C01 PASS count remains zero.

The independent review recorded 25 PASS. The root readback and actual diagnostic are preserved at the pinned paths in `manifest.json`. The actual diagnostic observation is 1,587 bytes, SHA-256 `3ebf3f8c71b5dab3d5f83cfe5af6a7fc28defcf3b94e36123dc8f37e264441e3`.

## Clean-source regression

The exact frozen R2 driver-source test and wrapper-source-fake test passed **25/25**, with zero failures or skips, under Python 3.11.5 and pytest 8.0.0. The command and output are in `qa/command.txt` and `qa/pytest-output.txt`. `qa/runner.py` verifies packet pins, materializes a short isolated source root, disables pytest plugin autoload and cache, and runs only those two test files.

The clean source root uses the 29 source payload snapshots in the frozen R2 packet, the four frozen R2 V18 test copies, nine R3-pinned fake-test support snapshots, and five exact baseline-HEAD snapshots needed by their transitive imports. All 14 additional snapshots are stored as flat, hash-pinned evidence inputs under `qa-inputs/`; their original repository paths and roles are recorded in `manifest.json`. No live checkout source is used as a fallback.

The only test path changes bind the frozen driver’s root/evidence paths and wrapper `REPO_ROOT` to the clean copy. No validator or hash check was patched. The fake source test executes the pinned wrapper, V18 entry, issuer public run, and `_run_candidate`; it separately checks the producer hook identity/code/pin and fakes custody and receipt leaves. Native provider invocation remains unproven.

The added snapshots stay under this documentation evidence directory and are labeled test-only. A targeted HEAD scan of `backtrader_runtime/registry.py`, `runner.py`, and `cli.py` found no references to these source-fake modules or test files; the round changes no default runtime dispatch code.

Formal C01 acceptance remains open. This run is public source-fake evidence and does not change the actual R2 `BLOCKED` result.

## Proposed commit scope

Use the exact frozen input directories and files listed in `manifest.json`, this evidence directory, and the five scoped `-text` rules in `.gitattributes`. Do not include the original V18 production/core source paths in this round.
