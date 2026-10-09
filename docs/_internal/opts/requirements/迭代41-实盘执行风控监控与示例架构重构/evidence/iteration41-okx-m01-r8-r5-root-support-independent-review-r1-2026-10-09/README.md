# OKX M01 R8/R5 additive Root-support proposal review

**Disposition:** `GO_ADDITIVE_SUPPORT_PROPOSAL_REVIEW_ONLY`  
**Scope:** additive manifest, nine new path rules, and four copied public Root support files. The frozen R1 proposal was treated as the reviewed baseline; its 31-pin and 26-member inventories were not repeated.

## Frozen proposal pins

- Additive `delivery-manifest.json`: 44,243 bytes, SHA-256 `d35bde50b75d5cc1a6f23463b3821ee8e7bf1360deda1432da276b212f80d942`.
- Additive `byte-preservation-rules-proposal.txt`: 1,710 bytes, SHA-256 `abc22786d63c73649f53fcd075f04f0fe0f87f8fa1430a21bf46ec9a3899641a`.
- Base remains `dev` at `e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b`.

## Additive consistency checks

- The corrected manifest no longer contains the stale `combined_rules_for_29_proposal_paths` field. It states 21 frozen R1 rules plus nine additive rules, for 30 combined paths.
- All nine additive rules are unique. Combined with the frozen R1 rules they exactly cover the 30 unique paths in `proposed_payload_paths`, with no missing or extra path.
- The two review rows match their files: the R1 proposal review is 3,250 bytes / `9f82a2c62e5fd2257caf140851257c93e7c208abca58be3abe06b79edc621582`; the R2 Root-driver review is 3,776 bytes / `7b5e653a7f9af790668347bf35345dbf79a0616f082948c79ddbe29c4d604318`.
- Each of the four archived Root files is byte-identical to its declared public `.codex-tmp` source, and both copies and source match the declared size/SHA-256:
  - `root-actual-driver-r2.py`: 29,420 bytes / `ddee4f2eb6058c61b0c2ef69964d33fdca82a85ead733e272d391f6f41d3d369`.
  - `root-original-receipt-r5.json`: 6,305 bytes / `c3e3f36358dabe335039f19dfe9b62ea23b42823d2b86f883ec9c150a6b19dc2`.
  - `root-outside-git-postverification-r5.py`: 4,256 bytes / `5f1c1126682e8c3a1c3f9c30592695486d74f1c9300d1f914c1cf882dc3d7c31`.
  - `root-pre-exit-exact-body-r5.py`: 3,708 bytes / `4906f69f305a9eeb4903f9725bd10f7feeaf135aab1c945f7ea473d966296f56`.

The original R5 receipt remains `PENDING` with `exit=false` and is preserved unchanged. Separate later outside-postverification and pre-exit records, together with the existing Root host-exit record, describe the later normal host exit; they do not rewrite that original receipt. Root R5 remains `ROOT_LOCAL_SYNTHETIC_GATE_ONLY`, with formal M01 passes at 0.

The inventory’s `opaque_software_payloads_read_or_copied_by_delivery_inventory_author=false` is scoped to the delivery inventory author. Root’s separate CUv2 actual held three pinned software byte values in caller state; this review did not read any software payload.

## Pending delivery items and limits

The proposed set has 30 paths, including the pending Root-authored round record. The separate final delivery-review artifact and the shared `.gitattributes` file remain outside that 30-path proposal. Adding this review requires one additional exact-path `-text` rule. No tests, actual/native/provider/account operations, source edits, staging, or Git mutations were performed.
