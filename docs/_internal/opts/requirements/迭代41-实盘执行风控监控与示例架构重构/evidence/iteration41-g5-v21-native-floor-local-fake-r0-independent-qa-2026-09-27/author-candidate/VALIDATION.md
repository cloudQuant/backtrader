# Validation — V21 native ActionRef floor seam candidate r0

**Result:** local fake-only design candidate; not account authority; no write route enabled.

## Frozen input and patch replay

- Source snapshot: `D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927`.
- `SOURCE-MANIFEST.json` SHA-256: `b3a614d62b2a4cf1b0dbdfefee463015157dee38bf4c9c5119c64ef2d71d6d24`.
- The snapshot's `SOURCE-MANIFEST.json` matches the actual `src/bt_api_execution/store.py` bytes at `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`. Its legacy `manifest.json` instead records stale Store hash `75b01d7badbf67043c65082bee8dc27efbe4a309a739ff9f5cadd50f21ccde72`; that stale entry was not used as the preimage.
- `ACTIONREF-NATIVEFLOOR.patch` SHA-256: `d09d0c7f8376696907e0df37ec97a9d923450273b96f3557586389df4beba66f`.
- Fresh copy at `D:\temp\iteration41-g5-v21-actionref-nativefloor-replay-r1-20260927` accepted `git -c core.autocrlf=false apply --check` and patch apply. All five changed/replayed payload hashes match the candidate targets in `PREIMAGE-TARGET-MANIFEST.json` exactly.

## Tests and lint

From the isolated candidate root, with `PYTHONPATH=src`:

```powershell
python -m pytest -q tests --junitxml=artifacts\nativefloor-r0-junit.xml
```

Result: **271 passed, 2 skipped** in 16.71s. JUnit SHA-256: `9d5759b0c4682a6a9e5bdce20ed03c4c5df2ffa817d20c6b47583ddd962158dd`.

```powershell
python -m ruff check src\bt_api_execution\store.py tests\_fake_native_action_ref_floor.py tests\test_ctp_dispatch_commands.py tests\test_ctp_callback_source_bridge.py tests\test_ctp_callback_session_router.py
python -m ruff format --check tests\_fake_native_action_ref_floor.py
```

Both checks pass. The frozen pre-existing V21 files were not globally reformatted to avoid unrelated churn.

## Main-tree G5 drift — read only

The plan's G5 source SHA-256 is `8e7abdd2819f66b6ec3d5ff1d5a049fcbb91ae8e71327665ee925098d35f647d`. The current main-tree `backtrader_runtime/ctp_managed_action_authority.py` was observed at `7caed2a83447173ff93755c5561713c2e2f8f410d21ae78e4a07cccd3f681c66`; its current test was `6a6435bc8857016204c75e0a45e402b4ba2f1a89ac1d347284b65b6a2acf16ab`. Neither file was modified. Rebind and cross-generation review against current sources before any integration decision.

## Limits

Tests use synthetic local data only. No credentials, native SDK, provider, network, CTP session, SimNow, production account, or main-tree edits were used. Tests establish Store-local fake behavior, not native-floor truth, account-wide exclusion, external authentication, old-writer rejection, migration correctness, or safe live execution. Independent review may verify the candidate patch, but G5/V21 one-authority acceptance remains blocked on the external service and coordinated migration described in `LOCAL_FAKE_ONLY.md`.
