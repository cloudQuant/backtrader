# R7 R3 Root source-scope normal-close review

**Decision:** GO_ROOT_NORMAL_CLOSE_ONLY for one use against the exact already-consumed R3 caller state below. This approves only the narrow normal close after the pinned pre-gate failure. It grants no gate invocation, host exit, provider/account acceptance, or formal M01 pass. The reviewer did not execute the helper or reread any opaque software payload.

## Subject and bound sources

| File | Bytes | SHA-256 |
|---|---:|---|
| .codex-tmp/okx_m01_r7_r3_source_scope_normal_close_root_20261009.py | 12,643 | 3e34dbe44e106d72da74fe1f7eb7f17cef5a762a619c0436dec0206ea8cc33db |
| .codex-tmp/okx_m01_r7_r3_root_actual_20261009.py | 19,238 | c6a6cdfccd34fafdc3e677f36ef165b6d683de1d12d31632680efaa5f2fde6d3 |
| scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r3.py | 75,579 | eb887d64e125d80e7e33736b7b9b860a947e91ed5967926f68e3940b6b07432a |
| tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r3_source_fake.py | 38,953 | 3a97722fb668fc7825fd336c3930aba76ffe8c8a4a24d285df95bd2f8b1fd7bd |
| CUv2 public snapshot, iteration41-cuv2-public-source-snapshot-r1-2026-10-08/cuv2-source.py | 2,344 | e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246 |
| R3 source map | 2,877 | 07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3 |
| R3 source index | 9,970 | 8cd0360bb9519daf785412a6176091d2ca0ff4471e2bf65aba011aeec3444564 |
| CUv2 candidate-pins manifest | 12,994 | 8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12 |
| R3 caller review README | 2,323 | d1f78957c1d065ea4aedea933d14675949431572e09557ebf7b6802aa239d223 |
| Consumed R3 public observation | 2,435 | 5cec40c0f1ab16bc48245fd3c21b92d9258d267c93b795be0fb4ea0a674bb6fb |
| Accepted R2 predecessor helper | 5,957 | 9310f3c38f32a0f71264b0bc855a9ab7dc55645d812834a2a96bafa946343c1f |

The public source map/index and manifest pins were read back at these exact hashes. The root caller declares 31 public rows and three fixed software rows; the CUv2 snapshot is itself one of the public rows and is also the source bound to the temporary CUv2 origin.

## Review findings

- The helper refuses any state except the exact R3 result shape: BLOCKED / cuv2_source_pin_mismatch / source_custody, gate count zero, source counters zero, software bytes returned and retained, no caller SHA recheck, retained references present, and scope still open. The sanitized consumed observation matches that state. It records no diagnosis beyond the finite caller reason.
- The helper rebinds the 31-row manifest to the pinned R3 caller and test, checks all public raw bytes and hashes, binds the fixed three software hashes, and requires the held map to contain exactly those 34 normalized paths. It validates the CUv2 method, generator, module globals, yielded raw map, and generator pin map before close. It performs hash-only current-path checks over all 34 pins before and after close; the helper code reads bytes to hash, but does not parse, log, or return opaque software contents. That path is for Root execution only; this reviewer did not read those contents.
- It places a one-shot record in the supplied Root namespace before calling the exact generator context manager’s __exit__(scope, None, None, None). On any raised or uncertain close, that record prevents retry. A successful close must return False and leave the original generator closed with no frame.
- After close it verifies the retained registry/list/tuple and held object identities, unchanged original result and Root state, unchanged caller/source bindings, public source bytes, all 34 current hashes, manifest/review pins, and Git state. It does not remove the retained row or alter host_exit_permitted.
- The new observation is finite and explicitly reports zero gate calls, false provider/account acceptance, false formal pass count, and false host-exit permission. The R3 consumed observation likewise has formal_m01_pass_count=0, root_host_exit_permitted=false, and source-custody failure before Gate0.

R3 preserves the accepted R2 predecessor’s normal context-manager exit and retained-row behavior. It tightens the accepted precondition and adds exact caller/test lineage, R3 manifest/review binding, caller-global/result/state postchecks, and post-close checks for all 34 paths. No source-fake or actual run was repeated.

## Boundary

This decision applies only when Root calls the helper with the live namespace of the exact pinned R3 driver and the already-consumed caller invocation. The helper accepts a namespace and bound callbacks, so it is not a general-purpose or caller-facing API. The R3 invocation was blocked before gate/module loading; this review establishes neither the gate result nor cleanup of the Root host. No private input, software payload, provider/account path, native operation, process, or test was read or run by the reviewer.

