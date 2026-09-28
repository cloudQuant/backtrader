# Independent QA receipt: r2b pure query evidence test seam

## Verdict

LOCAL_TEST_CONTRACT_PASS / PACKET_INCOMPLETE.

The test-only seam is locally acceptable against the exact r2b source bytes: patch check/replay succeeded, the focused fake-only runner reported 19 passing tests, and its three constructor route probes rejected before touching the opaque API. The original I22 nodeid and both core fail-closed assertions remain.

The candidate evidence is not unconditionally self-contained. Five of the 15 SHA256SUMS path entries do not exist at the literal paths inside the freeze. Their digest and byte-size values all match the corresponding payload found at the remapped locations/external source paths below, but the path layout must be corrected by a regenerated package before treating the index itself as complete.

## Independently checked inputs

- Frozen seam: D:\temp\iteration41-ctp-query-pure-seam-r2b-20260927.
- Exact r2b source root: D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b\backtrader.
- btapistore.py SHA-256: 24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518.
- The frozen test base patch-base\tests\unit\stores\test_btapistore_iteration22.py and current main I22 test both hash to 30EEAA2C9816E6D0792E801A6EA2A8960CC1BCAA3728679111318E5178AFA49D.
- The 481 Python files under the candidate backtrader tree and the copied source tree are byte-identical.
- Analysis input D:\temp\iteration41-r2b-200fail-analysis-20260927\analysis-summary.json hashes to EE60B8A12C5C76035EF7A4A649F50261D17A7B68FF60A3668C28C49528EEB9D0.

## Patch replay and tests

A fresh replay tree was created under repo\ in this QA directory from the exact r2b source tree plus test support. The original I22 test file was reset from the frozen base SHA above. git apply --check and apply both succeeded with core.autocrlf=false. The resulting modified I22 test SHA is C04745DE3D1FF2B42B425F9F3CFEA7C9B4A1F60C651C5ACA626964121944123E; the new pure test SHA is E550F425E73877064F41059F1B8A42C04511DF413C519B6BDC38028AB59F86E8.

Command run: C:\anaconda3\python.exe D:\temp\iteration41-ctp-query-pure-seam-r2b-independent-qa-20260927\qa_guarded_runner.py, with PYTHONDONTWRITEBYTECODE=1. Result: 19 passed, exit 0. Existing warnings were the Quandl deprecation and unregistered performance marker. The report's earlier autoload-failure is a plugin collection error (pytest_asyncio 0.23.0 accesses removed Package.obj); disabling plugin autoload/asyncio resolves the harness failure.

The three route probes were:
1. explicit provider="ctp_gateway";
2. provider="btapi" with nested api_kwargs.exchange_kwargs.CTP___FUTURE;
3. BT_STORE_PROVIDER=ctp_gateway with explicit provider="btapi".

All were rejected with BtApiStoreError; TrapApi attribute reads and calls were both zero. The import blocker recorded zero attempts and zero loaded modules for bt_api_py/_ctp.

## I22 assertion and evidence provenance

The canonical pytest path-form nodeid remains exactly tests/unit/stores/test_btapistore_iteration22.py::test_nested_query_failure_cannot_be_overridden_by_outer_success_fields. The analysis text summarizes the same source test using a dotted module shorthand; the function name and file path are unchanged. The original assertions remain semantically unchanged: nested timeout/incomplete evidence yields result["complete"] is False and _ctp_query_result_complete(result) is False. A successful normalized envelope assertion was added.

The new tests and migrated node use a fake CompleteQueryClient/ordinary Python dictionaries. Their values are synthetic query-shaped data only. The comments and report explicitly deny SDK/Actor authority; the route probes use an opaque trap object solely to detect attribute reads/calls. No real SDK, Actor receipt, CTP provider, private configuration, account, native module, or network was used.

The count 157 is exact for this source analysis: analysis-summary.json has 158 unique query/preflight/scope/quote/settlement evidence nodeids. The migrated node appears exactly once in that set. The CSV has 157 rows, 157 unique IDs, ordinals 1–157, and equals the 158-node set minus that one node; there are no unexpected or omitted IDs. This leaves 157 original failures un-migrated; it does not claim the other 157 are fixed.

## SHA index path discrepancy

All 15 indexed digest/size pairs matched an equivalent payload. Only 10 indexed literal paths exist within the freeze. The five remapped entries are:

- isolated/test_btapistore_iteration22.py → repo\tests\unit\stores\test_btapistore_iteration22.py
- isolated/test_btapistore_ctp_query_evidence_pure.py → repo\tests\unit\stores\test_btapistore_ctp_query_evidence_pure.py
- base/main-test-btapistore-iteration22.py → patch-base\tests\unit\stores\test_btapistore_iteration22.py
- base/r2b-btapistore.py → exact r2b candidate source path above
- base/r2b-analysis-summary.json → exact analysis input path above

The independent preflight JSON records each digest, byte length, literal-path existence and mapped path.

## Scope

This accepts one pure query-completion test seam only. It does not execute a query producer, prove query/session/account provenance, validate an Actor, re-enable Store construction, fix the remaining 157 nodes, or accept the I22 suite or any production route.

## Import-origin guard

A separate fresh CPython 3.11.5 process imported btapistore from this QA clone at repo\backtrader\stores\btapistore.py, verified the exact r2b SHA above, and observed no bt_api_py/_ctp import attempt or loaded module. See origin_guard.py and origin-guard.log.

The exact analysis-summary.json used for the 158-to-157 reconciliation is copied into inputs\analysis-summary.json in this QA packet.

