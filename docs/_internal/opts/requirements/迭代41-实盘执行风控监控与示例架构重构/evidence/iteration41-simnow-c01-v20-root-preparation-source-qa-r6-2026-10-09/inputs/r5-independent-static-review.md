# V20 Root caller R5 independent static review

Verdict: `GO_STATIC_REVIEW_ONLY / R4_PREPARATION_PLUS_R5_TEST_CLEANUP / EXECUTION_NOT_RUN`.

## Frozen inputs checked

The reviewed packet is `iteration41-simnow-c01-v20-root-credential-free-caller-r5-test-alias-cleanup-2026-10-09`. Its `artifact-pins.json` is 1,437 bytes, SHA-256 `62ddd86cc141a4b94dbe5eee6736c7b13099133f890e77a0f931f90d31bfef16`. All eight listed artifact rows matched their pinned size and SHA-256.

The production preparation source is unchanged from reviewed R4: 22,526 bytes, SHA-256 `720c9e559100196211d7c10d68a5c33d2b9167bcba48ad3e4ecf14641e2fb6b0`. The R5 source-fake test is 16,604 bytes, SHA-256 `6c91b361346cbe3ff1ac34125f0831fed70c128a081c13645b6cba437d8f76e2`. The pinned runtime map is 9,069 bytes, SHA-256 `e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387`; all 26 public source rows (23 child-frame plus three parent additions) match current sizes and hashes. Three software rows remain metadata only; no software payload was read.

## Review findings

The R4 production preparation logic and its previously reviewed root normalization and lease composition are unchanged. R5 changes the test teardown. `_restore_unretained_cuv2_alias` restores/removes the alias only if its current value is the exact module created by the test; when no created module is known or another binding is current, it leaves that binding in place (`test_root_gate_host_preparation_source_fake.py`, lines 24–32). The new regression checks both the no-created-module case and restoration from the test-created module back to the prior module, then restores the test process's original binding (lines 35–54).

The composed success-path teardown continues to remove `_root_public_custody_cli` only when it is identical to `host.cuv2_module` (lines 358–359); the no-host fallback now uses the identity-bound helper (lines 366–370). This resolves the R4 test-isolation caveat without changing the production preparation source.

## Limits

This review was static and hash-based. No pytest command was run. The public QA command/result artifacts were only hash-checked against the packet manifest. No CUv2/software payload, private input, account/provider, SDK/native, WinAPI, process, pipe, or actual gate operation was performed. The author reports 12 source-fake tests passed with one existing configuration warning and Ruff clean; this result was not rerun here. This review does not approve an actual gate invocation or formal C01 PASS.