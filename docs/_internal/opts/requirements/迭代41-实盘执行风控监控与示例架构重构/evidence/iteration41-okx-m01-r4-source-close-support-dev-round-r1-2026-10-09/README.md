# OKX M01 R4 normal source close support

Status: `PROPOSED_PUBLIC_SUPPORT_ONLY`.

This packet records Root’s one-time normal close of the original CUv2 source scope after the R4 credential-free local lifecycle Gate returned a blocked result. It is a support and evidence round. It does not change or accept an OKX production runtime path.

## Recorded outcome

Root invoked the frozen R4 caller once in host 77310. Its result remains `BLOCKED / gate_cleanup_not_certain` at `post_binding_check`. The Gate result remains `OUTPUT_MISMATCH`; `stdout_matches_fixed` is false, so the Gate is not accepted. The original caller result and retained row remain intact, and the Gate plus five production modules remain retained.

Root then called the original CUv2 context manager’s normal exit once. The exit returned `False`, the generator reached `GEN_CLOSED`, and the pinned CUv2 post-yield verification completed for 31 public and 3 software files. The helper itself rechecked only the 31 public files; it did not hash the held software bytes. The helper’s receipt keeps `formal_m01_pass_count=0` and `host_exit_permitted_by_this_receipt=false`.

The outside-host pre/post attestations report branch `dev`, HEAD `716ca992dd8a05d7d997d25cd667f212eae5bb1c`, an empty index, and matching Git state. The postverification checked seven public context pins; it explicitly did not check the retained host’s state. Host 77310 remains alive under Root’s instruction. After this actual close, Root committed the prior R3 support round; the proposed R4 delivery baseline is dev `14bde6fbac099f60b7d3b111be72ec14b485555b` (parent `716ca992dd8a05d7d997d25cd667f212eae5bb1c`).

## Source-context preservation

This revision adds exact copies of the R4 caller, its source-fake test, the candidate manifest, and the caller’s independent review. These are historical support-context fixtures corresponding to four rows of the R3 pre-attestation; their presence does not establish a new run or runtime acceptance. The pinned CUv2 source snapshot is already a committed inherited dependency and is referenced by path and hash without duplicating its bytes.

The first 17-file proposal’s README, round record, scope, and manifest were preserved byte-for-byte under `.codex-tmp/okx_m01_r4_source_close_support_initial_proposal_r1_20261009/` before this expansion.

## Output mismatch diagnostic

The included fixed Windows stdout reproduction shows text-mode `write()` converts LF to CRLF while binary write preserves LF. This makes newline conversion a possible explanation for the mismatch. It does not recover or establish the historical child’s actual output bytes, so the cause remains unproven.

## Evidence boundary

The 21-file archive contains public source, sanitized observations and receipts, and the fixed stdout reproduction. It contains no private captures, credentials, opaque software payload bytes, or historical child output. No test suite was run for this support packet. No production runtime, test, or `.gitattributes` file was changed by its preparation.

The accepted scope is limited to Root’s normal CUv2 source-scope close. It establishes no Gate success, native Job/process cleanup acceptance, provider/account acceptance, formal M01 pass, or host-exit permission.