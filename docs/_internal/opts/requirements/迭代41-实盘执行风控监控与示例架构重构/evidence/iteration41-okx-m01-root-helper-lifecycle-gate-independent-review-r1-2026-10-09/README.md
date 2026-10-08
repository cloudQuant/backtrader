# OKX M01 root-helper lifecycle gate independent review

**Decision: `GO_SOURCE_FAKE_ONLY`.** This review covers the final public lifecycle-gate source and its fake Win32 tests. It supports source/fake readiness for Root's separately controlled credential-free local synthetic-child gate. It is not an actual Win32 run, account/provider acceptance, M01 route result, or formal case result.

## Frozen source pins

The final gate and focused-test pins independently rechecked before and after the test run are:

- `scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r1.py`: 35,502 bytes, SHA-256 `2faa317a695c4cc5418f0d01f59bcbd92b32303101d7dd54d982082868f1bc5f`.
- `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r1.py`: 15,142 bytes, SHA-256 `380320a9585564911b3b0ffb078c15dd84159a8ea7a5266ab87e7e5f4b7e290b`.

The gate pins the three production source dependencies:

| Source | Bytes | SHA-256 |
| --- | ---: | --- |
| `examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py` | 63,711 | `b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734` |
| `examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py` | 71,188 | `188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82` |
| `examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py` | 60,000 | `aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41` |

Earlier lifecycle-gate handoff pins were superseded during review. This decision binds only the two final gate/test pins above.

## Review findings

The gate API requires Root to pass the exact held reader, V2 supervisor, and worker module objects to `run_fixed_synthetic_probe(reader_module, supervisor_module, worker_module)`. It checks module names, resolved origins, file digests, object relationships, reader and supervisor function `__globals__` identity, and source origin for the lifecycle functions and transitive create/bootstrap helpers. The production `_hold_runtime_files` function must have the pinned source origin and supervisor globals; a fake holder is explicitly marked `source_fake_only`.

The gate invokes the pinned reader with a fixed, tiny helper payload that only writes `OKX_M01_ROOT_HELPER_GATE_R1_OK\n`. Its observations are finite booleans/codes: process creation, Job assignment before resume, source-frame write, stdin close, process wait and cleanup wait/reap, exit-code presence/value, Job process count, stdout/stderr EOF and drain completion, overflow/error state, thread joins, handle-close results, runtime-registry state, and context retention. It returns no child output, paths, handles, environment values, credentials, or exception text; `production_acceptance` is always false.

The fake suite executes the pinned reader and V2 supervisor methods through in-memory Win32 leaves and executes the exact V2 bootstrap against fake stdin/stdout. It also rejects detached-global substitutes with the pinned filename for the reader runner, supervisor writer, and runtime holder. The close-failure case models the reader ignoring a failed final Job `CloseHandle`; the gate reports `LIFECYCLE_BLOCKED` and retains the gate context.

I separately reran that close-failure case using the test's `_FakeKernel`, with `ctypes.WinDLL`, `get_last_error`, and `_hold_runtime_files` replaced by fake leaves. The finite result was `handle_close_failures=1`, `process_reaped_after_cleanup=true`, `runtime_registry_empty_before=true`, `runtime_registry_empty_after=true`, and `retained_context=true`. This verifies that gate-owned references remain retained even when the source runtime orphan registry is empty; it does not exercise a native handle.

The driver wraps the production supervisor methods and restores their identities after the call. The tests replace Win32 and runtime-file leaves only for fake execution; they do not establish Windows Job, pipe, process, filesystem, ACL, account, or provider behavior.

## Independent fake test run

Repository: `D:/source_code/backtrader`; branch `dev`; HEAD observed as `d5fcfaa2c032d715def3969af4965522fd14a6fd`.

Interpreter: `D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe`.

Exact command, run from the repository root:

```powershell
& 'D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe' -m pytest -p no:asyncio -c NUL tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r1.py -q --tb=short
```

Result: **6 passed, exit 0, 0.61 seconds.** Pytest emitted two cache warnings because `-c NUL` maps its cache directory to `\\.\NUL`: one from the cache provider and one from stepwise. No test failures or other warnings were reported.

## Root actual-call preconditions

Root's next call is separate from this source/fake review. Before and after that same call, Root must:

1. Hold the exact compiled reader, V2 supervisor, and worker modules from the pinned source bytes, then pass those exact objects to the gate. Verify module origins, source digests, relevant code objects, function-global dictionaries, and the reader-to-supervisor/worker bindings before and after execution.
2. Run exactly one credential-free local synthetic-child probe in the serialized fresh TTY. Keep its result finite and source-bound; do not treat `LOCAL_SYNTHETIC_CHILD` or any other gate status as M01 account/provider acceptance.
3. Keep the TTY, gate module, held source modules, and returned context references alive whenever process reaping, pipe EOF, Job count, drain-thread joins, handle closes, or wrapper restoration is uncertain. Do this even if the source runtime orphan registry reports empty. Do not exit or discard that host/context on uncertainty.
4. Record the gate's same-call phase and lifecycle booleans with the public observation. The prior `root_helper_lifecycle_failed` result remains unexplained by this review; the new gate may provide local lifecycle facts but cannot establish what the prior private execution did.

No actual Win32 Job/Pipe gate, private deployment read, native payload, account, provider, or M01 route was invoked during this independent review. No source/test code was edited, staged, or committed as part of the review; this README is the new public evidence artifact.
