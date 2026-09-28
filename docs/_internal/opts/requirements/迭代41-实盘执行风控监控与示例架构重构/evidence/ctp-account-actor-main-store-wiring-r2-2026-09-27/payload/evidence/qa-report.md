# BtApiStore AccountActorPort wiring candidate r2

## Verdict

`AUTHOR_CANDIDATE / NO_WRITE`; no main production source was edited. R2 carries forward the route-close and non-CTP compatibility slice, including the guarded adapter-only case. It closes the r1 actor-seam hole: `require_account_actor_before_local_client` rejects every CTP route as unavailable before inspecting a supplied actor implementation, local API injection, receipt, credentials, or SDK. The Store's CTP actor branch is unreachable through the normal constructor in this candidate.

The explicit CTP route therefore stays unavailable. The actor ABC/DTOs are offline contracts only; no caller-supplied class, context, fake ledger, or unkeyed digest is considered authority. Default runtime/CLI remains unchanged and no live route is registered.

## Source identity

- Exact main-base `BtApiStore` input: `input-sources/btapistore.py`, SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`.
- Frozen r2 Store: SHA-256 `a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8`.
- Frozen r2 actor gate/module: SHA-256 `2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3`.
- Frozen r2 candidate boundary tests: SHA-256 `04968d98ae476d4b9ec33d448be11d19e0ffc9adb79585f423b37b37b759154f`.
- Exact-base three-file patch: `r2-apply.patch`, SHA-256 `6e8575874cefeab4c693f6fedd5f3fc89dcec935005f5ad3a0d64f0e1284f90f`; replay `--check` and apply succeeded from the frozen input Store. With `core.autocrlf=false`, all three resulting target hashes match this candidate byte-for-byte. With `true`, Store bytes still match; two new LF files are checked out with CRLF, as expected.
- R1 parent manifest SHA-256: `ada5018781a7417206b88e3d934d59a67a77beab0c5e09e002a0e8f89a16ade4`; original r1 source/report are retained separately under `evidence/r1-lineage/` and the canonical evidence archive.

## Fail-closed behavior

- CTP classification still wins for direct CTP and nested `exchange_kwargs`/symbol route evidence. The shared legacy test helper has `provider="btapi"`, a fake `api`, and `exchange_kwargs: {"CTP": {}}`, so it is a CTP route.
- CTP routing reaches `require_account_actor_before_local_client` before provider resolution, env rewriting, SDK resolution/import, API attribute reads, credential conversion, and autostart. R2's actor gate unconditionally raises `external_account_actor_unavailable`; caller ABC/context/test-ledger fields do not grant an exception.
- Focused negative tests verify a typed `_QueuePort`, caller-selected context, fake ledger, autostart, API attribute trap, credential trap, provider resolver, environment override, and SDK resolver all remain unused.
- The ambiguous `btapi` adapter-only path still accepts only the narrow inert shape, clears the raw API reference, cannot start, revalidates before/after adapter invocation, and blocks the legacy callback before provider dispatch. Known explicit non-CTP API injection remains accepted only with matching route selectors.

## Tests and compatibility result

- Candidate route boundary plus copied live-dispatch guard: **14 passed**, one existing Quandl deprecation warning (`evidence/r2-candidate-focus.txt`, JUnit `evidence/r2-candidate-focus.junit.xml`).
- Candidate route boundary, managed-execution adapter, and live-dispatch guard: **21 passed**, one existing Quandl deprecation warning (`evidence/r2-focused-tests.txt`, JUnit `evidence/r2-focused-tests.junit.xml`).
- Ruff and `py_compile`: passed (`evidence/r2-ruff.txt`, `evidence/r2-pycompile.txt`).
- The exact old 30-test Store regression run remains **9 passed / 21 failed** in `evidence/r2-legacy-ctp-compatibility-delta.txt`, JUnit `evidence/r2-legacy-ctp-compatibility-delta.junit.xml`; all 21 are existing tests that construct the old local CTP SDK Store path and now stop at the intentional CTP actor-unavailable gate. Exact-base main run is 30/30 in the separate r1 migration audit (exact-base log SHA-256 `2990563f46564515e525768480213e650b33b67dbd9687f898304bf23b6499d1`). That audit classifies 8 failures as fail-closed assertions, 13 as external Actor migrations, and 0 as ordinary NON_CTP compatibility defects; its report SHA-256 is `c2133a92cbc83a0a4b4c9cd3f10cccc2f7e4f7287026fddabb7bd1f6065cbd00`, original ZIP SHA-256 is `4fa06de543221c3457088ee32a62ec81dbc25ab9359dbd85cd488e9a59891152`. These are a deliberate safety/policy compatibility delta, not a reason to reopen local CTP SDK dispatch.

## Acceptance limits

This is not a provider acceptance, real AccountActor, F14, G1, G5, or live test. A future production route requires a reviewed code-owned external actor service with authenticated identity, signed/current per-action authority and expiry, durable idempotency, account-wide fencing, current-state/UNKNOWN recovery, and a same-session read/callback contract. Until then, CTP remains unavailable.
