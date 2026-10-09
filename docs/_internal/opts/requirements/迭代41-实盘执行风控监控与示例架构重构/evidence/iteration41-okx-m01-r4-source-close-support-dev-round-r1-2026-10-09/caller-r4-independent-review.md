# OKX M01 R7 Root Caller R4 Independent Review

**Disposition: SOURCE_FAKE_FAILURE_COMPOSITION_ONLY21**

This review covers the frozen R4 caller and its focused source-fake test. It does not establish a successful synthetic child lifecycle, normal CUv2 scope closure, or Root host exit.

## Frozen inputs

| File | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r4.py` | 76,931 | `c081b85b553c3600b3949d1da33d4449b047fa5668d1b7e3ab9426388cf30451` |
| `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r4_source_fake.py` | 40,982 | `d4a42fecb701c3e371798a22db59a3060036d96adb07abaefb2d8669cc2e9741` |

The R4 diff from R3 is limited to the new caller/test names and R4 output namespace, a fixed per-path byte-limit map for the three exact software sources, and separating the public-source cap from software-source caps. Public source count remains 31, software source count remains 3, and the exact held source set remains 34. Every public source remains capped at 2 MiB. Software caps are fixed to `python.exe` 92,160 bytes, `python311.dll` 5,991,424 bytes, and the CUv2 source 2,344 bytes. The caller still checks exact path sets, SHA-256 pins, and path alias rejection before loading the five production modules or invoking Gate. No additional source path or pin category is accepted.

## Verification

Command:

```text
D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe -m pytest -q -c NUL -p no:asyncio --noconftest tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r4_source_fake.py
```

Result: 21 passed, exit 0. The two `PytestCacheWarning` messages are from using `-c NUL` and concern cache-path creation.

The focused suite checks exact public/software pin sets, the 2 MiB public limit, the fixed software limits, and rejection of an oversized DLL. Its composed caller test uses 31 current public source pins, three synthetic software-source byte strings, the pinned CUv2 and five production modules, the pinned Gate, and a fake Win32 kernel. The synthetic DLL exceeds 2 MiB but remains within its fixed software limit. The Gate reaches one runtime-file open, then returns `LIFECYCLE_BLOCKED`; the fake records zero `CreateProcessW` calls. The caller reports `BLOCKED/caller_gate_binding_postcheck_failed`, retains references, and reports `scope_exit_attempted=false`, `scope_exit_confirmed=false`, and `host_exit_permitted=false`.

## Limits

This is source-fake evidence for the bounded source-custody correction and failure composition only. Software bytes in the composed test are synthetic; this review did not open or inspect the actual executable or DLL payloads. The test does not establish a successful Gate/child path, normal CUv2 post-yield close, or host exit. No actual/native/provider/account/private-input operation was performed. The prior R3 actual Root attempt remains a separate blocked result and was not repeated.
