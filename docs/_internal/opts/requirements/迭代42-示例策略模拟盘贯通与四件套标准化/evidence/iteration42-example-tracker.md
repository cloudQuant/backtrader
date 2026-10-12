# Iteration 42 public example status tracker

This deterministic snapshot uses fixed, hash-pinned public records. It does not scan
live-evidence directories or read ignored captures.

Source policy: FIXED_HASH_PINNED_PUBLIC_RECORDS_ONLY. This reports fixed path/hash verification, not Git tracking status.
Formal account PASS delta in this review: 0.
Audit snapshot: 2026-10-12 | branch dev | reviewed HEAD 9ef0e00aa38da900ca8835d93b81f2c16cf782d9 | PARTIAL_NOT_COMPLETE.
The reviewed HEAD is historical provenance, not a current-checkout pin.
Public seed SHA-256: 1cd122cd0f7ecfec1e095f7e5f4094629546873c46b902fd961fa63591df6677.
Superseded schedule: CANCELLED on 2026-10-11. The user cancelled the six-step Monday live schedule; the older checklist is historical only..

| Example | Current path | Dry | Replay | Historical best | Latest known attempt | Current capability |
| --- | --- | --- | --- | --- | --- | --- |
| 012_1_midfreq_cross_exchange | examples/unified/012_1_midfreq_cross_exchange | DRY | FORMULA_CHECK_PASS | MECHANICAL_DEMO_SMOKE_PASS (mechanical_demo_smoke, live-20261010T085734Z-82a55b70) | MECHANICAL_DEMO_SMOKE_PASS (mechanical_demo_smoke, live-20261010T085734Z-82a55b70) | SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED: The canonical and two local candidate-manifest source-binding repair was accepted at dev commit b3a6b7c712e92d57b3ca714bec0a98e51574f797 after 181 source/fake/offline tests passed (0 failed, 0 skipped, 0 errors). The pinned independent review confirms qualification-v3.json still has an inner-config hash mismatch, so strict qualification is not accepted. This is manifest-level source evidence only; no live 012 invocation was reverified. |
| 012_2_event_driven_cross_exchange | examples/unified/012_2_event_driven_cross_exchange | DRY | FORMULA_CHECK_PASS | MECHANICAL_DEMO_SMOKE_PASS (mechanical_demo_smoke, live-20261010T083916Z-f28557f7) | MECHANICAL_DEMO_SMOKE_PASS (mechanical_demo_smoke, live-20261010T083916Z-f28557f7) | SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED: The canonical and two local candidate-manifest source-binding repair was accepted at dev commit b3a6b7c712e92d57b3ca714bec0a98e51574f797 after 181 source/fake/offline tests passed (0 failed, 0 skipped, 0 errors). The pinned independent review confirms qualification-v3.json still has an inner-config hash mismatch, so strict qualification is not accepted. This is manifest-level source evidence only; no live 012 invocation was reverified. |
| 013_1_midfreq_cross_arbitrage | examples/unified/013_1_midfreq_cross_arbitrage | DRY | LOCAL_REPLAY_PASS | PASS (fill_round_trip, live-20261011T030536Z-7e938fc7) | PASS (fill_round_trip, live-20261011T030536Z-7e938fc7) | PARTIAL: Historical fill-round-trip evidence is accepted, but standard-front coverage was not separately demonstrated; no fresh capability claim is made. |
| 013_2_highfreq_calendar_arbitrage | examples/unified/013_2_highfreq_calendar_arbitrage | DRY | LOCAL_REPLAY_PASS | PASS (fill_round_trip, live-20261010T075431Z-3583ad31) | PASS (fill_round_trip, live-20261010T075431Z-3583ad31) | HISTORICAL_PASS_ONLY: Historical fill round trip is accepted, while HFT remains HFT_FAILED/NOT_ADMITTED and no latency conclusion is made. |
| 013_3_sa_midfreq_simnow | examples/unified/013_3_sa_midfreq_simnow | DRY | LOCAL_REPLAY_PASS | none recorded | FAIL (fill_round_trip, live-20261010T084209Z-54afd472) | UNACCEPTED_FAIL: The latest public live result failed no_fill_round_trip; no successful target run is recorded. |
| 014_1_ctp_options_lowfreq | examples/unified/014_1_ctp_options_lowfreq | DRY | LOCAL_REPLAY_PASS | none recorded | BLOCKED (strict_live_adapter, live-20261009T214444Z-5a848a7f) | BLOCKED: No three-leg fill round trip is accepted; the historical attempt blocked before arming. |
| 014_2_ctp_options_midfreq | examples/unified/014_2_ctp_options_midfreq | DRY | LOCAL_REPLAY_PASS | none recorded | BLOCKED (observation_only_feed_sealed, run id not stated) | BLOCKED: The latest known observation was blocked by live_event_clock_outside_run_mapping; no new session result is inferred. |
| 015_ctp_options_highfreq | examples/unified/015_ctp_options_highfreq | DRY | LOCAL_REPLAY_PASS | OBSERVATION_PASS (observation_only_tick_arrival, live-20261009T213253Z-39d69fb7) | OBSERVATION_PASS (observation_only_tick_arrival, live-20261009T213253Z-39d69fb7) | OBSERVATION_ONLY: Tick arrival was observed with zero order writes and zero cohort decisions; this is not a trading or HFT pass. |

