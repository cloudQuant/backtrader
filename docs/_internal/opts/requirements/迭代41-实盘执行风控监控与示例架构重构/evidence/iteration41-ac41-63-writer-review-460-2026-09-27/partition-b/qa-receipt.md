# Independent QA receipt — AC41-63 writer review partition B

## Result

**PASS AFTER AUTHOR CORRECTION — static evidence only.** The corrected partition maps cleanly to the frozen inventory and current source. The initial report contained a material overstatement about the 007 broker helper; the author corrected the report and affected candidate reasons, and the correction remains recorded below.

## Bound artifacts

- Corrected candidate packet: `D:\temp\ac41-63-writer-review-b-20260927-4149da78b9484fbba078f6446943ca8f\writer-candidates-121-240.json` — SHA-256 `D75D7826297871FFEB28F183B0F12699229348A269A3301454811F834DA4EDB8`
- Corrected author report: `D:\temp\ac41-63-writer-review-b-20260927-4149da78b9484fbba078f6446943ca8f\review-report.md` — SHA-256 `0677165870A04EE2EAC4CC9EE677C8B06362A43F6F0203C1B9461D0B727F6BE4`
- Source inventory: `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/live-execution-inventory-candidates.json` — actual and declared SHA-256 `03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456`

## Integrity checks

- The packet has 120 rows and maps exactly to inventory array indices 121–240, with IDs `WC-000121` through `WC-000240`.
- All 120 rows match the inventory on `path`, `line`, `call`, `method`, `class_name`, and `function_name`; no index, ID, or mapped-field mismatches were found.
- Each candidate source hash matches its current source file. All 60 paths in `source_hashes_by_path` also match the current files; no source hash mismatches were found.
- All 120 official dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`.
- Classification totals match the report: 47 certification calls, 17 framework order API calls, 6 custom-broker strategy calls, 2 guarded native/provider dispatch sinks, and 48 cleanup candidates.

## Independent static route checks

- `backtrader_runtime/ctp_simulation_execution.py:2119` is the session’s native submit call. Static source immediately around it shows admission, account lease, staged journal reservation, approval and writer-fence checks, and profile-scope revalidation. This confirms a guarded writer sink; it does not establish an accepted provider write.
- `backtrader_runtime/ctp_trader_client_port.py:1014-1036` dynamically resolves and invokes the injected trader method. The normal adapter path checks staged request and write authority. This remains an injected, same-process trust boundary.
- `backtrader_runtime/ctp_simnow_managed_runtime.py:197-208` delegates unknown attributes to `_port`; `CtpSimNowManagedRuntime.session` is a public dataclass field and the session stores its native port at `_native`. The report’s reflection limit is accurate: this is not a process boundary.
- The 007 registry entry at `backtrader_runtime/inventory.py:263-269` allows only the replay preset; the private 013_3 registration at lines 154-180 has a deny write policy and declares `live/managed_live_direct` unavailable. The registered 007 runner validates local simulation/replay and returns a no-action report (`examples/007_ctp/run_runtime.py:49-119`).
- The certification helpers in both Hongyuan and SimNow `common/runtime.py` unconditionally raise from `started_store` before constructing a Store. Direct case execution is routed through the legacy config-first fence before framework/provider imports. This supports the narrow claim that the retired cases are not part of the supported registered route.
- Strategy `self.buy`/`self.sell` calls remain broker dispatches. This does not create a supported registered live route or an account-wide fence for custom composition.

## Correction record

The initial author artifacts were JSON SHA-256 `BDBAB25532E0DD711CF5CE0AB9A5A8A83A5024463C3BA5A8B68EC0223B1B9773` and report SHA-256 `02D4FDEB7B3C7EB309B104919AE5EA046869F5AEA415577EFBF2E36BDDA4BCCE`. They stated that both `create_live_store` and `create_live_broker` fail closed. Independent source inspection found that claim false: `examples/007_ctp/ctp_example_support.py:699-705` fences `create_live_store`, while lines 707-718 return `BtApiBroker(store=store, **broker_kwargs)` from a caller-supplied store. This helper does not provide an account-wide writer fence.

The corrected packet and report now distinguish the two helpers and record the custom composition limit for WC-000187 through WC-000192. The corrected artifact hashes above were rechecked after the edits. This correction does not establish that an injected store can successfully write, does not make the composition a registered route, and does not alter any official disposition.

## Method and boundary

Review was read-only and static: file hashes, JSON parsing, text search, and source-line inspection. No project code or tests were imported or executed; no SDK, native/provider, network, credential, account, or private-config access occurred. No repository or shared documentation was edited. This receipt records source and inventory consistency plus report accuracy only; it is not live-trading or writer-closure acceptance.