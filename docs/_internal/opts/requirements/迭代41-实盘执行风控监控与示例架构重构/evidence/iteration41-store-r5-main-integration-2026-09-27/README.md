# Store R5 main integration and Store/Runtime regression snapshot

Disposition: `LOCAL_STORE_GUARD_REGRESSION_ONLY / NO_WRITE / LIVE_NO_GO`.

The current main-tree `backtrader/stores/btapistore.py` snapshot is SHA-256 `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`; the retained preimage is `40F776E783388DFA0A5499501E5886744FFD1D74D259E17D3ADECD9A20A5C457`. Store focused JUnit recorded 143 passed, zero failed. Ruff and `py_compile` passed; `diffcheck.log` carries the repository's LF→CRLF warning for the Store file.

The later combined `tests/unit/stores tests/unit/runtime` regression is a broad regression snapshot only. Its first run recorded 2,715 passed, 43 skipped, 2 xfailed, and one failure: `test_stale_epoch_rejects_before_fake_send_then_exact_current_receipt` asserted `bt_api_py` was absent from the pytest process's global `sys.modules`, but a prior Store test had imported it. This was an order-dependent test-process assertion, not evidence that the fake actor child loaded a provider. After removing the two global-module assertions while retaining the child-boundary and fresh-process registry checks, the corrected run recorded 2,716 passed, 43 skipped, 2 xfailed, zero failures in 110.01s, with one existing pytest configuration warning. Raw first and corrected logs, JUnit and exit files are retained.

Scope limit: broad counts are for Store/Runtime only and do not attribute behavior to any one patch or prove SDK/native/provider safety. No write, network, private config, CTP session, or live route is authorized. This is not Actor, G6-P, F14, or production acceptance.
