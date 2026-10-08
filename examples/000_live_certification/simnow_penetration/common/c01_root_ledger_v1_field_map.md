# C01 Root Ledger Content Validator v1 Field Map

This record documents the source fields consumed by
`c01_root_ledger_v1.py`. The validator checks content and joins from one V4
worker receipt and the held baseline/final snapshot bytes. It receives the
already source-loaded V3 protocol and V4 producer modules so it can call their
fixed worker/snapshot parser and projection functions. It does not prove that
either module or provider is authentic, mint a custody seal, or establish a
formal C01 result.

The API is `validate_c01_ledger_content_v1(worker, private_artifacts, *,
protocol_module, worker_module, expected_worker_source_sha256,
expected_protocol_source_sha256, expected_worker_module_source_sha256,
expected_pair_binding, expected_account_scope_sha256,
expected_credential_binding_sha256)`. The worker argument is the exact V3
receipt `to_dict()` projection; the artifact map contains the two exact held
snapshot byte strings. The required module objects expose the pinned V3 parser
and V4 producer projectors.

## Producer and wire sources

| Content | Public source | Mapping used by the validator |
| --- | --- | --- |
| Fixed eight-request plan and native request rows | `backtrader_runtime/certification_simnow_c01_native_v4.py:2504-2573`, `backtrader_runtime/certification_simnow_c01_v3_protocol.py:1089-1224` | Authenticate, login, then baseline orders/positions/funds and final orders/positions/funds. Each row binds method, native `request_id`, local `request_generation`, local `local_sequence`, UTC and monotonic issue clocks, return code, query result, and account/credential scope digests. IDs and generations are unique; the generation is the fixed one-based plan index. |
| Response callback rows | `backtrader_runtime/certification_simnow_c01_native_v4.py:2575-2756`, `backtrader_runtime/certification_simnow_c01_v3_protocol.py:1225-1325` | The callback's native RequestID and request generation join to one planned request. Callback arrival sequence and clocks are local SDK capture metadata. Every request callback has present RSP_INFO, integer `ErrorID == 0`, fixed callback name, and terminal position. Authenticate and login each have one terminal callback. Query callbacks are checked as ordered groups; no activity callback is admitted. |
| Authenticate/login identity origin | `backtrader_runtime/certification_simnow_c01_native_v4.py:2575-2756` | `FrontID`, `SessionID`, and `TradingDay` are accepted only on the `OnRspUserLogin` callback. Authenticate and all query callbacks must have those fields null. Both private snapshot scopes must match the login callback. Query source trading day is cross-checked against that native login day, but query-source identity fields are not projected as login identity. |
| SDK query result and query source row | `backtrader_runtime/certification_simnow_c01_native_v4.py:3929-4104`, `backtrader_runtime/certification_simnow_c01_v3_protocol.py:324-522` | Each of six query requests has one complete, non-timeout, supported result with a successful submit code, zero late callbacks, exact request/generation binding, fixed request type, and matching record/callback digests. The source row's request filters, timestamps, monotonic clock encoding, expiry, identity consistency, and row digest are checked. `seal_valid`, `issuer_is_client_query_lane`, and the source type string are content fields only; this validator does not trust them as authority. |
| Private snapshot request and callback content | `backtrader_runtime/certification_simnow_c01_native_v4.py:3323-3466`, `backtrader_runtime/certification_simnow_c01_v3_protocol.py:1625-1800` | The exact held canonical bytes are parsed for baseline and final. Each artifact's three query requests are canonically compared with the corresponding worker request; every callback row is joined positionally and field-by-field to the worker callback group. Detached rows are rehashed and bound to the SDK result/source digests. Snapshot summary request/count/row/first/terminal facts must match the artifact. |
| Projection digests and scope | `backtrader_runtime/certification_simnow_c01_native_v4.py:3376-3466` | All four snapshot projections are JSON-safe and their canonical digests match the worker summary. The two snapshot clients and scopes are bound to one worker client generation and the native login. Baseline and final projection, client, and scope values are compared canonically. |
| Write and native close facts | `backtrader_runtime/certification_simnow_c01_native_v4.py:4198-4280`, `backtrader_runtime/certification_simnow_c01_v3_protocol.py:1450-1525` | Both order-write counters must be exact integer zero. The fixed `CtpNativeStopReceipt` shape must report `join_required=False`, `join_completed=True`, `native_released=True`, `thread_alive=False`, and `timed_out=False`. These are worker content claims, not independent Root process/custody observations. |
| Worker receipt type and projection | `backtrader_runtime/certification_simnow_c01_v3_protocol.py:827-879`, `backtrader_runtime/certification_simnow_c01_native_v4.py:4198-4265` | The synthetic test uses V4 `_build_worker_receipt`, V3 `encode_worker_frame`/`parse_worker_frame`, and the parsed receipt's `to_dict()` result. The input to the validator is an exact `dict`, matching the actual producer projection. |
| V3 parser dependency | `backtrader_runtime/certification_simnow_c01_v3_protocol.py:1424-1441`, `1625-2032` | The validator receives `protocol_module`, reparses the exact worker mapping through the V3 frame encoder/parser, and parses each held snapshot byte string through `parse_private_snapshot_artifact`. This applies the V3 duplicate-key, canonical-frame, schema, bounded field, row, and projection-shape checks. Public source SHA-256: `C48B41272AE6378060B0B65188B56EF613F001B53D13DB7ACEAF13489D398160`. |
| V4 projection dependency | `backtrader_runtime/certification_simnow_c01_native_v4.py:2986-3320`, `3323-3452` | After the V3 parser accepts the snapshot, the validator passes detached rows from those exact snapshot bytes to the same four V4 producer projectors (`project_open_order_refs`, `project_order_economics`, `project_gross_positions`, and `project_funds`) and compares all four expected projections with the artifact projections. Broker/investor identifiers remain local to validation and are not returned. Public source SHA-256: `66666D2ADDC3BDDBF0F13A9A30FAB9FEA83479D7CAC7328879552E13BAEA5A66`. |

