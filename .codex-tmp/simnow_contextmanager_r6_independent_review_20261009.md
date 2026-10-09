# SimNow V20 context-manager R6 independent static review

**Decision:** `GO_SOURCE_FAKE_CONTEXTMANAGER_REPAIR_ONLY`

## Reviewed pins

- Preparation helper: 24,159 bytes, SHA-256 `02ac13bfd45c6ad94e0c8666bca4e05182a727eaf2449a1b21cb6b7b72be581f`.
- Root caller R2: 24,722 bytes, SHA-256 `359fd47ec9bb9e516b73b51465b675c977ae045167580ebb0ed0cb3b846c8ad0`.
- One-shot launch R2: 5,782 bytes, SHA-256 `9af785b32f1a807867789f70268c2580b43c032bcf2f7857ef4231a6a5ec7429`.
- Focused source fixture: 12,443 bytes, SHA-256 `7f913b6e3a5b91533a0b296c85e71d3cd6bf21c02809d8a7eb00e9789bd8a529`.

## Findings

R6 fixes the false assumption that the `contextlib.contextmanager` wrapper's globals must be the CUv2 module globals. In `simnow_v20_root_preparation_host_r6_20261009.py:312-342`, `_contextmanager_wrapper_matches` requires the wrapper's `__wrapped__` to be the exact generator, reconstructs the canonical wrapper through `contextlib.contextmanager(generator)`, and matches wrapper code, `contextlib.__dict__`, and closure contents by identity. `_cu_v2_module` at lines 350-385 separately binds the generator's globals and filename to the CUv2 module. Caller R2 repeats this check after entry at `simnow_v20_root_preparation_actual_caller_r2_20261009.py:276-303`; it does not equate wrapper globals with generator globals.

The loader and caller retain exact source/function/global identities. Caller R2 pins the helper at its current `.codex-tmp` path and hash; delivery must preserve that path. R6 bounded-reads and hash-checks the pinned precheck and caller before compiling exact bytes at lines 164-252. Caller R2 verifies the entered-state precheck validator, driver snapshots, `_outer_lease_current(require_entered=True)`, public-module byte pins, CUv2 wrapper/generator bindings, and the pristine gate/activation/native states at lines 306-489. The unchanged pinned driver likewise stores and rechecks wrapper and generator bindings separately.

The caller installs its import guard before invoking R6, which loads and runs the bounded public precheck and binds the 26 public modules (`actual_caller_r2:544-568`; `host_r6:215-250,415-505`). R6 builds empty-path package shells and does not execute package initializers. The focused fixture's first test is authored to exercise the real bounded precheck under that caller guard without CUv2; its other two tests cover the canonical wrapper and three rejection shapes. I reviewed these tests but did not run them; the reported author result of 3/3 is not independently verified here.

The 2 MiB read cap applies to public source files. The caller checks the exact three-row software pin map without applying that cap to software paths. The successful path enters the CUv2 lease, which is expected to hold and verify the exact software pins; this review did not inspect CUv2, executable, or DLL contents or verify their external size bound.

R6 appends and retains the host before lease entry and delegates uncertain-entry retention to the pinned driver (`host_r6:568-583`). Caller R2 does not close, clear, retry, or invoke `host.invoke_once`; its postcheck requires the gate and activation latches to remain unused. Launch R2 invokes `prepare_once` once, retains any caught exception object privately, and prints only a finite category and safe summary (`launch_r2:51-105`).

## Evidence boundary

This is a public-source static review only. No tests or candidate execution ran. No CUv2, executable, DLL, config, private input, host, process, provider, account, or Git operation was accessed. This decision supports only the source/fake context-manager repair; it does not establish Root preparation, Gate, provider/account, or formal C01 acceptance. The previously consumed host 65851 and R1 outcome remain untouched; do not retry there.
