# Iteration 10: explicit managed order time in force

Repository/branch: existing `D:/source_code/backtrader` `dev`, parent `4f3e6a1ca3c41c1e5a726d11cce162faec25b140`.

ServiceExecutionAdapter previously discarded `order.info.time_in_force` and sent GTC for every ordinary managed order. It now validates explicit GTC/IOC/FOK/DAY and sends the same normalized value to the service and recovery manifest. Ordinary and V1 sessions still default to GTC. Recovery V2 still defaults to FOK and rejects an explicit conflicting value before a journal write or RPC. No session-default configuration or Risk policy was added.

The Paper strategy fixture separately needs to request FOK explicitly through its existing buy kwargs. This source round does not claim that the AFI strategy integration has passed.

Validation used the existing focused pytest runner with no Host/provider/account activity:

- Root R1: 10 passed, two failed. New explicit-TIF forwarding, invalid-value rejection and V2 conflict rejection passed. The old exact-payload fixture omitted `deadline_ns: None`; the old V1 recovery fixture omitted the real order trade ID and a required recovery baseline.
- Root R2: the corrected payload node passed; V1 recovery still failed at the baseline guard.
- Author's diagnostic observed `service_execution_recovery_baseline_required`. The final fixture uses public `install_recovery_baseline` with matching account/strategy, empty position state and cursor zero, then asserts the persisted recovery binding and complete GTC payload.
- Author R3: only the remaining recovery node ran, one passed in 3.53 seconds. Root verified its raw result/JUnit/log hashes and unchanged source pins without repeating it. The cumulative selected set contains 12 unique passing cases; no single 12/12 run is claimed. Each run retains one known unknown-asyncio-config warning.

Raw evidence: `D:/temp/iteration10-bt-service-execution-tif-root-unit-20261017-r1`, `-r2`, and `-r3`. Production SHA-256: `1cdbb545c9707355acb6d75cb8d7de812d2bbf869efa1cbf219bcad903708a5b`; final test SHA-256: `74ab640e2e03c965922cbc2804c338193edc20eff88037075d198ac0c776da68`. Independent static review accepted the explicit-TIF behavior; final fixture review is recorded in the collaboration messages.

Only the adapter, its focused test and this record belong to this round. The exact commit and committed-blob check are recorded at `D:/bt_api_py/.codex-tmp/bt-explicit-tif-postcommit-20261017.json`.
