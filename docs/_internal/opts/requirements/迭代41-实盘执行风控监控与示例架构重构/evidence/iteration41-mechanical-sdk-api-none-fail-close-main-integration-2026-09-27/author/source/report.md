# Mechanical operator private-API fallback QA

Date: 2026-09-27

## Verdict

The line-968 fallback is **not reachable through the current default operator path**. `MECHANICAL_EXECUTION_ENABLED` is `False`; both `run_mechanical_cycle` and CLI `main` invoke the same fail-closed guard before credentials or API work, and `main` does so before reading the env file. Both pinned trust-root hashes are `None`; their validator raises `*_TRUST_ROOT_NOT_PINNED` before reading root bytes or resolving credentials. The direct Store builder also rejects without an explicit test-only token and injected fake Store, while `run_mechanical_cycle` supplies neither.

The fallback is still a concrete conditional bypass in the source. `BtApiStore.sdk_api` only returns `self._api`; when it is `None`, `_ensure_api_ready` is documented and implemented to import/construct `bt_api_py.BtApi`, connect/start it, and query balance. If the current release gates/pins were changed and a caller supplied an unconnected Store, this private call could start the SDK session. The candidate replaces that fallback with a stable fail-close error.

## Candidate

- Temp-only root: `D:\temp\iteration41-mechanical-sdk-api-failclose-r0-20260927`
- Patch: `candidate.patch`, SHA-256 `299cd0215a8636f25c7e3b74f70cd05c30372059efc1150e9bb96a47f668b70c`
- Main source preimage SHA-256: `aa4292252d86e560a733b1030ce3c1438bc37fd99cd5b66518c853fd87ccfa19`
- Patched source SHA-256: `549276111279275beb000d8104c4330a6d11b7c181ae66087079a555af26d81f`
- One-file, one-line change: `api = store._ensure_api_ready()` becomes `raise MechanicalBlocked("STORE_SDK_API_NOT_READY")` when `store.sdk_api is None`.
- The patch passes `git apply --check` against main; it was not applied. The main source remains at the recorded preimage.

## Fake verification

A temp-only test used a `FakeStore` with `sdk_api is None` and `_ensure_api_ready()` that raises if called. To exercise this otherwise unreachable branch, the test monkeypatched the disabled execution gate and earlier admission, receipt, trust-root, credential, and front resolvers to synthetic no-I/O stubs. It asserts `MechanicalBlocked("STORE_SDK_API_NOT_READY")` and proves the private method was not called.

The patched overlay ran the existing `tests/unit/test_ctp_options_simnow_mechanical_cycle.py` plus the new fake test: **28 passed**, with one existing Quandl deprecation warning. Provider/native import and socket guards recorded `[]`. Ruff passed for the patched module and added test under the repository configuration. No credentials, `.env`, real Store, SDK/native import, network, or provider were used.

## Compatibility and residual

Default behavior is unchanged because the cycle remains disabled. A Store with a non-null public `sdk_api` is unchanged. A cycle explicitly enabled in a future release now blocks if its injected Store does not expose a ready public API; such a release would need a separately reviewed public startup contract. No route is enabled and the writer audit disposition remains unresolved.

Manifest: `manifest.json`.
