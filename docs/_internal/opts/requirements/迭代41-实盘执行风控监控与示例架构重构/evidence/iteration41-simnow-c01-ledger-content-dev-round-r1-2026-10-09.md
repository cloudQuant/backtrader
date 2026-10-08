# SimNow C01 ledger content validator development round R1

Date: 2026-10-09. Repository: `D:/source_code/backtrader`. Branch: `dev`.
Parent before scoped delivery: `309fafdd0c43bd4b4d61ac3cc1c71ca6c80ea5f6`.

## Accepted scope

Three new, unregistered source/test/field-map members validate one exact V3
worker projection and its same-call baseline/final snapshot bytes. Validation
checks the eight-request plan, callback/request joins, six query receipts,
native close content, unchanged snapshot economics, V3 parser validity and
V4 projections recomputed from query rows. It never opens private files or
authenticates the caller, supplied module code, account or provider.
The result fixes authority to NONE and certification/source-authenticity false.
Root custody and formal case integration remain separate work.

The initial independent review was HOLD: refreshed artifact hashes concealed
malformed projections and projections that disagreed with query rows. The
repaired R2 review is SOURCE_CONTENT_REVIEW: PASS. Its two distinguishing
negative tests use the actual V3 parser and V4 projector code. Supplied module
objects and expected source hashes are content inputs; a future Root caller
must independently hold and verify exact module/function/global bindings.

## Acceptance evidence

Author and independent canonical focused QA each passed 13 tests with the
existing pytest configuration warning. Root tool de6b45 materialized the exact
three candidate members and two unchanged tracked V3/V4 dependencies into a
short selected-source artifact directory, with no Git worktree. The isolated
focused run passed 13, exit 0, in 0.20 seconds without warnings. It verified
actual module origins, source pre/post pins and an empty index. It used an
explicit backtrader_runtime module namespace to import only these two modules;
this does not accept default package imports. Native/SDK/network/process leaves
were denied before candidate imports and tests. Pytest/colorama console setup
was loaded before those guards. Root's first attempt, tool 460ec9, stopped in
colorama setup before test collection because the guard denied its WinDLL;
only the QA helper startup order was corrected, with candidate bytes unchanged.

The tracked dependencies are native V4 SHA-256
66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66
and protocol V3 SHA-256
c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160.
Neither dependency changes in this round.

Evidence level: SOURCE_CONTENT_VALIDATOR_ONLY. No actual account, provider,
native, process or certification invocation occurred. Formal SimNow C01 is 0.

## Explicit public payload whitelist

| Role | Path | Bytes | SHA-256 |
| --- | --- | --- | --- |
| candidate | examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py | 70205 | 4cbe8465c9b2854d2913de03d4e7a12f020debc8723d6c63539314d2ba7f424a |
| candidate | tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py | 21733 | a4f4d643fc3ca12c6e162e418312ec5b97291effaebefbf6f55573ef593fc88d |
| candidate | examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1_field_map.md | 9920 | c9912ba8793384d2057619a027db5aa0119ff1b81516021eb9c1dd06a45a7ec6 |
| public_review | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-root-ledger-v1-independent-review-r1-2026-10-09.md | 4517 | dac1135974af3aaa4f4e2c53c13236a96200dd9210daceb929c726b43fc71731 |
| public_review | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-root-ledger-v1-independent-review-r2-2026-10-09.md | 5655 | f32d02d0b23f48f2ae810385806f4c5854b457b9be290148c02adb3bacbeba9b |
| root_source_qa | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-ledger-root-source-qa-r1-2026-10-09/simnow_c01_ledger_root_qa_20261009.json | 1758 | f5b512ebc86141df0ea8b3a4c7b6d88fa3d829dee4c628c5ed4b00dde3c1c655 |
| root_source_qa | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-ledger-root-source-qa-r1-2026-10-09/simnow_c01_ledger_root_qa_20261009.py | 5439 | 380481976476cbde679014bb5160ae2663e61fdadbff562b55a5f029afea39c2 |

This record itself and `.gitattributes` are the only additional changed files.
Exact `-text` rules preserve all eight public payload/record members.
Unrelated modifications, historical worktrees, frozen production generations,
retained host 90344 and all private inputs remain outside this delivery.
