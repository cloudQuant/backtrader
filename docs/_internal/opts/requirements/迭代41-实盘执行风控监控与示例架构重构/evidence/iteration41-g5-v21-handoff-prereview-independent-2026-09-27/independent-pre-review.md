# G5 / V21 handoff pre-review

Date: 2026-09-27 (read-only source review; no candidate or production changes)

## Scope and input identity

This is a pre-review of whether V21's durable CTP order-target projection can be composed with the frozen G5 worker handoff. It is not an independent candidate replay and is not production acceptance.

- V21 frozen source: `D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927`
  - `SOURCE-MANIFEST.json`: `B3A614D62B2A4CF1B0DBDFEFEE463015157DEE38BF4C9C5119C64EF2D71D6D24`
  - `src/bt_api_execution/store.py`: `1F01EDA8466873B90359C25AAD2B61CB378D7A9FEB477FA8EC77A97FB2478E6A`
  - `src/bt_api_execution/ctp_single_worker_candidate.py`: `5E378EE77AD5C6E640AD2ECA0DACF154849E6FCFE0D04D73E9DA6EB2554087B3`
- Frozen G5 handoff patch: `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\iteration41-g5-worker-handoff-followon-2026-09-27\worker-handoff.patch`, SHA-256 `331B5AD8BE656815DBFD72D743587BB641767011B414C82A0CE4DCAF156A1F6D`.
- G5 identity authority source: `D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py`, SHA-256 `8E7ABDD2819F66B6EC3D5FF1D5A049FCBB91AE8E71327665EE925098D35F647D`.
- The G5 follow-on README describes an earlier frozen SDK snapshot which lacked the target projection producer/table/readback. V21 has since added a typed SQLite projection contract; that newer code does not supply the missing native query producer/verifier and is not the same worker snapshot as the G5 patch target.

## Disposition

**Partial data-shape fit; not composable as-is; local fake/offline only.** V21's projection carries the identity and native target facts needed by the worker: account/scope/day, account and registration digests, managed intent/runtime order ID/OrderRef, InstrumentID/ExchangeID, OrderSysID, target FrontID/SessionID, plus query/session/connection correlation. V21 staging rechecks exact target fields and binds one projection to one cancel command (`store.py:664–796, 8083–8123, 8214–8234`; worker `ctp_single_worker_candidate.py:420–475`). The projection intentionally has no ActionRef; that is a separate cancel-action identity.

There is an exact call-shape blocker. The V21 worker accepts `stage_prepared_dispatch(prepared, *, cancel_target_projection=None)` (`ctp_single_worker_candidate.py:420–425`). The frozen G5 patch calls the same method with `action_identity=...` (`worker-handoff.patch` additions around lines 9–16 and 107–110). A safe isolated signature probe reproduced `TypeError: ... unexpected keyword argument 'action_identity'`. Probe source/log: `D:\temp\iteration41-g5-v21-worker-handoff-pre-review-20260927\probe_v21_worker_signature.py` / `.log`; hashes are listed below. The probe imported only the V21 Python module and loaded no CTP extension, provider, SDK or `ctypes`.

There is also an ActionRef ownership conflict to resolve before integration. V21 allocates `OrderActionRef` inside `SqliteExecutionStore.stage_ctp_dispatch_command` from its own account counter, initially 1 (`store.py:9242–9293, 9893–9911`). G5 reserves a separate ActionRef in `CtpUnifiedOrderActionAuthority` and expects that value to be carried as `action_identity` and match the durable command. Two independent allocators cannot establish one account-wide sequence or avoid collisions without an explicit unified allocator/transaction contract. G5's current seed type is explicitly caller-supplied legacy ledger evidence, not trusted native MaxOrderActionRef proof. Native watermark, cutover and allocation must be resolved, then tested with parallel allocation/retry/exhaustion cases.

