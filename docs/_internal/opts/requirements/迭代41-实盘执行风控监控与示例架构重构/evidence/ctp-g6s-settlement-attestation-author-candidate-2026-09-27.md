# G6-S settlement attestation fake candidate archive

**Disposition: AUTHOR CANDIDATE ONLY — NOT ACCEPTED. No G6-S or G7-S acceptance.**

The frozen r1 fake adapter, tests, README, manifest and receipt are preserved byte-for-byte from D:\temp\simnow-settlement-g6s-20260927. The captured author run reports **75 passed** on CPython 3.11.5; its stdout is included.

## Archive

- Directory: D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-g6s-settlement-attestation-author-candidate-2026-09-27
- Raw ZIP: D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-g6s-settlement-attestation-author-candidate-2026-09-27.raw.zip
- Raw ZIP SHA-256: eebf640bdf8be00caa5bac4875002dc29c263729a7fda30fed2be88fc33c9c4f
- Frozen r1 manifest SHA-256: 126ace8778f4c679a491f3a76c8bbccd6f13bc3503dffa2848445829b6a88dc1
- Frozen r1 receipt SHA-256: 454538c4089252328d7ee80794a93d195f11926c0ba37c673cdff7c62bba9880
- See source-lineage-r2.json before applying r1 SDK-source findings. It limits r1 missing-request_filters observation to the exact dirty d3674e19 checkout/hash and records the distinct clean G4-r2 report as independently unverified here.
- provenance-r2.json was created after a root preflight reported 10/11 reviewed inputs valid and called the r1 matrix path unusable due to mojibake. That path finding was later disproved for the exact frozen manifest; see the correction below. Its matrix hash is a time-bounded capture at 2026-09-26T22:44:50Z, not a claim about later matrix edits or historical r1 matrix bytes.
- R2 matrix capture: docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/ctp-current-acceptance-matrix.md; SHA-256 73901647326beb1ec67ff470ba3c22153b28162942dec83b54f357c474075f4c.

**2026-09-27 correction:** [Independent byte-level review](ctp-g6s-settlement-attestation-independent-review-2026-09-27/review.md) of the exact frozen r1 manifest (SHA-256 `126ace8778f4c679a491f3a76c8bbccd6f13bc3503dffa2848445829b6a88dc1`) found the canonical Chinese matrix path, with no U+FFFD. The earlier root preflight and the provenance-r2 description of an unusable/mojibake path were incorrect for those bytes. The r1 matrix digest no longer matches the edited matrix; r2 remains a time-bounded content capture. The frozen r1/r2 files and the original observation are retained unchanged for audit.

## Archived member hashes

SHA256SUMS.txt lists all archive members other than itself.

| File | SHA-256 |
| --- | --- |
| manifest.json | 126ace8778f4c679a491f3a76c8bbccd6f13bc3503dffa2848445829b6a88dc1 |
| provenance-r2.json | aac303aae803756672c1e971e9f2e681e3f7595eecb11f4857d675d0e8528f6a |
| README.md | fbe319e36ae6ce0f2ece1a577ae795e4c7ad28a1d028716afd5fe9cae26e4aaf |
| receipt.md | 454538c4089252328d7ee80794a93d195f11926c0ba37c673cdff7c62bba9880 |
| settlement_attestation.py | f747706573534acd8d93b69eedcd79272c24dc231bb7077ddbd820295af1a76f |
| SHA256SUMS.txt | 27e537d3c3a1854e59baeec8cc2235da557a1cbc580116102150c6cb5f5ab3ee |
| source-lineage-r2.json | d88a4a93eb4c716a5a9d8a4ee74e7ab01f872faa5ebb3bf6b5b10a7ba31cbb37 |
| test_settlement_attestation.py | 8e433a9d030f11a9bbc8b0aa9053bc0dc2af9e91a770e121a8da216d452ba059 |
| test-stdout.txt | 210658d741f099f5eda0a232fae16f3831f83a15a734666fbf72f1539c9be002 |

## Candidate contract and limits

- Fake-only local contract: no SDK import, provider/native/network calls, credentials, protected-config access, or main production-code change.
- It binds the explicit selected pair, exact account fingerprints, current native TD TradingDay and connection generation, terminal settlement query provenance, one settlement read, and zero settlement-confirm/order-insert/order-action writes. Fake request_type is settlement_confirmation; query_settlement_confirmation is only the request counter.
- Settlement row scope uses BrokerID, InvestorID and ConfirmDate. Current TradingDay must be authenticated from the TD session/QuerySource; the native confirmation field itself has no TradingDay member.
- For the official SimNow 7x24 selected pair, unproved current settlement rejects with zero writes. There is no time/set/address fallback. Snapshot authority, an OS-session identity, an external writer fence, an execution gate and write authority are not established.
- Main readiness still needs an independent settlement-specific provenance validator for SDK source seal, retained query history/result digest, terminal callback and freshness. The existing seven-query certificate builder omits settlement confirmation. ADR-41-16 option B remains proposed/unapproved; strict F14 lacks accepted account-wide writer fence and coherent shared snapshot.
