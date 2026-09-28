# BtApiStore AccountActorPort r2b author evidence

Status: `AUTHOR_CANDIDATE / NO_WRITE`. This is a selected evidence bundle from the immutable r2b snapshot. The snapshot's 724-entry candidate manifest is included; this archive contains only the review-relevant source files, patches, migration table, logs, and exact main-base Store input listed in `archive-index.json`.

The main-base patch applies to Store SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`; isolated `git apply --check` and exact target replay passed. The pre-fix inert gateway-wrapper mutation probe and post-fix route-guard tests are both preserved. Final results: candidate focus 43 passed, regression set 30 passed, stores/runtime 55 passed, Ruff and py_compile clean. The 21-row table preserves old CTP behavior as unavailable/fail-closed pending an authenticated external Actor.

No external Actor authority, CTP provider, credentials, native SDK, default route, or write capability is included or accepted. Same-process direct private factory/raw-client access remains outside Store-level isolation. This evidence does not establish G1/G5/F14 or production acceptance.

Use `archive-index.json` and `COPY-RECEIPT.json` for per-file hashes and ZIP CRC verification. The complete 724-file frozen source snapshot remains at its original D:\temp path; it was not modified by this archive operation.
