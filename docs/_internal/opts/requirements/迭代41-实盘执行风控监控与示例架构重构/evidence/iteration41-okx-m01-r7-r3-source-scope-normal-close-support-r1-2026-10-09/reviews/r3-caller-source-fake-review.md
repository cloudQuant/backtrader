# OKX M01 R7 Root Caller R3 Independent Review

**Disposition: SOURCE_FAKE_FAILURE_COMPOSITION_ONLY20**

This review covers the frozen public caller and its source/fake test. It does not establish successful synthetic child execution, normal CUv2 source-scope closure, or Root host exit.

## Frozen inputs

| File | Bytes | SHA-256 |
|---|---:|---|
| scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r3.py | 75,579 | eb887d64e125d80e7e33736b7b9b860a947e91ed5967926f68e3940b6b07432a |
| tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r3_source_fake.py | 38,953 | 3a97722fb668fc7825fd336c3930aba76ffe8c8a4a24d285df95bd2f8b1fd7bd |

The caller binds the public CUv2 source snapshot at 2,344 bytes / SHA-256 e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246.

## Verification

The exact isolated command was:

    D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe -m pytest -q -c NUL -p no:asyncio --noconftest tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r3_source_fake.py

Result: 20 passed, exit 0, with two expected pytest cache warnings caused by -c NUL.

The test checks the caller’s exact 31-public/3-software source set, CUv2 source/function/global bindings, all five production module bindings, and the exact Gate source binding. Its full caller fixture invokes the Gate once with a fake Win32 kernel. Synthetic runtime executable bytes reach the production runtime-file verification path; the pinned source checks the digest before the CreateProcessW call. The fake records one runtime-file open and zero process-creation calls. The projected result is blocked and reports process_created false. The caller retains its Python references; scope exit was not attempted or confirmed, and host exit permission remains false.

## Limits

This is evidence for the composed failure path only. The fake executable and DLL bytes are deliberately synthetic and cannot satisfy the fixed production runtime digests. The successful Gate path, successful child lifecycle, clean caller CUv2 normal close, and host exit were not exercised or established. This review does not authorize or report an actual/native/provider/account/private operation. The reviewer did not access the Root host or software payloads.