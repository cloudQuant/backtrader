# SimNow readonly strategy closure: accepted source round

Repository: `D:/source_code/backtrader`, existing branch `dev`.
Parent: `79560db367196678ba558b3c969db8c85ff03259`.

This round integrates the six unregistered typed readonly plans (C01, M01, L02, TH01, TH03, TH05), their six local common modules, and the existing shared test's sole suite-root hunk from 007 to 000. The plans expose readonly observation and completion checks; they do not dispatch provider operations or establish certification PASS.

## Evidence

All thirteen current source files match the public source map from `000-certification-offline-qa-2026-10-01/sources-after.json` (SHA-256 `55e43e35a6a23560e9533bea1094790ff2bdf79d561364ff1c6f25f2b48ce95a`). That exact source checkpoint recorded **828 passed / 1 skipped**, with one existing pytest warning, under fake/offline QA. Its README SHA-256 is `1dca81e18e4e9d01c7006331e77a32170fcac7f3305384cc0f9ae9ae5154764b`.

On 2026-10-08, Root repeated the shortest C01 typed-plan checkpoint with the designated isolated SourceQA runtime: **1 passed** in 0.17 seconds, one existing pytest configuration warning. Its fixture imports all six strategies and the common package. The synthetic complete C01 plan remains `certification_pass=False` and `dispatch_permitted=False`; the missing production ledger/provenance checks remain required. Current source hashes were verified before this run. Staged checkout-filtered bytes are also checked against the accepted sources.

Acceptance is limited to the **readonly source/import contract**, not account/provider/trading behavior. SimNow C01 remains BLOCKED. Aggregate official acceptance remains 12 PASS / 3 BLOCKED / 84 NOT_RUN; optional components remain 0/16.

## Explicit source whitelist

- `examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py` — SHA-256 `c88501fda1ce83cebb334b58566776bee5154a5cfea1c5cc22d717a2e09d3f17`
- `examples/000_live_certification/simnow_penetration/cases/M01/M01_strategy.py` — SHA-256 `e754025730f24c82b45b0cbf0e58bc4d2ddf9dcd3e9cf5b6ea85f911d1afbdde`
- `examples/000_live_certification/simnow_penetration/cases/L02/L02_strategy.py` — SHA-256 `00dff98c5dde83db35b42133aa266c9e1ba3919d1863d8be851f32fdd74b3afc`
- `examples/000_live_certification/simnow_penetration/cases/TH01/TH01_strategy.py` — SHA-256 `32eb680329cb2e83b1e7365d42faf9460b0e47716db6647208af4dde5eb4b9eb`
- `examples/000_live_certification/simnow_penetration/cases/TH03/TH03_strategy.py` — SHA-256 `c657eebc39de4313eeeb28a303f1b45ff8c3b45fdc9cf9463cb365fbda0c8398`
- `examples/000_live_certification/simnow_penetration/cases/TH05/TH05_strategy.py` — SHA-256 `cd5620c9012c0c92976202e756f5edf94e531352ef05cf2bc71f2986692648bc`
- `examples/000_live_certification/simnow_penetration/common/__init__.py` — SHA-256 `8a57066df85f78c68ae091f520370c1db0fad53f4e53cdfd10206bd3cb50c981`
- `examples/000_live_certification/simnow_penetration/common/read_only_case_strategy.py` — SHA-256 `7ea3fe284c1b13b62c52882bcfba8f9a249c1a9268505652df8ae03562415c0e`
- `examples/000_live_certification/simnow_penetration/common/case_engine.py` — SHA-256 `f8dcbac821ea75ce1d6f49aaeb78f7a42626f5c24ecfca4a855831b66ed7aec1`
- `examples/000_live_certification/simnow_penetration/common/certification.py` — SHA-256 `1604afa4dba946cd1d1fbd327c6d47057f0380d766e42d9a4614c3369851d020`
- `examples/000_live_certification/simnow_penetration/common/completion_invariants.py` — SHA-256 `58ae3c8c59bccfbe17680f313fd30b9abbcd0a14e7f8ed7e51bc520985f4506e`
- `examples/000_live_certification/simnow_penetration/common/decision_engine.py` — SHA-256 `4d09f66266b4350d33029ca5366b7cdcbb94dd0a724c49b4386b0016c238ac6b`
- `tests/unit/live_certification/test_simnow_read_only_case_strategies.py` — SHA-256 `37550c426839392ce0189bc78a4229d5693e66883648c6256e3cb5a656858e9b`

The additional staged files are this record and `.gitattributes`, whose thirteen exact per-file eol rules preserve reviewed raw source bytes across checkouts. No private config, .env, provider captures, SDK/native artifacts, new bridge, or future funds candidate is included. The containing Git commit is this round's delivery commit; its hash is recorded in the next checkpoint. No new worktree was created.
