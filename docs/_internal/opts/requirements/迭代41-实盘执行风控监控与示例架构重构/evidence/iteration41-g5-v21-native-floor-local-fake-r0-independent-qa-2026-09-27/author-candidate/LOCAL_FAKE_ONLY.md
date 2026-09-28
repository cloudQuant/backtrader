# V21 native ActionRef floor seam — local fake-only candidate

**Disposition:** `LOCAL_FAKE_ONLY / DESIGN CANDIDATE / NO AUTHORITY / NO WRITE / LIVE_NO_GO`.

This isolated V21 candidate closes one local allocator gap for contract testing. It is not an account-authority implementation and is not registered in a runtime, API, CLI, Store factory, or production composition root.

## Behavior under test

`SqliteExecutionStore.stage_ctp_dispatch_command(..., operation="CANCEL")` now asks the Store's protected `_verified_ctp_native_action_ref_floor` seam for a typed, fresh, account-bound floor before allocating. The base Store raises `ContractValidationError` because no trusted external floor authority is available. An ordinary Store constructor has no seed, floor, verifier, or source injection parameter. The new `CtpNativeActionRefFloorSource` protocol and `CtpNativeActionRefFloorSnapshot` are unregistered contract candidates; the snapshot is explicitly not self-authenticating.

Only `tests/_fake_native_action_ref_floor.py` installs a synthetic floor, by monkeypatching a particular test Store instance. It lives under the isolated test tree and is not imported by the package or default application route. This fake is not native evidence, a verified floor, an account writer epoch, or authority to dispatch. Python same-process monkeypatching is not a security boundary and the Store seam must not be represented as one.

The existing V21 durable account counter/allocation transaction remains the allocator. With no prior counter or allocation history, a fake floor of 37 yields reference 38; exact command replay returns the same command/reference, and a different day/scope on that same account advances to 39. If an existing counter is below the supplied floor, or counter/allocation history is inconsistent, staging rejects and requires offline reconciliation. It does not silently rewrite a counter. The tests also prove the default missing-floor failure leaves allocation/counter/command state unchanged.

## External authority still required

A deployable account-wide service must hold the exclusive writer fence across all processes, hosts, package generations, and legacy writers that can reach the account. Under that fence it must obtain/authenticate the provider's native account-lifetime `MaxOrderActionRef` floor, reconcile the complete G5 and V21 histories (including ambiguous/UNKNOWN and unmapped legacy actions), preserve source digests and a durable reconciliation receipt, and issue a verifiable, account- and epoch-bound, short-lived proof. The consuming Store needs an authenticated verifier/transport and a durable migration/version barrier tied to that service. A local database lease, caller integer/seed, same-process boolean, typed Python object, or per-process account actor is insufficient.

The G5 and V21 histories/schema generations still have separate allocators. This patch does not modify G5, migrate or merge history, add a canonical cross-generation schema, fence old G5/V21 databases or writers, create an authenticated service, or resolve a historical collision. The earlier plan's G5 source hash is stale; see the manifest and validation record for the current read-only main-tree hash. No automatic migration is part of this candidate.

## Acceptance boundary

This artifact is suitable for isolated design review and independent QA of the fail-closed V21 seam and fake cases only. It cannot be integrated as authority, enable a runner, submit or cancel orders, establish SimNow or production readiness, or satisfy G5/V21 one-authority acceptance. Keep the normal runtime unavailable/no-write/live-no-go until the external account authority, coordinated offline history reconciliation, old-writer fences, schema/API cutover, and independent end-to-end acceptance exist.
