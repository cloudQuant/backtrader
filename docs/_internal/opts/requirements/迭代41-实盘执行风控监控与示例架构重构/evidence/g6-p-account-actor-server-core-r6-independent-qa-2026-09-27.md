# G6-P Account Actor server core r6 — independent QA

Date: 2026-09-27. This evidence covers only the exact frozen r6 fake/local candidate. It does not include or certify any later r6 work-in-progress.

## Frozen input and independent runs

- Frozen source: `D:\temp\iteration41-g6-account-actor-server-core-freeze-20260927-r6`
- `manifest.json` SHA-256: `9bc5f75a23db4870123c89c9d8a160c1389495c8fe63a7adb2d4ea6c8b23ac61`
- Independent source copy: `D:\temp\iteration41-g6-account-actor-server-core-r6-independent-qa-20260927\candidate`
- All **42/42** frozen manifest payloads were checked for byte length and SHA-256; `account_actor_port` and `account_actor_server_core` imported from the independent copy.
- Python 3.11.5. Full command `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v`: **56 passed, 0 failed**. The seven-node lifecycle/process/migration focus also passed **7/7**.
- Raw run logs, corrected and failed probe attempts, exact source copy, and r5 historical evidence are in the raw packet. The r5 original adversarial output has SHA-256 `8a611b05fb0d98f8103ae8262679a5cf46de823746af741d9a4dc1de7a16d1dc` and records v77 authorization returned again after publishing v78.

The r6 suite exercises multi-process writer-claim contention, same-intent process replay, stale authorization rejection after cross-process reopen, process death after a claim, claim persistence after reopen, and migration of v1 authorization history. The v1 migration probe uses a v1-shaped fixture constructed from a test DB (drop the v2 lifecycle table and set user_version=1); it is not a production historical database.

## Independent r6 probe results

- **v77 → v78:** r6 closes the r5 replay. Re-authorizing the old intent after v78 raises `dispatch_authorization_stale`; command becomes `BLOCKED`, lifecycle `REVOKED`, and outbox stays at one row. Claiming the old authorization raises `dispatch_authorization_not_available`.
- **v1 history:** reopen migrates to schema v2; old authorized command becomes `BLOCKED`, lifecycle `REVOKED`; old claim is unavailable and replay is stale.
- **CLAIMED persistence:** snapshot publish and writer revoke fail with `dispatch_claim_in_flight`. After close/reopen the row remains `CLAIMED` and snapshot publication stays blocked. There is no completion, release, or crash recovery API, so this candidate permanently freezes the account after claim/process death.
- **Same-permission SQLite writer counterexample:** after a local claim, direct SQL changed `actor_dispatch_lifecycle` from `CLAIMED` to `AVAILABLE`. Reusing the same authorization then returned a second `DispatchClaimV1` for the same dispatch id. This is a local state-machine bypass by a process with DB file write access; no provider call occurred.
- **Fake HMAC counterexample:** the injected test signer signed a synthetic four-domain v77 snapshot with funds `999999999999999999.99` CNY; local authorization and `DispatchClaimV1` succeeded. The fake key is not an external account/provider trust root.
- The first probe run exited 1 because the QA runner left a direct SQLite query connection open, causing Windows `TemporaryDirectory` cleanup to fail (`WinError 32`). That harness failure is preserved in the packet. The corrected runner closes the connection with a context manager; the same assertions then passed with exit 0. This is a QA-script cleanup issue, not a candidate test failure.

## Conclusion and boundary

**G6-P remains BLOCKED.** r6 locally prevents ordinary API replay of stale v77 authorization and persists one-shot claim/freeze state across reopen, but same-principal database write access can reset that state; the injected HMAC can bless arbitrary synthetic snapshots; and there is no safe recovery after a claim. This is a local fake contract improvement, not an operational account actor, external snapshot authority, cross-host fence, or provider dispatcher.

No main production code was modified. No SDK, CTP native API, provider, credentials, account, or network was accessed.

## Archived artifacts

- [Raw independent QA packet](g6-p-account-actor-server-core-r6-independent-qa-2026-09-27.raw.zip), SHA-256 `85296192504F909BA8EB134202EF4CB0066A547F936C2C33953CCB6259081E72`.
- [Packet index](g6-p-account-actor-server-core-r6-independent-qa-2026-09-27.raw.zip.index.json), SHA-256 `8A256A428F36247990CFD5A48854D4096570BD0299DAF66D30EABD63E1F38B72`; 65 archived entries were rehashed against the index.
- [QA manifest](g6-p-account-actor-server-core-r6-independent-qa-2026-09-27.qa-manifest.json), SHA-256 `15EEBBF7871C8809D0E07141B34A2E440CA94A1DC700BEF14586534B32C97F2E`.
- Machine-readable summary: [g6-p-account-actor-server-core-r6-independent-qa-2026-09-27.json](g6-p-account-actor-server-core-r6-independent-qa-2026-09-27.json).
