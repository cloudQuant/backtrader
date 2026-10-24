# Iteration 51 current CTP query-snapshot source route

This note records the public CTP API route for the user-selected temporary
same-day ranking policy. It does not replace the previous-complete-TradingDay
EOD route, and it does not claim a current or historical exchange-wide source
snapshot has been captured. No CTP account/native API was called for this
review.

## What the public API can provide

The SimNow/SFIT CTP manuals document `ReqQryInstrument` as a contract query;
empty request filters return all contracts. Its response includes the exact
`InstrumentID`, `ExchangeID`, `ProductID`, `ProductClass`, `IsTrading`,
`InstLifePhase`, and `ExpireDate` fields, and `OnRspQryInstrument` carries a
terminal `bIsLast` flag. The instrument list includes products beyond ordinary
futures, so selection must classify rows from this metadata and retain
non-futures as explicit exclusions. The SDK's `query_instruments_result()`
docstring further limits this universe to what is visible through the
connected front/account/trading day; a terminal-complete query does not prove
that a different front or the national exchange universe is represented.

The CTP manual says `ReqQryDepthMarketData` returns current snapshots only and
does not query historical market data. Its response rows carry
`TradingDay`, `InstrumentID`, `ExchangeID`, `Volume`, `OpenInterest`,
`UpdateTime`, and `UpdateMillisec`; the newer callback schema also carries
`ActionDay`. The SDK already exposes `query_depth_market_data_result()` with
empty filters documented as an all-visible-quote query. That behavior must be
confirmed against the selected live front by reconciling the returned IDs to
the complete instrument catalog; the SDK surface and the manual's current
snapshot guarantee alone do not prove complete quote coverage.

Both queries return the SDK's frozen `QueryResult` envelope. Its
`complete`/`is_last_seen` flags, `request_id`, `connection_generation`,
`started_at_utc`, and `completed_at_utc` establish request and terminal-query
facts. `CtpLiveFeed.get_session_state()` exposes one session-level
`trading_day`, `connection_generation`, and `read_only_ready` value; it does
not expose an ExchangeID-to-TradingDay map. Bracket both queries with those
session fields and also validate each returned quote row's own `TradingDay`.
The live result's `query_source` property points to an internal
`_QuerySource` carrying the terminal TradingDay and `records_sha256`; the
digest binds the SDK's canonical detached record snapshot, not original
exchange wire bytes. An adapter that avoids depending on this internal type
can compute and label its own canonical digest over the exact public records
it preserves. `QueryResult.as_dict()` does not include the SDK digest. A
ranking adapter can identify a query by source ID, connection generation,
and request ID, set `available_at` to observed terminal `completed_at_utc`,
and record the later local return time as `retrieved_at`. Retain only needed
provenance fields; do not serialize the whole internal source object, which
also includes session identity fields.

The quote query is a batch response, so its public result does not expose a
separate local receive timestamp for each row. When admitting a new selection
epoch, snapshot freshness should use the observed query
`started_at_utc`/`completed_at_utc`, local retrieval time, session generation,
TradingDay, and configured maximum snapshot age and collection span (both
default to 300 seconds in the provisional policy). These bounds admit the
new selection; they do not expire or rerank a mapping already frozen for its
TradingDay/epoch. Ongoing execution-quote freshness remains an independent
check.
Retain each row's native `ActionDay`, `UpdateTime`, and `UpdateMillisec` for
traceability, but do not treat them as local row-receive times or use an old
last-update time to remove a contract from OI/Volume ranking. The source time
and execution-price freshness rules are separate. `available_at` remains the
local observation boundary; it must not be backdated to a source event time or
interpreted as a previous-day publication time.

The SDK's `CtpTickerData` subscription path also retains `TradingDay`,
`ActionDay`, `UpdateTime`, `UpdateMillisec`, `Volume`, and `OpenInterest`, and
adds local `recv_time_utc`, `recv_monotonic_ns`, `ingest_seq`, connection
generation, and subscription epoch. Managed native callback rows set
`freshness_verified=False`; a caller must apply a real freshness policy rather
than trust that flag. This stream path is useful when per-row local receipt
times are required, but it needs explicit per-symbol subscription and coverage
checks.

## Required runtime evidence for a same-day decision

