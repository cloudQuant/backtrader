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

## Explicit Strategy account-book views

The session may also receive explicitly configured strategy/account read
routes. Each route fixes its runtime, mount, scope reference, strategy, account,
and ownership mode. The primary execution runtime's query route can serve its
own account-book view when the server grants
`execution.account_books.query`; an extra strategy needs a separately
configured route and runtime. The session starts, renews, and closes each
distinct `owned=True` runtime once. An `owned=False` runtime must already be
registered, and its external owner remains responsible for renewals and normal
close on the same thread. Missing or mismatched routes fail before the
account-book query RPC.

Add explicit identity parameters to each Strategy and bind the actual instance
from its normal `start()` method:

```python
class Alpha(bt.Strategy):
    params = (("strategy_ref", "strategy-alpha"), ("account_ref", "account-a"))

    def start(self):
        self.broker.bind_strategy_account_book(
            self,
            strategy_ref=self.p.strategy_ref,
            account_ref=self.p.account_ref,
        )

    def next(self):
        position = self.account_book.getposition(self.data)
```

`self.account_book` is a frozen, read-only Strategy view. It never changes the
shared Broker or its `getcash()`, `getvalue()`, and `getposition()` methods;
those methods keep their ordinary account-level behavior. A Strategy whose
explicit identity differs from the session's primary writer scope is rejected
locally if it tries to submit an order through that shared Broker. An account
book's risk budget is not cash. The current owner-book response contains net
quantity and fees, but no authoritative Strategy cash, lot cost basis, or NAV;
the view therefore raises `STRATEGY_CASH_UNAVAILABLE` and
`STRATEGY_VALUE_UNAVAILABLE` until the execution service publishes a coherent
owner-scoped funds and valuation contract. These routes are local synthetic
integration evidence, not account or trading authorization.

For a second Strategy identity, deployment code must separately construct a
trusted runtime and supply its exact query route to the same session. For
example, with `alpha_runtime` carrying the primary writer/query bindings and
`beta_runtime` carrying only Beta's granted query binding:

```python
from backtrader.stores.service_execution_session import (
    ServiceExecutionSession,
    ServiceStrategyAccountBookRoute,
)

session = ServiceExecutionSession(
    alpha_runtime,
    mount="broker.orders",
    scope_ref="alpha-orders-v1",
    query_mount="broker.order_query",
    query_scope_ref="alpha-query-v1",
    strategy_account_book_routes=(
        ServiceStrategyAccountBookRoute(
            strategy_ref="strategy-beta",
            account_ref="account-a",
            runtime=beta_runtime,
            mount="broker.order_query",
            scope_ref="beta-query-v1",
            owned=True,
        ),
    ),
)
```

An owned extra runtime is started, renewed, and closed by the session. Set
`owned=False` only for an already registered runtime whose external owner will
keep it alive and close it on that same thread; the session never starts,
renews, or closes borrowed runtimes. Each `(strategy_ref, account_ref)` route
can bind to one actual Strategy instance. A route mismatch, a second instance
trying to claim an occupied route, or an unbound Strategy trying to write
through a route with a configured account-book view is rejected locally.
