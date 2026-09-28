# AccountActorPort r2 independent QA — REJECTED for integration

Date: 2026-09-27

## Decision

**Reject the r2 source candidate for integration.** Its fake-only contract has reproducible local route-classification bypasses and lacks actor account/session/epoch binding and replay protection. The main Backtrader Store has no AccountActorPort gate; its no-adapter submit/cancel paths remain statically reachable through legacy dispatch. This review did not execute a main Store order or cancel.

**G6-P and LIVE_NO_GO remain unchanged.** This packet establishes no production actor, authenticated identity, cross-host/account fence, common snapshot, CTP SDK/provider call, network access, protected-config access, or live acceptance.

## Evidence

- Frozen candidate: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r2`; input manifest SHA-256 `ac45026c48d247b66f0da18e59211c7bd2e610cdaa5e7bd605a89cf1625f7a76`.
- Independent copy’s 9 source/evidence entries matched the frozen manifest with zero mismatches.
- Isolated command: `python -m unittest discover -s tests -v`; **15 passed**, exit 0. Environment and captured output are in the raw packet.
- Adversarial fake probe exited 0 and reproduced: unknown `custom_ctp_alias` + `api_cls` classified NON_CTP then used the fake local fallback; nested `symbol_routes` CTP was missed; injected `btapi` API `exchange_kwargs` property executed before missing-actor rejection; stale actor epoch and mismatched actor account were accepted; duplicate intent was accepted twice. Wrong command id and absent actor rejected as expected.
- Main source was read-only inspected. `btapistore.py` SHA-256 `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`; F14 admission protocol SHA-256 `7BA54C6C658EF269F1049FAB1A6D2C14D85D0A7B777767479081CE3F53B7016B`. Main static findings and line anchors are in `source-review.txt` inside the archive.

## Interpretation limits

The unknown-provider candidate fallback is a reproduced **candidate harness** behavior. Main source has a custom-provider/API-class legacy path by static inspection, but this QA did not instantiate the main Store or call a provider. The nested route issue is candidate-only; an actual main Store send through such a nested route was not demonstrated. See the machine record and raw packet for exact inputs and outputs.

Raw evidence archive: `ctp-account-actor-port-r2-independent-rejection-2026-09-27.raw.zip`, SHA-256 `C168377915A48E08DC30C0B93901EF5979AC051E235B26CAB041E535365CE397`.

