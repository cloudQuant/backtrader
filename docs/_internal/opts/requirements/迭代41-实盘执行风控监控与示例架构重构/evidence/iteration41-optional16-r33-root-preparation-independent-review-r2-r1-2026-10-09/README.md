# Optional16 R33 Root preparation R2 independent source review

Decision: `GO_FIXED_SOURCE_PREPARATION_ATTEMPT_ONLY` (`GO_SOURCE_FAKE_ONLY`). This review supports a fresh, guarded preparation-only attempt after Root's own custody and lifecycle gates. It does not approve activation, installer/worker entry, a provider call, or case acceptance.

## Candidate pins

| File | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_optional16_r33_root_preparation_call_r2.py` | 26580 | `f569bf401ee164758000f49bd3c98c0bafd67beda3d3fed05b91fd76c1faf5b2` |
| `scripts/iteration41_optional16_r33_root_preparation_driver_r2.py` | 21775 | `84f09496235c4bb3e269475c5f09d7e94628d9d30a0955228c090446b595c3c0` |
| `tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r2_source_fake.py` | 12998 | `f4b3bcb2bbf951c2df2b9c37d414bad1aeaa270813b95a98c7db3e3c95690300` |
| `tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_driver_r2_source_fake.py` | 4984 | `584086b355c92f87b5c32baacded53f96a48fc10a2dc6af331ca7f968b41385c` |

The packet source index is 6498 bytes, SHA-256 `a76dca4d4e86340e8234d2c26c3e03b2d91ea726339e7833b8d08f4e37b0d044`. Its source ZIP is 19022 bytes, SHA-256 `0f3dda5c03c9e535ff4979da9795614e63bdb2e35787842e259d9687f622b612`; it contains the four candidate files above with matching lengths and hashes.

## Fixed public dependencies

| File | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_optional16_r33_root_held_entry_r2.py` | 108188 | `80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead` |
| `scripts/iteration41_root_held_source_scope_v3.py` | 42252 | `f3270495d3ddb046f8617d689510d4ae6ee700d639e0db769c518a15099a7677` |
| `scripts/iteration41_root_held_source_scope_v4.py` | 31692 | `138c86e21de773822eceac07034e113e0adb5ea5d9056fcc16cee10a75c0e830` |
| `scripts/iteration41_optional16_r33_root_preparation_r1.py` | 18324 | `a626001a9f80bee26996a0fd3effb0e670c96ffd7a167ba154d23521eca64aa4` |
| `scripts/iteration41_optional16_r33_root_held_invoke_r28_r5.py` | 146687 | `710452c8358887faa152cd2c6d11333ccf8ecb18fbe64d511ce86eb8f112c99c` |
| `scripts/iteration41_optional16_r33_root_held_glue_r15.py` | 17658 | `f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98` |
| `scripts/iteration41_optional16_r33_root_driver_r19.py` | 168431 | `d7cd9a173e44510e8e2df8fbf68ff5420e495b5a7dd82c589bd1cbef3351c890` |
| `scripts/iteration41_optional16_r33_root_held_invoke_r27.py` | 98440 | `ea0a4f9ec5978508b854fe457dd1cfc3c0e9c41b7b23b89ec461bfed4d798339` |
| `scripts/iteration41_optional16_r33_whole_call_supervisor_r27.py` | 71265 | `bfdd7bc9530b9ded9722ec86c1c184f36de3fb6337fb6688cbe15fa0f77f2876` |
| `scripts/iteration41_optional16_r33_root_preparation_call_r1.py` | 22428 | `762cf58ed2d9d4e2eed2c089a967946610ba660854327d7786c63f463ae4ef8e` |
| `scripts/iteration41_optional16_r33_root_preparation_driver_r1.py` | 18779 | `7930bb76a89b4a29721b30aac40163bebb2714667474961a4a058e066d62d71c` |

All 11 dependency rows matched their declared size and SHA-256 during review. The four ZIP members matched the indexed candidate bytes.

## Source-fake review and QA

The production V4 loader creates the nested V3 module from its pinned source using `types.ModuleType`; this leaves V3's `__cached__` absent. R2 accepts an absent or `None` cache slot only when the module also matches the exact pinned V3 name, path, and digest. V4 and any other module still require an explicit `__cached__ = None`. The adapter retains the exact-source checks for code, globals, classes/descriptors, and same-scope held-byte rereads before calling the pinned R1 preparation helper.

Independent isolated run: **13 passed, 0 failed, 0 skipped**, 0.69 seconds, exit 0. One pre-existing pytest configuration warning reported the unknown `asyncio_default_fixture_loop_scope` option.

Command:

```powershell
& 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe' -I -S -B -X utf8 -c 'import os,sys; os.environ.pop("PYTHONPATH",None); os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"]="1"; sys.path[:0]=["D:/source_code/backtrader","D:/temp/iteration41-main-source-qa-20260926/venv/Lib/site-packages"]; import pytest; raise SystemExit(pytest.main(["-q","-p","no:asyncio","-p","no:cacheprovider","--basetemp=D:/source_code/backtrader/.codex-tmp/OPTIONAL16_PREP_R2_REVIEW_20261009_A","tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_call_r2_source_fake.py","tests/unit/scripts/test_iteration41_optional16_r33_root_preparation_driver_r2_source_fake.py"]))'
```

The tests execute the pinned public V4 loader and compare the resulting nested V3 module with references compiled from pinned public source. They also exercise fake held-handle reads, cache-slot/global mutation rejection, finite diagnostics, and the default-closed one-shot driver.

## Limits

The V4 scope in the tests is a fake scope. The review does not exercise a production Root scope, Entry R2's complete 582-row map derivation, the V4/R29 opaque profiler proof, R5/R27 transforms in a production scope, or installer/worker/activation. No private, opaque, SDK, native, provider, or account input was read. Root must still complete its own fresh custody checks and normal scope close before treating a preparation-only attempt as complete.