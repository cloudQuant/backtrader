# AC41-63 static writer review — partition C

Generated UTC: 2026-09-27T14:50:36Z

## Scope and binding

- Inventory: docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/live-execution-inventory-candidates.json
- Inventory SHA-256: 03658257d97e31c2d8f8bfd48685441533552b32674f5d63810141e3038ab456
- Reviewed 122 writer candidates (indices 241–362) and 97 dynamic execution candidates (indices 0–96).
- Per-candidate source SHA-256, line, classification, reason, exact source line, and unchanged inventory status are in review-findings.json.
- Static review only: no project/source imports, examples/tests, network/provider/SDK/native access, or credentials/config/accounts read.
- Official checklist remains unchanged. Every row remains REVIEW_REQUIRED / NOT_AVAILABLE and grants no write authority.

## Default runtime reachability

default_runtime_registry delegates to code-owned inventory. Shipped CTP/example registrations expose replay only; 010 OKX is public-market shadow; 013_3 private CTP profile is simulation/sandbox with no runner and deny writes; live/managed_live_direct is explicitly unavailable. dispatch_registered_runtime re-resolves the effective-config seal and rejects live mode before runner import. CLI registry injection exists for reviewed programmatic callers/tests; installed command uses the default inventory.

These source candidates do not form a default bt-runtime live/order route. The source tree retains importable Strategy classes and candidate modules. Core Strategy.buy/sell/close forwards to the attached broker. Custom in-process broker injection, direct native client use, or custom programmatic registry is outside default-registry enforcement.

## Highest-priority findings

1. Strategy orders remain broker-polymorphic. Candidate order calls in 007/010/012/013/014/example strategies ultimately use the attached broker. Default runner profiles fence supported entrypoints, but importing a Strategy and attaching a custom broker bypasses runtime registry selection. This is the broadest remaining route class. It does not establish a stock CTP write: current CTP Store wrapper insert/action methods raise unconditionally, and several legacy entrypoints fail closed.
2. Dynamic runner loading has two trust modes. Default CLI binds inventory registrations to fixed source roots, validates effective config, and blocks live dispatch before runner import. A non-inventory custom registration falls back to normal importlib.import_module; this is a programmatic extension point. The private loader executes source at the fixed registered module path and checks regular-file/no-reparse identity before/after reading, but does not compare expected source-content SHA-256. Module paths do not pin content against in-place local edits.
3. CTP reflection boundaries need scope discipline. BtApiStore._invoke_ctp_query reflectively invokes method_name from its internal query loop. Current callsites pass fixed query names; the helper has no local allowlist. It is private and no default live route reaches it. Current wrapper native insert/action methods fail closed, so no stock Store order bypass was established. _OwnedNativePort.__getattr__ forwards any wrapped-port attribute in the separate CTP managed candidate composition. That is not a sandbox and may expose writer methods to a same-process caller.
4. Candidate CTP write APIs remain unregistered. CtpTraderClientSimulationPort.submit_order_insert can dispatch only after write capability, staged approval/credential binding, durable order-reference mapping, and a second write check. It is not a default registration and its existence is not authorization. CtpManagedAccountRuntimeCandidate requires a sealed-scope factory and account-family/writer-lease acquisition; it is documented unregistered and supplies no default route.
5. Legacy CTP paths are fenced at supported entrypoints. 007 CTP runners and penetration run_case exit through config-first replay gates; old _legacy_main/case helpers raise before direct Store creation. 010 SimNow tests select the gate as scripts and skip at collection. 013_1/013_2 live helpers fail before config/Store construction. 013_3 standard runtime is local replay and its private CTP profile has no runner. 014_1/014_2 launchers route through replay-only config-first behavior and retained direct-writer names raise. These barriers do not constrain custom Broker/client construction or raw-object reflection.
6. Subprocesses are not authorization gates. In-scope subprocesses are fixed local fake/probe/diagnostic tools or historical code behind entrypoint fences. PilotSupervisor defaults to fixed run.py with timeout and requires execute=True, while constructor accepts runner callback injection. I10/I11/I13 and I3–I8 dynamic CTP imports are staged read-only market-data diagnostics, not order writers, and are separately callable.
7. Read-only proxies are same-process wrappers. 014/015 __getattr__ wrappers reject named write methods and expose safe-read allowlists, but keep wrapped API in private _api. A caller with object access can retrieve raw API; these wrappers do not sandbox arbitrary in-process code.

## Candidate classifications

- high: 48
- low: 94
- medium: 77

