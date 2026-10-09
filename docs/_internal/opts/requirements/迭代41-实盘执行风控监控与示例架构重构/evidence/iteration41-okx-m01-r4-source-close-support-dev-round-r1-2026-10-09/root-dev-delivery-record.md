# OKX M01 R4 source-close support delivery record

Status: `PROPOSED_FOR_ROOT_STAGING`.

This evidence-only round packages the frozen 21-path public R4 support packet, its independent delivery review, this record, and the repository `.gitattributes` file: 24 paths total, including 23 pinned public payload paths and 23 exact path-specific `-text` rules. The packet's `delivery-manifest.json` remains unchanged. The external review is `GO_DELIVERY_ONLY`; it reviewed scope, byte pins, origins, and historical classifications without rerunning tests or the source-close operation.

## Evidence and limits

The one-time Root source-scope close occurred on `dev` at HEAD `716ca992dd8a05d7d997d25cd667f212eae5bb1c`, in retained host `77310`. The R4 caller returned `BLOCKED / gate_cleanup_not_certain` at `post_binding_check`; its Gate result was `OUTPUT_MISMATCH` and `stdout_matches_fixed` was false. The original CUv2 normal exit returned `False`, the generator reached `GEN_CLOSED`, and CUv2 normal post-verification checked 31 public and 3 software pins. The close helper rechecked the 31 public pins; it did not hash software payload bytes. The original result and retained row, Gate, and five modules remained preserved.

The source-close result does not establish Gate success, native process or Job cleanup, provider or account behavior, a formal M01 pass, or permission to exit the host. Host `77310` remains alive. Formal M01 pass count remains zero. The fixed stdout reproduction supports only an inference about Windows newline conversion; it does not recover the historical child output.

The actual close's outside-host checks recorded branch `dev`, HEAD `716ca992dd8a05d7d997d25cd667f212eae5bb1c`, an empty index, and matching pre/post Git state. The delivery checkout is based on `dev` HEAD `14bde6fbac099f60b7d3b111be72ec14b485555b`, the checkpoint after the prior R3 support commit. No R4 runtime source is included in this round.

Four archived items are explicitly historical fixture context: the R4 caller source, its source-fake test, the R2 candidate manifest, and that caller's review. They do not imply a new runtime run or acceptance. The CUv2 source snapshot is an inherited committed input and is referenced without duplication.

No tests were run for this delivery proposal, and no Git staging, commit, or `.gitattributes` mutation has been performed while preparing it. Root's staging script is a separate proposal artifact and has not been invoked. Any eventual commit must preserve unrelated working-tree changes and verify exact staged bytes against the frozen manifest, this review, and this record.
