# Independent QA: CTP generic SDK queue fail-close r3

## Verdict

R3 replays exactly from the frozen A028 source and is behaviorally identical to r2. The only r2-to-r3 source change is the `_is_ctp_write_provider` docstring, which now accurately says the SDK route snapshot can originate from injected API `exchange_kwargs`, is not authorization, and the method does not dereference `_api`. The r2 and r3 module ASTs are identical after removing that method docstring; the candidate test bytes are unchanged.

The narrow tested fail-close behavior remains green. This is not writer closure or authorization. A conditional stale/inconsistent `_sdk_exchanges` snapshot still lets a direct `_invoke_sdk_command` fake CTP submit reach the fake API. The generic `_invoke_sdk_command` guard also does not cover the earlier managed-CTP dispatcher branch in `_execute_sdk_command`.

## Frozen r3 packet identity

- Packet: `D:\temp\ac41-63-store-generic-ctp-queue-failclose-r3-trust-boundary-20260927`
- Latest manifest SHA-256: `A37388BA20649D7C402E119F0E74838A45F84830BE8AC1597EFA6619F7F34D6F`
- Latest `SHA256SUMS.txt` SHA-256: `30EA0B87D5276117542B1618331E50A7A87077950648CCEC4A9103619E77FA98`
- All 15 entries in the refreshed packet sums verified.
- Exact A028 preimage: `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`
- Exact r3 patch SHA-256: `C1550368359A159F18CE6777F6377CCA83DA7F948DE81B99D8DE86BEEE6CCAD3`
- Exact replayed r3 Store target: `00D31700B8554E954C52A748E2DBA09CB781DAED403EEC82AA750D1844513F55`
- Candidate test SHA-256 (same as r2): `3201896CBC984054BB8124CBBB1489A207DB349AE6CEB74CEB701DA08F21D29A`

## Independent replay and verification

A separate QA copy was created at `D:\temp\ac41-63-store-generic-ctp-queue-failclose-r3-independent-qa-20260927`. Its baseline Store hash matched A028. Strict `git -c core.autocrlf=false apply --check` and apply succeeded, and the candidate hash matched the r3 target exactly.

Guarded fake-only results:

- Candidate focus: 12 passed, 1 existing Quandl deprecation warning.
- Baseline reachability: 2 passed, 1 existing Quandl deprecation warning.
- Independent route probes: 4 passed, including `provider=other/backend=gateway` and `provider=btapi/backend=gateway` with `CTP___X`, early managed cancel rejection, and explicit BINANCE gateway positives.
- Conditional snapshot residual probe: 1 passed; it intentionally confirms the stale-snapshot behavior described above.
- Project-config Ruff: all checks passed.
- `py_compile`: passed.
- AST comparison after stripping `_is_ctp_write_provider`'s docstring: identical between r2 and r3.

The guard rejects CTP SDK/native imports, DNS, non-loopback connect/connect_ex, `create_connection`, and `sendto`. Each guard log contains only local loopback IPC for pytest; no optional SDK/native import or non-loopback network event occurred. No private config or credentials, provider, native SDK, account, order, or cancel was accessed.

## Compatibility and limits

Both gateway CTP suffix variants reject before API writer-method lookup or generic queue hooks. Managed CTP cancellation rejects before `adapter.cancel_order` lookup. CTP read-only query and `market_data_only` local submit/cancel rejection remain available. Explicit fake BINANCE SDK and gateway submit/cancel queue behavior remains available.

Store initialization can copy `_sdk_exchanges` from explicit options or fall back to injected `api.exchange_kwargs`. A separate inert probe held that snapshot at BINANCE while the fake API advertised CTP; the route classifier returned false and direct `_invoke_sdk_command` dispatched the fake CTP call. This documents a conditional mismatch, not normal correctly initialized provider behavior or an accepted route. The managed typed branch in `_execute_sdk_command` is also outside this generic sink guard.

Official dispositions remain `REVIEW_REQUIRED` / `NOT_AVAILABLE`. This remains a local fail-close candidate with no real I/O, no write authorization, and no SimNow/production acceptance.