| Classification | Count |
|---|---:|
| ARTIFACT_GATED_CTP_MODULE_IMPORT | 1 |
| BACKTEST_STRATEGY_ORDER_INTENT | 20 |
| BROAD_NATIVE_PORT_FORWARDER | 1 |
| CALLER_SUPPLIED_CALENDAR_CALLBACK | 1 |
| DENYLISTED_OBSERVATION_PROXY | 3 |
| DYNAMIC_MANAGED_EXECUTION_PLUGIN_IMPORT | 2 |
| EVENT_LOOP_CLEANUP | 1 |
| FIXED_LOCAL_FAKE_SUBPROCESS | 1 |
| FIXED_SOURCE_METADATA_EXEC | 1 |
| FIXED_SUPERVISOR_CHILD_PROCESS | 1 |
| GATED_CTP_SIMULATION_ORDER_WRITER | 1 |
| GUARDED_READONLY_CTP_MD_IMPORT | 11 |
| INDIRECT_ACCOUNT_READ | 1 |
| INDIRECT_CTP_QUERY | 2 |
| INDIRECT_METADATA_READ | 4 |
| INDIRECT_READONLY_QUERY_OR_NORMALIZATION | 2 |
| INDIRECT_RESULT_GETTER | 1 |
| INDIRECT_SDK_COMMAND_DISPATCH | 1 |
| INDIRECT_TYPED_QUERY_OR_METADATA_READ | 4 |
| INDIRECT_TYPED_READONLY_QUERY | 8 |
| INDIRECT_VALUE_OR_PUBLIC_READ_CALL | 3 |
| INJECTABLE_PROCESS_FACTORY | 1 |
| ISOLATED_NATIVE_READONLY_DIAGNOSTIC | 1 |
| LAZY_RUNTIME_EXPORT_FORWARDER | 1 |
| LEGACY_CERTIFICATION_SUBPROCESS_AFTER_FENCE | 2 |
| LEGACY_CTP_SUBPROCESS_AFTER_FENCE | 3 |
| LEGACY_SIMNOW_TEST_SUBPROCESS_BLOCKED | 2 |
| LIVE_RUNNER_READ_QUERY | 1 |
| LOCAL_APPROVAL_TOOL_SUBPROCESS | 6 |
| LOCAL_DATA_TOOL_SUBPROCESS | 1 |
| LOCAL_FILE_CLEANUP | 5 |
| LOCAL_RESOURCE_OR_REPORT_CLEANUP | 9 |
| LOCAL_SIGNAL_LOG_CLEANUP | 2 |
| MARKETDATA_CLIENT_CLEANUP | 5 |
| MOCK_QUEUE_CLEANUP | 1 |
| NATIVE_PORT_RESOURCE_CLOSE | 1 |
| NON_TRADING_MODEL_METHOD | 1 |
| OPTIMIZATION_STRATEGY_ORDER_INTENT | 9 |
| OPTIONAL_CTP_SDK_IMPORT | 1 |
| ORDER_INTENT_LEGACY_CERTIFICATION_BLOCKED | 4 |
| ORDER_INTENT_LEGACY_CTP_HELPER_FAILCLOSED | 8 |
| ORDER_INTENT_LEGACY_SIMNOW_TEST_BLOCKED | 4 |
| ORDER_INTENT_REPLAY_ONLY_STRATEGY | 7 |
| ORDER_INTENT_REPLAY_REGISTRATION | 4 |
| PINNED_PUBLIC_MARKETDATA_IMPORT | 3 |
| PROBE_CONNECTION_CLEANUP | 1 |
| REFLECTIVE_ADAPTER_CAPABILITY_CHECK | 4 |
| REFLECTIVE_DEPENDENCY_LEASE_CHECK_OR_CLOSE | 2 |
| REFLECTIVE_PRICE_READ | 1 |
| REFLECTIVE_SDK_RESOURCE_CLOSE | 3 |
| RETIRED_SIMNOW_PROBE_ORDER_INTENT | 2 |
| RETIRED_SIMNOW_RESOURCE_CLEANUP | 8 |
| RUNTIME_RUNNER_CALLABLE_DISPATCH | 3 |
| RUNTIME_RUNNER_DYNAMIC_LOAD | 4 |
| SEALED_DEPENDENCY_MODULE_EXEC | 1 |
| SHADOW_CLIENT_RESOURCE_CLOSE | 1 |
| SHADOW_STRATEGY_OBSERVER_IMPORT | 1 |
| STRATEGY_ORDER_INTENT_EXAMPLE | 33 |
| TEST_CONFIGURATION_IMPORT | 1 |
| UNREGISTERED_ACCOUNT_CLAIM_CANDIDATE | 2 |

Full per-candidate data is in review-findings.json.
