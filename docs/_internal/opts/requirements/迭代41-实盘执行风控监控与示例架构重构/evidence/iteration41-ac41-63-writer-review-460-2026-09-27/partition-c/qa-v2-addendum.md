# AC41-63 partition C QA addendum

This addendum rebinds the original static QA result to the corrected v2 artifacts.

- Findings v2: `review-findings-v2.json` — SHA-256 `92bff46c4073694ace40a9c39e082dae6093e39d018bdac387830f48378b8af3`
- Report v2: `high-priority-report-v2.md` — SHA-256 `81a9bdc32cd04995fe9f730c08ec129228affd1cea241c2f55a1036a0f89e1f4`
- Inventory: SHA-256 `03658257d97e31c2d8f8bfd48685441533552b32674f5d63810141e3038ab456`
- Original full QA receipt: `qa-receipt.json` — SHA-256 `4dac380775603eb10dd51cf734bd751bfaf71dd3564c6eddcc63fc5dfdf9c4c4`

Version 2 corrects the registry trust wording: `RuntimeRegistry(trusted=True)` is the default, but neither the flag nor `cli.main` enforces review of an injected registry. A custom non-live runner can execute in-process. The installed CLI selects the code-owned inventory by default. **Live dispatch remains rejected before runner import.**

The v1/v2 JSON comparison found the same 219 candidate IDs in the same order. The only row changes are `reason` fields for `dynamic:056` through `dynamic:062`; all 219 statuses remain `REVIEW_REQUIRED / NOT_AVAILABLE`. The inventory digest is unchanged, and the current runner source hash matches all seven affected rows.

The original receipt contains the full 219-row index, inventory identity, source hash/line, and status checks. This addendum did not rerun them; it checked the v2 hashes, JSON delta, unchanged inventory and affected source binding, corrected wording, and explicit live rejection.