## Boundaries and public evidence

Historical best, latest known attempt, and audit-date capability are independent fields. A latest BLOCKED result remains BLOCKED even when an earlier historical result passed. This tracker grants no runner, strategy, or write authority.

### 012_1_midfreq_cross_exchange

- Admission labels: research=RESEARCH_REJECTED, HFT=NOT_APPLICABLE_TO_MIDFREQ, approval=NOT_APPROVED.
- Signature boundary: Mechanical demo evidence does not change research status or approval; any controlled rebind must update the candidate fingerprint and pass its source-fingerprint tests, and approval still requires a valid signed receipt.
- Current capability as of 2026-10-12: SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED — The canonical and two local candidate-manifest source-binding repair was accepted at dev commit b3a6b7c712e92d57b3ca714bec0a98e51574f797 after 181 source/fake/offline tests passed (0 failed, 0 skipped, 0 errors). The pinned independent review confirms qualification-v3.json still has an inner-config hash mismatch, so strict qualification is not accepted. This is manifest-level source evidence only; no live 012 invocation was reverified..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- historical best evidence:
  - r1_progress — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r1-live-run-progress-2026-10-10.md#012_1 and 013_3 public progress summaries — SHA-256 94a79e9b9c579c776f16e7fd50f1e9b5588d12d59e90dcb939c24616e2e9386c — Historical sanitized progress; not current-tree capability.
  - r2_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r2-acceptance-record-2026-10-10.md#012_1 earlier demo run and bounded acceptance notes — SHA-256 93f1773fa1fc7783d3b236387d7b32f83d371fab04a8179e95c45fc8cf1ddaed — Historical public provenance; later dated evidence controls the latest-known result.
  - r3_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r3-acceptance-record-2026-10-10.md#lines 26-33, 42-46, 82-106 — SHA-256 cd1ca39a3aa0fcdcf08e83770b2cdc9111412143c8eea3784e254c5f49361000 — 012 mechanical demo results with research rejection and HFT admission limits preserved.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- latest known attempt evidence:
  - r3_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r3-acceptance-record-2026-10-10.md#lines 26-33, 42-46, 82-106 — SHA-256 cd1ca39a3aa0fcdcf08e83770b2cdc9111412143c8eea3784e254c5f49361000 — 012 mechanical demo results with research rejection and HFT admission limits preserved.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - i43_relocation — docs/_internal/opts/requirements/迭代43-examples目录三类重构与config选层/evidence/r2-unified-relocation-2026-10-11.md#012 unified relocation and root-manifest reconciliation — SHA-256 db74c591e2ea60e500ac5d166c385d7e4927fc51114d29cc4aa1c994f5d32495 — Public path/source reconciliation; not a live retry or approval.
  - i43_manifest_qa — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/repair-i42manifeste-2026-10-12/result.json#head, parent_commit, evidence_level, counts, exact source scope, account_acceptance_added — SHA-256 ee40ecafcbc9d42dbdcdc571298358af201114c6e0e4a3d4b7d7ebe24d464875 — Root source/fake/offline QA for the canonical root manifest and two local candidate manifests; not a live/account result.
  - i43_binding_review — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/source-binding-review-2026-10-12.json#reviewed_commit, artifact_outer_pin_matches_public_head, artifact_inner_config_pin_matches_public_head, research_status, approval_status — SHA-256 eaf19d1a9760e834836f1532844c6b18fd5440a6bc0893cc66bc215d56cd1121 — Independent public-source review confirms qualification inner config pin mismatch, RESEARCH_REJECTED, and NOT_APPROVED.
