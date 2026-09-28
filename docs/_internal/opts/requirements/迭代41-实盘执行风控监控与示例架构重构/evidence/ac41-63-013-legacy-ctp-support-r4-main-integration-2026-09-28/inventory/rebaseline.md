# R4 writer inventory rebaseline

The full collector's raw JSON and stdout are retained under `collector/`. The raw/current inventory SHA-256 is `A959A3BC6284232EA90191F13ADC71A6931F5DFCBA6DB16E7AC72B1476B9D142`; stdout SHA-256 is `E8E8831CB3D456223B320A174B46EABC891F17BBD38EB843856A238831D25E2E`.

The strict R4 comparison found the same 460 candidate IDs in the same order, with the same 355 files, 363 writer candidates, and 97 dynamic candidates. Exactly four source locations moved from line 491 to line 495 after the inserted fail-close statements. No candidate was added, removed, or reordered.

The official writer disposition checklist is preserved unchanged at SHA-256 `B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426`. It still carries its historical line 492 locator. The checklist encodes disposition/review status, which did not change; the refreshed collector inventory records current locators. Every active row remains `REVIEW_REQUIRED / NOT_AVAILABLE`.

The full verifier output reports PASS for 460/460 and retains six historical tombstones. Scanner contract JUnit reports 15/15 passing. These are static inventory and contract checks only; they do not establish writer closure or authorize a route.