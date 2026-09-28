# Store wiring r1 — independent QA (2026-09-27)

## Scope and disposition

Independent read-only review of the frozen author candidate at `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r1`. The frozen manifest SHA-256 is `ada5018781a7417206b88e3d934d59a67a77beab0c5e09e002a0e8f89a16ade4`; all 629 manifested files (9,932,064 bytes) matched in the isolated QA copy. No production source, main worktree, provider, credentials, SDK, network, or CTP route was used.

**Disposition: candidate-only / no-write plumbing; not accepted as production/account authority.** Exact-base patch replay reproduced the candidate's three changed outputs byte-for-byte. New route/actor focus passed 14/14, and its managed-execution + live guard focus passed 21/21. The exact same legacy Store set is 30/30 on the base but only 9/30 on r1; all 21 candidate failures are the old CTP-local-SDK constructor tests stopping at the intended fail-closed `external_account_actor_unavailable` gate. This is a real compatibility exclusion, not a test-runner failure.

## Independent probes

- An explicit known `OKX` constructor with injected `api_cls` remains compatible: the fake class was constructed and connected once; SDK/native modules stayed absent. Unknown / CTP constructors with property traps were rejected without reading API properties.
- A `BT_STORE_PROVIDER=ib_web_gateway` environment rewrite plus forwarding/CTP route, API `__getattr__` trap, credential `str`/truthiness traps, and autostart rejected before provider/environment override helpers, SDK resolution, credential access, or API access.
- Nested CTP and gateway/forwarding route cases are covered by the 14/21 focus. The adapter-only `btapi` route stays ambiguous; projection-only access remains inert. Its legacy dispatch closure rejects; mutation to CTP is rejected before adapter/API calls (reads=0, calls=0).
- Scope caveat: the injected adapter is caller-supplied code. Its own projection callback can execute arbitrary caller code; these probes show the candidate does not classify it as authenticated NON_CTP or dispatch the local CTP SDK through that closure. They do not sandbox an adapter or prove that arbitrary external side effects are impossible.
- The local actor replay receipt remains fake/local evidence. It does not provide cross-process replay authority, identity, provider acknowledgement, or admission.

## Test and patch evidence

| Check | Result |
|---|---:|
| Frozen payload verification | 629 / 629 files, 9,932,064 bytes |
| Exact-base canonical patch replay | all 3 outputs byte-exact |
| Candidate focused boundary/live guard | 14 passed, 1 existing Quandl deprecation warning |
| Candidate boundary + managed adapter + guard | 21 passed, 1 same warning |
| Legacy 30-test set, exact base | 30 passed |
| Same legacy set, candidate r1 | 9 passed, 21 failed at fail-closed local CTP SDK constructor boundary |
| Explicit OKX `api_cls` inert positive | PASS; fake constructor=1, connect=1 |
| Adapter-only cancel + route mutation traps | PASS; API reads=0, adapter calls=0 |

The warning is the existing `backtrader.feeds.quandl` deprecation. No Ruff result is represented as broader project cleanliness; the author reports Ruff success for its applicable candidate files.

## Reproduction boundary

The archived raw package retains the frozen author manifest/patch, candidate and base Store inputs, relevant actor/test sources, all independent command logs, and probe scripts. Candidate manifest verification and exact-base patch replay are separately recorded. The 21 compatibility failures are retained in full. Results apply only to this isolated local fake candidate and do not enable CTP, SDK, network, account, or default-route use.