- admission boundary evidence:
  - r3_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r3-acceptance-record-2026-10-10.md#lines 26-33, 42-46, 82-106 — SHA-256 cd1ca39a3aa0fcdcf08e83770b2cdc9111412143c8eea3784e254c5f49361000 — 012 mechanical demo results with research rejection and HFT admission limits preserved.
  - approval_policy — examples/_support/strategy_candidate_approval.py#candidate fingerprint and signed approval verification — SHA-256 eec569d2c6fd6babc9d94b18e4c4deb8b6462212618559a5987d8cab167a7a2b — Public code boundary; tracker cannot create or amend approval.
  - approval_trust_root — examples/_support/demo-approval-trust-root.pem#pinned Ed25519 demo-approval trust root — SHA-256 42212201b7ec9159a00fbf0a0d1f2d541a88d4b81eb3330d587658391916e3e7 — Trust-root identity only; tracker does not mint or verify a signature.

### 012_2_event_driven_cross_exchange

- Admission labels: research=RESEARCH_REJECTED, HFT=HFT_FAILED/NOT_ADMITTED, approval=NOT_APPROVED.
- Signature boundary: Mechanical execution is not strategy admission; a controlled rebind must preserve candidate-specific fingerprint checks and approval still requires a valid signed receipt.
- Current capability as of 2026-10-12: SOURCE_BINDING_REPAIRED_QUALIFICATION_NOT_ACCEPTED — The canonical and two local candidate-manifest source-binding repair was accepted at dev commit b3a6b7c712e92d57b3ca714bec0a98e51574f797 after 181 source/fake/offline tests passed (0 failed, 0 skipped, 0 errors). The pinned independent review confirms qualification-v3.json still has an inner-config hash mismatch, so strict qualification is not accepted. This is manifest-level source evidence only; no live 012 invocation was reverified..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- historical best evidence:
  - r3_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r3-acceptance-record-2026-10-10.md#lines 26-33, 42-46, 82-106 — SHA-256 cd1ca39a3aa0fcdcf08e83770b2cdc9111412143c8eea3784e254c5f49361000 — 012 mechanical demo results with research rejection and HFT admission limits preserved.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- latest known attempt evidence:
  - r3_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r3-acceptance-record-2026-10-10.md#lines 26-33, 42-46, 82-106 — SHA-256 cd1ca39a3aa0fcdcf08e83770b2cdc9111412143c8eea3784e254c5f49361000 — 012 mechanical demo results with research rejection and HFT admission limits preserved.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - i43_relocation — docs/_internal/opts/requirements/迭代43-examples目录三类重构与config选层/evidence/r2-unified-relocation-2026-10-11.md#012 unified relocation and root-manifest reconciliation — SHA-256 db74c591e2ea60e500ac5d166c385d7e4927fc51114d29cc4aa1c994f5d32495 — Public path/source reconciliation; not a live retry or approval.
  - i43_manifest_qa — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/repair-i42manifeste-2026-10-12/result.json#head, parent_commit, evidence_level, counts, exact source scope, account_acceptance_added — SHA-256 ee40ecafcbc9d42dbdcdc571298358af201114c6e0e4a3d4b7d7ebe24d464875 — Root source/fake/offline QA for the canonical root manifest and two local candidate manifests; not a live/account result.
  - i43_binding_review — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/source-binding-review-2026-10-12.json#reviewed_commit, artifact_outer_pin_matches_public_head, artifact_inner_config_pin_matches_public_head, research_status, approval_status — SHA-256 eaf19d1a9760e834836f1532844c6b18fd5440a6bc0893cc66bc215d56cd1121 — Independent public-source review confirms qualification inner config pin mismatch, RESEARCH_REJECTED, and NOT_APPROVED.
- admission boundary evidence:
  - r3_acceptance — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r3-acceptance-record-2026-10-10.md#lines 26-33, 42-46, 82-106 — SHA-256 cd1ca39a3aa0fcdcf08e83770b2cdc9111412143c8eea3784e254c5f49361000 — 012 mechanical demo results with research rejection and HFT admission limits preserved.
  - approval_policy — examples/_support/strategy_candidate_approval.py#candidate fingerprint and signed approval verification — SHA-256 eec569d2c6fd6babc9d94b18e4c4deb8b6462212618559a5987d8cab167a7a2b — Public code boundary; tracker cannot create or amend approval.
  - approval_trust_root — examples/_support/demo-approval-trust-root.pem#pinned Ed25519 demo-approval trust root — SHA-256 42212201b7ec9159a00fbf0a0d1f2d541a88d4b81eb3330d587658391916e3e7 — Trust-root identity only; tracker does not mint or verify a signature.

### 013_1_midfreq_cross_arbitrage

