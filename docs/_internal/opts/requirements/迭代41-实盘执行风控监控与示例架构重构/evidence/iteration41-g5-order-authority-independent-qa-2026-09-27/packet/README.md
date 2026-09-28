# G5 OrderRef / ActionRef worker-handoff independent QA

**Disposition: G5 NOT ACCEPTED.** This review accepts only the local fake/offline contracts exercised below. It does not enable or accept a CTP write route.

## Frozen input integrity and provenance

The supplied candidate ZIP SHA-256 matched `92b3add8e73dc51e7552a1c439d2663ebb20053e755c4dcf9194cab39c53b4b3`. In an isolated copy, all 50 frozen input entries and all 91 final-output manifest entries matched their recorded sizes and SHA-256 values. The frozen-input manifest SHA-256 is `79bab5c0c0e136b722ef5f55c74f93aba2920f138a629b9ab8b4506d29003827`; the final-output manifest SHA-256 is `d9641aaf6757cf5aeff4a5246c42edb36b4bf6036268e05ff2134f41235d0e62`.

The candidate reports Backtrader source HEAD `ad2c142b9a8b42cede85886528c681abdfcb8096` and execution SDK source HEAD `2700cb5454ef4c3d1780eda28b6f33307a860998`. The candidate source/patch hashes are in `candidate-metadata/source-hashes.json`. Test module origins were asserted under the independent copy at `D:\temp\iteration41-g5-order-authority-independent-qa-20260927-r1\candidate`; no main-repository production file or default route was edited.

## Reproduction results

The exact candidate focus (identity authority, Store bridge, and worker handoff tests) passed **21/21**. The copied frozen SDK suite passed **57/57**. Ruff passed on the six changed source/test files. The two-file Backtrader patch passed `git apply --check` and `git apply` in a scratch tree; both resulting files matched candidate outputs after LF normalization.

Three independent fake-only probes passed:

1. Repeating the exact cancel stage reuses the same command and ActionRef, leaving one durable command, one action reservation, and one worker-handoff row.
2. A typed ActionRef dataclass with a substituted integer is rejected before command/handoff creation.
3. With the frozen Store class's missing target-readback API, cancel staging rejects before a command or handoff is created.

Existing candidate tests also cover cloned target-handle rejection, a mismatched exchange target, and UNKNOWN/no-replay after a possibly delivered send or crash after claim. Reopening the SQLite Store leaves UNKNOWN and does not call the sender again.

## Blocking target-projection source gap

The frozen SDK `inputs/sdk/src/bt_api_execution` contains no `CtpOrderTargetProjection`, `read_ctp_order_target_projection`, or target-projection producer API (see `evidence/target-producer-static-scan.txt`). The positive cancel tests define `_VerifiedTargetProjection` and `_target_projection` in the test module, then monkeypatch an in-memory `store.read_ctp_order_target_projection` backed by `store._g5_test_target_projections`. That fake reader uses exact handle identity and matching digest, so it tests the consumer-side validation seam only. It is neither a persisted target ledger nor a producer that verifies native query/session evidence. Without the fake readback method, the real frozen Store object fails closed before staging, as independently reproduced.

The worker also receives the projection as `Any` and checks its `to_payload`/fields plus exact Store readback; it does not import an SDK-owned nominal projection class. No native provider callback, account state, CTP request, credential, SDK native module, or network was used.

The two-file patch only changes the Backtrader worker protocol/builder source copy; it was not applied to the main working tree. The candidate SDK has no accepted release pin or actual provider integration. Caller-supplied seed values are not proof of native account watermarks. G5 remains `NO_WRITE / LIVE_NO_GO`.

## Test commands

Under CPython 3.11.5, with `PYTHONPATH` pointing only to the isolated candidate `implementation/sdk/src`, `implementation`, and (for the QA probe) `implementation/tests`; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONDONTWRITEBYTECODE=1`, `--noconftest -p no:cacheprovider`:

- Three candidate test files: 21 passed.
- Frozen `inputs/sdk/tests`: 57 passed.
- `qa-probes/test_worker_handoff_independent_probe.py`: 3 passed.

Raw command output, module origins, patch application, source scans, and the original candidate ZIP are retained in this packet. `packet-manifest.json` hashes each packet file.
