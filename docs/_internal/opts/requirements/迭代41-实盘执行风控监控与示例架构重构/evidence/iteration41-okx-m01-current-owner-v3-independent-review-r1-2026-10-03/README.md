# Independent OKX M01 V3 source review

**Decision:** GO_SOURCE_FAKE_ONLY

This review covers the frozen public source bundle and its fake-only test. The bundle contains 19 runtime source files and one focused test. Its 20 archive members matched the indexed hashes and the active checkout bytes. The focused test passed **10 tests** under the dedicated source-QA interpreter, with one existing pytest configuration warning.

The V3 fixed M01 entry checks protected source/deployment admission before asking the C01 proof factory to acquire current-read evidence. The proof and account-configuration read are tied to the same invocation. The issuer verifies that login, connection, and readiness belong to the same provider session; binds typed actions and observations to the invocation evidence window; replays the exact worker journal; and holds source/deployment/environment/proof leases through worker close, audit readback, and final result construction. Uncertain close or release is fail-closed.

The public source bundle does not contain the protected deployment/source map, so this verdict does not establish deployment admission, actual account readiness, or live M01 acceptance. No credential, private file, SDK/native module, provider, or network operation was read or run for this review.

## Accepted worker boundary

The standalone fixed read-only worker can be invoked by an internal trusted diagnostic path with a caller-supplied credential packet. It does not load the root .env or select the private account profile, and it cannot mint the V3 sealed CaseResult. The protected gate applies to the fixed M01 case CLI/issuer and its current .env resolution. This review does not claim blanket isolation for every Python process that already holds credentials.

## Frozen candidate

- ZIP SHA-256: 02f9605429a5e230dfe9f252a08f8d48af311f0b3833891676415bab8551cdde
- Index SHA-256: 42b55e501ed13f6e33be18fc15aca74ee386ef57401f871ee487fb624b525aae
- Source-map SHA-256: de8b619925353364b950b2f8beb97ccb5c7d5862868ff9665d081ba8afb83cdd
- Canonical source-pins SHA-256: 78e84aee4ba39d02711bc6bd9f95f49871a81f20422af764e3d36a7dbdc96e78
- Focused test SHA-256: c8137ceaa0683dec7a7a96468f3de28875acd427046f33a4987e97d85ecc536d

See review.json for the machine-readable scope, checks, and limitations. review-index.json pins this report bundle and the reviewed candidate.