V21's projection protocol requires a trusted verifier to prove the exact native query source/current SDK readback and a unique OPEN/PARTIAL row, but the package ships only a rejecting default; no native `ReqQryOrder` producer/verifier is present in the V21 source. The typed structure's hashes are references to evidence, not authentication by themselves (`store.py:664 docstring, 1540–1557, 7858–7987`). `query_match_count == 1`, complete/terminal, no timeout/error/late callback, open quantity arithmetic and a maximum five-second monotonic TTL are enforced locally. They do not prove who produced the query or that it is the unique current provider snapshot.

V21 has `session_generation_id` and `connection_generation`, but no distinct OS worker/process generation bound to a Windows Job, owner/fence or process-death proof. Those session fields cannot establish that the prior native owner is dead. Claimed-command recovery remains a local owner/fence transition, not Job-empty/process-death evidence.

Freshness is checked at projection issue/persist/readback, staging/claim, and just before entering the injected sender. The worker permits an awaitable sender (`ctp_single_worker_candidate.py:523–530`), so this is not enough to prove the target remains fresh at the actual native `ReqOrderAction` call after an await/delay. The native-owner adapter must do a final monotonic expiry and same-session/connection-generation check immediately before the non-await SDK send boundary.

## Reproduction recorded

The signature probe used the V21 worker method's actual signature and passed the G5 keyword. It was rejected before any Store or native/provider construction:

- `probe_v21_worker_signature.py` SHA-256 `73019F38B93D13BF939C595FE028E4695F2253AF37E0C3F0C30963A3AE8516B0`
- `probe_v21_worker_signature.log` SHA-256 `DD346C33BDA5703685181EF7A515B7492647796CECD7723BC6B8B03539D648C5`
- Outcome: `REJECTED`; `bt_api_ctp_loaded=false`, `bt_api_py_loaded=false`, `ctp_loaded=false`, `ctypes_loaded=false`.

## Required independent QA after a new candidate is frozen

1. **Provenance and compatibility:** hash every manifest payload; replay patch against exact declared V21 base and require byte-identical outputs. Verify worker/store signatures match and do not rely on earlier SDK snapshots.
2. **Projection positive cases (fake verifier only):** one exact complete current query row for OPEN and PARTIAL; verify identity/target round-trip through SQLite and native request payload; check quantity arithmetic; same-store exact readback; one-use consumption; same-command retry idempotency; restart invalidates ephemeral handle and requires a new query.
3. **Projection rejection cases:** default/no verifier; zero or multiple matching rows; wrong account/scope/day/registration/fingerprint/reservation/intent/runtime ID/OrderRef/InstrumentID/ExchangeID/OrderSysID/FrontID/SessionID/query ID/generation; incomplete/nonterminal/timeout/error/late callback; stale/expired result; non-open state; inconsistent quantities; mutated payload/hash/row; reuse by a second cancel.
4. **ActionRef authority:** prove one allocator and one account-wide durable sequence; test caller-forged or mismatched ActionRef, old/native watermark cutover, duplicate/retry, concurrent cancels, int32 exhaustion, and that `OrderActionRef` in the queued native payload equals the sole durable allocation. No native MaxOrderActionRef source exists in these local fakes, so this remains a hard integration blocker unless separately provided and verified.
5. **Freshness and generation:** expire at each boundary (before persist, stage, claim, sender and actual SDK send); delayed/awaitable sender must recheck at the actual send call. Disconnect/reconnect, connection/session generation changes, caller death, old claimed rows and process-generation migration must fail closed; require independent Job/process death evidence for recovery.
6. **Scope:** all of the above may establish only local fake contract behavior. Do not report G5, native CTP, account, or production acceptance from these tests.

## Limits

No new frozen integration candidate was modified or executed. No native/provider/credential/network path was used. This review does not establish an end-to-end target producer, native snapshot uniqueness, process-death proof, or CTP acceptance. Await a newly frozen candidate for full independent QA.
