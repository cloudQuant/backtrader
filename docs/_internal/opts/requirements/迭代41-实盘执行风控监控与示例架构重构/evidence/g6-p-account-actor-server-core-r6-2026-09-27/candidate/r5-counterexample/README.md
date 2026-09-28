# Preserved r5 stale-authorization counterexample

These are byte-preserving copies from the independent r5 QA directory `D:\temp\iteration41-g6-account-actor-server-core-r1-independent-qa-20260927`. The original QA directory and frozen r5 candidate were not changed.

- QA manifest SHA-256: `9dd201cff9325765a08169a251e3026519b024a9afa550e78259abbef07ca6e7`
- Probe script SHA-256: `c9c6123d79b28dc80c5152f8186dbe586973600acd427c8b7d21873ece6b7bf7`
- Captured stdout SHA-256: `8a611b05fb0d98f8103ae8262679a5cf46de823746af741d9a4dc1de7a16d1dc`
- Probe exit marker SHA-256: `c1e97067c5f479a44a6f57297a0a8f87a59d181c3c529910f8bf059094bc3abb`

The probe demonstrated: authorize at snapshot v77, publish v78, then repeat authorization returned the same v77 `AUTHORIZED_LOCAL_OUTBOX` object while the database current version was 78. r6 adds durable revocation and a one-shot final local claim gate. This historical output is retained unchanged as the r5 finding; it is not an r6 test result.

The full frozen r5 candidate, including its original manifest and receipt, is in `frozen-candidate/`. Its manifest SHA-256 remains `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`.
