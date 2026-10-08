# Binance TH01 spawn/Pipe gate R1 independent review R3

Date: 2026-10-09  
Verdict: `GO_ROOT_LOCAL_SYNTHETIC_GATE_ONLY`

## Reviewed pins

| Role | Repo-relative path | Bytes | SHA-256 |
|---|---|---:|---|
| Gate helper | `scripts/iteration41_binance_th01_spawn_pipe_gate_r1.py` | 46,541 | `1186154869ed2c9ec8389d867e8caaeb492b3d2ad45cfda407950cb47bd848de` |
| Fake source tests | `tests/unit/live_certification/test_binance_th01_spawn_pipe_gate_r1.py` | 24,651 | `a0b65255415056b64b883c35789271b3c07c138e45c220be56c367f692e0d562` |
| R2 launcher | `scripts/iteration41_binance_th01_account_window_candidate_r2.py` | 11,391 | `698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6` |
| R2 candidate | `examples/000_live_certification/binance_penetration/_certification/th01_account_window_candidate_r2.py` | 62,664 | `4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63` |
| Accepted fixed-GET owner | `examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py` | 92,566 | `290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f` |

All five pins matched before and after review. Checkout was `dev` at `5ba88c6eaf6987330ac4506d24036e34fa8fb4db`; helper and test were untracked. This review did not stage or commit files.

## Source-fake checks

The isolated CPython 3.11.5 QA interpreter ran the focused test file with `-I -S -B`, explicit QA `site-packages`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH` removed, and asyncio/cache plugins disabled: **15 passed**, with the existing `asyncio_default_fixture_loop_scope` configuration warning.

The cold command `python -I -S -B scripts/iteration41_binance_th01_spawn_pipe_gate_r1.py --qa-source-only` exited 0 and returned `SOURCE_ONLY_QA`; `worker_spawned`, provider read, credential read, account snapshot, trading write, and formal pass were false. No actual spawn/Pipe gate was run.

## Review findings

The helper leaves `multiprocessing.context.SpawnProcess` bound to its canonical class so `ForkingPickler` can resolve the Process object during Windows spawn serialization. It guards direct `BaseProcess.start()` and constrains the observed `SpawnContext.Process` factory. The focused test confirms the class remains pickle-resolvable, demonstrates that substituting a non-class binding makes `ForkingPickler` reject the object, restores the class, and verifies direct start is denied without starting a process.

The wrapper sets `start_attempted` and the `worker_start` phase before delegating. It sets `start_returned` only after the delegated start and PID read succeed. Any exception during that interval sets `_GATE_START_OUTCOME_UNKNOWN`; the fixed public projection reports only `worker_start_lifecycle_uncertain`, without exception text. I inspected the local CPython 3.11.5 Windows spawn source: `CreateProcess` occurs inside `Popen.__init__` before process-object serialization, while `BaseProcess.start` assigns the returned Popen object only after its constructor returns. A pickle failure can therefore follow child creation while the Process object has no assigned Popen handle.

The helper handles that uncertainty conservatively. Its finalizer treats the sticky start-unknown flag or attempted-without-return as uncertain even if owner cleanup closes the wrapper and removes it from the owner's active list. It retains the same-call owner, process wrapper, and endpoints, keeps the RootTTY host open, and leaves source/network guards installed. Two fake tests exercise a start exception after simulated creation, including owner-side close/removal and the final Root result. They use fake process/endpoint objects only.

## Scope limits

This accepts only the next Root-local synthetic spawn/Pipe gate invocation from the interactive TTY entry. The partial-start behavior above is simulated; it is not evidence that a real child was created or cleaned up. No credentials, private captures, provider/network calls, native/WinAPI calls, real Pipe, process spawn, or Root actual path were used. The accepted R2 candidate's 19-test result was not repeated.
