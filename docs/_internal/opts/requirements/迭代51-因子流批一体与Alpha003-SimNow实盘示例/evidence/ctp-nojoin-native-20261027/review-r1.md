# Static review: CTP no-Join native gate

**Verdict: GO for one credential-free native API primitive run only.**

Reviewed `.codex-tmp/i51_ctp_nojoin_native_gate_20261027.py` (12,392 bytes; SHA-256 `6841e813cbfa38cab6e5272addf4e14ec29aa006c00621290ddb907249e7976f`). Review was static; the gate was not imported, executed, or tested.

The source pins the installed consumer interpreter root, installed `bt_api_ctp.ctp.client` path and `client.py` digest; uses only `127.0.0.1:1`, verified as unserved; creates separate MD and TD API/SPI instances; and orders `RegisterSpi`, `RegisterFront`, `Init`, SPI detach, and one captured `Release()` call per API. It has no `Join()` call or credentials, configuration, client login, provider endpoint, query, or account operation. API/SPI references, worker references, and exceptions remain in `GATE_STATE` on incomplete or failed release paths. The result is explicitly limited to `COMPLETE_OBSERVED_WINDOW_ONLY`.

For the one Root run, launch the pinned consumer with the documented `python -I -i` host and independently verify the approved installed artifact pins; the gate checks `sys.prefix`, module path and `client.py`, but does not assert interpreter startup flags or the native extension digest. Keep the host and retained references alive if setup or release hangs or fails; do not retry in the same namespace, manually release, or exit that host.

Evidence boundary: this can establish the observed `Init`/detach/`Release` returns on the closed loopback front and the bounded post-release observation window. It does not establish `stop_and_wait` receipt behavior, complete native callback quiescence, native thread termination, SDK production integration, or account/provider acceptance. Callback counts cover only the listed Python SPI callbacks during the observed windows; `join_calls=0` and similar zero counters describe this gate's own actions, not internal SDK instrumentation. A zero-callback window is valid evidence for this limited claim.
