# Archive note: G6-P Account Actor server core r6

This is an author candidate archive of the isolated fake-only r6 snapshot. It is not an accepted production path. Independent QA by mcp_isolation is in progress; no acceptance is claimed here.

Frozen inputs: r6 manifest SHA-256 9bc5f75a23db4870123c89c9d8a160c1389495c8fe63a7adb2d4ea6c8b23ac61; r6 receipt SHA-256 757f0f85d7d15c198f3663dc69936e1faeb079dc7fb8987a6a1e30dadc70051d. The manifest covers 42 payload files. It also preserves the r5 candidate, r5 stale-authorization counterexample, and original logs/receipts.

The recorded r6 author checks are 56 unittest cases passed, Ruff clean, and five Python files compiled in memory. The tests cover schema v1 to v2 migration with old rows revoked, stale authorization after snapshot advancement, final one-shot claim, and crash leaving the local account frozen.

**G6-P remains BLOCKED.** No provider dispatcher, native SDK, credentials, account, network, main Store, MCP, or default route is connected. A same-user SQLite writer can modify or replace the database; fake HMAC is not a trust root. There is no authenticated service identity, cross-host writer exclusion, manual-client fence, or provider-proven common CTP snapshot across funds/orders/trades/positions. A CLAIMED command has no safe completion/recovery path and remains frozen after crash.
