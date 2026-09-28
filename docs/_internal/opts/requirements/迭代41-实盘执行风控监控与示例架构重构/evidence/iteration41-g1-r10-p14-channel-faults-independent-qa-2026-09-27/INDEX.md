# G1 R10-r1 P14/channel-close independent Windows QA archive

**Disposition: FEASIBILITY_DIAGNOSTIC_ONLY; G1 CLOSED.** Local Win32 failure returns and valid disposable Job cleanup were reproduced. Wrapper-delay trials ended before target API entry and do not demonstrate a kernel/API hang or production custodian recovery.

- [Independent report](packet/REPORT.md)
- [Frozen input and run evidence](packet/): source snapshot, original ZIP, independent source copy, raw stdout/stderr, exit codes, JSON, wrapper markers, and verification scripts.
- [Independent QA packet ZIP](packet/independent-qa.raw.zip)
- [Packet manifest](packet/packet-manifest.json)
- [Copy verification](copy-verification.json), [copy receipt](copy-receipt.json), and [archive manifest](archive-manifest.json)

Verified frozen `manifest.json` SHA-256: `8eb904c372046b233c474dc5c9825ebbe82c95cfb3ece4277aa6eaffdc4994c5`; frozen `evidence.zip` SHA-256: `880fb7b05152de0e9099b0d236b2f602178470d80bcf409d79e8ecb14f57fddd`. The independent Win32 probe exited 0 on CPython 3.11.5. It observed invalid/restricted handle error returns, valid Job active count `1 → 0`, and duplicate close error 6. Its ~100 ms sleeps were user-mode pre-call delays; `API_REACHED=false` and `API_RETURNED=false` for both, while the separate outer test Job terminated each child and reached zero.

No CTP/native SDK, provider, private config, credentials, account, network, or default route was used. A true kernel API hang, production P14 propagation/recovery, and whole-command hard deadline remain unproved. G1 stays closed.