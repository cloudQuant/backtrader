# Main-tree R4 safe focus

- Safe guarded focus: 32 passed, 1 deselected, 0 failed. The deselected test is the one that read untracked example config files in the invalid 33-test attempt.
- JUnit SHA-256: `778FAD9EA2EF4C317D97E39043711B7BE375BA7B5401B6B1997DC07871488869`.
- Guard JSON SHA-256: `407D0472E0E545089725F1E19305A0EBFA3C8A5F9B8C77C671E26FFEECDF030A`; it is an empty event list.
- Candidate guarded helper test: 1 passed. Its log is under `independent-qa/candidate/`.
- Ruff: persistent test clean; support sources show only four existing `SIM112` findings, two per module.
- Full inventory verifier: PASS 460/460, all active rows remain `REVIEW_REQUIRED`, six tombstones.
- Scanner contract JUnit: 15/15 passed.
- No real SDK/native/provider/network/account/order/cancel was involved.