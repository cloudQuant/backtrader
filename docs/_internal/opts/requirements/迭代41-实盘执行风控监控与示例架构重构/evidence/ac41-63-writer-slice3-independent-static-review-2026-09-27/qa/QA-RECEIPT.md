# AC41-63 controlled writer slice 3 r2 — independent QA receipt

**Verdict:** `PASS_STATIC_AUDIT_SCOPE_ONLY`; no write, production, or closure acceptance.

**Input:** `D:\temp\ac41-63-writer-slice3-20260927-r2.zip` — SHA-256 `4d90d2e1abda09c44dfeb4845526b7a07b12d617bab9952de60d360832b37000`. ZIP CRC is clean; 11 members consist of the freeze manifest plus 10 payloads, all 10 payload hashes and lengths verified.

## Coverage and dispositions

- Slice 3 has 21 unique IDs, disjoint from the prior 22; all 21 match candidate rows in the 389-entry inventory and disposition index.
- `22 + 21 = 43`; `389 - 43 = 346` unexamined. The count and overlap assertions agree across selected candidates, predecessor slice 2, and the coverage ledger.
- All 389 official dispositions remain `REVIEW_REQUIRED` / `NOT_AVAILABLE`; the report retains `NO_WRITE / LIVE_NO_GO` and explicitly says reviewed source points are not marked safe or closed.

## Source and static-chain checks

- All 21 selected main-source file hashes and byte counts match the current working-tree files; all 21 candidate call locations match their current source line and column. All 38 main-source excerpt blocks were checked line-for-line against their referenced files.
- All 7 SDK excerpt blocks match the local SDK working-tree files line-for-line. The two SDK file hashes match the recorded values: `client.py` `B61B32F9A2A2E61035BF88BCB7ACF669C8C7EE8E5BF5D7E1F6E375E69F053EAB`; `ctp_env_selector.py` `1FADCA9398CC7F5D00025CA1D563DB4E8E423909CFF7C80014A1F1DC81DFC861`. The SDK checkout is dirty (`ce1edd60785eb4c66fefa16a994a66946a1e068f`) and these are working-source excerpts, not release/deployment evidence.
- Static Store chain verified: constructor dispatch resolves `_resolve_bt_api_client(self.provider)` at `btapistore.py:16459`; the CTP branch is at `1761–1775`; public `BtApiStore.arm_registered_sim_execution` is at `8025–8055`; it calls the API arm after readiness checks. The nested wrapper at `1896–1931` calls `trader_client.arm_execution_for_registered_sim` and stores the result in mutable `_execution_gate_capability`; typed insert/cancel helpers at `1933–1959` pass that capability to the SDK methods.
- The dirty local SDK source describes an exact registered Hongyuan simulation-pair gate, explicitly rejects official SimNow/unknown fronts, and rechecks identity/capability on typed writes. Arming may perform settlement confirmation and server readback if the session is not trading-ready. The caller-supplied strategy/preflight digest fields are only checked for 64-hex formatting before being included in SDK-generated proof; this is not external actor approval.
- Therefore the report’s finding is a conditional, source-reachable direct Store path to the local SDK’s registered simulation arm outside the Iteration 41 runtime/actor path. It is **not** evidence that any real order was sent or accepted, does not establish production/live reachability, and does not claim the direct path is closed. The report recommends a separate decision about retiring or externally binding that direct path.

The selected Store current hash (`05268B4953A20FA0699639F7E05EE354A4BCAFC4B47915DD4BA352B26276E0D9`) differs from its historical frozen-source-manifest hash (`DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`) because the r2 rev2 Store change is already present in shared main. The report states this explicitly; all other selected source hashes matched their frozen manifest rows.

**Scope:** Static reads, SHA checks, ZIP verification, and source-line comparisons only. No imports, tests, provider/native execution, network, private config, credentials, account access, order, or cancel occurred. No source tree was modified.

Machine-readable results and the verification script are in `verification.json` and `verify-slice3.py` in this QA directory.
