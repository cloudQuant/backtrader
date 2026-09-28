# Limitations and acceptance boundary

`LOCAL_FAKE_ONLY / NO AUTHORITY / NO_WRITE / LIVE_NO_GO`.

This isolated candidate adds a V21 Store fail-closed native-floor seam, its test-only synthetic-floor helper, and a source-bound fake contract test against frozen current G5 candidate sources. It does not modify any main-tree source or default inventory. No test calls CTP, a provider, native SDK, network, private config, credential source, SimNow, or production account.

The V21 floor snapshot/port remains a typed design contract only. The base Store has no issuer/verifier and raises before new ActionRef allocation; only a test-local Store instance is monkeypatched with fake evidence. Same-process methods, flags, dataclasses, local SQLite leases, and caller seeds are not external account authority.

Acceptance still requires all of the following:

1. An authenticated account authority that obtains the provider's native account-lifetime `MaxOrderActionRef`, binds it to a durable source digest and offline G5/V21 history reconciliation receipt, and holds an exclusive account-wide writer epoch across every process, host, Store generation, and legacy writer.
2. An explicit offline migration/cutover of real account history. Exact duplicate facts may be coalesced only after every immutable mapping field matches. Same-reference/different-action conflicts, missing maps, unreadable history, uncertain UNKNOWN actions, a counter below any source history, or a stale writer must preserve source rows and produce a sticky fence. No automatic max()+1 merge, renumber, deletion, reset, or inferred history is allowed.
3. Coordinated API/schema/package identity, durable migration/version barriers, and old-writer rejection. G5's current adapter pins package metadata version `0.2.0` and exact runtime types; that does not by itself prove the installed wheel is the frozen V21 r3 source.
4. A separately accepted service-owned final authorization/dispatch boundary. The current verifier documents that its final local check cannot hold an external fence atomically through the native provider call.
5. Independent cross-package QA, then real SimNow acceptance under a separately authorized operator workflow. This candidate provides no such evidence.

The archived G5/V21 dual-ledger collision applies to the older G5 SDK candidate identified in `CURRENT-G5-V21-INTERFACE.md` and the manifest. Current main G5 verifier source has no second ActionRef allocator. The source classification does not prove every external package/database in deployment is current or migrated, so the account remains fenced/unavailable until the external authority and offline inventory/cutover exist.
