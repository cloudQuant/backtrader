# OKX M01 R8/R5 delivery proposal review

**Disposition:** `GO_DELIVERY_PROPOSAL_REVIEW_ONLY`  
**Evidence level:** static delivery review; no tests, actual calls, staging, or commit.

## Reviewed pins and base

- Proposal `delivery-manifest.json`: 35,443 bytes, SHA-256 `1d65a59367a4cb3b2e976c84d8fe8bd828d123aae71bc641d4eabe9deb43c930`.
- Proposal `README.md`: 3,889 bytes, SHA-256 `f1cda456f58a12ad9ed0441651757da765d6b4c12c9051c82fca27c85c8df522`.
- Proposal `byte-preservation-rules-proposal.txt`: 3,624 bytes, SHA-256 `236e0da3859ed9785614b985148cf8f53cc88ee1018301fa26bc6b1b179d2c61`.
- Baseline: `dev` at `e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b`; index empty. The `.gitattributes` baseline pin in the proposal matched.

## Static checks

- All 31 public input pins matched the current checkout. Twenty-five were byte-identical at the base commit; six were proposed additions.
- All 18 proposed artifact additions matched their declared sizes and SHA-256 hashes.
- The source index contains 26 unique rows: 19 runtime-source rows and seven test/support rows. The pinned ZIP has the same 26 unique member names, with matching sizes and SHA-256 hashes. Twenty-four members were already at HEAD; the two R8 Gate source/test members were proposed additions. The archive is source/test fixture provenance and does not prove those modules are imported at runtime.
- The 21 quoted, path-specific `-text` rules were unique and covered the 18 proposed artifact paths plus the three proposal files.
- The source index’s capture HEAD (`716ca992dd8a05d7d997d25cd667f212eae5bb1c`) is correctly distinguished from the Root R5 invocation base (`e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b`).
- The independent R8/R5 source-fake review is bounded to `GO_SOURCE_FAKE_ONLY`. The composed fake caller reaches the production Gate once but stops before `CreateProcess` on its synthetic runtime hash mismatch; it does not establish a successful composed close or host exit.

## Root R5 support evidence

The four sanitized Root R5 records pinned in the proposal support its `ROOT_LOCAL_SYNTHETIC_GATE_ONLY` summary: one invocation in fresh host 39102 (tool `f6d251`); fixed stdout matched and stderr was empty; both stdout/stderr reached EOF, readers completed and joined, with no overflow or read errors; one bounded process wait succeeded without fallback; process exit was zero and reaped; 11 observed handles were closed with zero close failures; Job observations reached zero; runtime and reader registries were empty; CUv2 normal postverify close covered 31 public and three software source pins; and the host exited normally with code 0. No account/provider operation was accepted. Formal M01 passes remain 0.

The field `software_payloads_read_or_copied=false` in the proposal inventory is understood to describe inventory collection. Root’s actual record says three software payloads were returned to and retained in caller state; this review did not read any software payload.

## Limits

This is a review of the delivery proposal and its public pins. It does not accept account/provider behavior, actual M01 execution, or a formal M01 pass. No candidate source, shared attributes, Git index, or commit was changed, and no test or actual gate was run.
