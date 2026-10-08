# OKX M01 V3 protected metadata helper delivery round

## Scope and acceptance

Backtrader `dev`, base HEAD `9de5439cf3daadd42b96915b94e3c9b6e7a0e1cc`. The source-only helper review is `GO_ROOT_PROTECTED_METADATA_ONLY`; the exact helper and test pins below were reviewed, and the independent focused fake suite passed 14 tests with exit 0 and no warnings. Root also performed one bounded metadata rebind/admission release: actual result `METADATA_REBOUND_ADMISSION_VERIFIED`, scope `PROTECTED_METADATA_ADMISSION_RELEASE_ONLY`, followed by normal CUv2 postverify/close and host exit 0.

This round establishes no account, provider, WebSocket, or native result and no formal M01 case pass. Formal M01 pass count remains 0. The already accepted 19-runtime R2 map is unchanged. Retained host `90344` was not touched.

## Exact proposed 15-path stage set

Two helper source/test files, three independent review files, seven public actual archive files, and three small plan files are proposed. The complete machine-readable list and exact path-scoped `-text` suggestions are in `delivery-whitelist.json`; no attributes or index changes were made here.

| Path | Bytes | SHA-256 |
| --- | ---: | --- |
| `scripts/iteration41_okx_m01_v3_protected_rebind_r1.py` | 26554 | `772157d54079f3e0900caee75e9be78632084b32a729b15abaee4529e010a296` |
| `tests/unit/scripts/test_iteration41_okx_m01_v3_protected_rebind_r1.py` | 25909 | `4880f722fb9cbaf7cba09d0917a3b6b40f9095fffc1c89abcdfb2ce536e61c46` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-independent-review-r1-2026-10-09/review.json` | 7507 | `f19e6086d9473a3914dce13809b43d38a82693322005298371ac9dd8cb6227de` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-independent-review-r1-2026-10-09/README.md` | 2795 | `e09d4daa948088b5fb95032eadcd78e46135c439189e946475e26e01adc8d412` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-independent-review-r1-2026-10-09/qa-command.txt` | 940 | `2ce1a6623a516bb5201b3f69da4882af41eb6243d153b680ceb745be5e106c18` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/observation.json` | 862 | `13eced1ab0ce7389fd7c3fadb19d41d2b295121bf87f80a26605d758c9430a62` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/host-pre-exit.json` | 269 | `a72528bc73329631ad17a9ff0b8217b4c92730110349aefc5f2ffb1acab47677` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/root-rebind.py` | 12115 | `ce33952692a1600b6b17eb8615b176847abad624416cbfb8cfc3f6fe2d16927a` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/root-host-exit.json` | 1685 | `de5a873aecefdc4dd4b47acfbd23b673a9ea9bb266b462bdfe80a43fb2efbca5` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/root-source-pin-manifest.json` | 12803 | `23ddf5bf0d451797c9d38cb03cff80e697964678ecd1945860243ba38fa1f039` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/README.md` | 1950 | `97c98404359a42b617087f45f90dbb04b98f98def8a58559043e0cbf054d1aa0` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-root-actual-r1-2026-10-09/archive-pins.json` | 1415 | `da7e623efc780579cf60ecbfd9d2eaba1fedc2598f82358e0b518909602a3101` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-dev-round-r1-2026-10-09/round-record.md` | see `plan-pins.json` | see `plan-pins.json` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-dev-round-r1-2026-10-09/delivery-whitelist.json` | see `plan-pins.json` | see `plan-pins.json` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-protected-rebind-dev-round-r1-2026-10-09/plan-pins.json` | see `plan-pins.json` | see `plan-pins.json` |

The actual archive's `root-source-pin-manifest.json` is derived by literal parsing of the Root driver's public constants and exact hashing of the current 20-row source index closure. It contains 30 public path/hash/byte rows (20 source-index rows, 9 support pins, and the original Root driver) and 3 software references from constants only; external software payloads were not read.

The archived actual run is tool `99b114` on fresh host session `48777`. The Root-reported public code-binding precheck was `306f46`; normal host exit tool result `e9cec2` returned exit 0. The existing observation and pre-exit records are pinned without modification. The staged-blob preparation history is recorded: stop `82d5b4` before mutation on the attributes CRLF comparison; preparation `fc95c4` omitted the pinned initializer due to the index stat cache; Root renormalized only the exact pinned 66-byte initializer (`d5fc60`), then verified all 41 source staging blobs (`365305`) before commit result `471023`. These are historical notes, not operations performed for this record.
