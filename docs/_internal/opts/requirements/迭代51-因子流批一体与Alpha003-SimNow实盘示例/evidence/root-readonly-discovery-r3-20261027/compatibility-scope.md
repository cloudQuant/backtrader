# CTP zero-request-ID MD login scope (2026-10-27)

## Finding

The existing `allow_zero_login_response=True` option is suitable for a narrowly
configured zero-write discovery run **without creating an authenticated MD
identity**. It changes only the MD login-response correlation rule: on its
accepted zero-ID path, `MdSpi.OnRspUserLogin` marks the market-data client ready
for quote subscription, sets diagnostic disposition `READ_ONLY_ACCEPTED`, and
clears the active MD identity rather than constructing an `MdIdentityObservation`
(`bt_api_ctp/ctp/client.py:2371-2445`). `MdClient.active_md_identity` returns
`None` unless a current authenticated observation is bound to the active API,
SPI, generation, and request (`:2639-2663`).

Use the exact JSON boolean `true` in the live Store `api_kwargs` for this
Root-owned discovery call. The option is already passed from
`CtpClientWrapper.__init__` into `MdClient` (`backtrader/stores/btapistore.py:2010-2013,
2352-2360`); the wrapper currently coerces it with `bool(...)`, so a string such
as `"false"` would also enable it. The SDK constructor itself requires an exact
bool and defaults to strict mode (`bt_api_ctp/ctp/client.py:2531-2546`).

This is not an unauthenticated session. The direct wrapper still requires
nonempty front addresses and broker/user/password and starts both clients;
after MD readiness it separately waits for the Trader client (`btapistore.py:
2340-2409`). The zero-ID option applies only to `MdClient`; it does not bypass
Trader authentication/login or establish Trader readiness.

## Remaining read-only gates

The example's query-selection path is Trader-backed. `build_ctp_query_market_plan`
calls `registered_sim_collect_futures_snapshot` and then performs point-in-time
selection/calendar/grid construction (`examples/unified/028_alpha003_simnow_minute/run.py:422-571`).
The Store adapter requires the already-connected direct CTP `RegisteredSimStore`
and its Trader client (`backtrader/stores/btapistore.py:4067-4104`). Its
`query_instruments_result` and `query_depth_market_data_result` methods delegate
to `TraderClient` (`:2458-2465,2517-2543`). The snapshot collector requires the
Trader session to be connected and `read_only_ready`, and binds both complete
queries to the current trading day and connection generation
(`backtrader/feeds/futures_ctp_snapshot.py:248-264,526-628`).

Before selection, `run_live` waits for Store readiness and requires Trader
`read_only_ready`; it requires `trading_ready` only when writes were explicitly
enabled. It then checks that Trader trading-day and connection-generation
facts stayed stable during selection (`run.py:4547-4568`). The later refresh
loop also needs complete, current query evidence before it can publish factor
execution facts. Therefore enabling zero-ID MD compatibility can get startup
past the reported MD callback mismatch, but a failed Trader read-only login or
incomplete/stale Trader catalog/depth query remains a hard blocker. The
reported MD diagnostic alone does not establish Trader readiness or query
completion.

After selection, the live runner's initial refresh asks for the five core
Trader query families (account, orders, trades, instruments, positions) plus
bounded instrument-margin queries for authorized targets
(`backtrader/stores/factor_execution_facts.py:30-45,2540-2623`; runner calls it
with `include_core=True` and `max_queries=6` at `run.py:4751-4775`). In
zero-write mode, an incomplete initial refresh is recorded but is not raised
as a startup exception (`run.py:4769-4775`); this does not create complete
factor/account facts or authorize any action. The preceding main-contract
selection still requires the complete catalog and depth snapshot described
above.

For the zero-write case, preserve all existing write gates: `_write_requested`
returns false unless both the live config and explicit CLI grant permit writes
(`run.py:3957-3965`); `RegisteredSimStore` receives `allow_writes=False`
(`run.py:4517-4525`); the Broker is created with `market_data_only=True` and the
strategy gets `execution_enabled=False` (`run.py:4635-4649,4777-4797`). The
Store refuses arming in shadow mode (`backtrader/stores/registered_sim.py:840-843,
1913-1916`), while the Broker rejects submits in market-data-only mode
(`backtrader/brokers/btapibroker.py:3589-3595`). The MD option itself does not
toggle any of those controls.

The SDK accepts the zero-ID path only for an exact integer request ID of zero
on the current connected/pending login generation, with `bIsLast is True`,
zero provider error status, broker/user echoes either empty or matching the
constructor-bound values, and a valid trading day (`client.py:2361-2409`). The
reported finite diagnostic has zero request-ID relation, zero response error,
empty broker/user shapes, and a valid trading-day shape, but does not report the
terminal marker or the pending-generation facts. It consequently explains the
strict-mode mismatch; it does not by itself prove that the callback would pass
the opt-in gate. Root's run ended before the full query, so this review makes no
query, account, or acceptance claim.

## Existing tests and coverage boundary

SDK public tests covering the option are in
`D:/bt_api_py/bt_api/bt_api_ctp/tests/test_md_client_identity.py`:

- `test_collector_zero_id_login_can_collect_without_publishing_correlated_identity` (line 53)
- `test_zero_id_compatibility_still_rejects_invalid_login` (line 79)
- `test_zero_id_compatibility_cannot_accept_disconnected_or_old_spi` (line 88)
- `test_read_only_zero_id_login_accepts_empty_echoed_account_fields` (line 100)
- `test_compatibility_rejects_blank_account_on_correlated_login_or_invalid_day` (line 109)
- `test_read_only_zero_id_front_can_reconnect_and_resubscribe` (line 120)

`test_ctp_md_diagnostics.py::test_regular_login_diagnostic_is_value_free_and_cannot_grant_identity`
(line 62) covers the default strict request-ID mismatch. Backtrader's relevant
existing contracts include `tests/unit/test_registered_sim_store.py::test_shadow_store_refuses_arm_and_all_direct_ctp_writes`
(line 381), `::test_route_eligibility_is_a_read_only_projection_not_write_authorization`
(line 1408), `tests/unit/feeds/test_futures_ctp_snapshot.py::test_real_query_results_flow_through_collector_into_equal_weight_selector`
(line 434), `::test_incomplete_or_failed_query_facts_have_distinct_refusal_codes`
(line 499), and `tests/unit/test_alpha003_simnow_runner.py::test_live_write_grant_requires_mode_config_and_live_entry_tier`
(line 4353).

The Backtrader test tree has no current `allow_zero_login_response=True`
integration case for the wrapper-to-SDK option path; existing literal
references in its tests are false-valued config fixtures. This is a source
coverage gap, not evidence that the pass-through is broken. No tests, imports,
provider/native calls, or private inputs were used for this review.
