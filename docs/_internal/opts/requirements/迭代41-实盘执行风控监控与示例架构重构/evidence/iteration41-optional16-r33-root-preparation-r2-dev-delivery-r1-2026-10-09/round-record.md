# Optional16 R2 preparation source component delivery round

**Classification:** `SOURCE_FAKE_PREPARATION_REPAIR_COMPONENT_ONLY`  
**Baseline:** `dev` at `aaee6995e6317b2d42d9d04ecc43428ff4a12424`; index empty.  
**Whitelist:** [`delivery-manifest.json`](delivery-manifest.json), SHA-256 `e9d25db4e98b043fd09b1a119da1c6d5d04be7018ac7b05fb38572bc85725c15`, 32746 bytes.

## Proposed scope

The proposed whitelist adds 34 payload files: 13 source/test files (four R2 candidates and nine untracked inherited dependencies) plus 21 sourcefake review and QA artifacts. The 15-file source/test closure also references two already tracked, clean dependencies by exact pin; those files are listed in the manifest and are not additions. The frozen R2 source index binds all four candidates and 11 fixed dependencies. Root QA checked 16 pre/post pins.

Six predecessor source-index/review pairs retain the reviewed lineage for the R1 call, R1 helper, R1 driver, R19, R27 and R28-R5 pieces. These results are sourcefake-only. The proposal excludes the full 582-row runtime map and opaque profiler/cache payloads.

## Verification and limits

The frozen R2 independent review is `GO_FIXED_SOURCE_PREPARATION_ATTEMPT_ONLY / GO_SOURCE_FAKE_ONLY`. Root QA tool `e558cd` reported 13 passed, 0 failed, 0.64 seconds, exit 0, and no warnings against the candidate and fixed dependency pins. The archived runner and result are included. No tests were rerun while preparing this delivery record.

This delivery is only a sourcefake preparation repair component. No actual preparation, full-map/profile closure, installer, worker, or activation was verified. Optional16 remains 0/16. Host 25932 is retained; the consumed R1 host is not to be retried. Adding these manual, unregistered components to `dev` does not approve an actual gate or runtime dispatch.

## Attribute plan

The manifest lists 36 exact quoted `-text` rules for the 34 payload paths and two delivery metadata paths. The existing `.gitattributes` is clean at the recorded baseline; this task did not modify it, stage files, or commit.

## Complete file pins

The machine-readable manifest records each proposed path, byte count, SHA-256 and baseline tracked/untracked state. It also records the two inherited tracked-clean dependency pins and the exact attribute lines for Root's staging step.
