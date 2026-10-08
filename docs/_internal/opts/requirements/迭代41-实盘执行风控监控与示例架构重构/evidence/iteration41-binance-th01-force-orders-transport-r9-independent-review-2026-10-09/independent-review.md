# Binance TH01 forceOrders transport R9 independent review

**Verdict: GO_COMPONENT_SOURCE_FAKE_ONLY.** The frozen R9 extension, test, Root wrapper, owner, candidate, and launcher pins matched before review and again after the checks. R9 fixes the R8 reader-verifier arity mismatch and adds a production-loaded, cold-wrapper fake that exercises session construction, the live binding callback, and postflight before stopping ahead of any forceOrders request or worker.

## Frozen inputs

- Extension: `examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r9.py` — 73,002 bytes, SHA-256 `c937a07671a6df7991fb29e131d895c0eca21644d28140542fab7c8b0db1b944`; canonical self-pin `baa9a92fe71258528291a4748af0b811cdc0cece40f3ac80859c6a54d1801f63`.
- Test: `tests/unit/live_certification/test_binance_th01_force_orders_transport_r9.py` — 40,454 bytes, SHA-256 `90a2e9acd17ddcf2996ffb99d300c706d415afab420a940237e441f70375183f`.
- Root wrapper dependency: `scripts/iteration41_binance_th01_root_account_window_call_r1.py` — 132,886 bytes, SHA-256 `ba0360ecc5ed99b37196e3d077e25a78cd771facec8e224ab1371635cf9be021`.
- Owner R1 dependency: `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` — 92,566 bytes, SHA-256 `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f`.
- Account-window candidate R2 dependency: `examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py` — 62,664 bytes, SHA-256 `4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63`.
- R2 launcher dependency: `scripts/iteration41_binance_th01_account_window_candidate_r2.py` — 11,391 bytes, SHA-256 `698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6`.

The historical R8 extension/test remain byte-identical to their HOLD pins; R9 did not overwrite them.

## Checks

The designated QA venv ran the prescribed source-fake command with plugin autoload disabled and `-p no:asyncio`: **20 passed, exit 0**, with one existing `PytestConfigWarning` for `asyncio_default_fixture_loop_scope`. `py_compile` passed for the extension, test, and Root wrapper. Host Black check passed with `--check --line-length 100 --target-version py311` (the installed formatter does not support the repository's py312 target). Host Ruff passed.

The new test loads the exact frozen wrapper and owner source, installs R9, creates only fake credential/writer leaves, and invokes `run_root_cold_account_window`. The actual wrapper session setup and three-argument reader verifier run; the sourcefake collector performs the live extension binding check and then raises the fixed `sourcefake_stop`. The wrapper returns `BLOCKED_ACCOUNT_SNAPSHOT` with preflight and postflight complete, `force_orders_bound=true`, request count zero, and worker lifecycle incomplete. This demonstrates source-level wrapper compatibility and orderly fake failure reporting. It is not an actual GET or worker-lifecycle result.

Static review confirms the installed callback signature now accepts `(candidate, auth, capability)` and checks `candidate is owner`, matching the wrapper's three-argument calls. The route remains fixed to `/fapi/v1/forceOrders`, with only `startTime`, `endTime`, and `limit=100`; symbol and `autoCloseType` are omitted. Intervals remain strictly under seven days and the owner account-window bound. Root's retained attempt ledger records reservations and terminal failures, and the existing wrapper bisects 100-row saturation while failing closed at one millisecond. The extension delegates through the pinned base signed-GET dispatcher and worker. The install publisher keeps its failure latch and rolls back touched owner keys; sourcefake coverage exercises failed publication. Callback, code/global, route, reader, owner, and Root-ledger bindings remain pinned in source and fake tests. The public failures and `FixedForceOrdersGetV1` repr are bounded and omit credential values.

## Evidence limits

This review used public source and fake fixtures only. No `.env`, ignored config, private capture, external binary, SDK/native/WinAPI, real process/Pipe, network, provider, or account operation was used. It does not establish actual transport behavior, process/Pipe cleanup, account completeness, full TH01 acceptance, or a formal TH01 PASS. Adapter-level integration remains outside this review. No candidate source was changed, staged, or committed; only this public review packet was added.
