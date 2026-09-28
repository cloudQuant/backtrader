# Store AccountActor r2d placeholder compatibility candidate — independent QA archive

**Verdict: LOCAL_COMPATIBILITY_CANDIDATE_PASS / CTP_WRITE_NO_GO.**

This archive preserves the frozen author candidate and its independent review evidence. It is a narrow local compatibility result for unsupported placeholder providers; it does not enable CTP reads/writes, install external Actor authority, or alter the main Store. The r2c broad integration still has 258 failures, and r2d has not been applied to the main Store.

## Frozen identity and integrity

- Author ZIP SHA-256: 328acbe6fb46d0227b2b61209df14d99e81d2900fd79c6602f9472741e79365e.
- Freeze manifest SHA-256: c53def54dfbb88b49d035991bc363ce6c92e6760c70e6894418b86b947967658.
- Payload index SHA-256: 37ee26fca8a95fd047eeb53eb621089569346faa80fd646cf1a1cf619a09f7b9.
- Source patch SHA-256: 3fbcfea33b022683644c601a31a2e5ef950c0cf7e4e0c0e323be4764ae9b7e75.
- Source preimage SHA-256: 53cd937a7202990df883fa071c210d31573f11df83937c05880abb3cbc50e90b.
- Candidate Store SHA-256: 57c9f5b45a44a89d6152c5182aee2faddf8faec078efea5acb5dac081245c4ae.
- Independent QA manifest SHA-256: d9d0a008f9774c9284f7c1f6fbc57bc442809a40ef39adb2cef9a6d737ab8158.
- Independent QA receipt SHA-256: 1eb19dcedcc5cfe08af313578818e566685dfefb9620fa5d7c7b0b3ea2590e18.

The author package has 1,019 ZIP members; its freeze manifest covers 1,010 payloads. The independent copy rechecked every one of those 1,010 payload hashes and sizes against ZIP bytes, and ZIP CRC validation was clean. All 29 independent-QA manifest entries were also verified before and after copying.

## Independent focus and security traps

- Baseline: 6 tests, 3 expected placeholder-provider failures and 3 passes.
- Candidate: 6 passed, 0 failed, 0 skipped.
- The separate secret-placeholder probe recorded zero trap reads.
- The QA receipt records guarded source-root checks and no SDK/native/network calls from the tests.

The candidate only restores the old exception timing for empty/default Store shapes with provider futu, oanda, or vc: construction succeeds, while start() raises BtApiProviderNotImplementedError. It does not make those providers operational. Direct and nested CTP shapes continue to reject.

## Limits

This candidate does not clear the r2c 258-failure broad Store integration blocker, establish trusted Actor authority, authorize CTP operations, or change the main Store. Keep CTP writes and live execution closed.

## Evidence files

- [Author candidate ZIP](author/iteration41-store-account-actor-r2d-20260927.zip)
- [Independent QA receipt](qa/raw/receipt.md), [QA manifest](qa/qa-manifest.json)
- [Frozen author manifest](author/freeze-manifest.json), [exact patch](author/r2d.patch)
- [Source preimage](author/source/btapistore.preimage.py), [candidate source](author/source/btapistore.candidate.py)
- [Baseline JUnit](author/junit/baseline.xml), [candidate JUnit](author/junit/candidate.xml)
- [Author ZIP validation](author-zip-validation.json), [copy receipt](COPY-RECEIPT.json), [evidence manifest](evidence-manifest.json)
- Independent QA's full 29-file manifest set is under [qa/raw](qa/raw/), including logs, JUnit, secret trap output, node IDs, and diagnostic scripts.
