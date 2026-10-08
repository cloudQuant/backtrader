# TH01 synthetic spawn gate failure snapshot

This packet preserves the exact helper, test, and independent R2 review bytes used by Root's one local gate attempt. `snapshot-manifest.json` records their pins and the sanitized attempt facts provided by Root. The attempt record is a transcript-backed summary, not a raw tool transcript or newly retrieved process output.

Root reported `BLOCKED_SYNTHETIC_GATE` with `synthetic_spawn_or_pipe_gate_failed`; all four post-call source pin checks passed. Root's child stderr ended in `multiprocessing.spawn.spawn_main -> reduction.duplicate -> _winapi.DuplicateHandle` with WinError 6. The parent process exited normally, and its pre-exit reference checks were empty. That does **not** prove the child exited: a failure in `Process.start()` can occur after process creation but before assignment of the process handle, so child lifecycle is recorded as **UNPROVEN**.

A pure source-only `ForkingPickler` check reproduces the `SpawnProcess` class-resolution failure if `multiprocessing.context.SpawnProcess` is replaced by a function. The exact original parent-side exception was not retrieved, so this is a reproduced source defect and a plausible explanation for the observed child error, not proof of the historical parent exception.

No provider/account read, private input read, native API call, or retry was performed.
