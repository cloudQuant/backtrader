# AC41-63 CTP writer fallback r2 rev2

Latest frozen candidate: R2-REV2-PACKAGE.zip with R2-REV2-METADATA.json and a package SHA-256 sidecar. This is isolated. Nothing has been applied to the shared main tree.

Apply in order: PATCH-GIT.diff, then TEST-MIGRATION.diff. PATCH-GIT.diff was strict-checked and applied against the exact mixed-EOL base with core.autocrlf=false; result Store SHA is listed in metadata. The Store patch changes only backtrader/stores/btapistore.py. TEST-MIGRATION.diff passed read-only git apply --check against the current main test source and changes only tests/unit/stores/test_btapistore.py.

The test migration preserves the submit-order positive nodeid, now using a typed fake and non-null capability. It adds a raw-only submit rejection test with typed-descriptor and .api property traps. It adds a parameterized raw cancel rejection test: no capability rejects before typed descriptor access, and a capability with no typed method rejects without accessing .api or raw ReqOrderAction. Focused before/after JUnit and two-file baseline/patch JUnit include exact failure nodeids.

Eight fake boundary probes passed with zero .api reads and zero raw ReqOrderInsert/ReqOrderAction calls. Full-tree source comparison covered 1025 files and found only the Store file changed.

The source proposal does not establish authorization. _execution_gate_capability remains mutable same-process private state; a caller can inject a non-null value and typed method. Remain NO_WRITE / LIVE_NO_GO pending independent QA and broader regression.

r2 rev2 supersedes the initial r2 package only for the test migration and results. The initial r2 package remains preserved unchanged. r1 remains unchanged with NEEDS_REVISION. Replay and review after r2b/r2c wiring or any source change.
