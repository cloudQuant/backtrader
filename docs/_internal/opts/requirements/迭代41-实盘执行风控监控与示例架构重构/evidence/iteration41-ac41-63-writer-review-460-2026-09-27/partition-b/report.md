# AC41-63 static writer review — partition B

**Scope:** `writer_candidates` array indices 121–240 inclusive (120 candidates) from `live-execution-inventory-candidates.json`.

**Input inventory SHA-256:** `03658257d97e31c2d8f8bfd48685441533552b32674f5d63810141e3038ab456`.

The accompanying `writer-candidates-121-240.json` gives each row a stable review ID (`WC-000121` through `WC-000240`), candidate line, current candidate-source SHA-256, classification, route reachability, and reason. All official dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`. This is static review evidence only; no import, execution, SDK/native/provider access, network, credentials, private config, account, or execution occurred. No repository or shared documentation was edited.

## Route findings

The slice contains 120 rows: 47 certification-case order/cancel calls, 23 other strategy order API calls (17 ordinary examples and 6 CTP strategy calls), 2 managed CTP order-dispatch sinks, and 48 resource, journal, descriptor, or loader cleanup candidates. The 47 certification calls are in retired Hongyuan/SimNow cases. Their runner fences direct entry, and each case’s shared `started_store` now unconditionally raises `legacy_direct_execution_not_supported` before store construction. The registered `007_ctp` runtime accepts only `simulation/replay` and returns a no-action report. These case calls are therefore not reachable through the supported registered route.

The two genuine native sinks are explicitly composed paths, not the default runtime route:

- `backtrader_runtime/ctp_simulation_execution.py:2119` — `CtpSimulationExecutionSession.submit_order` invokes `_native.submit_order_insert`. The call follows execution admission, a local account-flow lease, staged order binding, approval checks, active writer-fence checks, and profile-scope revalidation. The module says the CTP execution path is not registered by the default runtime inventory. The current registry’s 007 and 010 CTP migrations are replay-only; 013_3’s private profile declares `live/managed_live_direct` unavailable and has a deny write policy. This is a real writer reachable only when a caller explicitly assembles the CTP execution authorities and native session. It is not accepted live authority.
- `backtrader_runtime/ctp_trader_client_port.py:1014-1036` — the CTP adapter dynamically obtains and invokes the trader’s `submit_order_insert` method. The adapter checks typed/staged request state, approval and credential binding, durable runtime order mapping, and write capability before dispatch. The provider client is supplied through the managed composition dependencies, so this method remains within a same-process trusted composition boundary rather than being isolated by the registered CLI.

The strategy candidates at `examples/007_ctp/ctp_example_support.py:483` and `examples/007_ctp/ctp_sa_dual_ma_strategy.py:196-226` are ordinary framework `buy`/`sell` dispatches. The retired direct CTP runners are fenced, and `create_live_store` raises before constructing a Store; however, `create_live_broker(store, config)` at lines 707-718 is not fenced and returns `BtApiBroker(store=store, **broker_kwargs)` for a caller-supplied store. The 007 registered runtime remains replay/no-action and does not load these strategies. In `ConfigurableFuturesStrategyBase`, `enable_trading` gates the strategy call, while the broker module check only changes order metadata. An imported/custom caller can supply a store to `create_live_broker` and then bind that broker to a reusable strategy; neither the Strategy nor this helper enforces an account-wide writer fence. This is a custom composition gap, not evidence of a supported registered live route or an accepted write.

The ordinary examples (`001`, `004`–`006`) similarly call Backtrader Strategy APIs; their checked-in examples use local/demo compositions and are not registered live routes. If embedded with a custom broker, downstream behavior is chosen by that caller. The archive/text, SQLite, ACL, runtime-directory, file-descriptor, and module-loader closes are local cleanup or lifecycle work, not order writes.

## Highest-priority dynamic/reflection gaps

1. `backtrader_runtime/ctp_simnow_managed_runtime.py:197-208` defines `_OwnedNativePort.__getattr__` as unrestricted delegation to the wrapped port. The returned managed runtime also exposes its `session` field, and Python private attributes are convention-only. A same-process consumer can inspect `runtime.session._native` and the wrapper’s `_port`. This is not a process boundary. The delegated object is still subject to its own adapter checks on its typed methods, but static review does not prove that private/native internals cannot be used independently.
2. `backtrader_runtime/ctp_trader_client_port.py:1014` resolves a provider write method with `getattr` and invokes the supplied trader object. The authorization checks are present on the normal adapter method path; static route analysis does not establish the identity or safety of arbitrary injected factories or monkeypatched objects.
3. Strategy calls such as `self.buy`, `self.sell`, `self.close`, and `self.broker.batch_cancel` rely on the broker bound during composition. They are not an account-wide authorization boundary. In 007, `create_live_store` is fenced, but `create_live_broker(store, config)` remains callable and wraps a caller-supplied store in `BtApiBroker`. A custom/imported caller can therefore compose the historical strategy and this broker helper outside the registered no-action runtime; downstream Store guards and the caller-provided store determine whether any write can proceed.

These are trust-boundary and writer-closure gaps to keep visible in review. They do not establish a successful bypass of the current CTP SDK gates, and they do not establish any accepted CTP/SimNow/native behavior.

## Evidence anchors inspected

- `backtrader_runtime/inventory.py:154-181,263-278,332-358` — default registrations; CTP private profile is readonly/deny and live unavailable; 007/010 migration profiles are replay-only.
- `examples/007_ctp/run_runtime.py:49-119` and `examples/007_ctp/README.md` — 007 requires local `simulation/replay`, reports zero network/order writes, and labels the report as no-action/config-gate evidence.
- `examples/007_ctp/ctp_example_support.py:448-494,631-718` — strategy order calls remain generic broker dispatch; credential, SimNow, and Store helpers raise the legacy-entrypoint error, while `create_live_broker` returns `BtApiBroker` from a caller-supplied store.
- `examples/007_ctp/live_certification/simnow_penetration/common/runtime.py:20-37,72-79` and corresponding Hongyuan helper — direct-case fence and unconditional `started_store` rejection.
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-store-sdk-api-none-r1-main-integration-2026-09-27/README.md` — recorded disposition is `NO_WRITE / LIVE_NO_GO`; it explicitly limits the Store result to a narrow fail-close, not a same-process isolation boundary or live-trading acceptance.

## Correction history

Independent QA identified an overstatement in the initial partition B draft. It said both `create_live_store` and `create_live_broker` fail closed. That statement was incorrect: current source lines 699-705 make `create_live_store` raise, while lines 707-718 implement `create_live_broker` as `BtApiBroker(store=store, **broker_kwargs)`. The per-candidate reasons for WC-000187 through WC-000192 and this report now record the caller-supplied-store composition path. The correction does not change the fact that the 007 registered runtime is replay/no-action, nor does it establish downstream Store write success or authorize a route.

## Result boundary

The JSON enumerates candidates and static routes only. No official writer disposition was changed. No finding enables order entry, cancellation, live dispatch, or a real-provider route.
