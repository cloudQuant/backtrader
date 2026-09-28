# AccountActorPort r6 LOCAL_FAKE contract candidate

Date: 2026-09-27. Result: `LOCAL_FAKE_CONTRACT_PASS`; no production or external-actor acceptance is claimed.

## Frozen inputs

- The r4 `candidate-original/manifest.json` was reverified at SHA-256 `8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8`; its sidecar matched and all 9 `candidate-copy` payloads matched size and SHA-256.
- r5 base freeze manifest SHA-256: `73521009058983a0e34172c4ca0020c5f32f4cbf25da7b1fb554f4d68baaa4bd`; all 16 payloads matched. Its `base_manifest_sha256` binds the verified r4 manifest.
- r5 independent QA receipt SHA-256: `823190e5647a33a38ed2d9da615be8f5a39f5e5ed107b275a8ba0dbdfebf59fb`; verdict `PARTIAL / NEEDS_REVISION` for the constructor callback TOCTOU described there.
- Verification output is in `BASE-VERIFICATION.txt`. r5 and r4 frozen inputs were not modified.

## Change scope

Only the isolated r6 candidate under `D:\temp\iteration41-ctp-account-actor-port-r6-local-fake-20260927` changed. No main-tree file was modified; the main source tree was searched read-only for references to the test-only dispatch module. No private configuration, SDK/native module, network/provider, or account/order was accessed.

`StoreBoundaryHarness` now rechecks the stored route snapshot's route kind, canonical bytes, and SHA-256 digest immediately before and after each constructor callback that it invokes. The credential resolver is checked before it runs and again immediately after it returns. The gateway factory has a pre-call check, and its result is assigned to `self.api` only after a post-call check succeeds. Constructor selector facts used later are retained as immutable scalar/presence values rather than rereading the mutable descriptor dictionary after a callback. Exact route descriptor access still uses the instance dictionary and route snapshots accept only exact built-in nested values; no caller property or custom mapping method is invoked during recheck.

The CTP and unavailable-actor gate still runs before credentials, gateway/API factories, or local dispatch. Ordinary `StoreBoundaryHarness` has no `test_only_local_fake_dispatch` boolean; a test proves that passing it is rejected and does not call the fake actor. The only fake command path remains the explicit `store_boundary_harness_testonly.LocalFakeStoreBoundaryHarness` module. It is caller-controlled test plumbing, not external authority, production authorization, or a security gate. The separate test-only module is not imported by the main Store/runtime source tree.

## Verification

Environment: CPython 3.11.5. The unit/pytest runs loaded an evidence `sitecustomize.py` tripwire that rejects `bt_api_py`/`_ctp` imports and socket DNS/connect entry points; pytest plugin autoload and cache were disabled.

- `python -B -m unittest discover -s tests -v`: **44 passed**.
- `python -B -m pytest -p no:cacheprovider -q tests --junitxml=JUnit/r6-results.xml`: **44 passed**; JUnit retained.
- Ruff on the four Python source/test files: **All checks passed**.
- In-memory syntax compilation of four source/test files: **passed**.
- The r6 patch passed `git apply --check`, `git apply --ignore-whitespace`, `git diff --check`, and normalized replay comparison on an isolated temporary Git copy: **4/4 changed files matched**. Details are in `patch-application-check.txt`.

The adversarial additions verify: (1) resolver mutation from IB_WEB to CTP stops before gateway/API factory calls and an opaque API descriptor is never read; (2) a nested IB_WEB→MT5 mutation is rejected even though route kind remains NON_CTP; (3) replacing the route config with a custom mapping rejects without invoking its `items()` method; and (4) a gateway factory that mutates the route is rejected before its result is published or an API factory can run. The inherited equal-content mapping replacement test still passes, because semantic route bytes are unchanged.

The default harness test submits the same intent through repeated handles and a fresh child process; each rejects with `trusted_durable_remote_actor_unavailable` before fake actor dispatch (`0` actor calls). The separately imported local test-only fake can only exercise its process-local ledger and makes no reopen/cross-process uniqueness claim.

## Limits

These checks cover the synchronous callback sequence in this harness. They do not make arbitrary concurrent mutation of caller-owned route data atomic, and cannot undo effects performed inside a callback before its post-callback check. The API factory parameter is not invoked by this candidate. The fake ledger is memory-only. There is no authenticated remote Actor, trusted epoch/receipt, durable cross-host idempotency, provider snapshot/callback feed, Store/runtime integration, G6-P, F14, G7-S/G7-P, or live/write acceptance.
