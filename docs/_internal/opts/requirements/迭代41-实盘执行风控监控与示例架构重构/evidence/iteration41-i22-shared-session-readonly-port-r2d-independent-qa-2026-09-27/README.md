# I22 shared-session read-only port r2d — local fake candidate archive

**Verdict: FAKE_READ_PORT_CONTRACT_ONLY / NO_WRITE / LIVE_NO_GO.**

This archive preserves the r2d author candidate ZIP and independent QA receipt for a local fake shared-session read-port contract. It does not prove a shared snapshot, account/session authority, Store runtime binding, production admission, or write authority.

## Frozen identity and independent checks

- Author ZIP SHA-256: 0160b69c0c91a046d2b47d5a55ddcfc2cdd6c979db5b0a023e69892d18f84a9b.
- Independent QA receipt SHA-256: c315d20a2a900bf6c4ce5eac83cec9a210bfaaf5edbd3481464766e9d6872924.
- Author patch SHA-256: 423111adfbfb47eb56e5303e917815c4f4594760c203d18930c44cf6b800094c.
- Embedded author manifest SHA-256: 3e4b386ec95f52bb27d268a857aa4d5223d28ba2daf1952e2b6caf95eaf9f199.
- Author archive contains 36 members: 35 manifest payloads plus manifest. CRC and all 35 payload hashes were independently rechecked.
- The independent audit receipt reports 3 of 200 original I22 nodeids migrated, 197 untouched; focused QA passed 7 tests with one existing pytest configuration warning. SDK/native imports, network, private-config and .env guards recorded zero attempts. QA reports the patch is additive to unmerged r2c and not directly applicable to current main.

## Scope and limits

This is a fake read-port contract only. It adds no accepted production read source and does not authorize any write route. The candidate depends on unmerged r2c; the r2c Store/Runtime broad integration still has 258 failures. No main code was changed. Keep NO_WRITE / LIVE_NO_GO.

## Preserved evidence

- [Author ZIP](author/r2d-author-final.zip), [author report](author/report.md), [author manifest](author/manifest.json)
- [Independent QA receipt](qa/final-independent-qa-receipt.md), [QA focused JUnit](qa/candidate-focused.junit.xml)
- [Exact patch](author/r2d-shared-session-readonly-port.patch), [author ZIP validation](author-zip-validation.json)
- [Independent patch-replay preimage](qa/replay-preimage), [replayed result](qa/replay-final)
- [Copy receipt](COPY-RECEIPT.json), [evidence manifest](evidence-manifest.json)
