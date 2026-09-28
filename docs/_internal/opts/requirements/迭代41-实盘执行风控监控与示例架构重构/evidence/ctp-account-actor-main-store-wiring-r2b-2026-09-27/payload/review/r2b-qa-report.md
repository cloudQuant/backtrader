# BtApiStore AccountActorPort candidate r2b

## Verdict and scope

`AUTHOR_CANDIDATE / NO_WRITE`. This is an isolated candidate for independent QA and possible review. It does not enable CTP AccountActor dispatch, Store writes, credential/SDK/provider access for CTP, a default route, or live execution. It is not a claim of external Actor, F14, G1, G5, or production acceptance.

The candidate preserves r2a and r2's exact inputs under `evidence/r2-parent/`, `evidence/r1-lineage/`, and `input-sources/`. R2b carries the 21-row old CTP-local-SDK migration map in `evidence/r2b-old-ctp-21-migration.md`. Each row records the old capability checked, the current fail-closed assertion/disposition, and the future positive contract that must be supplied by an authenticated external AccountActor. No `xfail` or skip was used to make the CTP policy tests green.

## Frozen identity and patches

- R2a parent manifest SHA-256: `5ad9cce0851fbebd9ac07d520919b7a02f793ab99a133cf96e91f58cede405fb`.
- R2a parent Store SHA-256: `18a02f00ec3b2031932284c9e855395c1c70c3e448dbafcd054e4f079048c4d0`.
- Main-base Store SHA-256: `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`.
- R2b Store SHA-256: `24f8199e199bbe84bbb113c3edbbee9e71d4736fdd8573297e24ead3298f2518`.
- R2b actor module SHA-256: `2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3`.
- R2b focused test SHA-256: `fc675d30a1cd3e303357406e81edc067af0b7559d2230ac6a2ee3732466cc2c6`.
- R2b full patch from the exact main-base Store: `r2b-main-base-apply.patch`; SHA-256 is recorded in `r2b-main-base-patch-replay.txt`. It adds the ActorPort module and candidate tests/migration expectations. Replay used `core.autocrlf=false`; `git apply --check` and exact target hashes passed against a scratch tree whose Store base was the SHA above.
- R2b full main-base patch SHA-256: `1a16aadb94edb99924553d6472bf72dcb02bd04c7f994276816d91991a729f37`.
- R2a-to-r2b delta: `r2b-apply.patch`, SHA-256 `d27a724711c3eb9c3622e5103c4d70da65d977510e740bb5030dea7990abf9dc`; `r2b-patch-replay-final.txt` records exact replay. The earlier `r2b-test-migration.patch` is retained as historical r2b evidence, not the complete current patch.

## Internal route-boundary audit

An inert gateway client exposed one candidate-only gap. Construct a non-CTP `BtApiStore(provider="ib_web_gateway", backend="gateway", config={"exchange_type": "IB_WEB"})` with a fake `bt_api_py.gateway.client.GatewayClient`, call `_ensure_api_ready()`, then change `store.provider` to `"ctp"`. Before the r2b change, direct calls through the retained gateway wrapper's `submit_order` and `cancel_order` reached the fake client's dispatch methods without the Store public-method route recheck. The pre-fix run is retained in `r2b-internal-route-pre-fix.log` (hash in the manifest); the direct wrapper test's failed `raises` assertion is the reproduction. The companion test setup failure in that initial log was a trap fixture missing the constructor's harmless `ctp_query_min_interval_seconds` attribute; the corrected fixture uses the explicit default and the final test is clean.

R2b attaches a Store route callback only to the internally-created gateway wrapper (`backtrader/stores/btapistore.py:3274`, attached at `:16936`). The wrapper rechecks immediately before its `submit_order` (`:3504`) and `cancel_order` (`:3531`) delegate calls. The Store rechecks after wrapper construction and before adopting it (`:16939`). The callback rejects after either the Store provider or its sealed routing config is mutated to CTP. The new fake gateway regression tests pass in `r2b-internal-boundary-final.log` and `.junit.xml`.

The legacy private paths already rechecked the route at method entry: `_submit_order_legacy` (`backtrader/stores/btapistore.py:8348` / guard `:8357`), `_cancel_order_ref_legacy` (`:8689` / guard `:8693`), and forwarding-client construction (`:17029` / guard `:17033`). The new mutation tests invoke those helpers plus public submit/cancel/ref and `_cancel_managed`; on changed provider or config, they reject before order attributes, injected API dispatch attributes, or client constructors are touched.

The Store gate is not an isolation boundary against arbitrary same-process Python code. A caller that directly invokes the module-private `_create_ctp_gateway_wrapper_class` can construct an unbound wrapper; direct access to `wrapper._client` also bypasses wrapper methods. Such access has no Store route authority and is outside this candidate's guarantee. These boundaries must not be treated as an external Actor or as real CTP acceptance.

## Verification

All commands ran from this isolated candidate root with the existing local Python 3.11 environment. Pytest emitted only the pre-existing Quandl deprecation warning.

- Candidate boundary + migrated CTP-local-SDK file: `python -B -m pytest tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py tests/unit/stores/test_managed_ctp_store_adapter.py -q --tb=short`; **43 passed** (`r2b-candidate-focus-final.log` / `.junit.xml`).
- Internal route mutation probes: **4 passed** (`r2b-internal-boundary-final.log` / `.junit.xml`).
- Original three-file regression set (`test_managed_execution_store_adapter.py`, migrated `test_managed_ctp_store_adapter.py`, `test_runtime_live_dispatch_guard.py`): **30 passed** (`r2b-exact-30-final.log` / `.junit.xml`). The 21 migrated CTP rows now explicitly assert unavailable external Actor before local dispatch.
- All `tests/unit/stores` and `tests/unit/runtime`: **55 passed** (`r2b-related-stores-runtime-final.log` / `.junit.xml`).
- Configured Ruff on the five changed Python files: passed (`r2b-ruff-final.log`).
- `py_compile` on the five changed Python files: passed (`r2b-pycompile-final.log`).
- Exact main-base patch generation/replay: passed (`r2b-main-base-patch-replay.txt`).

The 30-test pass validates the local fail-closed candidate behavior and retained non-CTP adapter contract only. It does not turn the 21 former local CTP behaviors into accepted production operations; their future positive external-Actor contracts are specified row by row in the migration table.
