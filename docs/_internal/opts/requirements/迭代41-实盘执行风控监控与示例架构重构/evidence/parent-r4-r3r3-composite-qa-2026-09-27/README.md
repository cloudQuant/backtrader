# Parent R4 + R3r3 composite QA evidence

This is a byte-checked copy of the completed offline source-only QA record. It preserves the input manifests, test-only adaptation diffs, commands, stdout/JUnit/exit records, source-origin guard implementation and JSONL logs. `ARCHIVE-INDEX.json` lists SHA-256 and size for every copied input; copied bytes were re-hashed after transfer.

Results: parent fake issuer/control 44 passed; main original bridge nodes 3 passed; five-file bridge focus 73 passed; cancellation-control focus 20 passed. Source-only lane only: no wheels were built or installed, and no CTP provider, native SDK, credentials, private config or network was used. The default route remains NO_WRITE. This is not release/wheel acceptance.

Known limitations: the composite parent source candidate still carries package metadata version 0.15.5 despite changed source bytes; this is an identity collision and blocks release. R3r3 test adaptation is retained as a test-only diff under provenance. Ruff reported test import-order findings and existing S110 findings in frozen source; details are in the original logs.
