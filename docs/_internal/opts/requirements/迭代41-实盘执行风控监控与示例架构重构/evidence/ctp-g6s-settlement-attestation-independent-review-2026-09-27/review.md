# G6-S settlement candidate — independent review

**Disposition: author candidate only; G6-S and G7-S remain closed.** This review was read-only against the frozen fake candidate, archive, and SDK source snapshots. It did not import or invoke the CTP SDK/native module, contact a provider, use credentials or protected configuration, or change production/default-route code.

## Results

- Reran the frozen candidate on CPython 3.11.5: **75 passed**. The isolated QA-only ConfirmDate-shaped probe added two cases and passed **77 total**: one positive attestation using only the fields the actual confirmation row exposes, and one missing-request-filters negative with all write counters zero.
- Verified the author raw ZIP SHA-256 `eebf640bdf8be00caa5bac4875002dc29c263729a7fda30fed2be88fc33c9c4f`. Every ZIP member is byte-identical to its archived directory file; every SHA256SUMS entry, including the recorded checksum of SHA256SUMS.txt, matches. The r1 candidate source, test, README and manifest hashes match the frozen r1 manifest/archive.
- The frozen negative `test_correct_looking_row_without_exact_native_provenance_rejects_with_zero_writes` covers missing request filters, unverified source seal, history mismatch and record-digest mismatch. Each asserts one settlement query and zero settlement-confirm/order-insert/order-action calls; missing request filters bypasses the verifier. The r1 fixture supplies both `TradingDay` and `ConfirmDate`. The bundled CTP 6.7.7 structure has `ConfirmDate` but no `TradingDay`; the added isolated probe verifies the candidate also accepts ConfirmDate-only with complete fake provenance and rejects it without request filters.
- Independently checked the exact clean G4-r2 `client.py` bytes: SHA-256 `C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF`. Lines 8021–8051 pass both `request_filter_field=field` and `request_intent_filters=intent_filters` to `_execute_query`. The r1 dirty SDK file hashes to `B61B32F9A2A2E61035BF88BCB7ACF669C8C7EE8E5BF5D7E1F6E375E69F053EAB`; lines 6171–6184 omit those arguments. The r1 finding is therefore specific to that dirty source snapshot and should not be generalized to clean G4-r2.
- The CTP 6.7.7 `CThostFtdcSettlementInfoConfirmField` declaration contains `BrokerID`, `InvestorID`, `ConfirmDate`, `ConfirmTime`, `SettlementID`, `AccountID`, and `CurrencyID`; it has no `TradingDay`. TradingDay provenance must come from the authenticated session/query source, not a fabricated native row property.

## Matrix-path note

The root preflight reported that the r1 matrix path contained mojibake. I independently parsed the exact `D:\temp\simnow-settlement-g6s-20260927\manifest.json` bytes (SHA-256 `126ace8778f4c679a491f3a76c8bbccd6f13bc3503dffa2848445829b6a88dc1`; byte-identical to the ZIP member). Its decoded path has no U+FFFD and equals the canonical current matrix path, so I did not reproduce the spelling failure for these exact bytes. The r1 listed digest differs from the current matrix bytes, and the r2 provenance records a time-bounded matrix capture. The current matrix has changed since those captures, so this review does not claim historical matrix-byte equivalence.

## Limits

This is fake-only evidence. The verifier is injected; the tests do not establish a deployed SDK source seal, retained query-history authority, freshness under real callbacks, a coherent cross-query snapshot, external account-wide writer exclusion, or an execution/write gate. No G6-S or G7-S acceptance follows from these tests.

## Raw evidence

- `independent-receipt.json` contains hashes, test commands/results, matrix-path comparison and source lineage checks.
- `candidate-pytest.txt` is the direct frozen-candidate run.
- `confirmdate-probe-pytest.txt` plus `confirmdate-probe-snapshot/` are the two-case QA-only extension; the copied candidate files match r1 hashes.
- `source-review.txt` contains narrow exact line excerpts for clean-vs-dirty SDK source, CTP structure, and the negative test.
- `raw-evidence.zip` and `SHA256SUMS.txt` provide a hash-bound bundle.

