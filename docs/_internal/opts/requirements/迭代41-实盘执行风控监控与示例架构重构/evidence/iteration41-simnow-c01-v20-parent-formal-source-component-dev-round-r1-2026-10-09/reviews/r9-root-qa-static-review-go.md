# SimNow C01 V20 Root QA harness R9 static review

**Decision:** `GO_STATIC_REVIEW_ONLY / EXECUTION_NOT_RUN`

## Frozen subject

- Harness `.codex-tmp/iteration41-simnow-c01-v20-parent-formal-root-qa-r9/root_qa_harness.py`: 121,074 bytes, SHA-256 `199f71febac7583781011d614e931d7708c009e1d63ae645b54aba658fe13090`.
- Inventory `.codex-tmp/iteration41-simnow-c01-v20-parent-formal-root-qa-r9/input-inventory.json`: 24,731 bytes, SHA-256 `7e816abf38830289ce6820bbce581c143ea02d1fed7d97a16c1a116f9491c6b1`.
- Candidate pins `.../iteration41-simnow-c01-v20-parent-formal-composition-r7-2026-10-09/candidate-pins.json`: 11,822 bytes, SHA-256 `dfc523215960b8d279b3ad68fc81a91b0fc196941fdbcf573b3a5f06009798af`.
- Artifact pins at the same packet path: 1,014 bytes, SHA-256 `8cae29ebc204fecf43650844c67a78bb5ba5153f57c7cbe160d5218b05290b02`.
- R7 root-seal fixture test: 23,802 bytes, SHA-256 `2a3c087dc4c037d77d06cbf4b5ebe34386a939ed82636384a161eccc95550e99`.

## Findings

R9 fixes the R8 inventory-pin type error. `EXPECTED_INVENTORY_BYTES` is the integer `24731`; `EXPECTED_INVENTORY_SHA256` is the matching string literal `7e816abf...91c6b1`, and `_inventory()` compares those against byte length and computed SHA-256 separately. The R8-to-R9 harness diff is limited to those corrected constants and R9-specific output/temp names.

All 41 inventory file rows were independently checked for repository-bounded paths, uniqueness, exact byte count, SHA-256, and declared origin where present: 26 source rows, 8 focused tests, 6 packet artifacts, and the separate review reference. Every row matched. The candidate and artifact pin files match the harness constants. The inventory retains the 118-call strict outcome contract and the previously reviewed isolated namespace, preload, denial, external pytest configuration, and result-reporting rules. No change to the 26 production source rows, 8 focused test rows, or R7 packet was found.

The inventory still describes the R7 fixture review as pending. That status predates the exact-byte R7 review: the fixture teardown itself was reviewed and found to restore all seven `sys.modules` bindings, while the R7 harness/inventory review was held for stale candidate/artifact pin constants. See `iteration41-simnow-c01-v20-parent-formal-root-qa-r7-independent-static-review-r1-2026-10-09/README.md`, SHA-256 `d4c8b51618890a7e1454c48851707a77683645a06adb873456e8b0909633a6b6`. This historical status wording does not change R9's input validation or execution gates; this review records the superseding review state.

## Scope

This is a static review of the exact R9 harness and inventory. I did not execute the harness or tests and make no claim that the 118-test gate passed, that a Root invocation occurred, or that SimNow/provider/native behavior was accepted. The next QA run remains subject to the harness's own fixed-suite gates and output.
