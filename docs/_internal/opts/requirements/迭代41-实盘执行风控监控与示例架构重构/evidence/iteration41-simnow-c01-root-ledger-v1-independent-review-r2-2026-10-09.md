# C01 Root Ledger V1 Independent Source Review — R2

**Verdict: `SOURCE_CONTENT_REVIEW: PASS`**, subject to Root’s documented held-source boundary below. This reviews the corrected successor pins only; it does not modify or supersede the earlier R1 HOLD record for its earlier bytes.

The corrected validator parses the exact worker projection and held snapshot bytes with the supplied V3 protocol module, then recomputes all four projections from the joined callback rows using the supplied V4 producer projectors. The two previously identified position-projection failures now have focused negative coverage.

## Reviewed pins

| File | Bytes | SHA-256 |
|---|---:|---|
| `examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py` | 70,205 | `4cbe8465c9b2854d2913de03d4e7a12f020debc8723d6c63539314d2ba7f424a` |
| `tests/unit/live_certification/test_simnow_c01_root_ledger_v1.py` | 21,733 | `a4f4d643fc3ca12c6e162e418312ec5b97291effaebefbf6f55573ef593fc88d` |
| `examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1_field_map.md` | 9,920 | `c9912ba8793384d2057619a027db5aa0119ff1b81516021eb9c1dd06a45a7ec6` |
| `backtrader_runtime/certification_simnow_c01_native_v4.py` | 199,788 | `66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66` |
| `backtrader_runtime/certification_simnow_c01_v3_protocol.py` | 80,745 | `c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160` |
| `backtrader_runtime/certification_simnow_c01_v3_contract.py` | 59,663 | `19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0` |

All six byte counts and hashes matched before and after the independent focused run. The reviewed checkout was `dev` HEAD `309fafdd0c43bd4b4d61ac3cc1c71ca6c80ea5f6`.

## Source and fixture review

The validator normalizes the worker mapping through V3 `encode_worker_frame`/`parse_worker_frame`, requires the returned exact V3 receipt type, and parses each exact held snapshot byte string through V3 `parse_private_snapshot_artifact`. It also checks the canonical one-line JSON bytes. See the [worker and module checks](../../../../../../examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py#L473) and [snapshot parser](../../../../../../examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py#L1494).

After joining snapshot callback rows to the worker callback groups and checking the row digests, the validator recomputes `open_order_refs`, `order_economics`, `positions`, and `funds` from those rows with the V4 `project_*` functions, then compares each complete projection. See the [projection check](../../../../../../examples/000_live_certification/simnow_penetration/common/c01_root_ledger_v1.py#L1318). V3 parser shape/type checks run first; the reference V3 contract independently has its own artifact parse and projection-reconciliation path at [contract lines 1008–1018 and 1152–1180](../../../../../../backtrader_runtime/certification_simnow_c01_v3_contract.py#L1008).

The synthetic fixture uses the pinned V4 `C01NativeCapture`, request/callback, query-result, snapshot, and receipt producers and the V3 worker-frame parser. Its SDK-shaped source/result/callback and stop-receipt leaves are synthetic; it does not import an SDK, contact a provider, start a child process, or use native/WinAPI calls. It exercises the eight planned requests, nine total callbacks, six query requests, seven query callbacks, and two artifacts. The result remains `authority=NONE`, `CONTENT_VALIDATED_ONLY`, `certification_pass=False`, `source_authenticity_verified=False`, and `provider_source_sequence=0`.

The new malformed-projection case updates both artifact and projection digests but keeps `positions` as a string; V3 rejects it and the validator returns `snapshot_protocol_invalid`. The second case creates a V3-valid positions projection from a phantom row, updates both digests, and confirms the V4 recomputation rejects its mismatch with the actual query rows. These cover the concrete schema and row-consistency gaps from R1. The row recomputation intentionally uses the same pinned V4 producer projectors, so its scope is consistency with that implementation, not an independent proof that the producer’s business rules are correct.

## Root caller boundary

The API requires exact `ModuleType` objects and checks the required parser/projector interface. The expected V3/V4 SHA inputs are format-checked and included in the private content commitment; **the validator does not compare those hashes to the supplied module bytes or authenticate module origin**. It explicitly documents that boundary. Before relying on this result, Root must hold and verify the exact V3/V4 source/module/function code and relevant global bindings, retain the same module objects for the call and postverify, and bind the exact artifact bytes to its custody lease. This review does not certify any Root caller implementation or custody path.

## Independent QA and scope

The designated isolated source-QA interpreter reran the focused file with `-I -S -B -X utf8`, explicit repository and venv `site-packages` paths, plugin autoload disabled, and cache/asyncio plugins disabled. Result: **13 passed, 1 existing `PytestConfigWarning`** for `asyncio_default_fixture_loop_scope`; exit 0. Basetemp: `.codex-tmp\c01-ledger-validator-corrected-independent-review-20261009-r1`.

This is public-source and synthetic-fixture evidence only. No private inputs, account, SDK, provider, native, WinAPI, or live execution was accessed. It does not establish source authenticity, custody, official C01 `PASS`, or account acceptance.
