# Credential safety migration replay

- Isolated source: `D:\temp\credential-safety-r2b-migration-20260927`
- Base commit: `ad2c142b9a8b42cede85886528c681abdfcb8096`
- Store preimage SHA-256: `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`
- Replayed r2b patch SHA-256: `1A16AADB94EDB99924553D6472BF72DCB02BD04C7F994276816D91991A729F37`
- Migration patch SHA-256: `CCE753315DC4B23F1BAF6C644962B5AE479AF6377255E067512C9B6A976A7657`
- Pre-replay overlay hashes: `overlay-before.sha256`

## Test results

Successful runs used `python -B -m pytest -p no:asyncio` because the globally installed `pytest-asyncio` plugin fails collection here (`Package` has no attribute `obj`). Disabling that unrelated plugin leaves one existing warning for `asyncio_default_fixture_loop_scope`.

- Before r2b replay: `tests/unit/stores/test_credential_safety.py` — **7 passed**; JUnit `before.junit.xml`, SHA-256 `54DA1975C2990D8D2043C438E159EC069A6C799B02CBC708A442EBAF96E9CDEF`.
- After exact r2b replay, before migration: **4 passed, 3 failed**; JUnit `r2b-before-migration.junit.xml`, SHA-256 `E81501CB53E496029A13954C706DEDAA14826C2CC184EF51BC8D87DCFCF2B522`. Failing nodeids:
  - `tests/unit/stores/test_credential_safety.py::test_repr_does_not_leak_password`
  - `tests/unit/stores/test_credential_safety.py::test_str_does_not_leak_password`
  - `tests/unit/stores/test_credential_safety.py::test_repr_is_informative`
- After migration, those three focused nodeids: **3 passed**; JUnit `after-focused.junit.xml`, SHA-256 `216FD2CD45CA61982AE417DFCCAD9250EF4CBC8403D53BC731813BD99613E429`.
- After migration, containing file: **8 passed**; JUnit `after-file.junit.xml`, SHA-256 `DF8C31DE8A70848BEBE9547EBE3CE0F26A0C7962AF16AE1A9285EC2B08205CC2`.

## Migration

The three repr/str tests use an inert, code-owned `okx` Store with synthetic credential-shaped values and retain the no-leak and masked-account assertions. A new negative guard sends a trap credential mapping and a trap SDK class through the explicit CTP route with `autostart=True`; it requires the documented fail-closed error, so neither trap can be touched. Existing recursive masking tests remain unchanged. No private configuration, real secret, SDK, native code, network, or order path was used.

`git diff --check` passed. The isolated source contains the exact r2b replay plus this one-file migration; the shared checkout was not modified.