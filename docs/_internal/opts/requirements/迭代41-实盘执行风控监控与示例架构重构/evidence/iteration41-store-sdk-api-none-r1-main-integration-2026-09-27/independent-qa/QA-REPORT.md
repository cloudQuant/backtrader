# Independent QA — Store `sdk_api is None` r1 + mechanical fallback p4

## Verdict

**SAFE_TO_APPLY_FOR_FAIL_CLOSED_PUBLIC_API_ONLY.** This is a public API behavior change, not a Python same-process isolation boundary. Do not claim that `sdk_api is None` prevents trusted in-process code from reading private `store._api` or calling `_ensure_api_ready()` directly. No real SDK/native/provider/config/network operation was performed.

## Frozen inputs and replay

- r1 candidate root: `D:\temp\iteration41-store-sdk-api-guard-only-20260927\freeze-r1-none`
- r1 manifest SHA-256: `77361DCDB642CA42C32CF9E5E68DB915C29FDBDA0EA002DC277637F9958EE227`; manifest sidecar SHA-256: `F0917CE1CE96C015A92ECCD58C3F2DAE7622327EAA56FB3F653C067B35834951`
- r1 patch SHA-256: `C4075E0395D312B476511365B1FFFE40D981BB1A42E22B2A6E282BE360917A65`
- expected preimage `backtrader/stores/btapistore.py` SHA-256: `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`; current main and scratch preimage matched it before patch application.
- expected candidate Store SHA-256: `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`
- r1 focused test SHA-256: `477225A7668DD10FE26A532EF49AAF018FE8FF4187C5446C42AD7D97A2AFD7D6`
- p4 source patch SHA-256: `299CD0215A8636F25C7E3B74F70CD05C30372059EFC1150E9BB96A47F668B70C`; p4 test patch SHA-256: `5DB64E45C19C63F060786740242B081998ED079E2E4D7086B4C7A99201E453F7`; p4 source candidate SHA-256: `549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F`.
- All three patches passed `git apply --check` and applied in a fresh scratch copy. The r1 Store candidate/replay byte hashes differ because Windows `git apply` normalized line endings; LF-normalized contents are equal. The replay-vs-main diff contains only the `sdk_api` property hunk. `_ensure_api_ready` was unchanged by r1. The current main p4 example already has the p4 candidate source hash.

## Verification

Final command, from `D:\temp\iteration41-sdk-api-none-r1-independent-qa-20260927`, with `PYTHONPATH` set to that scratch root, plugin autoload disabled, bytecode writing disabled, and `sitecustomize.py` blocking imports of `bt_api_py`, `bt_api_ctp`, and `_ctp`:

```text
python -m pytest --noconftest -q --tb=short --color=no tests/unit/stores/test_btapistore_sdk_api_none.py tests/unit/test_ctp_options_simnow_mechanical_api_boundary.py tests/unit/test_r1_actual_store_composition.py --junitxml=independent-final.junit.xml
```

Result: **14 passed, 1 existing warning** (`Unknown config option: asyncio_default_fixture_loop_scope`). JUnit SHA-256 `73EE149B1C9DA3950B9DE44777C2C02C2FF5185BE274AFBD4FE7AC66951A7ED2`; stdout log SHA-256 `5E59AA04C064AA24839C9FF8E8022E3B640E17157A3AF2CF497F0632E946FF83`; exit-code file SHA-256 `5FECEB66FFC86F38D952786C6D696C79C2DBC239DD4E91B46729D73A27FB57E9` (value `0`).

The original nine Store tests cover direct CTP, configured CTP SDK, CTP gateway, forwarding, no-client, non-CTP direct object identity, and an internal read-only CTP metadata query with no writes. The p4 fake tests reject `sdk_api is None` before the private lazy-connect fallback. An additional QA-only composition test used a real `BtApiStore(provider="ctp", api=fake)` with the p4 mechanical function; it observed `MechanicalBlocked("STORE_SDK_API_NOT_READY")`, zero `_ensure_api_ready` calls, zero fake API writes, and no fake connection. A QA-only property enumeration found no public CTP property returning the fake API identity; the non-CTP direct getter still returns its supplied object.

## Limits and setup note

The first scratch test invocation lacked imported example support files; a later scratch-copy step briefly replaced the patched example with main source. Those setup errors were corrected, and the final command above ran against the patched p4 example at the exact manifested hash. They are not product failures.

The getter blocks ordinary public `sdk_api` access for CTP, gateway, and forwarding routes while preserving internal queries and non-CTP direct behavior. Python reflection/private attributes remain accessible in-process, so this does not provide hostile-code isolation, an unforgeable capability boundary, or provider authorization. Default execution remains NO_WRITE / LIVE_NO_GO.

A repository search for `.sdk_api` call sites found the mechanical example as the only production-source consumer; Iteration 14/15 adapters explicitly avoid unwrapping it, and tests assert the transferred-Store paths do not access it. This makes the intentional in-repository impact localized to the now fail-closed mechanical example. External downstream callers may still observe the documented CTP getter behavior change and need compatibility review before any release.
