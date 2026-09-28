# Independent QA — mechanical SDK API boundary test patch r1

Date: 2026-09-27

## Verdict

**NO_MERGE for the frozen directory as-is; SAFE for the canonical test-only patch contents.** The manifest-designated r1 test file independently proves the changed branch: the old source produces one failure and one pass; the reviewed source produces two passes. The 29-test combined focus and Ruff pass. The NO_MERGE qualifier is package hygiene only: the frozen root also contains an older, unmanifested `replay` copy with different test bytes and a stale failed run. Do not treat that directory as one unambiguous freeze until the stale copy/log are removed or explicitly excluded in a new manifest. No main files were edited.

## Frozen identity and exact replay

Candidate root: `D:\temp\iteration41-mechanical-sdk-api-failclose-testpatch-r0-20260927`.

- Frozen manifest SHA-256: `D9EF746E7CA56EC8E1BCDBB45B4CE033D1CCB541619D69E2B15FC88FD3201F1A`
- Test-only patch SHA-256: `5DB64E45C19C63F060786740242B081998ED079E2E4D7086B4C7A99201E453F7`
- Added test file SHA-256 (manifest value): `3F462651E3CC5F66B990B495BE2BFC50913BB60E11D17D28F02F215E67998783`
- Related mechanical-cycle test SHA-256: `67614A96854400E175EEFC69F1F291914E036160DDBBB80D448365A4AF2189A4`
- Source patch SHA-256: `299CD0215A8636F25C7E3B74F70CD05C30372059EFC1150E9BB96A47F668B70C`
- Replayed patched source SHA-256: `549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F`
- New test target `D:\source_code\backtrader\tests\unit\test_ctp_options_simnow_mechanical_api_boundary.py` was absent in main.
- Both patches passed non-mutating `git apply --check -p1` against main. Fresh disposable Git replay applied `source.patch` followed by `tests-only.patch`; replay source and added test hashes match the frozen manifest exactly. The main target status remained empty and its source preimage remained `AA4292252D86E560A733B1030CE3C1438BC37FD99CD5B66518C853FD87CCFA19`.

## Red/green test evidence

I made separate QA copies of the overlay and replaced only the source module in the baseline copy with the exact main preimage.

- Old source, two new tests: **1 failed, 1 passed**. The missing-API test reaches the old `store._ensure_api_ready()` call and fails on its fake-store assertion. The non-null public API control passes.
- Reviewed source, two new tests: **2 passed**.
- Reviewed source plus existing mechanical-cycle test: **29 passed**, one existing `asyncio_default_fixture_loop_scope` pytest-config warning.
- Candidate-only JUnit XML SHA-256: `9A1930FB3925F4AFEA27ABBCFB535F59EFB23064A4F88963DF90C2B2ADEFF0B9`
- Baseline-red JUnit XML SHA-256: `9F45094CF4BA00C46B2D9EF29E9A460810EF4F8C06E3579F0C435690CB7DD2C3`
- Combined 29-test JUnit XML SHA-256: `EF9F0A4842408E317C6E20839442255C46BCE5B4DD070D1E25760758336946AB`
- Import/native/SDK/socket guard logs for baseline, candidate, and combined runs are each `[]`, SHA-256 `4F53CDA18C2BAA0C0354BB5F9A3ECBE5ED12AB4D8E11BA873C2F11161202B945`.
- Ruff passed for the added test and for both main/candidate versions of the source using the repository `pyproject.toml`.

Commands used for the focused red/green runs (with working directory set to the corresponding temporary overlay):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:MECHANICAL_QA_GUARD_LOG='<QA-root>\guard-<baseline-or-candidate>.json'
$env:PYTHONPATH='<QA-root>\<baseline-or-candidate>;D:\source_code\backtrader'
python -B -c "import sitecustomize,pytest; raise SystemExit(pytest.main(['-q','<QA-root>\<baseline-or-candidate>\tests\unit\test_ctp_options_simnow_mechanical_api_boundary.py','--junitxml=<QA-root>\<baseline-or-candidate>-junit.xml','--tb=short']))"
```

The combined command used the repository pytest config and the two temporary test files:

```powershell
python -B -c "import sitecustomize,pytest; raise SystemExit(pytest.main(['-q','-c','D:\\source_code\\backtrader\\pytest.ini','<QA-root>\\candidate\\tests\\unit\\test_ctp_options_simnow_mechanical_cycle.py','<QA-root>\\candidate\\tests\\unit\\test_ctp_options_simnow_mechanical_api_boundary.py','--junitxml=<QA-root>\\combined-final-junit.xml','--tb=short']))"
```

## Mock scope and limits

The 153-line file is heavily stubbed by design to isolate a narrow API readiness boundary. It replaces disabled admission, receipt/trust-root validation, credential/front resolution, runtime/evidence hashing, bundle/gate verification, and the settlement function. None of those fakes can validate approval policy, evidence freshness, SDK semantics, account state, or a write.

The assertions are still meaningful for this patch: the negative test proves the old implementation enters its private fallback and the candidate instead fails closed; the positive test proves the exact supplied public API object is read once and forwarded to the existing settlement boundary without calling `_ensure_api_ready`. That boundary is replaced by a sentinel before any API/write action. The test has no `.env`/private-config path, uses `env={}`, replaces credential/file-reading helpers with synthetic stubs, and uses a fake Store. The explicit import/socket tripwire recorded no event. No credentials, SDK/native module, provider, network, or order was accessed.

## Frozen-directory inconsistency

The manifest names `replay-r1` and its added test has the canonical SHA above. The same root also contains an older unmanifested `replay` directory whose test SHA is `081B92D9AF270283431FBC24A11588F64FBC9001BBD8B4FE1391D81117164820`; that copy omits `bundle.exchange_id`. The unmanifested `combined-tests.txt` contains the resulting `1 failed, 28 passed` run. The manifest-designated `replay-r1`, overlay, and fresh patch replay all contain the correct matching test bytes. I did not edit or clean the frozen candidate; this residual is why the directory itself receives NO_MERGE despite the canonical patch passing independent red/green verification.

This is local fake test evidence only. It does not authorize any CTP/SimNow route, production merge, live operation, or F14 acceptance.
