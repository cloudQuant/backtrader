# Store AccountActor r2d independent QA

Verdict: `LOCAL_COMPATIBILITY_CANDIDATE_PASS / CTP_WRITE_NO_GO`.

## Frozen input integrity

- Snapshot: `D:\temp\iteration41-store-account-actor-r2d-20260927\freeze-r2d-20260927`
- Manifest SHA-256: `c53def54dfbb88b49d035991bc363ce6c92e6760c70e6894418b86b947967658`
- ZIP SHA-256: `328acbe6fb46d0227b2b61209df14d99e81d2900fd79c6602f9472741e79365e`
- Payload-index SHA-256: `37ee26fca8a95fd047eeb53eb621089569346faa80fd646cf1a1cf619a09f7b9`
- Independent checks: 1,010/1,010 manifest payloads and index entries match; ZIP has 1,019 members, all manifest payloads present, CRC clean.
- Patch `r2d.patch`: `3fbcfea33b022683644c601a31a2e5ef950c0cf7e4e0c0e323be4764ae9b7e75`; preimage SHA `53cd937a7202990df883fa071c210d31573f11df83937c05880abb3cbc50e90b`; candidate SHA `57c9f5b45a44a89d6152c5182aee2faddf8faec078efea5acb5dac081245c4ae`. Replaying with `core.autocrlf=false` exactly reproduces candidate hash. Baseline and candidate trees each contain 498 files with one byte-level difference: `backtrader/stores/btapistore.py`.
- Both selected test files are byte-identical baseline/candidate: `test_btapistore.py` SHA `694887fc723367e04e5ad339a24649fe22cff1877d4e48190bd7e7f14dc4a075`; `test_ctp_account_actor_store_wiring_candidate.py` SHA `dac659e7c252330ce03c3af87d21107b12d419facb40b9f16ad52e824140211b`. No skip/xfail or test migration was introduced.

## Independent focused results

The exact six frozen nodeids are listed in `nodeids.txt`. They ran from fresh baseline and candidate copies with plugin autoload and bytecode disabled, and the frozen `sitecustomize.py` tripwire. Independent JUnit:

- Baseline: 6 tests, 3 failures, 3 passes. The only failures are `[futu]`, `[oanda]`, `[vc]`, each raising `BtApiStoreError: store provider unsupported` during construction before the test reaches `start()`.
- Candidate: 6 tests, 0 failures, 0 skips. The same unchanged placeholder tests construct an inert Store then assert `BtApiProviderNotImplementedError` from `start()`. The other three nodes pass for forwarding/environment + secret traps, direct CTP, and nested CTP.

Separate fresh-process guard checks against both copied source roots confirm `backtrader.stores.btapistore.__file__` resolves to the expected copy. Direct builtin imports of `bt_api_py` and `_ctp`, DNS lookup, and `socket.socket.connect` were stopped by the tripwire; no such module loaded and no network connection was attempted. The CTP tests' own traps assert no route-environment reads for direct CTP, no API/API-class/actor/context/credential descriptor reads, and no local resolver/SDK calls. The forwarding/secret-trap test also asserts no API-property reads or local resolver/environment override calls.

## Scope and limits

The 72-line source-only patch restores the old placeholder-provider exception phase for exactly the empty/default `BtApiStore(provider=...)` shape with provider `futu`, `oanda`, or `vc`, no explicit backend/client/config/route extras, no actor/adaptor, no autostart, and no route environment selector. `start()` rechecks the unsupported route then raises `BtApiProviderNotImplementedError`; it does not resolve a provider client. Explicit direct/nested CTP cases still reject at construction before route-environment/caller-secret traps and local SDK/forwarding boundaries.

This is only a narrow local compatibility result. It does not make unsupported providers operational, accept CTP reads or writes, install external Actor authority, validate the broader r2c integration, or alter the main tree. `G6-P/LIVE_NO_GO` and the r2c merge decision remain unchanged. One expected existing DeprecationWarning came from `backtrader.feeds.quandl`; no native/provider/network action followed.

Raw logs, JUnit, guard probes, patch replay, source-tree comparison, exact nodeids and corrected verification scripts are preserved in this directory. `qa-manifest.json` hashes all independent raw files.

Reviewer tooling diagnostics were retained: the first index parser assumed a two-column index (the frozen index has digest, size, path); the corrected verifier confirmed all 1,010 entries. The first patch replay used ambient `core.autocrlf`; the corrected exact replay set it to false and matched the candidate. A first guard probe used `importlib.import_module`, which bypasses the patched builtin import hook; the corrected fresh-process probe used builtin `__import__` and verified the guard. These were QA harness corrections, not candidate failures.

## Additional adversarial trap

A separate candidate-origin probe inserted a synthetic object that raises and records on any attribute lookup, `__bool__`, `__str__`, or `__repr__` in both direct and nested CTP credentials. Both routes rejected as `external account actor unavailable` with zero trap reads. It also constructed each default placeholder candidate and verified `_api`/`_api_cls` remain absent and `start()` raises the exact `BtApiProviderNotImplementedError`. Raw output is `secret-placeholder-probe.log`.
