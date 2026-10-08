# TH01 synthetic spawn gate: partial-start source diagnosis

## Reproduced source defect

The reviewed R2 gate replaced the canonical `multiprocessing.context.SpawnProcess` class with a deny function. Its authorized factory still instantiated the saved original class. On CPython 3.11.5, a source-only `ForkingPickler.dumps` of such a process object fails because the class object is no longer identical to the module's `SpawnProcess` binding. The regression reproduces this without starting a process or creating a pipe:

- Construct `multiprocessing.context.SpawnProcess(target=abs, args=(-1,))`.
- Temporarily set a non-null spawning marker using `multiprocessing.context.set_spawning_popen(object())`.
- Replace `multiprocessing.context.SpawnProcess` with a function and call `multiprocessing.reduction.ForkingPickler.dumps(process)`.
- Result: `PicklingError`, “it's not the same object as multiprocessing.context.SpawnProcess”. Restoring the canonical class allows the same process object to serialize.

Public CPython source supports the partial-start sequence. `multiprocessing.popen_spawn_win32.Popen.__init__` calls `CreateProcess` at line 74 before dumping the process object at line 94. `multiprocessing.process.BaseProcess.start` assigns `self._popen = self._Popen(self)` at line 121 only after that constructor returns. If serialization fails after `CreateProcess`, `start()` can raise before the owner sees a process handle. The child can then encounter `spawn_main` → `reduction.duplicate(pipe_handle)` → `_winapi.DuplicateHandle`; the previously observed WinError 6 is consistent with this path. The original parent-side exception was not retrieved, so this source reproduction does not prove it was the historical exception.

CPython source identity for the checked runtime (Python 3.11.5):

| Public source | SHA-256 | Relevant lines |
|---|---|---|
| `C:/anaconda3/Lib/multiprocessing/context.py` | `bd8628d1e140d933d40ed14b51009820c1b0b9b5b6c71971df5fc761da65bd08` | Windows `SpawnProcess` class 283; `SpawnContext.Process = SpawnProcess` 308 |
| `C:/anaconda3/Lib/multiprocessing/process.py` | `67f0c2a7a3a83c92dd024705bac18619a2e123c9df77c414beb81035ea4a0e18` | `BaseProcess.start` 110; `_popen` assignment 121 |
| `C:/anaconda3/Lib/multiprocessing/popen_spawn_win32.py` | `ba4202e8a5665b9eab49cd5e282d1e3b98d4b717790d6a50534e32bdff9ce16b` | `CreateProcess` 74; `reduction.dump(process_obj, to_child)` 94 |
| `C:/anaconda3/Lib/multiprocessing/spawn.py` | `ebf9fa40eb622384c37690d8c78e7208744df031155ab4ceedab0fc791a1669b` | `spawn_main` 98; `reduction.duplicate(pipe_handle, ...)` 113 |
| `C:/anaconda3/Lib/multiprocessing/reduction.py` | `4999f8b9ae7b3e8a7f5de302612b4131498dc2e238a2c47f894905c1c63294fe` | Windows `duplicate` 71; `_winapi.DuplicateHandle` 79 |

## Correction and guard

The successor leaves `multiprocessing.context.SpawnProcess` bound to its canonical class so the standard spawn serializer can resolve it. It retains the exact `SpawnContext.Process` factory checks and the `BaseProcess.start` delegation token, so direct starts remain denied. A source-fake test proves both process-object pickle success with the canonical binding and `PermissionError` for a direct unauthorized `.start()`; a negative control reproduces the former class-resolution failure.

The process observer records `start_attempted` before delegation and `start_returned` only when the wrapped start returns successfully. Any attempted-but-unconfirmed start keeps the Root TTY host open and retains owner, process, and pipe references even when owner cleanup removed its own registry entry and wrapper/pipe close calls succeeded. The safe public projection reports only fixed `failure_phase` / `failure_category` values. It does not expose exception messages or claim child exit.

## Checks and scope

- Focused source-fake suite: 15 passed; one existing pytest configuration warning.
- Black check passed with the installed tool's supported Python 3.11 target; `git diff --check` passed.
- Cold source-only CLI passed and reported `worker_spawned=false`.
- Independent review returned `GO_ROOT_LOCAL_SYNTHETIC_GATE_ONLY` for the exact pins in `source-pins-and-qa.json`; the review copy is `independent-review-r3.md`.
- No actual process or pipe, provider/account operation, private input, or native API was invoked by this agent. Formal TH01 remains unaccepted.