- Admission labels: research=NOT_ASSESSED_IN_THIS_TRACKER, HFT=NOT_APPLICABLE_TO_MIDFREQ, approval=NOT_APPLICABLE.
- Signature boundary: This tracker records evidence only and cannot change strategy admission or create approval.
- Current capability as of 2026-10-12: PARTIAL — Historical fill-round-trip evidence is accepted, but standard-front coverage was not separately demonstrated; no fresh capability claim is made..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- historical best evidence:
  - r4_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r4-implementation-and-smoke-record-2026-10-10.md#lines 121-130 — SHA-256 1e52d6a203f3813d1b64c0c995d2195c279c5e7d6db4eb05052094585fcdfce0 — Historical 013_1 fill-round-trip record; no fresh current-tree run claim.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- latest known attempt evidence:
  - r4_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r4-implementation-and-smoke-record-2026-10-10.md#lines 121-130 — SHA-256 1e52d6a203f3813d1b64c0c995d2195c279c5e7d6db4eb05052094585fcdfce0 — Historical 013_1 fill-round-trip record; no fresh current-tree run claim.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - r4_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r4-implementation-and-smoke-record-2026-10-10.md#lines 121-130 — SHA-256 1e52d6a203f3813d1b64c0c995d2195c279c5e7d6db4eb05052094585fcdfce0 — Historical 013_1 fill-round-trip record; no fresh current-tree run claim.
- admission boundary evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.

### 013_2_highfreq_calendar_arbitrage

- Admission labels: research=NOT_ASSESSED_IN_THIS_TRACKER, HFT=HFT_FAILED/NOT_ADMITTED, approval=NOT_APPLICABLE.
- Signature boundary: Execution evidence does not grant HFT admission; HFT status remains failed and not admitted.
- Current capability as of 2026-10-12: HISTORICAL_PASS_ONLY — Historical fill round trip is accepted, while HFT remains HFT_FAILED/NOT_ADMITTED and no latency conclusion is made..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- historical best evidence:
  - r5_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r5-implementation-record-2026-10-10.md#lines 34, 50, 61, 171-177 — SHA-256 3442f7ffce09afc2df7d20b27ce6a17d2ad5fc62c9faa31a26f2903bb0419405 — Historical 013_2 HFT boundary and 013_3 no-fill result.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- latest known attempt evidence:
  - r5_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r5-implementation-record-2026-10-10.md#lines 34, 50, 61, 171-177 — SHA-256 3442f7ffce09afc2df7d20b27ce6a17d2ad5fc62c9faa31a26f2903bb0419405 — Historical 013_2 HFT boundary and 013_3 no-fill result.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - r5_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r5-implementation-record-2026-10-10.md#lines 34, 50, 61, 171-177 — SHA-256 3442f7ffce09afc2df7d20b27ce6a17d2ad5fc62c9faa31a26f2903bb0419405 — Historical 013_2 HFT boundary and 013_3 no-fill result.
- admission boundary evidence:
  - r5_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r5-implementation-record-2026-10-10.md#lines 34, 50, 61, 171-177 — SHA-256 3442f7ffce09afc2df7d20b27ce6a17d2ad5fc62c9faa31a26f2903bb0419405 — Historical 013_2 HFT boundary and 013_3 no-fill result.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.

### 013_3_sa_midfreq_simnow

- Admission labels: research=NOT_ASSESSED_IN_THIS_TRACKER, HFT=NOT_APPLICABLE_TO_MIDFREQ, approval=NOT_APPLICABLE.
- Signature boundary: This tracker does not grant strategy admission or live-write authority.
- Current capability as of 2026-10-12: UNACCEPTED_FAIL — The latest public live result failed no_fill_round_trip; no successful target run is recorded..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- latest known attempt evidence:
  - r1_progress — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r1-live-run-progress-2026-10-10.md#012_1 and 013_3 public progress summaries — SHA-256 94a79e9b9c579c776f16e7fd50f1e9b5588d12d59e90dcb939c24616e2e9386c — Historical sanitized progress; not current-tree capability.
  - r5_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r5-implementation-record-2026-10-10.md#lines 34, 50, 61, 171-177 — SHA-256 3442f7ffce09afc2df7d20b27ce6a17d2ad5fc62c9faa31a26f2903bb0419405 — Historical 013_2 HFT boundary and 013_3 no-fill result.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - r5_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r5-implementation-record-2026-10-10.md#lines 34, 50, 61, 171-177 — SHA-256 3442f7ffce09afc2df7d20b27ce6a17d2ad5fc62c9faa31a26f2903bb0419405 — Historical 013_2 HFT boundary and 013_3 no-fill result.
