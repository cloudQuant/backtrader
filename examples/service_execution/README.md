# service_execution

Iteration 65 example (step 65.10): one strategy client selects Execution routing
for a limit parent order, lets the Execution service schedule it with the
configured `PASS` / `SLICE` / `TWAP` algorithm, consumes the Execution -> Monitor
relay composition, and cancels by the original identity.

This folder is self-contained: `README.md`, `config.yaml`,
`execution_route_strategy.py`, `run.py`. It does not import another example.

> Every value in `config.yaml` is an operator-supplied placeholder. This example
> is **not** an account, provider or trading authorization, and it contains no
> credentials. The offline dry-run only proves configuration shape.

## Run

```bash
cd examples/service_execution
python run.py --dry-run          # exit 0, bounded JSON summary
python run.py --live             # bounded preflight; always fail-closed here
```

From the repository root:

```bash
python examples/service_execution/run.py --dry-run
```

Exit codes follow the repository example convention: `0` PASS, `1` FAIL,
`2` BLOCKED.

`--dry-run`:

* validates `client_config` with `bt_api_py.service_config.parse_client_config`
  (pure, no I/O);
* validates the `execution_routing` option with
  `bt_api_py.execution_routing.parse_execution_routing` (pure, no I/O);
* pre-checks the client-side scheduler class/version/params;
* derives the Monitor relay scope with the SDK composition helper;
* reports netting and the D67-01 calendar configuration;
* starts no service, opens no network connection, reads no credential, creates
  no checkpoint/sqlite/state file, and never reads the calendar directory.

`--live` repeats the same validation and then:

1. refuses while any value still starts with `REPLACE-`;
2. refuses an unconfigured/invalid calendar (`calendar_root_unconfigured`,
   `calendar_config_invalid`, `calendar_package_seed_unsupported`, D67-01);
3. probes each distinct `rpc_connect` endpoint with a 1 s TCP connect and
   refuses when a required service/port is unavailable;
4. refuses at `trusted_runtime_and_credentials_required` even when the ports are
   reachable. The example never reads credentials and never fabricates the
   trusted wire identity that a real parent submission needs. A deploying
   application must build its own `ServiceClientRuntime`/transport and
   `GatewayOrderIntent`, then bind an `SdkExecutionRoutePort`.

## Architecture

```
 strategy process (this example)                         Execution service (65)
 +------------------------------------------+           +---------------------------+
 | config.yaml                              |           | parent.submit port        |
 |   clients.execution.settings.options     |           | scheduler PASS/SLICE/TWAP |
 |     .execution_routing.rules[0]          |  submit   | child planning/dispatch   |
 |       .algorithm = scheduler selection   |---------->| via Gateway (Risk is     |
 |   clients.gateway broker.direct_write    |           | an optional component)   |
 +-------------------+----------------------+           +-------------+-------------+
                     |                                              |
    parse_client_config / parse_execution_routing                   |
                     v                                              |
          ExecutionOrderRouter.route(intent)                        |
            durable original request identity                       |
            and digest before one parent.submit                     |
                     |                                              |
                     |            Execution -> Monitor relay        |
                     |   assemble_execution_monitor_relay(source=..)|
                     +---------------- poll/ACK ------------------->Monitor sink
                     |
          router.cancel(original intent)
            same request_key + digest -> cancel by original identity
```

The strategy itself (`ExecutionRoutingDemoStrategy`) submits once, polls the
selected relay, and cancels after `cancel_after_bars`. It never splits an order:
splitting is the Execution service's scheduler, not the strategy's job.

## Configuration keys

