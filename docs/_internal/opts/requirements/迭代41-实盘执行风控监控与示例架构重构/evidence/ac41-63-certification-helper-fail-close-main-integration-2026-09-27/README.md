# AC41-63 007 certification-helper fail-close main integration

**Disposition:** narrow local fail-close helper integration only; `NO_WRITE / LIVE_NO_GO`.

The two reviewed 007 certification helpers now deny execution when their required preflight/arm interface is absent. This records helper behavior and local regression coverage; it does not establish SDK/native behavior, registered-simulation authority, account authorization, or a real provider route.

## Source and test identities

| Target | Baseline SHA-256 | Main-integrated SHA-256 |
|---|---|---|
| `examples/007_ctp/live_certification/simnow_penetration/common/runtime.py` | `B24B5A64DDF2DD24CC52F399CC16A0D7A9F3CF70505550EA297E1F1FBB0557F5` | `F339D880BF1006CD1C8F69F68B9A1B99753FF2CCBC33566B1FB302691AF582E6` |
| `examples/007_ctp/live_certification/hongyuan_penetration/common/runtime.py` | `FA21C48F88E72672E427AB3B5EDC7A29AF0ACDCAAE608D53DF7219B41117E136` | `2CE3FE0530A42586353A8D4D678EABD0B424B53A085F2DE9CCE0A315F0388160` |

The corresponding main-tree tests are `tests/unit/live_certification/test_simnow_penetration_certification.py` (SHA-256 `07A7F374AC79883EAA86DE6A4C945DBB237034BCEE37C9A8A35A930F0AC1A5AE`) and `tests/unit/live_certification/test_hongyuan_penetration_strictness.py` (SHA-256 `CFAEE420FC99FC41EFAF730A21BFC5E67C36F9710C225265DF4D836AED271FB6`).

The independent report was run before main application and correctly records that its isolated candidates were not applied during QA. Root later applied the exact candidate source bytes to the two main targets; their current hashes above match those candidates.

## Verification

- Independent isolated QA used AST-extracted helper bodies only: SimNow fake tests **5 passed** and caller review **17/17**; Hongyuan fake scenarios **3 passed** and caller review **24/24**. The original QA report is preserved in [independent-QA-REPORT.md](independent-QA-REPORT.md), SHA-256 `0FF4C1DC974998D8D385658CB312DEDF1191715B60D6886742A16139F71E459C`; its source was `D:\temp\ac41-63-admission-helper-qa-20260927-1\QA-REPORT.md`.
- Main-tree command: `python -m pytest -p no:asyncio tests/unit/live_certification -q` — **92 passed**, one existing warning; baseline was **90 passed**. The root added two test functions and migrated one old fail-open Hongyuan expectation before this final run.
- Ruff, `py_compile`, and `diffcheck` exited 0. Git reported LF-to-CRLF normalization warnings for test files only.

## Limits

The isolated fake QA extracts and executes helper function bodies; it does not import the runtime modules. The main 92-pass suite is separate regression evidence and is not an import-boundary proof. These helper checks show fail-close behavior when preflight/arm interfaces are missing at call time; they do not prove that importing the direct runtime modules avoids `.env` or credential access. The 013_1/013_2 helper r1 remains held for revision because module import calls `load_dotenv_if_available()` before its helper fence. No provider, SDK/native, network, private config, account, or real order was used. No trade/write authority is granted.
