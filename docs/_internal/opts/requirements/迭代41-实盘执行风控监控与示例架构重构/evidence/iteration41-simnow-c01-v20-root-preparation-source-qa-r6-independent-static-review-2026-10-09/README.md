# SimNow V20 Root preparation QA R6 — independent static review

**Verdict:** `GO_STATIC_REVIEW_ONLY / EXECUTION_NOT_RUN`.

## Frozen subject

- QA packet `iteration41-simnow-c01-v20-root-preparation-source-qa-r6-2026-10-09/`
- `artifact-pins.json`: 1,788 bytes, SHA-256 `8e6b330737dbc19e52723b553c75eddb1b1cdcf859599d853122ed65c7a64499`
- Runner: 57,775 bytes, SHA-256 `9c94763b52404802bcf63a3d2056a037ab6f4a6d47487a55e0b1924d677d173d`
- Result schema: 7,596 bytes, SHA-256 `4d7317d7d066021bd5b04d43eb4dcb58bbbd3dd7245d917b404ccf14eb38612d`
- Root command: 1,007 bytes, SHA-256 `030080c186423b337269a000b10ace34846c649a9cf792e87a78a3e3d3978849`
- README: 4,688 bytes, SHA-256 `5de0954cb8aef9008117fbd6411cea2e4ee972e8d098f5d52cf94089bd792d06`

All 10 R6 artifact rows and all 42 selected R1/R5/public-source input rows matched their pinned byte lengths and SHA-256 values during this review. The 26 public source rows were independently rechecked. The R5 fake-test file is pinned at 16,604 bytes / `6c91b361346cbe3ff1ac34125f0831fed70c128a081c13645b6cba437d8f76e2`. The runner binds 12 exact selected tests and requires 12 collected and passed, zero failures, skips, xfails, xpasses, collection errors, deselections, warnings, and failure diagnostics. The schema parses and requires 42 result keys.

## Review findings

R6 fixes the R5 temp-path blocker narrowly: it creates only the fresh run directory and leaves the `pytest-tmp` child absent for pytest to create as `--basetemp`. It does not broaden accepted filesystem roots for extended-length paths. The self-check still requires an extended `.env` probe to fail as a private-config access, even when the normalized target is inside the run directory.

The added failure diagnostics are bounded and sanitized: allowlisted selected test name, phase, whitelisted exception class, safe source/function/line frames, and denied-event category/name plus two booleans. Raw exception text, locals, raw paths, and arbitrary traceback filenames are not emitted. A passing status requires an empty diagnostics list. The open-mode/flags and mutation-path/dir-fd guards from R3/R4 remain present; the dir-fd rule permits only `None` or exact integer `-1`, and synthetic CPython-shape checks do not perform filesystem mutations.

The run command uses the fixed QA interpreter with `-I -B -X utf8`, intentionally without `-S`; the runner checks the exact executable and flags, including `no_site == false`. It uses `--noconftest`, `--capture=sys`, an explicit fresh log, pinned pytest config, and an absent fresh basetemp child. The Root-attested repository checkpoint is bound to `refs/heads/dev`, HEAD `902d55daa397d601a947141b6a87eb1ca1df4d0a`, HEAD-file SHA-256 `bda77d7d12a90332080071375095fb080d8cd2a6702e6ee44552863a0ca4317e`, and raw index 2,863,553 bytes / 13,505 entries / SHA-256 `b555903584c1b95e5f0da20fcef2fe87095bf608cd12a97e8b5e45b2af5a189b`. Root separately attests cached-diff cleanliness; index entry count alone is not a clean-index claim.

No material defect was found in the reviewed R6 change. This is a bounded static review of the fixed source-fake runner and pins only. No QA, tests, Gate, native/WinAPI, provider, account, private input, software payload, or Git operation was run. Any Root QA result remains `SOURCE_FAKE_ONLY`; this review does not authorize the credential-free Gate or C01 activation and establishes no actual/account PASS.
