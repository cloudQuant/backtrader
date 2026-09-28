# AccountActorPort r6 independent QA

Disposition: `LOCAL_FAKE_CONTRACT_PASS_WITH_LIMITS`. Independent QA verified the r6 candidate manifest and source payloads, and replayed the guarded fake suite: 44 pytest and 44 unittest cases passed. The observed stable resolver mutation from IB_WEB to CTP is rejected before gateway/API factory calls; stale account/session/epoch and default no-dispatch checks remain local fake evidence.

The r5 stable-state constructor TOCTOU is fixed for the tested synchronous mutation sequence. Limits remain material: a resolver that transiently changes the route to CTP and restores the original canonical route before return is accepted; a gateway factory that mutates the route is called once before its post-callback check rejects and prevents publication. This does not prove callback confinement or undo side effects within injected callbacks.

There is no external authenticated Actor, durable cross-process authority, provider/runtime integration, real SDK/native module, private config, account, network, or order. G6-P/F14 and real-account acceptance remain closed. Raw author, isolated replay, and independent QA trees are preserved in the four raw ZIPs; `ARCHIVE-INDEX.json` records per-member hashes and sizes.
