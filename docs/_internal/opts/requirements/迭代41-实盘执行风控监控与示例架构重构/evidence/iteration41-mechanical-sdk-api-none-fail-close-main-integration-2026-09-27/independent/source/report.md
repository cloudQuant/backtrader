# Independent QA — mechanical SDK API fail-close r0

Date: 2026-09-27

## Verdict

**SAFE for the narrow fail-close source change; no live/production acceptance or route approval.** The candidate replaces a private lazy-start fallback with a stable refusal when an injected Store has no ready public API. Default mechanical execution remains disabled. No SDK/native import, provider call, network, credential, private configuration, or order was used.

## Frozen identity and replay

- Frozen candidate: `D:\temp\iteration41-mechanical-sdk-api-failclose-r0-20260927`
- Frozen manifest SHA-256: `09A430C20D684D6F24D6CB359519328AF65A552A7B9195B683F6D8FE4FD31C4E`
- Patch SHA-256: `299CD0215A8636F25C7E3B74F70CD05C30372059EFC1150E9BB96A47F668B70C`
- Main target preimage SHA-256: `AA4292252D86E560A733B1030CE3C1438BC37FD99CD5B66518C853FD87CCFA19` (matches the frozen manifest)
- Candidate source SHA-256: `549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F`
- Independent replay source: `D:\temp\iteration41-mechanical-sdk-api-failclose-r0-independent-qa-20260927\replay\examples\ctp_options_simnow_mechanical_operator.py`, SHA-256 `549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F`
- `git -C D:\source_code\backtrader -c core.autocrlf=false apply --check -p1 <candidate.patch>` passed. The patch was not applied; `git status --short -- examples/ctp_options_simnow_mechanical_operator.py` was empty, and the main source still hashes to the preimage.
- The diff is one line: in `run_mechanical_cycle`, `api = store._ensure_api_ready()` is replaced by `raise MechanicalBlocked("STORE_SDK_API_NOT_READY")` under `if api is None`.

## Independent tests and guards

Fresh QA overlay imports were verified to resolve the patched module from the QA temp directory (not the main checkout). One initial invocation from the repository working directory selected the main module and failed the candidate-specific assertion; that invocation was discarded. The corrected invocation ran from the isolated overlay and resolved the replayed source.

Focused command (PowerShell, working directory set to the QA overlay):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:MECHANICAL_QA_GUARD_LOG='D:\temp\iteration41-mechanical-sdk-api-failclose-r0-independent-qa-20260927\guard-events-final.json'
$env:PYTHONPATH='D:\temp\iteration41-mechanical-sdk-api-failclose-r0-independent-qa-20260927\overlay;D:\source_code\backtrader'
python -B -c "import pytest; raise SystemExit(pytest.main(['-q','-c','D:\\source_code\\backtrader\\pytest.ini','D:\\temp\\iteration41-mechanical-sdk-api-failclose-r0-independent-qa-20260927\\overlay\\tests\\unit\\test_ctp_options_simnow_mechanical_cycle.py','D:\\temp\\iteration41-mechanical-sdk-api-failclose-r0-independent-qa-20260927\\overlay\\tests\\unit\\test_mechanical_sdk_api_failclose_candidate.py','--tb=short']))"
```

Result: **28 passed**, one environment pytest-config warning (`asyncio_default_fixture_loop_scope` unknown). The provider/native import and socket tripwire log is `[]`, SHA-256 `4F53CDA18C2BAA0C0354BB5F9A3ECBE5ED12AB4D8E11BA873C2F11161202B945`. Captured focused output SHA-256: `EF4691EF17C3530259940E4B02B3E7E1E7F0AD614D690BB1056FFB9217BF649C`.

The fake negative test reaches the branch only by replacing disabled admission and earlier input resolvers with synthetic no-I/O stubs. Its `FakeStore.sdk_api` returns `None`; `_ensure_api_ready()` raises an assertion if invoked. The candidate raises exactly `MechanicalBlocked("STORE_SDK_API_NOT_READY")`, and no provider/native import or network attempt was observed.

A separate temp-only positive control used a fake non-null `sdk_api` and made the next preflight method raise a sentinel. It reached that sentinel after the readiness guard, while `_ensure_api_ready()` remained forbidden. Result: `PASS`; import/network guard log `[]`. Probe source SHA-256 `F7FF0E68246710C44E5DDA1FFE2969AB14E9F1F8B0F84D03C87D476DC02F4F40`.

## Default ordering and source/approval binding

Static review confirms `MECHANICAL_EXECUTION_ENABLED = False`; `run_mechanical_cycle` checks that gate before receipt, credential, Store, or API work; CLI `main` checks it before `load_operator_env`. The pinned trust-root constants are `None`, and `_require_pinned_trust_root` fails before reading root bytes, approvals, or credentials. The default Store builder separately rejects absent its explicit test-only token and injected fake Store. Thus this candidate does not make the branch reachable through the default route.

The operator builds `source_hashes` including `ctp_options_simnow_mechanical_operator.py` and passes the aggregate digest into the mechanical-gate binding and bundle-authorization builder. I recomputed the aggregate using the same sorted compact JSON encoding: base `46a19abae9a4b7a8d9eabe7b290daec57c5b251af6c51a156de5a489b186063b`; candidate `89f49d9099f4f7a5eff3eda5f84aa0317ee2edd3bee896f39cb577216734cb8d`. Exactly that source entry changed, and the aggregate changed. The entry-approval issuer includes and validates `source_hashes_sha256` in the signed payload. Existing receipts/approvals bound to the prior aggregate therefore do not satisfy the candidate binding; fresh separately governed evidence would be needed if a future release enables those gates.

## Limits

This is a local source/fake QA verdict only. It does not establish external Actor authority, SDK behavior, CTP/SimNow connectivity, writer closure, real-account safety, or F14 acceptance. It does not approve route activation or production merge.
