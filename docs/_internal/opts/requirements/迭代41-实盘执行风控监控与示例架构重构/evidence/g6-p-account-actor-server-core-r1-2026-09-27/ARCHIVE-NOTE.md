# G6-P Account Actor server core r5 archive

This archive preserves the frozen fake-only candidate bytes and their author verification records. It is evidence packaging, not an integration or acceptance decision.

- Frozen candidate manifest SHA-256: `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`
- Frozen candidate receipt SHA-256: `0132ff5b6097483a131fac26d2c8ee42d1d9de7b2178466a2f950a8c07d469c2`
- Candidate has 11 manifest-listed payloads, including source, tests, 50-test raw log, Ruff result, and compile result.
- Recorded author checks: 50 unit tests passed; Ruff clean; in-memory compilation clean.
- Independent QA is in progress. No independent pass is claimed here.

## G6-P status: BLOCKED

The candidate models a local SQLite fake actor only. It has no authenticated external service identity/key source, no cross-host writer exclusion, no manual-client fence, and no common provider snapshot version for CTP funds/orders/trades/positions. The local fake HMAC and SQLite transaction are not external authority. It is not connected to Store, SDK, MCP, credentials, network, provider, or any default route, and performs no provider dispatch.
