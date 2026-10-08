# Optional16 R33 Root preparation driver R1

This packet adds a default-closed Root driver for the already reviewed R1
preparation helper and R1 call adapter. It builds the frozen R27 metadata
payload in memory from hash-pinned public R5/R27 source, opens the existing
Entry R2 production V4 source scope on the owner thread, adds only the two
preparation helper source rows, and calls the reviewed adapter with V3/V4
bytes reread from that same scope.

Entry R2's pinned pre-installer prefix derives the source map from its held
inputs. It validates the 518-row cold request, 575-row active public map, and
their exact 582-row union, then adds the 5-row software map and derived support
union to that same scope. The three fixed profiler modules are verified only
after these rows are held. The call ends before the R5 worker installer. The
driver never calls Entry R2 `run()`, the worker installer, an R27 control or
claim, a child process, an SDK, or a provider.

The frozen R27 payload includes fixed control-path strings because the R5
payload builder emits them as metadata. This driver does not inspect, create,
clear, or reuse those paths. The previously consumed R27 claim is preserved.

## Root TTY procedure

Run the procedure only on the Root-owned Windows host after checking this
packet's source index and current public dependency pins. Use the pinned
CPython 3.11.5 runtime on the owner thread and keep the interpreter process
open until a finite receipt is returned. The procedure performs source holds
and the existing profiler proof; no credential or provider configuration is
an input.

Start a fresh interactive interpreter from PowerShell:

```powershell
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
& 'C:\anaconda3\python.exe' -I -S -B -X utf8
```

At the Python prompt, read the public driver once with its bound size limit,
check the exact pin from `source-index.json`, and compile those same bytes:

```python
from pathlib import Path
import hashlib
import json
import types

path = Path(r"D:\source_code\backtrader\scripts\iteration41_optional16_r33_root_preparation_driver_r1.py")
with path.open("rb") as stream:
    raw = stream.read(256 * 1024 + 1)
assert 0 < len(raw) <= 256 * 1024
assert hashlib.sha256(raw).hexdigest() == "7930bb76a89b4a29721b30aac40163bebb2714667474961a4a058e066d62d71c"
module = types.ModuleType("iteration41_optional16_r33_root_preparation_driver_r1")
module.__file__ = str(path)
module.__package__ = ""
exec(compile(raw, str(path), "exec", dont_inherit=True), module.__dict__, module.__dict__)
receipt = module.prepare_root_held_source_gate(requested=True)
print(json.dumps(receipt, sort_keys=True))
```

The request flag only calls the bounded preparation path. A successful receipt
must report `PREPARATION_VERIFIED_NO_AUTHORITY`, 582 public rows, 5 software
rows, 3 profiler modules, `before_r5_worker_installer`, and `scope_state=CLOSED`.
The receipt carries no authority. Stop after that receipt.

If the result reports a retained or unknown scope, keep this interpreter
process open, do not retry in this process, and have Root reconcile the scope
through its owner-thread procedure. The driver deliberately does not attempt a
second close after the frozen R1 release path. A failure before scope creation
returns `NO_SCOPE_OPENED`; the one-shot request still prevents a retry inside
that interpreter.

## Source and map bindings

The driver pins these public inputs directly: Entry R2, Root held-source V3
and V4, R5, the R27 invocation and supervisor sources, the frozen R1
preparation helper, and its reviewed R1 call adapter. The packet index also
inherits the exact 27 fixed dependencies from the call-adapter packet and
binds that packet's independent review record.

Entry R2 and the reviewed helpers retain their fixed source contracts:

- The public map has 582 rows after exact cold/active union derivation.
- The software map has 5 rows; the support union is derived from held source
  bindings instead of a driver-authored subset.
- V4's R29 proof uses the three fixed profiler source/cache descriptors from
  the held scope. Cache content is never returned in the receipt.
- V3 performs same-handle postverify and release. Any failure or uncertain
  close remains retained for the Root process.

The prior R1 helper review is `GO_SOURCE_FAKE_BOUNDARY_ONLY`; the prior call
adapter review is `GO_SOURCE_FAKE_CALL_GATE_ONLY`. Neither review ran a real
scope or V4/R29 against cache inputs. This new driver's tests also avoid scope
opening and cache reads.

## QA and limits

The focused source-fake tests passed **4 tests**, with one existing pytest
configuration warning. The final run used the isolated source-QA interpreter,
disabled plugin autoload and cacheprovider, cleared `PYTHONPATH`, and used the
unique repository basetemp
`.codex-tmp/m01-root-prep-driver-r1-freeze-focus-20261009-4a65`.

The tests exercise default-closed behavior, one-shot retained-state reporting,
exact public payload construction, default-disabled R27/R5 switches, and the
receipt's exact row/close gate. They do not open a real source scope, read
profiler cache payloads, invoke V4/R29, call Windows APIs, start a process, or
establish any Optional16 acceptance. The driver is unregistered and has no
`__main__` execution path.

## Candidate files

- `scripts/iteration41_optional16_r33_root_preparation_driver_r1.py` —
  18,779 bytes, SHA-256
  `7930bb76a89b4a29721b30aac40163bebb2714667474961a4a058e066d62d71c`
- `tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_driver_r1_source_fake.py`
  — 3,823 bytes, SHA-256
  `585a6a3f1b2e266cf7ee1d8c9257b57e679077f98329dfc38865b2b89f01f362`

`source-index.json`, `qa-summary.json`, `source-packet.zip`, and
`checkpoint.json` bind the source closure and this source-fake run.
