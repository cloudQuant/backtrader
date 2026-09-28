# G6-P Account Actor server core r5 evidence archive

- ZIP: `g6-p-account-actor-server-core-r5.zip`
- ZIP SHA-256: `92d60f7d70a40fdf2485d17523d14a70e0129c9ebe747c1c2703dbf1130a2410`
- Index JSON SHA-256: `d26b8dccebe78705a16bc76f8d7a5000bff0a2f6f871fcf1d8515e2f8eeeffab`
- Frozen candidate manifest SHA-256: `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`
- Frozen candidate receipt SHA-256: `0132ff5b6097483a131fac26d2c8ee42d1d9de7b2178466a2f950a8c07d469c2`
- Frozen candidate payloads: 11 (all manifest entries validated byte-for-byte)
- ZIP members: 16 (candidate payloads, original manifest/receipt and hash sidecars, plus archive note)
- Recorded verification: 50 unit tests passed; Ruff clean; compile clean. Raw output is included in `candidate/test-results.txt`, `candidate/ruff-results.txt`, and `candidate/compile-results.txt`.
- Independent QA: pending; this archive does not claim independent acceptance.

## Status

**G6-P remains BLOCKED.** This is a fake/local SQLite actor model, not an externally authenticated account actor or provider path. It does not prove cross-host writer fencing, exclude human/manual clients, authenticate a production service/key source, or provide a common CTP snapshot version across funds, orders, trades, and positions. No Store/SDK/MCP/default route, credentials, network, provider, native code, or dispatch is connected.

The ZIP member hashes and exact candidate metadata are in `archive-index.json`. The frozen r5 source directory was not modified.
