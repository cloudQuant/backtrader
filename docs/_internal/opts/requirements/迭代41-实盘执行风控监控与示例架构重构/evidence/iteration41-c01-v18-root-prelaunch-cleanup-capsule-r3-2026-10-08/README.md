# C01 V18 Root prelaunch cleanup capsule R3

This is an additive source-only successor to cleanup capsule R2. R1 and R2
remain frozen with independent HOLDs. R3 only repairs the unreachable final
preclose checks and adds state mutation regressions; it does not change the
R4B actual-driver source, R5 activation wrapper, Root result, or CUv2 source.

## Bound state and close gate

The capsule is restricted to the frozen R4B driver (`f23aa6af…`), frozen R5
activation wrapper (`ce221c68…`), R5 pin map (`3c1fdd78…`), the exact public
BLOCKED projection, and the retained outer CUv2 lease. It requires the complete
31 public + 2 software rows, a single exact `KEEPALIVE` holder tuple, and the
same exact built-in `KEEPALIVE` list object captured at admission. The wrapper's
exact built-in unresolved-job reference list must also remain the same empty
list at admission and immediately before close.

Admission rejects instance-level shadows of `verify_held`,
`postverify_and_close`, and `keepalive`. It snapshots the expected held map
independently of the lease's mutable mapping. It captures the exact current
`HeldSourceLease` class, source-pinned class functions and their code/globals,
and required driver module functions. Before close, R3 checks the retained
holder identity, lease lifecycle state, independent expected map, CUv2 bytes,
held wrapper bytes/module, and unresolved-list identity. Only after those
checks does it rebind the frozen driver and current function/class identities,
then return the captured `postverify_and_close` class function for direct call
with the retained lease. It never performs a mutable
`lease.postverify_and_close` lookup at the call boundary.

The result must be the complete R4B 22-key public projection with
`BLOCKED / admission_namespace_not_fresh`, exactly one wrapper call, verified
31/2/33 held counts, and official C01 count 0. The no-child conclusion comes
from the pinned R5 source-order proof: the unique namespace-freshness failure
occurs before the first yield, and `_run_core` reaches the fixed CLI only after
that context has yielded. Zero request/job fields alone are not treated as
evidence that no downstream calls occurred.

## Root API

After independent review, Root may use the additive capsule in the same
original owner process and thread:

```python
capsule = cleanup_module.prepare_prelaunch_cleanup(_c01_driver, _c01_result)
cleanup_receipt = capsule.cleanup_once()
```

This performs one normal CUv2 postverify/close attempt on the existing lease.
It never starts or retries activation, performs no late private-capture read,
and removes only the exact retained tuple after positive postverify and close
checks. Any mismatch or uncertainty returns a finite blocked receipt and keeps
the lease references available. The original BLOCKED result stays unchanged
and official C01 PASS remains 0.

## Verification

The focused isolated source/fake suite passed **23 tests**, with one
pre-existing pytest configuration warning. The regressions cover preexisting
and post-admission method shadows, class-method replacement, post-admission
`KEEPALIVE` container replacement and member removal, expected-map mutation,
and each mutable lease lifecycle flag. These failures are rejected before the
captured close function is invoked. The successful fake path verifies that the
captured class function is called directly once. Exact QA command and output
are pinned in `qa/command.txt` and `qa/pytest-output.txt`.

QA uses the approved isolated interpreter at
`D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe`, with
`-I -S -B -X utf8`, explicit site path
`D:\temp\iteration41-main-source-qa-20260926\venv\Lib\site-packages`,
pytest plugin autoload disabled, and packet-specific basetemp. No actual Root
cleanup, candidate driver/wrapper execution, CUv2 call, native/provider call,
network, WinAPI, process, private input, or private capture was performed.

The three copied public references and candidate files are hash-bound in
`pins.json`. Independent review is pending; do not call the API until R3 gets
GO and Root separately authorizes the one-use cleanup. Official C01 PASS
remains 0.
