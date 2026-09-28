# R10 independent static-review addendum (post-freeze)

This is a post-freeze source review supplement to the R11 design audit. The original R11 design source remains byte-for-byte preserved at `frozen_source/R11_G1_HARD_DEADLINE_AUDIT.md`; the original R10 source remains unchanged in the frozen R10 author archive.

The independent R10 replay/static reviewer identified an unbounded broker shutdown path in the frozen `r10_custodian.cpp` (SHA-256 `4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3`):

- `WriterThread` calls `CancelIoEx` at line 200 and then unconditionally calls `WaitForSingleObject(c->ovEvent, INFINITE)` at line 205 when the cancel event wins. If cancellation fails or the final I/O completion/event never arrives, the writer thread can remain blocked and never set `writerDone` at line 216.
- `BrokerMain` sees shutdown at lines 333–337, signals `cancel` when `writerDone` is false, and does not break its loop until `writerDone` becomes true. It can therefore remain in its `Sleep(1)` loop if the writer is stuck. After the loop, line 340 also performs `WaitForSingleObject(writer, INFINITE)` before closing broker resources.
- This means caller-side UNKNOWN/ticket CAS does not bound broker shutdown, cancellation drain, or control release. Without an already-live higher custodian holding independent process/Job controls, R10 cannot claim the reaper remains available to prove eventual Job-empty. A higher custodian that itself blocks still has the same top-level user-mode limitation documented in R11.

**Evidence class: static source-path review only.** R10’s successful trials did not dynamically trigger a stuck writer, failed `CancelIoEx`, missing kernel completion, P14, or higher-custodian failure. This supplements the R11 risk analysis; it does not change the frozen R10 source/trials or claim a reproduced Windows hang. G1 remains closed.
