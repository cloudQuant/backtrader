# Independent QA — BtApiStore AccountActorPort wiring r2

**Disposition: `CANDIDATE / NOT MERGE-READY under the requested ordering contract`.** The frozen exact-base patch and candidate source were reproduced byte-for-byte. The candidate boundary, adapter, non-CTP, and live-dispatch focused cases pass; the legacy Store delta matches the prior 8/13 migration audit exactly. One explicit acceptance requirement is not met: an explicit CTP construction reads `BT_STORE_PROVIDER` and `BT_GATEWAY_EXCHANGE_TYPE` before reaching the unconditional actor-unavailable gate. This changes which fail-closed error is returned when provider environment is altered. The probe found no caller trap, client, SDK, native, or network side effect and no CTP bypass, but the required read order is still violated.

## Frozen input and independent reproduction

- Source archive: `ctp-account-actor-main-store-wiring-r2-2026-09-27/r2-author-candidate.raw.zip`, SHA-256 `1b6c0a9d03295d9c96548ee63342a6931d7ab7a23e214161c2cde8661739f98a`.
- Archive index SHA-256: `27da48132a1beb2b3e93b2a711114760abbd1f6d5ed000cde5b35ad9d7916051`; frozen candidate manifest SHA-256: `5b68f9ed2a457e51941bbd60052a100d2e045907b9b2e3bb454482304badd27a`.
- `zipfile.testzip()` returned `None`; ZIP contains 651 members and the 649 declared payload entries all match manifest path, digest, and size.
- Exact Store base input SHA-256: `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`. Patch SHA-256: `6e8575874cefeab4c693f6fedd5f3fc89dcec935005f5ad3a0d64f0e1284f90f`.
- In an isolated temporary replay tree, `git -c core.autocrlf=false apply --check` and `apply` both succeeded. Store, ActorPort, and candidate test output digests exactly match manifest (`a25edc…586b8`, `2e4b04…44ee3`, `04968d…9154f`).
- The legacy test sources match the independently reviewed exact-base set: managed CTP adapter `2b5f929cac960ed6a7105eb2cc0b7401961fdb7c7b97761288d279b415b15e3f`; managed execution adapter `c9262dc03c3905a54b1397c10db12b1a5dc68508874e550590039d22a482a030`.

## Test commands and results

All commands ran from the extracted candidate root `D:\temp\iteration41-store-actor-r2-independent-qa-20260927b\candidate` with the compatible Python 3.11.5 venv, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `-B`, and `-p no:asyncio`. Each command emitted JUnit and raw stdout/stderr in the QA archive.

1. `python -B -m pytest -p no:asyncio tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py tests/unit/runtime/test_runtime_live_dispatch_guard.py -q --tb=short --junitxml=evidence/r2-independent-candidate-focus.junit.xml` — **14 passed**, 1 existing Quandl deprecation warning.
2. `python -B -m pytest -p no:asyncio tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py tests/unit/stores/test_managed_execution_store_adapter.py tests/unit/runtime/test_runtime_live_dispatch_guard.py -q --tb=short --junitxml=evidence/r2-independent-focused-tests.junit.xml` — **21 passed**, 1 same warning.
3. `python -B -m pytest -p no:asyncio tests/unit/stores/test_managed_execution_store_adapter.py tests/unit/stores/test_managed_ctp_store_adapter.py tests/unit/runtime/test_runtime_live_dispatch_guard.py -q --tb=short --junitxml=evidence/r2-independent-legacy-delta.junit.xml` — **9 passed, 21 failed**, exit 1, 1 same warning. Each failure stops at `external account actor unavailable` during Store construction; one old expected-error regex instead expects the later `typed runtime adapter` text.
4. The same 30-test command with only `backtrader/stores/btapistore.py` replaced by the exact base input — **30 passed**, 1 same warning. The two legacy test files’ hashes match the prior exact-base audit inputs.

The 21 candidate failure node IDs match the frozen migration table exactly: **8 `FAIL_CLOSED_ASSERTION`, 13 `EXTERNAL_ACTOR_MIGRATION`, 0 unmapped**. There is no ordinary non-CTP regression in this set. The complete node-by-node match is in `legacy-disposition-comparison.txt`; prior dispositions remain unaltered.

## Behavioral checks

- Positive non-CTP coverage passed: explicit OKX route keeps a raw injected API; detached route facts reject later internal route changes. Unknown, contradictory, nested CTP, and gateway routes remain closed.
- The ActorPort boundary tests pass with fake caller port, context, API/API class traps, credential `__str__`/`__bool__` traps, resolver overrides, and `autostart=True`; actor methods, API properties, secret conversion, provider resolver, env override helper, and SDK resolver are not reached in those tests.
- Static scan of the three focused test inputs found no direct socket/HTTP entry points. A source-origin smoke resolved `backtrader`, `btapistore`, and `ctp_account_actor_port` to the extracted candidate and found no `bt_api_py`, `_ctp`, or `ctp_wrap` modules loaded.

### Specific ordering blocker: environment reads precede Actor rejection

The constructor first reads both provider environment selectors while creating `initial_route` at `backtrader/stores/btapistore.py:3678-3681`; the CTP branch reads them again at `:3743-3751`; only then does it call `require_account_actor_before_local_client` at `:3753`. That gate itself unconditionally raises `external_account_actor_unavailable` for CTP at `backtrader/stores/ctp_account_actor_port.py:442-460`.

The independent probe intercepted `os.environ.get` without consulting actual environment values. With both selectors forced absent, it observed reads in this order: `BT_STORE_PROVIDER`, `BT_GATEWAY_EXCHANGE_TYPE`, `BT_STORE_PROVIDER`, `BT_GATEWAY_EXCHANGE_TYPE`; final error was `external account actor unavailable`. With the intercepted provider selector set to `okx`, it observed provider/exchange/provider reads and final error `store route ambiguous for account actor handoff`. In both cases API, actor, context, and credential traps remained untouched and no SDK/native module loaded. Thus this is an ordering/contract failure, **not** evidence of a dispatch bypass. Fix the ordering in a new candidate or revise the required contract explicitly before merge; do not count the green test focus as clearing it.

## Recommendation and limits

Do not merge this as accepted Actor wiring under the requested “reject before provider-env read” contract until that ordering is fixed and independently rechecked. The candidate otherwise preserves a useful hard-closed CTP boundary, and its OKX/non-CTP compatibility focus is green. The 13 external-Actor behavior cases remain deferred until a real, authenticated external Actor API exists; the 8 fail-closed cases need assertions migrated to the earlier boundary. The candidate has no accepted actor authority, CTP session, provider/native/network proof, or live/write route. This QA is local fake/source evidence only.
