# C01 Root Ledger V1 Independent Source Review

**Verdict: `SOURCE_CONTENT_REVIEW: HOLD`**

The focused source-fake suite passes, but the validator accepts malformed private position projections when their summary digests are updated. The pinned V3 parser rejects the same artifact. This is a deterministic public-source content-validation gap; the validator should not be integrated as a complete snapshot-content validator until it checks projection schemas and consistency with query rows.

## Reviewed source pins

| File | Bytes | SHA-256 |
|---|---:|---|
| `examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py` | 64,707 | `85e245565acdae451a921ad595ea0f4bee9755cc2d4bec66aa83e0566f6ee6cb` |
| `tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py` | 18,697 | `5b7112ec92e50822f80b60f03253e8f8269dc96c7185c82fd3bf6ef7b6836792` |
| `examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1_field_map.md` | 7,223 | `d2561c14267a4c9aa9d4d56ff11563ff98e4a8c59b577f7d29403e4498feaeb2` |
| `backtrader_runtime/certification_simnow_c01_native_v4.py` | 199,788 | `66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66` |
| `backtrader_runtime/certification_simnow_c01_v3_contract.py` | 59,663 | `19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0` |
| `backtrader_runtime/certification_simnow_c01_v3_protocol.py` | 80,745 | `c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160` |

## Reproduction and source comparison

The test fixture calls the pinned V4 `C01NativeCapture`, `native_request`, `response_callback`, `_query_result_summary`, `_private_snapshot`, and `_build_worker_receipt`; it encodes/parses the receipt with the pinned V3 protocol. The QueryResult/source objects, native callback leaves, stop receipt, and account rows are synthetic. The fixture covers the eight planned requests, their callbacks, two private artifacts, and content-only/no-authority result. It does not import an SDK or contact a provider.

At [the validator snapshot check](../../../../../../examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py#L1238), `_validate_snapshot` requires the projection keys, accepts any `_json_value`, and compares each projection digest with its worker summary. It does not invoke the V3 private-snapshot parser or recompute the projection from callback rows. In contrast, the pinned [V3 protocol parser](../../../../../../backtrader_runtime/certification_simnow_c01_v3_protocol.py#L1893) requires `positions` to be an object with the exact schema, dimensions, and bucket structure. The pinned [V3 contract](../../../../../../backtrader_runtime/certification_simnow_c01_v3_contract.py#L1008) parses held artifact bytes and later recomputes order references, order economics, funds, and gross positions from the snapshot/query data (lines 1152–1178).

Independent probe, using the test's producer-generated bundle: for both baseline and final artifacts, set `projections.positions` to the string `"malformed"`, recompute the V3 `positions_sha256` and artifact SHA-256 in the matching worker summary, and leave requests, callbacks, and query-row digests unchanged. The validator accepts the bundle as `CONTENT_VALIDATED_ONLY`, `authority=NONE`, `certification_pass=False`; the pinned V3 parser rejects both artifacts with `C01ProtocolError:private_snapshot_positions_invalid`. A second semantic check is also needed: a schema-valid projection that disagrees with its query rows must not pass merely because the two snapshot projections and their digests agree.

## Independent QA and limits

The focused file passed **10 tests**, with one existing `PytestConfigWarning` for the unknown `asyncio_default_fixture_loop_scope` option; exit code 0. It ran under `D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe -I -S -B -X utf8`, with only the repository root and that venv's `Lib\site-packages` explicitly added to `sys.path`, plugin autoload disabled, and cache/asyncio plugins disabled. Basetemp: `.codex-tmp\c01-ledger-validator-independent-review-20261009-r3`.

All six reviewed source files had the exact sizes and SHA-256 values above both before and after the focused QA and probe. No candidate source or test was edited. This review used only public source and synthetic data; it establishes no SDK, native, provider, account, or official C01 result. The validator's no-authority/no-PASS result is preserved, but does not cure the projection-content gap.
