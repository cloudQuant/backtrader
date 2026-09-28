# Iteration 41 G1 overlapped-I/O custody — main integration

Date: 2026-09-28. This archive records one local pipe-channel custody subgate. Independent QA verdict: `GO_LOCAL_SUBGATE` only. **Strict whole-command G1 remains `NO_GO`; ordinary CTP preflight remains closed.** No live dispatch or write permission follows.

## Change identity

The frozen candidate changed only the worker output-channel source and its focused test. Main now has those exact candidate bytes:

| Artifact | SHA-256 |
| --- | --- |
| [`scripts/ctp_i13_i15_worker_output_channel.py`](../../../../../../../scripts/ctp_i13_i15_worker_output_channel.py) | `4f9ff31428cdfd9d62acc8118ae4bb00bc09cc0e5883fb07c6b1daea85f41178` |
| [`tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py`](../../../../../../../tests/unit/scripts/test_ctp_i13_i15_worker_output_channel.py) | `25332e48979f7827fa97e5dc4c8fa4fb7acd8eb17262c505bde4f4afec182861` |
| [Frozen patch](candidate/PATCH.diff) | `c27ddf0d605a9705956dff9ba00b05f3b6640492162c8e58f4e07d4791a44bdd` |
| [Frozen manifest](candidate/FROZEN-MANIFEST.json) | `074235d2ff29afb6256ef385f29f5c6b7a9e84be8eacbb3bc3fb4fbaa472668c` |

The change cancels pending pipe I/O, consumes final connect/read OVERLAPPED completion before releasing its storage/events or associated pipe handle, and retains unresolved channel custody on missing/unknown completion. It binds cleanup to the existing absolute D and rejects frame publication after D. Independent QA replayed the frozen patch and verified its output hashes against this main checkout.

## Verification records

| Scope | Result | Raw evidence |
| --- | --- | --- |
| Main guarded channel focus | 33 passed, exit 0; 1 existing pytest configuration warning | [log](main-focus/pytest.log), [JUnit](main-focus/junit.xml), [exit](main-focus/exit.txt), [guard](main-focus/guard-logs/23572.json) |
| Adjacent 12-file guarded I13/I15 suite | 305 passed, exit 0, 60.66s; 1 existing pytest configuration warning | [log](adjacent-suite/adjacent.log), [JUnit](adjacent-suite/junit.xml), [exit](adjacent-suite/exit.txt), [guard](adjacent-suite/guard-logs/27784.json) |
| Independent candidate QA | `GO_LOCAL_SUBGATE`; replay + adversarial additions 36 passed, Ruff clean, compile exit 0 | [QA receipt](qa/INDEPENDENT-QA-RECEIPT.md), [QA test source](qa/qa-extra-test-source.py), [raw QA log](qa/qa-focus.log), [JUnit](qa/qa-focus-junit.xml), [exit](qa/qa-focus-exit.txt) |

The adjacent suite contains: `bootstrap_receipt_runtime`, `guardian_deployment_anchor`, `inert_deadline_supervisor`, `outer_watchdog`, `parent_launcher`, `readonly_roles`, `runtime_closure`, `sealed_import`, `windows_guardian`, `windows_guardian_service`, `windows_job_backend`, and `worker_output_channel`.

Both main guard records contain `events: []` and `native_modules_loaded: []`. The focused and adjacent main test outputs are local Windows-only regression evidence. QA also used inert Win32 fakes; its two local named-pipe smoke tests use a local Python child. No CTP native SDK/provider, trading credentials, or external network was used.

## Static inventory check

A fresh official collector run reports 363 writer candidates and 97 dynamic candidates across 355 files, zero parse errors and zero unclassified paths. Exact ordered writer and dynamic rows match the current checked inventory; zero records were added, removed, or moved. The changed channel source has zero inventory rows. This is inventory coverage only, not writer closure.

- [Fresh collection](inventory/fresh-collection.json), [collector output](inventory/collector.log), [exit](inventory/exit.txt)
- [No-change comparison](inventory/no-change-result.json), [comparison script](inventory/compare_inventory.py)
- Current inventory: [`live-execution-inventory-candidates.json`](../live-execution-inventory-candidates.json), SHA-256 `0874a81ac23ba4f659acaac833a976ecec44fa892a3a97778ea3d9779db67a67`.

## Decision boundary

This subgate establishes orderly custody of pending overlapped pipe operations in the tested cases. It does not bound synchronous `CancelIoEx`, `CloseHandle`, `LocalFree`, SCM operations, CLI/bootstrap startup, or top-level Windows scheduling. A prewarmed service request SLA starts after the service is already running and its identity is checked; it does not establish a whole-command deadline that includes CLI launch, service startup, or SCM. Therefore strict whole-command G1 remains **`NO_GO`**, and ordinary CTP preflight remains **closed** pending a separately accepted bounded Windows Job supervisor.

Archive packaging made no additional source or test edits; the two integration files listed above were integrated in the main checkout before packaging. No acceptance matrix, shared evidence index, or repository-level README was edited for this archive. Detached hashes are listed in [SHA256SUMS.txt](SHA256SUMS.txt).