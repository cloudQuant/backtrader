# SimNow C01 V20 Root QA harness R7 — independent static review

**Decision:** `HOLD_STATIC_PIN_MISMATCH / EXECUTION_NOT_RUN`

## Frozen subject

| File | Bytes | SHA-256 |
|---|---:|---|
| `.codex-tmp/iteration41-simnow-c01-v20-parent-formal-root-qa-r7/root_qa_harness.py` | 121,076 | `001efdff1203a2c1327aebbdcac40fc006d8ac497f3c4353efcbbc400c5e96fb` |
| `.codex-tmp/iteration41-simnow-c01-v20-parent-formal-root-qa-r7/input-inventory.json` | 23,483 | `c709d0be37561306ced547922544733ee879d823436ee8752438a4550d5449d8` |
| R7 `candidate-pins.json` | 11,822 | `dfc523215960b8d279b3ad68fc81a91b0fc196941fdbcf573b3a5f06009798af` |
| R7 `artifact-pins.json` | 1,014 | `8cae29ebc204fecf43650844c67a78bb5ba5153f57c7cbe160d5218b05290b02` |
| Changed root-seal fake test | 23,802 | `2a3c087dc4c037d77d06cbf4b5ebe34386a939ed82636384a161eccc95550e99` |
| Preserved prior root-seal fake test | 22,639 | `2f640d72c07f3da0e15bb724d862bff88240c8c0f02dde0f223a54ed816cc7e1` |

The test’s old bytes are preserved at `.codex-tmp/iteration41-simnow-c01-v20-rootseal-r7-preservation-20261009/test_certification_simnow_c01_rootseal_custody_v1_source_fake.py`. The R7 packet is `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v20-parent-formal-composition-r7-2026-10-09/`.

## Findings

The fixture repair itself is source-grounded and correctly scoped. In `test_certification_simnow_c01_rootseal_custody_v1_source_fake.py`, `env()` snapshots all seven names it inserts or replaces in `sys.modules` before the first load (lines 181–192), wraps setup and the yielded test lifetime in `try/finally` (lines 193–294), then restores each prior object or removes a name that was originally absent (lines 295–299). This preserves pre-existing canonical protocol/native module identities and removes root/custody test aliases. A setup exception also passes through the `finally`. The fixture change is the only difference from the preserved test bytes. The harness’s three-module persistent identity policy remains unchanged; it adds no alias waiver or forced cleanup.

The R7 harness packet pins are stale. Its constants at lines 48–55 still expect the R1 candidate pin file (11,291 bytes, SHA-256 `68d2626ce4a14c4b95a15c59608bcc4103b00ab6ffec04ffee2c26b5b58215f9`) and R1 artifact pin file (1,049 bytes, SHA-256 `73ce21de624ec921d3716f7c241a44dc6f78617a85e84ce03c06c5012b6c0c3c`). The R7 inventory instead points to the R7 files pinned above. `_input_rows()` reads the paths from that inventory and compares their bytes and hashes to those stale constants (lines 568–584), then raises `packet_pin_file_mismatch` on mismatch. Therefore the harness deterministically blocks before launching its child or pytest. R7 must receive a distinct successor with both constants and its packet/output identity rebound; these frozen R7 bytes should remain unchanged.

The inventory’s 26 source rows, 8 focused test rows, 6 packet artifacts, and separately pinned review reference were checked against the 41 declared file sizes and SHA-256 values; no mismatches were found. Comparing R6 and R7 candidate pins confirms all 26 production source rows are unchanged and only the root-seal fixture test row changed. R7 declares 118 expected test calls. Its packet labels QA `NOT RUN`; I did not run the harness or tests.

The repository was on `dev` at HEAD `8598c2decdff92085a48bc2b89856926a1051670`; the staged index was empty at review time.

## Scope limits

This is a bounded public-source and pin review only. No harness, tests, candidate runtime, private input, SDK, native code, provider, network, real process, or actual Root activation was used. R7 has no QA pass from this review, and the parent formal C01 route remains unaccepted by this record.