The catalog and quote results must both be terminal-complete, successful, and
from the same active session generation and TradingDay. At new-epoch
admission, the whole collection must fit the configured span, the snapshot
must fit its configured age, and the session generation/day must not change
across the catalog and quote queries. Preserve the exact provider
`InstrumentID`; join quotes to catalog rows by exact `(ExchangeID,
InstrumentID)`, then take `ProductID` and ordinary-future classification from
the catalog. Classify all catalog rows before reconciling quote coverage.
Options, combinations, continuous aliases, nontrading/expired contracts, and
contracts with fewer than five exchange trading days remaining are explicit
exclusions and do not require quote rows. For eligible ordinary monthly
futures, require exactly one well-formed quote row per exact catalog ID.
Missing, duplicate, ambiguous, malformed, or unmatched quote rows must be
reported explicitly and block a complete ranking; never let dictionary
insertion order silently discard duplicates. If contract classification or
the five-day safety decision is unknown, block rather than treating that
contract as an exclusion. Quote rows that match a catalog contract already
classified as excluded are recorded as excluded and do not enter ranking.

For each product, the proposed temporary score is
`0.5 * OpenInterest + 0.5 * Volume`, using the native CTP quantity fields as
reported. This is a same-snapshot score, not a prior-day EOD score. Bind every
row to the same TradingDay and query snapshot. Keep each row's source update
fields as audit data; the depth query has no per-row local receive timestamp,
so `ActionDay`/`UpdateTime`/`UpdateMillisec` cannot be promoted to receipt
times or used as an OI/Volume candidate freshness gate. Enforce age and span
at new-epoch admission using query/session timestamps; they do not trigger
automatic reranking or invalidate the frozen mapping after five minutes.
Apply deterministic ties (score descending, OI descending, volume descending,
expiry ascending, exact instrument ID ascending). Keep the existing exclusions
for options, combinations, continuous aliases, inactive/expired instruments,
and instruments with fewer than five exchange trading days remaining. CTP's
`ExpireDate` is a calendar date; it does not provide the trading-day calendar
needed for the five-day rule.

The current snapshot result must be persisted with the query and catalog
provenance, exact eligible row IDs, scores, explicit exclusions, and retrieval
time before it is used for historical replay. A later live query cannot
reconstruct the earlier as-of values. Freeze the active main-contract mapping
for its TradingDay/epoch; a new snapshot may start a later epoch but should
not silently switch the contract on every tick. Ongoing price-freshness
checks remain independent of the selection snapshot's admission age/span.

## Batching, rate, and coverage limits

The narrowest query path is one unfiltered instrument query followed by one
unfiltered depth snapshot query. The SDK serializes TraderClient queries with
one lock and defaults to 1.05 seconds between submitted queries
(`BT_API_PY_CTP_QUERY_INTERVAL_SEC` can override this); this is a local pacing
default, not an exchange-front allowance or rate guarantee. Each query still
needs its own terminal result and exact ID reconciliation. The selected front's
actual query limits and observed return coverage are not established by this
static review.

If depth-query coverage is insufficient, `MdClient.subscribe_batched()`
submits a supplied symbol set in chunks (defaults: 100 IDs per request and
0.1 seconds between batches) and retains the full pending set for reconnect.
These are SDK defaults, not a vendor maximum. The official CTP subscription
manual says a full-market subscription must explicitly pass the full list of
instrument IDs; an empty list does not subscribe to all instruments. It also
says subscriptions push only the latest data, not history, expired contracts
receive no ticks, and exchange-sliced quotes are typically about two per
second. A successful batch submission alone therefore does not establish
subscription acknowledgement or first-quote coverage for every candidate.

For either query or subscription mode, completeness is measured against the
catalog candidate set, not inferred from the number of returned rows. If the
selected front cannot provide exactly one quote row for every eligible
catalog future, the snapshot is incomplete and must not produce a full
universe main-contract decision. This route is limited to the SimNow/CTP
visible scope; it does not close the remaining official EOD source gaps for
the six-exchange historical policy.

## Source references

- [SimNow CTPIIMini API application development reference, version 1.2](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf): `ReqQryInstrument` and `ReqQryDepthMarketData` at §§3.1.33–3.1.34; response structures at §§3.2.23–3.2.24.
- [SFIT CTP Mini API application development reference, version 1.7.0](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf): `SubscribeMarketData` at §4.1.9 and `OnRtnDepthMarketData` at §4.2.8.
- Public SDK implementation in `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/ctp/client.py`: `MdClient.subscribe_batched` (around line 2860), query pacing (around line 4812), `TraderClient.query_instruments_result` (around line 9744), and `TraderClient.query_depth_market_data_result` (around line 9935).
- Public SDK result and stream types in `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/query.py` (`QueryResult`, `query_source`) and `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/containers/ctp/ctp_ticker.py` (`CtpTickerData`).
- Public feed delegates in `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/feeds/live_ctp_feed.py` (`query_instruments_result`, `query_depth_market_data_result`, and `CtpMarketStream`).

This is a static public-source route record. It does not claim live account
acceptance, full selected-front coverage, a captured market snapshot, or a
historical point-in-time replay pass.
