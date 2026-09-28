# Independent QA: Store API route identity r2

Status: **PASS_NARROW_CONDITIONAL_WITH_DOCUMENTED_RESIDUAL**. The candidate blocks the two archived fake bypass shapes and the tested lazy/malformed route cases. It does **not** establish general Store/API identity closure: a custom injected API that hides route metadata in `__getattribute__` remains able to reach fake direct submit/cancel sinks. Treat this as a narrow compatibility-preserving check only; it makes no CTP authority, provider acceptance, or real-write claim.

## Frozen candidate identity

Packet: `D:\temp\ac41-63-store-api-identity-r2-20260927`

- Base/current Store preimage: `A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE`
- Candidate Store: `CE04ECBADDD3D3EA01C707313EA9B144650C47E322D0BDFC915000C0110094CA`
- Added route identity tests: `4AD2A69E10B918708D01113C0D2748A692167F96EF481C17A1ED31F57B73C45A`
- Patch: `AEF2BD46AA261576F936580502DF53C7FDC669856E3A7A59812CE43655493E59`
- Final packet manifest: `14CA1DDD9EA18CA5BB09B5B851470164042510BFD3C202FC287F265E4F9EC15A`
- Final packet checksum index: `AA0161F9299A21B1BB8B7CDCB292A7C228BEFBEB12A62BED027A7D4A94630F49` (13 entries, verified). Historical pre-correction manifest `7770B105335576518B1B8A0A4E63B2788B78A23ECCFE6ABC28D466B3CA627964` and sums `C5FD40182FA47C593887612E74D4D35CB2CADB6E491B990A48F453F4D5B039E1` are superseded; source, test, and patch bytes did not change.

A fresh independent minimal replay used the exact A039 preimage, `git -c core.autocrlf=false apply --check`, then apply, from the QA replay directory. It produced the exact CE04 Store and 4AD2 test hashes. The replay log is in `runs/exact-replay.log`.

## Independent fake-only checks

- **16/16 route identity contracts passed.** This includes Store/API mismatch denial before method lookup, full CTP suffix mutation detection, queue/sink guard placement, managed worker pre-dispatch checking, read-only query and matching non-CTP positive, malformed route container/conversion rejection, property/slot descriptor non-evaluation, and lazy direct API post-construction identity checks.
- **4/4 recovery matrix cases passed.** R4’s `recovery_exit` × `market_data_only` × managed-adapter combinations abort/disarm before identity error propagation and leave the queue/native path untouched. One existing unknown `performance` marker warning appeared.
- **4/4 independent inert probes passed.** The direct mismatched injected CTP fake is rejected before fake method lookup; the mutable BINANCE→CTP SDK snapshot fake is rejected before queue/API sink use; an ordinary injected no-route non-CTP API remains compatible; and the dynamic `__getattribute__` residual is reproduced as described below.
- The protected compatibility set attempted 462 cases: **443 passed, 1 skipped, 18 blocked by the required import tripwire**. This is not a 461-pass result. The 18 failures arose when optional-CTP tests explicitly called `optional_sdk("bt_api_ctp.ctp.client")`; the meta-path guard raised at `bt_api_ctp` before a package loader ran. No native module was loaded. Details and exact node IDs follow.
- `py_compile` and project-config Ruff checks passed for the candidate Store, candidate tests, and inert QA probe.
- The 479-file Python support overlay matched the current main tree byte-for-byte except for the target Store module.

### The 18 tripwire-blocked tests

Two were in R4’s `test_btapistore_iteration22.py`:

- `test_native_ctp_wrapper_rejects_market_before_req_order_insert`
- `test_native_ctp_wrapper_defaults_to_read_only_and_rejects_implicit_settlement_write`

Sixteen were in `tests/unit/stores/test_btapistore.py`:

