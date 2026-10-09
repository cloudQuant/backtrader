# OKX M01 R7 R2 pre-gate source-scope close — independent static review

Date: 2026-10-09  
Verdict: **GO_FOR_THIS_ONE_SHOT_PRE_GATE_NORMAL_SOURCE_SCOPE_CLOSE_ONLY**

## Reviewed public source pins

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| Root close snippet: `.codex-tmp/okx_m01_r7_r2_source_scope_normal_close_root_20261009.py` | 5,957 | `9310f3c38f32a0f71264b0bc855a9ab7dc55645d812834a2a96bafa946343c1f` |
| Root invocation script: `.codex-tmp/okx_m01_r7_r2_root_actual_20261009.py` | 13,004 | `0e88307e24e2e685e2ed72bc0696ab55aac8c5e7dc1de258f491c009892a16ee` |
| R2 Root caller: `scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2.py` | 70,462 | `0c5673dfa71cb083a59b15852f087991519bf520c1384392453bac55878cd200` |
| CUv2 public source snapshot | 2,344 | `e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246` |

Static review matched the Root script''s expected caller and CUv2 pins to the R2 caller and the public CUv2 snapshot. No tests or tools were run for this review.

## Static review basis

R2 receives the failure `cuv2_source_set_mismatch` at `source_custody` after the CUv2 generator yields and before it imports the five M01 modules or loads/calls the Gate. Its retained row contains the original CUv2 module, wrapper and generator functions, raw source argument, suspended generator and globals, original scope, yielded tuple, and raw-byte map; its Gate slot is `None`, module map is empty, and Gate invocation count is zero.

The pinned CUv2 source forms its held map from the union of the 31 public pins and 3 software pins, then yields that 34-entry map. On ordinary generator completion, it checks each locked file identity and re-reads/hashes each pinned path before the `ExitStack` closes the held contexts. The reviewed Root snippet rebinds the exact caller/CUv2 source, checks the original 34-key map and generator locals, writes a one-shot record before invoking the original context manager''s `__exit__(scope, None, None, None)`, and requires a `False` return plus the same generator in `GEN_CLOSED` state. It preserves the original result and retained row, keeps host-exit permission false, and projects that three software raw entries were returned in the original held tuple; it does not alter the earlier result object.

This is a static review of the one-shot normal source-scope close path. The reviewer did not run the close snippet, access host 91482, read opaque software payloads or private inputs, or rerun QA. This review does not authorize host exit or establish Gate, account/provider, or formal M01 acceptance.

## Root-reported execution reference

Root reports that the normal close was consumed once in session 91482 (tool `e50603`) after outside pin check `cec72c`. Root reports status `SOURCE_SCOPE_NORMAL_CLOSE_RETURNED`, 31 public plus 3 software pins checked, normal `__exit__` result `False`, generator closed, original caller result and retained row preserved, registry length one, and Root caller global-identity postcheck passed. No Gate, five-module load, or account action occurred; the host remains alive and exit permission remains false.

The public observation is referenced by SHA-256 `9fe9a3a67ad9d1d10174c1021a8311554853e05f6555b29214b5c0bc777d5196` (662 bytes). Its contents were not opened for this review. The execution facts in this section are Root-reported, not independently inspected.
