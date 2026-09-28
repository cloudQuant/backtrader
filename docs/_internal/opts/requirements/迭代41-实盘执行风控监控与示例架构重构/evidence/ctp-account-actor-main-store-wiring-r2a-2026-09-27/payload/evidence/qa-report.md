# BtApiStore AccountActorPort wiring r2a

## Verdict

`AUTHOR_CANDIDATE / NO_WRITE`, derived only from frozen R2; no main source or default route was edited. R2a changes only the preconstruction ordering and the focused regression tests. It keeps every CTP route unavailable.

Explicit `provider="ctp"` or `"ctp_gateway"` is rejected directly before reading `BT_STORE_PROVIDER` or `BT_GATEWAY_EXCHANGE_TYPE`. For route-based CTP such as a nested `exchange_kwargs`/`symbol_routes` CTP selector, R2a first creates a descriptor from reviewed scalar facts and exact built-in dictionaries with both environment fields unset. The route snapshot helpers do not inspect arbitrary custom mappings or API/client objects. A neutral-provider classification detects explicit nested CTP evidence and rejects before environment reads. Caller actor/context/API/credential objects remain uninspected.

For selectors that need environment facts, R2a retains R2's environment-aware classification. A `provider="btapi"` route changed by `BT_STORE_PROVIDER=okx` remains ambiguous and rejects before resolver/client/adapter dispatch. Tests assert both expected env reads and zero local side effects. Unknown custom route objects are left opaque and fail closed without iteration or attribute access.

## Source identity and patch

- Frozen parent R2 manifest: `evidence/r2-parent/candidate-manifest.json`, SHA-256 `5b68f9ed2a457e51941bbd60052a100d2e045907b9b2e3bb454482304badd27a`.
- R2 parent Store input: SHA-256 `a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8`.
- Main-base Store identity carried from R2: SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`.
- R2a Store: SHA-256 `18a02f00ec3b2031932284c9e855395c1c70c3e448dbafcd054e4f079048c4d0`.
- R2a focused test: SHA-256 `6b8eab8156f40e5b14403e4063b323386edb3671e9c614c882604e2c02f6ca4b`.
- Exact two-file delta from R2: `r2a-apply.patch`, SHA-256 `7708df2f0923b74e5f95315390580eb417e9ca05cfa4c6fe41422bc410908e99`. `evidence/replay_r2a_patch.py` verifies `git apply --check`, application, and exact target hashes with `core.autocrlf=false`.

## Verification

- Environment/API/credential/actor/context/resolver negative focus: **4 passed** (`r2a-explicit-env-focus.txt` and `.junit.xml`). This includes direct CTP, nested CTP, env-classified ambiguous `btapi`, and an opaque custom route object.
- Candidate boundary plus live-dispatch guard: **18 passed** (`r2a-candidate-focus.txt` and `.junit.xml`). Explicit OKX/non-CTP raw API injection positive and CTP forwarding/nested-route negatives pass.
- Candidate boundary + managed-execution adapter + live guard: **25 passed** (`r2a-focused-tests.txt` and `.junit.xml`).
- Legacy 30-test Store comparison remains **9 passed / 21 failed**; all 21 stop at the intended CTP actor-unavailable gate (`r2a-legacy-ctp-compatibility-delta.txt` and `.junit.xml`). Exact-base remains 30/30 in the separately frozen r1 migration audit; R2's same legacy comparison was also 9/21.
- Ruff passed; `py_compile` passed. The only pytest warning is the existing Quandl deprecation warning.

## Limits

CTP Actor dispatch remains unavailable. This candidate adds no external authority, provider access, credential access, SDK/native access, network access, F14/G1/G5 acceptance, default route, or write capability. The 21 legacy failures are retained as the policy compatibility delta, not relaxed.
