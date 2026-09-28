# Mechanical SDK API boundary tests — clean r2 freeze

This directory is the clean freeze. It contains no replay tree and no stale or failed replay log.

- Canonical tests-only patch: `tests-only.patch`, SHA-256 `5DB64E45C19C63F060786740242B081998ED079E2E4D7086B4C7A99201E453F7`.
- Adds only `tests/unit/test_ctp_options_simnow_mechanical_api_boundary.py`; candidate SHA-256 `3F462651E3CC5F66B990B495BE2BFC50913BB60E11D17D28F02F215E67998783`. The target was absent in main when checked; `git apply --check` passed.
- Fresh exact isolated replay applied the separately frozen source patch SHA-256 `299CD0215A8636F25C7E3B74F70CD05C30372059EFC1150E9BB96A47F668B70C` to source preimage `AA4292252D86E560A733B1030CE3C1438BC37FD99CD5B66518C853FD87CCFA19`, then applied the tests-only patch.
- Focused pytest: **29 passed, 0 failed**, with one existing Quandl deprecation warning. See `focused-tests.txt` and `focused-junit.xml`.
- Ruff: **PASS** (`ruff.txt`). SDK/native/network guard event list is empty (`guard-events.json`); harness is retained as `sitecustomize.py`.

The added fake tests prove `sdk_api is None` raises `STORE_SDK_API_NOT_READY` without calling `_ensure_api_ready`, and a supplied public `sdk_api` is forwarded unchanged to a sentinel settlement boundary without private fallback. The sentinel stops before any API/write action. This tests the local fail-close compatibility boundary only; it confers no route or write authority. `hash-index.json` binds every other file in this clean freeze.
