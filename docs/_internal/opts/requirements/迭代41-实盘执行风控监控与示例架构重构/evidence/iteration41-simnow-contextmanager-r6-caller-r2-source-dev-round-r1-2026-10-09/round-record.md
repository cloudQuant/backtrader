# SimNow V20 context-manager repair — source delivery round R1

Status: READY_FOR_ROOT_STAGE. This packet is bound to Backtrader dev parent 88711feb0685d64910c768faa35c0bc5b0a7c6b8. This additive metadata revision follows Root stage check 1132d4, which stopped before writes or index changes after finding the public runtime source-pin manifest absent from HEAD.

## Scope

The corrected delivery contains ten payload paths plus .gitattributes (eleven changed paths total), with ten exact path-specific -text rules. The manifest is 18199 bytes, SHA-256 36753f336c81c59dc94243166279c57d3727a6ae1574ec4f432a497e3ca550f6. It records eight pinned public artifacts, the complete 32-input Root QA pin set, and the exact staged scope.

The 32 QA inputs classify as four new source/test files, one required untracked source-binding dependency, and 27 inherited public dependencies. The required dependency closure has 28 public files: the 26 source rows, bounded precheck, and runtime source-pin manifest (9,069 bytes / e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387). The runtime manifest is included as SOURCE_BINDING_DEPENDENCY_NOT_GATE_ACCEPTANCE; this does not accept a Gate or actual preparation. Root read-only check c03006 found only this manifest absent from HEAD and confirmed an empty index. Root will verify all raw HEAD pins and statuses before staging. Preserve the three known clean CRLF checkout exceptions unstaged: backtrader_runtime/ctp_front_pair_probe.py, scripts/ctp_i13_i15_outer_watchdog.py, and scripts/ctp_i13_i15_windows_job_backend.py.

## Acceptance evidence

Root focused QA tool 0ec9c4 passed 3/3 at 88711feb0685d64910c768faa35c0bc5b0a7c6b8. It recorded zero warnings, errors, failures, skips, or denials, four passing guard self-checks, and unchanged input pins/status/index. This QA was not repeated for the metadata correction.

Independent static review decision is GO_SOURCE_FAKE_CONTEXTMANAGER_REPAIR_ONLY. Its exact artifact pin is listed in manifest.json. The reviewed helper, caller, launch source, focused fixture, Root harness, result, and review remain byte-identical; only manifest and round-record metadata changed.

## Repair and limits

R6 and caller R2 validate a canonical contextlib.contextmanager wrapper and separately bind the wrapped generator globals to the exact CUv2 module. The launch R2 source is AST-parse verified only and remains unexecuted.

The consumed R1 preparation invocation in retained host 65851 remains preserved; its exact exception cause was not observed. No fresh Root preparation, credential-free Gate, provider/account operation, or formal C01 PASS occurred. Formal C01 remains 0.
