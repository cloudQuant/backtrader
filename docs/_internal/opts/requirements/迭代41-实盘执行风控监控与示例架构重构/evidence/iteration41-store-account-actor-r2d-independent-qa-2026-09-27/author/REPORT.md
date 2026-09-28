# Store AccountActor r2d narrow compatibility candidate

## Scope

This isolated patch restores the legacy placeholder-provider lifecycle for exactly the empty/default `BtApiStore(provider=...)` constructor shape when the provider is one of `futu`, `oanda`, or `vc` and the route classifier returns `UNSUPPORTED`. Construction records inert Store state without resolving a client or importing an SDK. `start()` revalidates the sealed route and raises `BtApiProviderNotImplementedError`.

The branch is deliberately narrow: non-default arguments, explicit backends, API/client inputs, route metadata, actor/adapter inputs, or any environment route evidence do not match it. Explicit direct CTP and nested/forwarding CTP continue to reject before route environment reads, caller-object traversal, SDK resolution, or local dispatch. The external account actor unavailable gate remains in place; this patch does not authorize local CTP clients or external actor authority.

## Exact delta and preimage

- Changed source: `backtrader/stores/btapistore.py` only; 72 added lines, no deleted lines.
- Exact preimage: `preimage/btapistore.py`, SHA-256 `53cd937a7202990df883fa071c210d31573f11df83937c05880abb3cbc50e90b` (byte-identical to the r2c candidate source at the recorded path).
- Candidate source: `candidate/backtrader/stores/btapistore.py`, SHA-256 `57c9f5b45a44a89d6152c5182aee2faddf8faec078efea5acb5dac081245c4ae`.
- Patch: `patch/r2d.patch`; it applies cleanly to the exact preimage with `git apply --check` and reproduces the candidate source hash.
- The two selected test source files are unchanged from r2c. Static comparison excludes only generated `.ruff_cache` and Python bytecode caches.

## Focused results

The same six pytest nodes were run against isolated baseline and candidate copies with Python 3.11.5 / pytest 8.0.0, plugin autoload disabled, and an import/socket guard in `guard/sitecustomize.py`.

- Baseline: 3 failed, 3 passed. Only the three placeholder-provider nodes fail, each during construction with generic `BtApiStoreError: store provider unsupported`.
- Candidate: 6 passed. The three placeholder-provider nodes now construct and reject from `start()` with the legacy provider-not-implemented exception. The other passing nodes cover external actor unavailable with secret traps, explicit direct CTP rejecting before route-environment/caller-object reads, and nested CTP rejecting before SDK or forwarding construction.
- JUnit XML and console logs: `JUnit/baseline.xml`, `JUnit/candidate.xml`, `evidence/baseline.log`, and `evidence/candidate.log`.
- Ruff diagnostic comparison on the whole changed source file: 591 diagnostics before and after; no new or removed `(code, message)` groups. The file has pre-existing diagnostics; this is not a clean-lint claim.

The test guard blocks imports of `bt_api_py` and `_ctp`, plus socket DNS/connect calls. These are offline fake tests only. No real SDK, native runtime, network, private configuration, account, order, or production route was used.

## Limits

This is a local safety/compatibility increment only. It is not external Actor authority, a production security boundary, a CTP acceptance result, or evidence that broader r2c integration is ready to merge. The r2c frozen candidate and main working tree were not modified.

## Focused test nodes

```text
tests/unit/stores/test_btapistore.py::test_placeholder_provider_raises[futu]
tests/unit/stores/test_btapistore.py::test_placeholder_provider_raises[oanda]
tests/unit/stores/test_btapistore.py::test_placeholder_provider_raises[vc]
tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py::test_ctp_forwarding_env_rewrite_and_secret_traps_reject_before_any_local_boundary
tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py::test_explicit_ctp_rejects_before_route_environment_or_caller_object_reads[direct_ctp]
tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py::test_nested_ctp_routes_reject_before_sdk_or_forwarding_construction
```