- admission boundary evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.

### 014_1_ctp_options_lowfreq

- Admission labels: research=NOT_ASSESSED_IN_THIS_TRACKER, HFT=NOT_APPLICABLE_TO_LOWFREQ, approval=NOT_APPLICABLE.
- Signature boundary: A blocked observation is not a strategy approval or permission to write.
- Current capability as of 2026-10-12: BLOCKED — No three-leg fill round trip is accepted; the historical attempt blocked before arming..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- latest known attempt evidence:
  - r6_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r6-0141-strict-live-adapter-2026-10-10.md#lines 101-107 — SHA-256 a8bd88210b7532425b7a065e9040d4390e39ca9ed57c2b7d3c4409627502015b — Public 014_1 blocker, not three-leg fill acceptance.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - r6_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r6-0141-strict-live-adapter-2026-10-10.md#lines 101-107 — SHA-256 a8bd88210b7532425b7a065e9040d4390e39ca9ed57c2b7d3c4409627502015b — Public 014_1 blocker, not three-leg fill acceptance.
- admission boundary evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.

### 014_2_ctp_options_midfreq

- Admission labels: research=NOT_ASSESSED_IN_THIS_TRACKER, HFT=NOT_APPLICABLE_TO_MIDFREQ, approval=NOT_APPLICABLE.
- Signature boundary: Observation-tier evidence does not grant strategy admission or live-write authority.
- Current capability as of 2026-10-12: BLOCKED — The latest known observation was blocked by live_event_clock_outside_run_mapping; no new session result is inferred..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- latest known attempt evidence:
  - r7_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r7-0142-observation-tier-2026-10-10.md#lines 75-83 — SHA-256 e7252e53d307bc2a97294d3e4bf224394e8aa5390b4580619467f3c67a0144de — Public 014_2 observation-tier event-clock blocker.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - r7_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r7-0142-observation-tier-2026-10-10.md#lines 75-83 — SHA-256 e7252e53d307bc2a97294d3e4bf224394e8aa5390b4580619467f3c67a0144de — Public 014_2 observation-tier event-clock blocker.
- admission boundary evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.

### 015_ctp_options_highfreq

- Admission labels: research=NOT_ASSESSED_IN_THIS_TRACKER, HFT=HFT_FAILED/NOT_ADMITTED, approval=NOT_APPLICABLE.
- Signature boundary: Tick-arrival observation and zero writes do not establish strategy admission or HFT performance.
- Current capability as of 2026-10-12: OBSERVATION_ONLY — Tick arrival was observed with zero order writes and zero cohort decisions; this is not a trading or HFT pass..
- offline evidence:
  - audit_json — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.json#offline_example_commands and public_input_sha256 — SHA-256 a6fe36d02313071629c9799c128a96e3785d4f1e92e76f5d5706288eccbf01c9 — Sanitized dry/replay outcomes and public-input integrity map; not raw live evidence.
- historical best evidence:
  - r8_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r8-015-observation-tier-2026-10-10.md#lines 58-83 — SHA-256 51be17859d45171d850931c422ed972c046d2ee6fa3edf31cb254b718a88565b — Tick-arrival observation and explicit zero-write/HFT bounds.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- latest known attempt evidence:
  - r8_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r8-015-observation-tier-2026-10-10.md#lines 58-83 — SHA-256 51be17859d45171d850931c422ed972c046d2ee6fa3edf31cb254b718a88565b — Tick-arrival observation and explicit zero-write/HFT bounds.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
- current capability evidence:
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
  - r8_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r8-015-observation-tier-2026-10-10.md#lines 58-83 — SHA-256 51be17859d45171d850931c422ed972c046d2ee6fa3edf31cb254b718a88565b — Tick-arrival observation and explicit zero-write/HFT bounds.
- admission boundary evidence:
  - r8_record — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/r8-015-observation-tier-2026-10-10.md#lines 58-83 — SHA-256 51be17859d45171d850931c422ed972c046d2ee6fa3edf31cb254b718a88565b — Tick-arrival observation and explicit zero-write/HFT bounds.
  - audit_md — docs/_internal/opts/requirements/迭代42-示例策略模拟盘贯通与四件套标准化/evidence/acceptance-audit-2026-10-12.md#lines 42-53, 83-95, 119-123 — SHA-256 2d3468baa907ebd5e8ac916751741b2905e32b3df085cd8f9271be7c907576f8 — Public audit conclusions and source-bound blockers as of its documented review.
