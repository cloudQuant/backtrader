# Main-tree application chronology (supplement to frozen isolated evidence)

Recorded 2026-09-27 05:31 UTC. This note is separate from the frozen isolated replay ZIP; it records a later main-tree action by the root coordinator.

## Timeline

1. The combined Store/Runtime test replay and the guarded three-node 013_3 focus were run in `D:\temp\i41-store-merge\src`, using a selective copy rooted at the then-current exact-source manifest. At that time, the isolated candidate contained formal 013_3 r2: `run.py` SHA-256 `1C3D37A7485C05EC4EBB82BA1A66218B6B739063E04819D7B327BA4D8847B58E`; its runtime test SHA-256 was `00F9DB83E22735539920A7F033AB0A888906ECF61109C156513BCFE1D9C64678`. The manifest baseline copies before patch 5 had `run.py` SHA-256 `16D6A184F1A57C0C2843511DD0BD7ADA4825D945402665BE1AAF8B624FC9576C` and test SHA-256 `146833DF60C0C847E5AC64C1F8239673E525F5C08DDA86453CF81B3B11327CD5`.
2. After independent G1 formal r2 QA reported `SAFE_TO_APPLY_LOCAL_REPLAY_ONLY`, the root coordinator deliberately applied the exact local-replay-only patch to the main working tree. This was not performed by the isolated integration task.
3. At the follow-up hash check, main `run.py` and the runtime test matched the isolated formal-r2 target hashes above. Main `backtrader/stores/btapistore.py` still matched the required Store base SHA-256 `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`; Store r2b/r2c and the other Store integration patches remain outside the main tree. The observed `git status` marks the Store file modified relative to HEAD because the shared working tree already contains the base candidate source; the content SHA confirms the requested base bytes.
4. The root coordinator reports a subsequent focused replay of 28 tests passed. The Store/Runtime full run was still in progress at the time of this note; no result is inferred here.

## Scope

This chronology does not alter the frozen test logs, JUnit, patch-series hashes, same-source baseline/candidate failure-nodeid diff, ZIP, or original copy receipt. It records the source-state transition so the isolated test-time statement is not confused with the later root-owned application. The main-tree patch is local replay only; it does not accept Store wiring, enable a default route, authorize a provider, or establish G5. Do not revert the root coordinator's change.
