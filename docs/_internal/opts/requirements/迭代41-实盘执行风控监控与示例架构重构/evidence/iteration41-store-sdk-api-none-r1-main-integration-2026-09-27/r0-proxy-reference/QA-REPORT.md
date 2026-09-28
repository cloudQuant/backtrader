# Independent QA — Store `sdk_api` getter-only guard r0

Verdict: **NO_MERGE as a security/authority boundary**. The narrow getter behavior passes its fake focus, but ordinary same-process Python introspection can recover the original raw client and invoke a fake write method. The candidate therefore narrows the ordinary property surface; it does not isolate or protect the underlying SDK object.

## Frozen input and replay

- Frozen root: `D:\temp\iteration41-store-sdk-api-guard-only-20260927\freeze-r0`
- Manifest SHA-256: `68E78410E35C41C02843CE44D67D825E9AFA6E42566840E56565A3883323E91C`; its `manifest.sha256` sidecar matches.
- Patch SHA-256: `687AA34EEE0A94ED042ED5447883A11DA332338750DD9B6772221DB9AF4A5709`; `git apply --check` against the unchanged source preimage exited 0.
- Preimage `backtrader/stores/btapistore.py`: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF` (matches the current main-tree source at review time).
- Preimage existing Store test: `F7E1FA01AA383367F518C61A0AE30285DB2C8EEFF22B9CF75BA0E1C3D774F853`.
- Candidate Store source: `16EFA561A56465B1BD8165318F705EEA240A7A6D2E97CDE3B68286A41A778575`.
- New focused test: `9643D7659E7B95E60560BB3990A13079233F5DCBA941A36AB0B73DD885449E6E`.
- Independent replay used the copied candidate tree, CPython 3.11, `--noconftest -p no:asyncio`, and a `sitecustomize` meta-path guard rejecting `bt_api_py`, `bt_api_ctp`, and `_ctp`. Result: **5 passed, 0 failed**, one existing `asyncio_default_fixture_loop_scope` warning. JUnit SHA-256: `5BC54F47CB28E622FD001389EFBD478AFE119ABB1FA264ABFC17B98F89416881`; stdout/log is `focused.log`.

Two exploratory attempts to exercise managed `_ensure_api_ready()` without a supplied API were stopped by the import guard at the attempted `bt_api_py` import; no SDK module loaded. The final introspection probe instead used an injected fake factory on the unmanaged CTP branch and triggered no blocked import.

## Behavior reviewed

The five candidate tests cover a managed `provider="btapi"` with a CTP exchange marker, all four allowed methods, ordinary attribute denial for write methods and private names, gateway/forwarding/unmanaged/no-client CTP returning `None`, non-CTP direct identity preservation, and an internal read-only CTP metadata query. The unstarted managed CTP Store with no client returns `sdk_api is None` as asserted.

The mechanical example calls exactly these four allowlisted methods: `build_ctp_execution_approval_context`, `redeem_ctp_execution_approval`, `confirm_ctp_settlement_from_approval`, and `reserve_ctp_execution_budget`. However, at `examples/ctp_options_simnow_mechanical_operator.py:966-968`, when the property is `None`, it calls `store._ensure_api_ready()` and keeps the raw return value. `BtApiStore.start()` and `_ensure_api_ready()` are explicitly unchanged by this patch. This fallback is a remaining raw-handle path; the focus does not test or remove it.

## Introspection counterexample

For the slots-backed view, ordinary `getattr` rejects `_api`, `_invoke`, `__dict__`, `_CtpSdkAuthorityView__api`, and `submit_order`. But the same fake view yields the exact raw API through each of:

1. `object.__getattribute__(view, "_CtpSdkAuthorityView__api")`;
2. `type(view).__dict__["_CtpSdkAuthorityView__api"].__get__(view, type(view))` (the slots member descriptor); and
3. the `self` retained in `view.reserve_ctp_execution_budget.args[0]`, followed by `object.__getattribute__`.

The probe then called `raw.submit_order(...)`; the in-memory fake write counter recorded `submit_order`. Probe JSON SHA-256: `2F9E317738AC5BACE16CFD8AF9723AEDBD46A1B24B3CB0B972C35B57291AF974`.

This is expected Python object-model behavior, not a defect that another `__getattribute__` check can close. A caller holding the Store also retains existing same-process access paths such as `store._api` and `store._ensure_api_ready()`. The candidate may be an API ergonomics wrapper, but it cannot serve as a trust or write-authorization boundary. No legitimate mechanical allowlisted method was removed in this review; the unresolved issue is raw-client access, not a failure of those four calls.

No main-tree source or test was edited. No SDK/native/provider, private configuration, credentials, network, or live operation was used. The candidate does not establish CTP or account authorization.
