# Binance TH01 R2 account-window + R3 synthetic worker gate delivery

Date: 2026-10-09  
Base: existing `dev` at `5ba88c6eaf6987330ac4506d24036e34fa8fb4db`  
Proposed scope: `SOURCE_FAKE_ACCOUNT_WINDOW_COMPONENT_AND_ROOT_LOCAL_SYNTHETIC_TRANSPORT_ONLY`  
Delivery state: source/evidence whitelist prepared for Root exact-hash review and commit; this inventory did not stage or commit files.

## Reviewed result

The R2 account-window candidate and cold launcher were independently reviewed `GO_SOURCE_FAKE_ONLY`. The original review recorded 19 passing focused tests with one existing pytest configuration warning. R3 repaired the earlier simulated partial-start uncertainty; its source review was `GO_ROOT_LOCAL_SYNTHETIC_GATE_ONLY` and recorded 15 passing focused tests with one existing configuration warning.

Root's canonical source QA tool `8f3da9` subsequently ran those two focused test files in separate fresh processes. The candidate focus passed 19 and the gate focus passed 15; each process exited 0 with zero warnings. The QA recorded exact origins and matched all eight candidate/helper/launcher/owner/test/dependency source pins before and after. Private, native, SDK, network, process-spawn, and Pipe access were denied before candidate imports. The exact QA harness and JSON result are archived under the R3 Root actual folder's `qa/` directory. Tool `49da0f` updated public provenance without rerunning tests; final results remained unchanged.

Two earlier harness attempts remain documented in the archived JSON and this record. The initial combined harness reported 29 passed/5 failed after a repository basetemp rejection and a function-valued socket class observation; the shared-state root cause was not established. The second isolated attempt reported 15 passed/4 failed because a cold `ssl.SSLSocket` import encountered the fake socket class, while production source remained unchanged. The final repair changed only the QA harness: it used a short external artifact basetemp, ran each file in a separate fresh process, and imported `ssl`/`http.client` before the fake socket fixture. The final evidence is 19+15 from those two processes; it is not a passing combined-process suite.

Root then invoked the canonical R3 helper once after source precheck `47e301`: the exact command is archived at `iteration41-binance-th01-spawn-pipe-gate-r3-root-actual-r1-2026-10-09/command.md`. Root invocation `13bb2a` on host `85573` returned `ROOT_LOCAL_SYNTHETIC_GATE_PASSED`. All ten observation checks are true. The same-call worker path used a real spawned child and the accepted fixed signed-GET worker body with only synthetic `account_configuration` data (`HTTP 200`, `[]`); the result recorded one frame plus EOF, worker exit 0, no forced shutdown, closed Pipe endpoints/process, and zero active workers. Candidate, dependency, launcher, and owner pin groups matched before/after the call. Pre-exit tool `aadcf2` recorded zero active gate references, retained owners, and retained resources; the host then exited normally with code 0.

The earlier R2 synthetic gate failure remains preserved as a distinct five-file historical snapshot. It recorded child lifecycle `UNPROVEN`; the R3 result supersedes that transport defect evidence without rewriting it.

## Scope limits

This is source-fake and Root-local synthetic transport evidence only. No provider call occurred, no account-wide snapshot was issued, and no formal TH01 `PASS` was issued. The R2 candidate remains `CANDIDATE_ONLY`; provider-backed trade-universe closure, three complete `account_full` phase snapshots, actual TradeLogger ingestion, independent monitor output, and the full TH01 case gate remain outstanding. The accepted owner, protected reader, and private artifact helper are inherited dependencies and are excluded from this round's source additions.

No tests or actual operation were rerun while preparing this delivery update. `delivery-whitelist.json` pins 28 payload files and lists 29 exact quoted `-text` rules, one for each payload path plus the whitelist. Including the whitelist and a separate `.gitattributes` update gives 30 proposed commit files. The whitelist hash is reported separately to avoid self-reference. Root should recheck every payload hash, calculate the manifest hash, and confirm the index is empty before staging.