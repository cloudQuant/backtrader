# V20 Root preparation QA runner independent static review

Verdict: `HOLD_STATIC / WINDOWS_PYTEST_BOOTSTRAP_AND_CAPTURE / EXECUTION_NOT_RUN`.

## Frozen inputs checked

Packet: `iteration41-simnow-c01-v20-root-preparation-source-qa-r1-2026-10-09`.

- `artifact-pins.json`: 1,394 bytes, SHA-256 `6e512153dfecc182a2fe772f4b4be445b7dc7702a329e321825167e88346fe2b`.
- Runner: 23,968 bytes, SHA-256 `22a3f2ee7abfc3aff772e5d0fe6a56739084a7e871919a0ecdf87906d3265f14`.
- Seven non-QA payload rows matched their manifest pins. The `qa/command.txt` payload was not read or hashed, per review scope.
- The copied R5 runtime map is 9,069 bytes, SHA-256 `e3e6940ba4799b6e783ef4227a07dd43d628ba74b96e5e958a6c7ffec3a6e387`; all 26 public source rows (23 child-frame, three parent additions) matched current sizes and hashes. The three software rows were metadata only; no software payload was read.

## Blocking findings

1. On Windows, the runner installs its hard native guards before importing pytest. `_prepare_guards()` replaces `ctypes.WinDLL` at lines 427–455; `pytest` is first imported at line 488. The known cold pytest capture bootstrap imports colorama, whose Win32 loader calls `ctypes.WinDLL`. That call will hit the guard, record `native_library_load`, and abort collection as `BLOCKED_SOURCE_QA`. Use the previously reviewed narrowly bounded console bootstrap before hard denials, with candidate test/source imports still after the guards.

2. The pytest argv at lines 500–515 leaves default capture and logging setup enabled. The pinned `pytest.ini` is only `[pytest]`; it does not redirect capture or the logging file. The known Windows setup path can open `os.devnull`, which this runner's allowed-root file guard rejects. Add `--capture=sys` and direct `log_file` to a fresh file inside the allowed run output directory (or explicitly disable pytest logging if the selected tests do not use it).

## Other static observations

The runner checks the R5 packet's eight artifact rows plus the 26 public source rows before and after the focused suite. It verifies the copied packet pins and review input before collection, records current `.git/HEAD` and index metadata before/after without invoking Git, and emits a fresh UUID result path with the pinned result shape. Root must separately bind the exact QA interpreter (`D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe`, with `-I -B -Xutf8`) and check its dynamic branch/index policy; the runner records `python_origin` as a fixed label and checks pytest's origin, but does not compare `sys.executable` to that exact path or require a particular branch or empty index.

The test report hook does not inspect `report.wasxfail`, and the PASS predicate does not require a zero warning count. An XPASS could be counted as passed, and warnings do not prevent `PASS_SOURCE_FAKE_ONLY`. Tighten these gates if the acceptance contract requires exactly twelve ordinary passes and no warnings.

`result-schema.json` is pinned and its fields correspond to the constructed result object, but the runner does not validate its result against that file. Root should perform the finite schema/result check on the emitted JSON.

## Limits

This review was static and hash-based. No tests or QA command were run; no QA-path payload was read. No software/private payload, CUv2, provider/account, SDK/native, WinAPI, process, pipe, or actual gate operation was performed. This HOLD concerns only the QA runner and does not change the R5 preparation review or authorize an actual gate.