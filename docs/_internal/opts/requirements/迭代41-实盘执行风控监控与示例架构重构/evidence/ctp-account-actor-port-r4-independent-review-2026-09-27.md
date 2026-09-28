# AccountActorPort r4 independent QA

**Disposition: ACCEPTED_WITH_LIMITS_FOR_FAKE_LOCAL_CONTRACT_ONLY.** **G6-P: NOT ACCEPTED.** This review establishes neither external actor authority nor production/live integration.

The frozen candidate at D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4 matched manifest SHA-256 8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8. All 9/9 payload entries matched exact size and SHA-256, and the frozen directory contained no unlisted payload. Its original receipt SHA-256 is ee5fb7d0d3362a7f4d82bbf03d846c92ae542365b6207c173f799ec498293a4f.

An independent copy passed the original fake suite, 34/34. The expanded isolated suite passed 41/41. Probes confirmed stale epoch/wrong account reject before fake actor invocation; wrong operation and tampered digest receipts reject without native fallback; an injected API trap property is not read; and a shared in-process ledger rejects repeated intents.

Two reproduced gaps remain:

1. Route mutation: an OKX/NON_CTP route's shared config dict can be mutated to CTP after StoreBoundaryHarness construction. The cached route kind remains NON_CTP, and submit enters the legacy path.
2. Cross-process replay: a fresh process with a new FakeLocalActorReplayLedger successfully claims an intent already claimed by another process.

The command digest is unkeyed SHA-256 and can be recomputed after payload changes. The actor context and epoch are caller-supplied local values. The fake ledger is not durable idempotency; these checks do not authenticate an external actor or establish account/session authority.

## Archive hashes

- QA evidence manifest SHA-256: 37b5e5f078a5fa92140855fbfbd253731fb0cf8daa30ca1da298b70cb579b1c6.
- QA receipt SHA-256: 89760b36c62a7a30752af20887c111261f7f3ad1a05a9f0a95eb886627e30777.
- Full evidence directory index: ctp-account-actor-port-r4-independent-qa-2026-09-27/INDEX.md.
- Archive file checksums: ctp-account-actor-port-r4-independent-qa-2026-09-27/SHA256SUMS.txt.

No SDK, account, provider, credentials, network, native code, or default route was used. The frozen candidate and production source were not changed.
