# AC41-63 writer review: full 460-candidate static coverage

This compact archive consolidates partitions A, B, and C against the current official static inventory. It records source review coverage and selected independent checks only. It does not close writer routes or authorize CTP, SimNow, or production writes.

## Inventory coverage

The source inventory is [live-execution-inventory-candidates.json](../live-execution-inventory-candidates.json), SHA-256 03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456. It contains 363 writer and 97 dynamic candidates across 355 scanned files, with zero parse errors.

| Partition | Inventory positions | Count | Independent evidence |
|---|---:|---:|---|
| A | writer 0–120 | 121 | [A QA report](partition-a/qa-report.md) |
| B | writer 121–240 | 120 | [B QA receipt](partition-b/qa-receipt.md) |
| C | writer 241–362 and dynamic 0–96 | 219 | [C v2 QA addendum](partition-c/qa-v2-addendum.md) |
| Total | all inventory positions | 460 | [coverage verification](coverage-verification.json) |

The coverage receipt maps every partition row to an official disposition candidate ID, verifies 460 unique inventory positions with no gaps or overlap, and confirms all 460 official rows remain REVIEW_REQUIRED / NOT_AVAILABLE. The current checklist is [live-execution-writer-dispositions.json](../live-execution-writer-dispositions.json), SHA-256 B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426; its static trace label is STATIC_AST_CANDIDATE_NO_RUNTIME_TRACE, closure status is NOT_CLOSED_STATIC_REVIEW_REQUIRED, and it retains six historical tombstones. No official disposition was changed by this archive.

The checklist preserves line/column locators from its earlier snapshot for stable-ID candidates whose source line moved; candidate IDs are based on semantic locators and remain unchanged. The coverage verification records these locator deltas explicitly.

## Findings and correction history

Partition A identifies A-019–A-021: the CTP gateway wrapper's direct submit/create/cancel methods trust a mutable instance flag. The [AST-extracted fake-sink probe](partition-a/source-fake-sink-probe.py) confirms default rejection, then reaches only an in-memory fake after deliberate same-process flag mutation. It imported no Backtrader/provider module and made no network/native calls. This is a conditional private-object path, not evidence of default registered-route reachability or real provider behavior.

Partition B records two native/provider writer methods behind explicit same-process execution composition, plus legacy strategy helpers. Its correction history matters: the initial draft incorrectly said create_live_broker was fenced. The corrected report states create_live_store raises, while create_live_broker accepts a caller-supplied Store and builds a BtApiBroker. This identifies an out-of-registry custom composition; it does not establish a successful external write. See the [corrected B report](partition-b/report.md) and [B QA correction receipt](partition-b/qa-receipt.md).

Partition C reviews both the remaining writer indices and all dynamic candidates. Its v1 wording treated custom registries as if review trust were enforced. The v2 report corrects this: RuntimeRegistry(trusted=True) defaults to true, so a documented reviewed-caller expectation is not a code-enforced credential. The default CLI uses the code-owned registry and rejects live dispatch before runner import; custom non-live injected registries remain in-process extension paths. The [C v2 report](partition-c/report-v2.md) supersedes the preserved [v1 report](partition-c/report-v1.md). The [QA addendum](partition-c/qa-v2-addendum.md) binds the corrected findings and confirms the 219-row order is unchanged; only dynamic candidates 056–062 had their reason text corrected. The addendum inherits the original 219-row source/hash check rather than rerunning every source.

## Evidence limits

Partition A's source-only AST extraction with inert fakes is the only dynamic probe in this review. B and C were reviewed statically; their QA checked inventory locators, source hashes, and bounded source claims without importing project code or reaching a provider. These checks do not establish route authorization, account isolation, successful CTP I/O, or universal write closure.

The default registered runtime remains governed by its own no-write/live-no-go controls, while importable strategy, broker, client, and reflection paths can be composed in-process by custom callers. All official entries remain REVIEW_REQUIRED / NOT_AVAILABLE.

Source files, shared indexes, the official disposition checklist, and shared documentation were not modified by this archive. The inventory/disposition records are linked above rather than duplicated.

## Archive integrity

[ARTIFACT-MANIFEST.json](ARTIFACT-MANIFEST.json) SHA-256 27A69D61F18F7F1324C6EE8BBC2DA28B76799BC350A17C796BDC23110BB2249B. [SHA256SUMS.txt](SHA256SUMS.txt) covers every archive file except itself. All relative links were checked; payload origins, hashes, and sizes are recorded in the manifest.
