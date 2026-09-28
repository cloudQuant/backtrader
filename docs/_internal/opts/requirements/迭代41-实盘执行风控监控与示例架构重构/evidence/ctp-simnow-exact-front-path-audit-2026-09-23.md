# Iteration 41 CTP SimNow exact-front path audit (updated 2026-09-24)

**Finding:** no endpoint-selection gap was found in the config-driven read-only composition. For an admitted private `config.yaml`, the configured `ctp_simnow.td_front` and `ctp_simnow.md_front` remain the only TD/MD addresses passed to the SDK. This is a source and offline-test audit; it did not read real credentials or connect to SimNow.

## Source trace

1. `backtrader_runtime/config.py:965-1045` parses required `td_front` and `md_front` fields, rejects surrounding whitespace, and stores those values in `CtpSimNowPrivateConfig`. `ctp_simnow_operator.py` checks the pair against the exact code-owned allowlist in `ctp_artifact_provenance.py:505-550`, then copies both configured strings into the admission. The former injected-clock skew gate has been removed from this read-only path; the pair is not selected by time or calendar.
2. `ctp_simnow_readonly_runtime.py:108-153` rechecks the admission pair against the sealed private config. `_sdk_scope_from_admission` at `:171-194` copies the same pair into the SDK scope.
3. `ctp_sdk_readonly.py:415-429` calls the SDK's `official_simnow_fronts(profile)` only to compare its fixed pair with the scope pair. If they match, it constructs `TraderClient` with `scope.td_front`. In the inspected SDK checkout (`D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp\client.py`), `TraderClient` binds its constructor argument at line 1935 and registers that bound address at line 3613.
4. `ctp_sdk_market_readonly.py:413-443` takes `admitted.md_front` directly and passes it to `MdClient`. In the inspected SDK checkout, `MdClient.start` registers `self.front` at `client.py:1394`.
5. The inspected SDK callbacks handle disconnect/login and MD resubscription on the existing client/API (`client.py:1018-1096, 1554-1724`). Backtrader contains no retry that replaces the configured address with another profile. These callbacks do not implement a second endpoint choice.

The SDK also exposes standalone time/calendar/environment selection in `D:/bt_api_py/bt_api_py/ctp_env_selector.py:122-205`. That selector is **unreachable from this composition**: the adapter imports and calls only `official_simnow_fronts` (`ctp_sdk_readonly.py:109, 415`), a fixed profile-to-pair lookup in `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/ctp_env_selector.py:411-417`. Profile/environment labels are derived from and checked against the configured pair; they do not choose a replacement address.

## Offline coverage

- `tests/unit/runtime/test_ctp_simnow_config_operator_route.py:128-172` checks the configured pair is retained for the supported profile cases; `:179-202` rejects custom or mixed pairs before credentials, composition, or sockets; `:206-234` checks the configured query scope, and `:237-277` checks CLI preflight dispatch without a time source.
- `tests/unit/runtime/test_ctp_simnow_readonly_runtime.py:223-234, 305-313, 457-505` has fake TD and MD constructors that assert the exact configured strings are supplied; `:683-705` rejects a mutated sealed config before credential resolution or MD import.
- `tests/unit/runtime/test_ctp_sdk_readonly.py:208-242` asserts seven allowlisted reads, zero write counters, and no submit/cancel/settlement methods; `:336-350` rejects a profile/environment mismatch.
- `tests/unit/runtime/test_ctp_credential_binding.py:382-441` verifies that a changed configured front pair changes the non-authorizing HMAC and that reviewed-route refresh keeps the exact config and full admission binding. The reviewed-route tag payload uses schema/domain v3 after removal of its unused clock fields.

Focused offline command after removing the read-only clock prerequisite:

```text
python -m pytest -p no:asyncio tests/unit/runtime/test_ctp_simnow_config_operator_route.py tests/unit/runtime/test_ctp_credential_binding.py tests/unit/runtime/test_ctp_simnow_readonly_runtime.py tests/unit/runtime/test_ctp_sdk_readonly.py -q --tb=short
94 passed, 1 warning in 5.18s
```

The warning is the repository's unrecognized `asyncio_default_fixture_loop_scope` pytest option in this environment.

This audit establishes the local source path and fake-client contracts only. SDK artifact provenance and route registration remain separate gates; it is not evidence of a live package/session or provider acceptance.