- `test_create_ctp_wrapper_patches_missing_spi_callbacks`
- `test_ctp_wrapper_accepts_dict_snapshots_from_trader_client`
- `test_ctp_wrapper_positions_accept_float_string_ctp_codes`
- `test_ctp_wrapper_positions_use_contract_multiplier_and_exchange_fields`
- `test_ctp_wrapper_polls_order_insert_error_events_with_order_ref`
- `test_ctp_wrapper_order_submit_reject_status_overrides_unknown_order_status`
- `test_ctp_wrapper_trade_callback_accepts_float_string_ctp_codes`
- `test_ctp_wrapper_fetch_open_orders_converts_ctp_rows`
- `test_ctp_wrapper_fetch_open_orders_accepts_float_string_ctp_codes`
- `test_ctp_wrapper_submit_order_rejects_caller_forged_store_capability`
- `test_ctp_wrapper_submit_order_rejects_raw_only_client_before_api_access`
- `test_ctp_wrapper_cancel_rejects_without_raw_action_access[missing-capability]`
- `test_ctp_wrapper_cancel_rejects_without_raw_action_access[caller-forged-capability]`
- `test_ctp_wrapper_submit_order_rejects_non_integer_lots[0]`
- `test_ctp_wrapper_submit_order_rejects_non_integer_lots[1.5]`
- `test_ctp_wrapper_submit_order_rejects_non_integer_lots[bad]`

Each failure was caused by the guard intercepting that explicit optional SDK import. The blocked prefix was `bt_api_ctp`; tests did not use an import-skip helper. Without the tripwire those tests can import the installed CTP package, whose `_ctp_base.py` imports bundled `._ctp`. The author’s earlier unguarded 461/1 run is therefore contaminated for a no-native-import claim and is not used as QA evidence.

## Residual and compatibility boundary

The two historical audit cases are now blocked under the normal visible-metadata paths:

1. An injected API with `exchange_kwargs={"CTP___TEST": {}}` under `provider="binance"` and an empty Store snapshot fails before `submit_order`/`cancel_order` attribute lookup.
2. An injected SDK API whose snapshotted BINANCE route is changed to `CTP___TEST` fails before generic queueing or async sink lookup. In the fixture, `_is_ctp_write_provider()` alone remains false and `_is_ctp_session_provider()` becomes true; the identity guard catches the full-key drift.

The admitted residual is narrower but concrete: with an already-injected API, an empty Store snapshot, and a route exposed only by a custom `__getattribute__` override, static route lookup cannot see `exchange_kwargs`. The public direct `submit_order` and `cancel_order_ref` paths can then reach that API’s fake CTP sinks. The candidate manifest documents this compatibility boundary. It must not be described as closing all custom injected-API or same-process mutation paths.

## Main-tree apply/reversal incident

During QA, I accidentally ran one `git apply` while the shell working directory was the main repository. It applied exactly this patch: the Store became CE04 and the new 4AD2 test appeared. I immediately notified the parent. The parent reversed this exact patch. I then verified the main Store bytes were A039 and the new test path was absent; the parent separately confirmed `git diff --check`. The fresh independent replay above was rerun with the explicit QA `workdir`. No other main-tree path was targeted by my replay.

## Safety

All candidate tests and custom probes used local fakes. The guard replaced `bt_api_py` with an inert stub, blocked optional CTP/native module prefixes before loaders, and blocked all non-loopback sockets. The three focused runs recorded only the fake SDK stub and local loopback use; the compatibility run recorded the expected `bt_api_ctp` import blocks. No provider, native extension, private configuration, credential, external network, order, or cancel was used.



## Reusable guarded main-tree runner

The receipt includes `run_guarded_main_broad.py` for a post-integration main-tree compatibility run. It refuses to start unless this receipt's fake-only `sitecustomize` tripwire is active. It runs the requested Store/Runtime/queue/identity paths and deselects the 16 exact repository Store tests above that explicitly import `bt_api_ctp.ctp.client`. The two blocked R4 `test_native_ctp_wrapper_*` tests are in an external R4 temp file and are not part of that main-tree path list; add the R4 file only if needed, and keep those two excluded. Example PowerShell invocation:

```powershell
$qa = 'D:\temp\ac41-63-store-api-identity-r2-p3-independent-qa-20260927\receipt-r2-final'
$env:PYTHONPATH = "$qa\guard"
$env:ITER41_GUARD_LOG = "$qa\guard\main-broad.guard.json"
$env:ITER41_GUARDED_JUNIT = "$qa\guarded-main-broad.junit.xml"
python "$qa\run_guarded_main_broad.py"
```

This command was syntax-checked only; it was not run against main. It requires the route identity test to be integrated first and does not authorize loading or exercising a real SDK/native extension.
