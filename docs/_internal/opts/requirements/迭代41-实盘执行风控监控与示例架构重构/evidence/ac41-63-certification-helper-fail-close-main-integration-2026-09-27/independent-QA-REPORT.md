# AC41-63 isolated helper candidate QA

## Scope and safety

QA was performed only in this fresh temporary copy:
`D:\temp\ac41-63-admission-helper-qa-20260927-1`.
The tested source files were extracted as AST function bodies by the fake-only tests. No runtime module imports, provider/SDK/native imports, network access, or real orders were used.

## SimNow candidate

- Baseline SHA-256: `B24B5A64DDF2DD24CC52F399CC16A0D7A9F3CF70505550EA297E1F1FBB0557F5`
- Candidate SHA-256: `F339D880BF1006CD1C8F69F68B9A1B99753FF2CCBC33566B1FB302691AF582E6`
- Candidate changes both missing-interface paths from `CtpWriteAdmission(True)` to `CtpWriteAdmission(False, reason, next_action)`.
- Fake-only pytest: **5 passed**. Candidate missing-preflight denies before reading optional health attributes; missing-arm performs only stubbed preflight/health reads and denies; the fully stubbed positive case retains the typed arm call shape.
- Static caller review: **17/17** certification case calls assign the admission and immediately branch on `if not admission.ok` before the strategy order call.
- Verdict: **PASS for this narrow helper change in isolated fake-only scope.**

## Hongyuan candidate

- Baseline SHA-256: `FA21C48F88E72672E427AB3B5EDC7A29AF0ACDCAAE608D53DF7219B41117E136`
- Candidate SHA-256: `2CE3FE0530A42586353A8D4D678EABD0B424B53A085F2DE9CCE0A315F0388160`
- Patch SHA-256: `557EA7542E2539A7139717E57D26B9291D938EB8061D10E9627F7C9CBF4E964B`
- The patch changes the two missing-interface returns into `RuntimeError` raises.
- Fake-only script: **3 scenarios passed**. Missing preflight and missing arm each raise before the fake broker callback (0 calls); fully stubbed interfaces preserve the fake arm path and allow the fake callback (1 call).
- Static caller review: **24/24** certification case calls are standalone expressions whose return values are ignored, so raising is necessary to prevent continuation on missing capabilities.
- Verdict: **PASS for this narrow fail-close change in isolated fake-only scope.**

## Static checks and limits

- `py_compile` passed for both candidate source copies.
- Ruff passed for both copies when run with the repository `pyproject.toml` configuration.
- Baseline/candidate inputs were hash-checked before copying, and the fresh QA copies matched those hashes after replay.
- The main checkout's two helper source hashes remained equal to their baseline hashes during QA. `git status` already showed both files modified before the QA runs and showed the same state afterward; QA did not write to either main-tree file.
- These tests establish only helper behavior under fake stores and fake broker callbacks. They do not establish SDK/native behavior, registered-simulation authority, a real SimNow route, account-level authorization, or production acceptance. Neither candidate was applied to the main tree.

