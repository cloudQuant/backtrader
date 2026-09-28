# G6-P Account Actor server core r6 archive

Status: **author candidate; G6-P BLOCKED; independent QA pending**.

- Candidate payloads: 42, verified against frozen r6 manifest.
- Frozen r6 manifest SHA-256: 9bc5f75a23db4870123c89c9d8a160c1389495c8fe63a7adb2d4ea6c8b23ac61.
- Frozen r6 receipt SHA-256: 757f0f85d7d15c198f3663dc69936e1faeb079dc7fb8987a6a1e30dadc70051d.
- Raw ZIP: g6-p-account-actor-server-core-r6-raw.zip
- Raw ZIP SHA-256: 18522d8a67cbb5a812da2f5a2541a03884386a9c3baf4595cc22e1d9dab77413.
- Archive index SHA-256: 72a1218532848633ab9e1b2630931d613e3747223e76df142f040bc72a16d9c7.
- Candidate author checks: 56 passed, 0 failed; Ruff clean; 5 Python files compiled in memory.

The ZIP contains the exact frozen r6 payloads and metadata plus ARCHIVE-NOTE.md. It preserves the complete r5 candidate and stale-authorization counterexample under candidate/r5-counterexample/. archive-index.json lists and hashes every ZIP member.

G6-P remains blocked: fake local SQLite/HMAC does not provide authenticated service identity or cross-host exclusion; same-user database mutation/replacement remains possible; no provider/native/credentials/network/default route is connected; common provider snapshot and safe CLAIMED recovery are absent.
