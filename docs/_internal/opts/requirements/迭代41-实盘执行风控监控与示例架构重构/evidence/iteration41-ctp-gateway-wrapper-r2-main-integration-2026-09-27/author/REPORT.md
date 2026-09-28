# CTP gateway wrapper direct-write guard R2 rebased on Store R5

Frozen 2026-09-27 as a temp-only patch against the landed Store R5 source. The shared source tree was not edited.

## Hashes and replay

- Store R5 target SHA-256: `40F776E783388DFA0A5499501E5886744FFD1D74D259E17D3ADECD9A20A5C457`
- Candidate Store source SHA-256: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`
- Fresh replay source SHA-256: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF` (matches candidate: True)
- Patch SHA-256: `DCD748DBF2D1041F5B524278F32E2CE696BDC9080980BB3430415D6F1BFF1451`
- Focused test SHA-256: `7CFB514C466A300A0A47339748F6D0ECF88B2A409B114373A131F2B7B2101BE9`
- Focused replay tests: 6 passed.

Replay by copying the Store R5 target into `replay/backtrader/stores/btapistore.py`, then running `git -C <candidate-root>\replay -c core.autocrlf=false apply --check -p2 <candidate-root>\r2.patch` and `git -C <candidate-root>\replay -c core.autocrlf=false apply -p2 <candidate-root>\r2.patch`. The manifest records the exact PowerShell test command.

## Behavior

The built-in Store wrapper receives its authoritative `_is_ctp_session_provider()` result in an internal marker. CTP session classification overrides an exchange label. The wrapper treats exact CTP and any `CTP___…` venue prefix as CTP; only exact normalized `BINANCE`, `IB_WEB`, `OKX`, and `MT5` gateway names remain enabled for direct delegation. Unknown, non-string, and malformed names fail closed. This allowlist reflects the static local `GatewayRuntime.ADAPTER_REGISTRY`; its source hash is in the manifest.

CTP and unknown exchange wrapper construction does not import or construct `GatewayClient`. The public submit/create/cancel guards run before lazy `_client` access. Non-write methods can still lazily construct the client; explicit supported non-CTP gateway behavior remains eager. The tests use only an AST-extracted factory and fake gateway module/client. CTP cases verify zero import attempts and zero fake-client construction. No credentials/config, real SDK/native import, network, or provider/broker I/O occurred.

## Limits

`wrapper._client` remains a direct raw-client bypass; custom Store `api`/`api_cls` and direct SDK construction are outside this patch. Same-process mutation/override can bypass Python guards. CTP read/connect operations can still import/construct and potentially connect a real client. This is not account-level authorization or SimNow/production acceptance.
