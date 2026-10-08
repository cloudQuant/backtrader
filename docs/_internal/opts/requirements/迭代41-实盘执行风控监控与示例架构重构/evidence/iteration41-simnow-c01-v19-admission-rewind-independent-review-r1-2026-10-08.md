# SimNow C01 V19 admission rewind independent review (R2)

SOURCE_FAKE_ONLY_REVIEW: PASS

## Packet and source pins

Reviewed packet: `iteration41-simnow-c01-v19-admission-rewind-source-r2-2026-10-08`.

- `payload-pins.json`: 10,330 bytes, SHA-256 `2b16886181798ed85486504693baa3e894faac7604365951b54e2b5be09e0738`.
- Core ZIP: 205,745 bytes, SHA-256 `199b83b21ef0e8a2d1c2f3fd5879316f1c561c9fb95c44a7cc70e888f703aab6`; all 25 members and workspace files match their pins. The V19 manifest has 19/19 pinned source rows. R1-to-R2 core change is limited to the focused test.
- Fixture support ZIP: 52,827 bytes, SHA-256 `8d73ab3e8ab51f56c3a81496bb82f06536f59643f0c803633a7bcb1d942c641c`; all three members match exact size/SHA pins, and the R2 test checks them before importing the V17 baseline modules.
- README: 1,666 bytes, SHA-256 `26a6ae5486193f589b5d852c27d074919d541834cd197eb63f0be7212e93be15`.

V19 chain pins: issuer `3de1024b233a0eee55fba7c30df69f04afa38746c9a0e88996e0db7df283fd40`; manifest `fec7bc9d0ea5f90c1b2d0a7b8ec8bb663422ff0c2a8763fece6427a45091e5d1`; schema `95f0c05c0b6e3f80f9b6b0d7a23532ed28ddc84ffc7e8f03cfe827f4a6db30c2`; front V13 `636b1ecbd72c4a6b3c7d0911dd221ae08d684efa29f97042e168cd9b9bbff43a`; Root wrapper `167b638cf84ac9e19c430497e1930d56714c5a68f928e0b3842b300034475b29`; runner `e2d8e0481969c01a169a313de09cc1f31bd3042af46f3392130fd6c74448e05f`. Admission binding names issuer and runner separately. Worker V4, shared private helper, and R3 CLI helper remain pinned to the packet's unchanged bytes.

R2 adds these V17 test-only baseline pins: issuer (189,499 B) `fa202e00da45fced059b6409e17c2ea9d41b0f8e0f1666f56491735a7f39b795`; Root wrapper (70,858 B) `1c1b2a09c39d680b3c5cf2687dc2514a57c2faa71d8e9191cdf1444f106d650c`; runner (9,129 B) `9d34964cae9eb4b6a7435cb77a641dab6fb4c08a38eb4ac4e357a81c007cbd9d`. Focused test: 15,392 B, SHA-256 `db74fe6640a0ec1fe62e73fe0be29e9fb86dd05b15a66ac3f4d8f9a76de26854`.

## Lease and fixture review

For each retained admission, consumed-marker, and claim-file handle, V19 checks the original file identity, calls the ACL check, seeks that same handle to byte zero with `SetFilePointerEx(FILE_BEGIN)`, requires a successful seek and returned offset zero, then uses the pinned production bounded reader and compares the complete bytes with the original. Seek exceptions/failures fail closed. Namespace checks remain after the three rereads.

The cursor-backed fixture uses the production R3 CLI `_locked_readonly_file`, `_locked_file_identity`, and `_read_bounded_handle`, with fake `ReadFile`, `SetFilePointerEx`, file-information, and ACL API leaves. It reproduces V17's EOF reread failure; verifies all three V19 handles are reread from offset zero with a bounded full-length read and have ACL checks before and after; verifies per-file failed-seek and changed-content cases fail closed; and checks handles close. The ACL leaf is synthetic and asserts a protected descriptor; this does not execute Windows ACL APIs.

Independent isolated QA passed: `tests/unit/runtime/test_certification_simnow_c01_v19_admission_rewind_contract.py` — **8 passed**, with the existing `asyncio_default_fixture_loop_scope` unknown-config warning. It used the designated interpreter `D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe -I -S -B -X utf8`, explicit repo and approved QA `site-packages` paths, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `no:cacheprovider`, `no:asyncio`, and fresh basetemp `.codex-tmp/v19-lease-rewind-20261008-independent-r2`. R1's malformed `qa.command` prefix is corrected in R2.

This is source-fake evidence only. It does not exercise real WinAPI, native SDK, provider, account, or an actual SimNow run, and it does not establish official C01 PASS.