## Local and provider sequence distinction

V4 `local_sequence`, `issued_monotonic_ns`, and `arrived_monotonic_ns` describe
local request/callback order and capture clocks. The framework's
`CertificationEvidence.source_sequence` remains zero for C01 authenticate and
login because CTP supplies no provider-issued callback sequence; the separate
`LocalCallbackArrival.source_sequence` is local metadata
(`examples/000_live_certification/simnow_penetration/common/case_engine.py:402-435`,
`1602-1730`). The validator result therefore fixes
`provider_source_sequence=0`; it never re-labels its local callback sequence as
a provider sequence.

## Result and trust boundary

`C01ValidatedContent` contains frozen request, callback, query, and private
snapshot fact tuples. Underscored commitments bind the canonical worker
receipt, exact held artifact bytes, and each query join. Those commitments are
for a future Root custody consumer after it has established its exact source
lease and invocation scope. `safe_summary()` returns only fixed counters,
fixed status/authority enums, and booleans; `repr` redacts identity and
commitments, and the type has no public serializer.

The required `protocol_module` and `worker_module` arguments are exact module
objects supplied by the caller. The function checks their type and required
function interface, but module names/attributes are not source pins. Before
stage or postverify calls, the Root caller must verify both module and function
code against the held source pins, retain those exact module objects, and pass
the same objects through both calls. The content validator does not read module
paths or authenticate module origins. Expected V3/V4 source hashes are format
checked and included in the private content commitment; only Root's held source
lease can establish that those hashes match the supplied module code.

The validator always returns `authority=NONE`,
`status=CONTENT_VALIDATED_ONLY`, `certification_pass=False`,
`source_authenticity_verified=False`, and `provider_source_sequence=0`. The
synthetic test deliberately exercises the producer's content labels and query
seal flags while asserting that none can create trusted authority or formal
PASS.

## Focused source QA

The synthetic test builds its input through the pinned V4 producer and V3
worker-frame parser, then mutates producer-generated receipts for the negative
cases. It also confirms that the V3 parser rejects a malformed projection with
matching artifact/summary digests, and that a V3-valid positions projection
still fails when it disagrees with the native query rows. On 2026-10-09, the
following focused checks passed:

```text
python -m ruff format examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py
python -m ruff check examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py
python -m pytest -q -p no:asyncio tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py
13 passed, 1 warning in 0.49s
```

Pytest emitted one configuration warning because this environment's
`pytest-asyncio` plugin is disabled for the focused run and the project config
contains its plugin-specific `asyncio_default_fixture_loop_scope` option.
These are synthetic, local source-contract checks only; they do not establish
provider, account, custody, or formal C01 acceptance.
