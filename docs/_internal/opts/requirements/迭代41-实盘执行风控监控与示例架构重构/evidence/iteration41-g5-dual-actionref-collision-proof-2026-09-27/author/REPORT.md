# G5 dual ActionRef authority review (fake-only)

## Result

A same-database structural collision reproduced twice, with byte-identical JSON stdout. The G5 identity authority persisted `native_action_ref = 1`; the V21 Store allocator independently returned `1` for the same synthetic account. Both use a fresh SQLite `:memory:` database and caller-supplied synthetic zero floors. The V21 per-account counter persisted at 1. This identifies a structural blocker to one durable account-wide ActionRef authority. It is **not evidence** of a duplicate sent to, accepted by, or observed at a provider.

The candidate intentionally calls V21's internal `_allocate_ctp_native_action_ref` primitive inside its own Store transaction. It does **not** stage a full V21 cancel command, so `ctp_native_action_ref_allocations` remains empty in this probe. The two actual schemas are preserved in `sqlite-schema.json`; the run output records the G5 reservation, V21 counter, and empty V21 command mapping table. The source caller in V21 `stage_ctp_dispatch_command` invokes that primitive and then inserts the mapping in its own transaction.

## Reproduction

- Script: `repro_actionref_collision.py`
- Interpreter: CPython 3.12.10 at `C:\Users\yunji\AppData\Local\Programs\Python\Python312\python.exe`
- Runs: 2; both exit 0, both report `STRUCTURAL_COLLISION_REPRODUCED`, stdout identical
- Database: in-memory SQLite only
- Setup: canonical-form synthetic `ctp` scope; local account-family owner and writer lease; synthetic caller-supplied OrderRef proof with empty mapping inventory and zero native/legacy maxima; one OrderRef reserved through G5's shared order API; synthetic ActionRef floor 0; then one V21 allocator call in a committed transaction
- Observed: OrderRef `000000000001`; G5 ActionRef `1`; V21 ActionRef `1`; G5 reservation row and V21 counter row both name the same account key
- Native CTP binding/provider modules loaded: none; network, credentials, SDK/native send: none
- SQLite DDL: `sqlite-schema.json`; captured complete run result: `run-output.json`; second identical capture: `run-output-second.json`

G5 and V21 ActionRef constraints are each scoped to their own tables. G5 uses a unique `(account_key, native_action_ref)` constraint on `ctp_action_identity_reservations`. V21 uses `(account_key, native_action_ref)` as the primary key of `ctp_native_action_ref_allocations`, driven by `ctp_native_action_ref_counters`. There is no shared counter or cross-table uniqueness constraint. Each allocator can therefore issue 1 before seeing the other's row.

## G5 blocker matrix

| Area | Current evidence | Blocker / status |
| --- | --- | --- |
| v5 command outbox | Main acceptance note TC83-O records 57 offline package tests for CANCEL-as-Modify shape validation and v4→v5 migration. The command candidate is explicitly not connected to the SDK/default runner. | `NOT_ACCEPTED`. Fake-native shape tests prove only local validation/migration, not dispatch. |
| Main Store and typed SDK route | Main `BtApiStore` rejects the legacy native submit/cancel dispatcher when managed CTP is active. Its managed OrderRef path says OrderRef must come from a single execution outbox reservation and refuses a second SDK allocation. | Safe fail-close behavior, but no accepted single end-to-end Store/SDK command path. G5/V21 handoff review also records that V21 `stage_prepared_dispatch` does not accept G5 `action_identity=`. |
| OrderRef / MaxOrderRef | V21 `CtpOrderRefSeedProof` is documented as caller-supplied exact-session cutover input; it can enforce local monotonic allocation and imported mapping consistency. | No authenticated native `MaxOrderRef` observation or complete, cleanly pinned legacy inventory supplies the cutover floor. A shape-valid caller proof is not a native watermark. |
| ActionRef / MaxOrderActionRef | This reproduction proves G5 reservation and V21 counter independently produce 1 for one synthetic account in one DB. G5 `CtpActionRefSeedProof` is caller-supplied legacy evidence. | Hard blocker until one allocator owns both outboxes and a trusted account-lifetime native ActionRef watermark/cutover is specified and verified. No native `MaxOrderActionRef` source is accepted. |
| Cross-day cancel | V21 `stage_ctp_dispatch_command` queries the reserved target by current `(account_key, trading_day, scope_key)` and validates projection day against the current reservation. Main acceptance note TC83-O explicitly says cross-trading-day cancel is unsupported for v5. | Prior-day resting-order cancel is not supported by these contracts. Needs explicit cross-day identity/query semantics and tests; do not infer from account-wide OrderRef monotonicity. |
| UNKNOWN reconciliation | V21 worker returns existing projection for `UNKNOWN` and does not redispatch. It persists ambiguous post-claim outcomes as `UNKNOWN`; its default authority verifier rejects. | No trusted native-query reconciliation/resolution producer. UNKNOWN remains fenced; caller/sender assertion cannot clear it. |
| Account-wide writer exclusion | V21 has a durable account-family owner and SQLite writer lease within its Store/journal. | This is local ledger coordination, not an external cross-host/account-wide fence; other databases, hosts, or raw SDK writers are not excluded. No deployed account actor/final server-side writer fence is accepted. |

## Existing evidence and scope

The current main acceptance matrix keeps G5 `BLOCKED / NOT_ACCEPTED / NO_WRITE`. Its historical G5 OrderRef/ActionRef independent review records candidate tests, but also says the current worker rejected G5 `action_identity=` before the method body, the seed was caller-supplied, and G5 remained closed. The V21 handoff pre-review calls the two counters a separate ActionRef ownership conflict, finds no native query verifier/producer, and notes that async sender validity can age before the actual SDK send boundary. These are offline/local contracts, not provider evidence.

No main-repository file was edited. This candidate does not change or enable CTP submission, cancel, preflight, run, live, or write behavior. It imports only the frozen Python execution-store package plus the isolated G5 identity-authority Python module to exercise their SQLite APIs; it does not import the native CTP binding or the parent `bt_api_py` package.

## Hashes

Frozen probe inputs and candidate artifacts are listed in `source-hashes.json`. The source set includes the V21 manifest, exact V21 Store and worker source, and exact G5 authority source. Relevant review-time main-tree sources/docs:

- `D:\source_code\backtrader\backtrader\stores\btapistore.py` SHA-256 `05268B4953A20FA0699639F7E05EE354A4BCAFC4B47915DD4BA352B26276E0D9`
- `D:\source_code\backtrader\tests\unit\stores\test_btapistore_execution_evidence.py` SHA-256 `0EBF16764D232DBD34A98720560C55B3EB21F8AEAFC87221B1B53625000C2BBA`
- `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\ctp-current-acceptance-matrix.md` SHA-256 `8F425BA0BCF93308412FE0C794B9417788D318B28FDD79650E035E080E413A87`
- `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\验收用例与基准.md` SHA-256 `7D07E4876372B2A9549B9F40B4A8D640CA617C12FBCE4C39FBA2C4C98B569299`
- `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g5-v21-handoff-prereview-independent-2026-09-27\independent-pre-review.md` SHA-256 `8C961F01E015B815D6342100952B9E2BF05B7E386125577BC9CD14287DBAFC1C`
- `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g5-orderref-actionref-independent-qa-2026-09-27.md` SHA-256 `362A64EB31DC41A032E3B8D02E6475061E02E66F6C55B04237FBCA37B8DA1D05`