| Key | Meaning |
| --- | --- |
| `example.name` | Example label, printed by the dry-run. |
| `client_config.client_config_schema_version` | SDK strategy-client schema. `1` is the legacy/current field accepted here; `config_schema_version: 6` is the other accepted root spelling. |
| `client_config.process_role` | Must be `strategy_client`; `execution_routing` is only valid for this role. |
| `client_config.registration.strategy_ref` | The one strategy subject. Must equal `execution_routing.strategy_ref` (`EXECUTION_ROUTING_SCOPE_MISMATCH` otherwise). |
| `client_config.clients.execution.settings.bindings[]` | The `broker.execution_parent` writer route. Its `account_ref`, `instance_id` and `service_id` are bound to the selection; the SDK requires exactly one parent binding for that account. |
| `...options.execution_routing` | The selection: `schema_version: 1`, trusted `account_ref` / `strategy_ref` / `execution_domain_ref`, `component` (Execution instance id), versioned `grant_revision`, `delegation`, complete neutral `instruments[]`, and an ordered `rules[]`. |
| `rules[].match` | Conjunction: instrument, side, offset, limit-only `order_types`, `minimum_quantity` + `quantity_unit`. First match wins; no rule merging. An unmatched order keeps the ordinary direct path (D65-10). |
| `rules[].scheme` | Versioned Execution scheme selection. The service checks it against its registry and the account allow set. |
| `rules[].algorithm` | Scheduler selection (D65-08). `PASS` uses `params: {}`; `SLICE` uses `{max_child_qty, child_price, child_timeout_s}`; `TWAP` uses `{slices, start_ns, end_ns, child_price, missed_slice_policy}`. `child_price` is `limit`, `passive` or `cross`; the missed policy is `DROP` or `ROLL_FORWARD`. |
| `rules[].deadline` | Absolute, timezone-aware deadline. Normalised to UTC at acceptance. It is never extended, replaced or silently dropped. |
| `rules[].time_in_force` / `trading_day` | `DAY` defaults `allowed_trading_days` to `[trading_day]`; `GTD` requires an explicit sorted list starting with `trading_day`. |
| `clients.gateway.settings.bindings[]` | Required `broker.direct_write` route for the same account. The SDK refuses a selection without it (`EXECUTION_REQUIRES_GATEWAY`). Gateway itself does not additionally enforce the strategy route (D65-13). |
| `communication.profiles.*` | One `tcp://host:port` `rpc_connect` per service. Replace both the profile refs and the endpoints. |
| `monitor_relay.source` | Explicit single-source choice: `projection` (parent/child projection relay), `journal` (Execution journal relay) or `none` (neither relay module is imported). This is a **constructor argument**, not a frozen SDK service-config key. |
| `monitor_relay.scope_ref` | Trusted Monitor scope used to build the projection sink from a registered runtime. Required for `projection`/`journal`; omit for `none`. |
| `monitor_relay.checkpoint_dir` | Directory for the durable relay checkpoint. The SDK derives the file name from the source and trusted scope. The dry-run does not create or read it. |
| `netting.enabled` | Example-local internal-netting switch. Ships `false`; the dry-run refuses `true` as `netting_not_covered_by_example`. Netting is independent of routing and scheduling (D65-09). |
| `calendars.root` | D67-01 explicit calendar root. A Gateway or write-admission entry must configure it; missing is `calendar_root_unconfigured`. `package_seed` is refused by this example because it does not bind the package seed. |

### Switching the scheduler

`config.yaml` ships `PASS`. Replace the `algorithm` block with one of:

```yaml
# SLICE: sequential children, next child after the previous terminal observation
algorithm:
  class: SLICE
  version: 1
  params:
    max_child_qty: "3"
    child_price: limit
    child_timeout_s: 30
```

```yaml
# TWAP: equal time windows over [start_ns, end_ns); no default catch-up
algorithm:
  class: TWAP
  version: 1
  params:
    slices: 4
    start_ns: 4102444800000000000
    end_ns: 4102446600000000000
    child_price: limit
    missed_slice_policy: DROP
```

`max_child_qty` is an algorithm parameter, not a Risk limit and not a substitute
for one. `start_ns`/`end_ns` are absolute epoch nanoseconds and must be supplied
by the operator; the example does not compute them from wall-clock time.

## Crash, cancel and day-cut behaviour

* **Crash / lost reply.** Before any remote side effect the SDK router durably
  records the stable request key and content digest. A restart replays the
  original outcome by that identity; it never resends under a new key and never
  falls back to the direct path. A lost reply is `EXECUTION_UNKNOWN` with the
  original durable identity retained, not a definite rejection.
* **Cancel.** `router.cancel(intent)` uses the same original intent, so the
  cancel is bound to the original request key and digest. A cancel accepted by
  Execution is not itself proof that every child or venue order is cancelled.
  For `SLICE`/`TWAP`, the scheduler cancels the unfilled remainder of a child
  according to its own bounded cancel budget; the strategy still cancels the
  parent by identity.
* **Day cut.** The original deadline, trading day and allowed trading days are
  frozen at acceptance. Restart, configuration drift or a day cut cannot extend
  or replace them. Cross-day closing re-checks the provider's close-today /
  close-yesterday rules and the real position; this example does not implement
  or prove that mapping. `TWAP` pauses outside the session and follows the
  configured missed-slice policy; it does not concentrate missed slices by
  default. A `DAY` parent does not silently become `GTD`.
* **Unmatched orders.** An order that no rule matches (wrong instrument, side,
  offset, order type or quantity) is `DIRECT_PATH` (D65-10). This example
  neither requires Execution to be online for a definite non-match nor claims
  the direct path supports market orders.

## Explicitly NOT covered

* Real `bt_api_gateway`, `bt_api_risk` or `bt_api_execution` processes, provider
  dispatch, real Gateway/Execution protocol loops and their acceptance evidence.
* SimNow, any demo or production account, credentials, account balances,
  positions, reconciliation, fills or order status.
* Internal netting. `netting.enabled: true` is refused by this example.
* Runtime proof of `PASS`/`SLICE`/`TWAP` behaviour. Only the client-side config
  shape is pre-checked; the service revalidates against its registry, plan,
  journal and facts.
* Risk selection and the `execution -> risk -> Gateway` child route.
* Real Monitor component integration and alerting (iteration 68); only the
  relay selection and derived scope are shown.
* The unified Execution web page and its UI/acceptance (iteration 69).
* The retired `ServiceExecutionSession` / `execution/account_owner` path
  (D65-11). This example uses the SDK composition path instead.
* Package-seed calendar binding.
* Windows-specific paths, permissions, services and process management.
* Any trading authorization, profitability claim or production readiness.
