# Configured execution session with Cerebro

From the Backtrader repository root, run:

```powershell
C:/anaconda3/python.exe -m examples.service_execution_session.run
```

The command reads `config.example.json`, starts a fresh local synthetic
execution service process, creates a normal `BtApiBroker` and `Cerebro`, and
runs three deterministic CSV bars through `run_configured_cerebro`. It uses
ephemeral CURVE keys generated for that invocation. The example service labels
its dispatch leaf `synthetic-no-write` and rejects any provider write. The
strategy submits no orders. The Backtrader Store's local legacy client returns
synthetic empty position/open-order lists and has no account-balance method, so
there is no account cash snapshot or guessed cash value. The displayed data
must not be interpreted as account evidence.

The JSON file wraps an SDK `strategy_client` configuration under
`client_config`. The example selects an unused loopback port and replaces only
the configured `rpc_connect` endpoint in memory before parsing it with the SDK.
All route IDs, scope references, account/strategy labels, service identity,
permissions, and credential generation are held by the trusted local example
code. They are synthetic identifiers and do not authorize a real account.

`run_configured_cerebro` accepts the SDK's legacy client-config schema version
1 or current strategy-client schema version 6, then supports only one exact
execution client with required `broker.orders` and `broker.order_query`
bindings. Both routes must use the same service, instance, account, and
transport; their scope references are resolved by trusted deployment code.
It does not load code, resolve identities, or read credentials from config.
`None` preserves the ordinary `cerebro.run()` behavior. A supplied but invalid
or unsupported config raises; it never falls back to an unmanaged run. Other
client aliases, optional order-query routes, extra execution mounts, channel
runs, optimization, broker sharing, and cross-account/group coordination are
outside this helper's supported subset.

The command prints one `SERVICE_EXECUTION_SESSION_DEMO` JSON record after the
client and service close normally. It is a local synthetic entry and lifecycle
proof only. It does not establish a production provider callback, account cash,
orders, reconnect behavior, BT01/BT02 acceptance, or full Iteration 10 stage P7
acceptance. For a deployed service, application code must build the
`ServiceClientRuntime` from its own trusted identity, scope/peer resolvers, and
transport factory, then call the same configured entry with its SDK client
configuration and a preconfigured normal Cerebro instance.
