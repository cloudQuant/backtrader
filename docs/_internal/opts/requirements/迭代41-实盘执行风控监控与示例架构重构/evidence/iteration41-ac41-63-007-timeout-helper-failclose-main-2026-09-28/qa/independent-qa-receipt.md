# 独立 QA：007 run timeout helper fail-close candidate

结论：**GO（仅限窄范围 helper fail-close 候选）**；**NO_GO（CTP live/write acceptance、account-wide isolation 或 writer closure）**。

## 冻结输入与独立复放

- Frozen candidate: `D:\temp\ac41-63-007-run-timeout-failclose-candidate-2026-09-28`
- Patch: `patch.diff`, SHA-256 `99AD01EC1433CCCF3E9D0ACA9764E630F31E53C4F1C7D156D0FBCFA39677157D`
- Manifest: `SHA256SUMS.txt`, SHA-256 `924D724E2F7CB15C02AFD547281724C74F6106C395D844EEEEBDDD01831585D8`
- Candidate index: `CANDIDATE-INDEX.md`, SHA-256 `0FF00B8446704E8DD124588692C41D0DF0C01036F66EB8557D494AC100023C6F`
- Fresh replay root: `D:\temp\ac41-63-007-timeout-independent-qa-2026-09-28`
- Replay root `git config --local core.autocrlf` was `true`. Before applying, `pwd` and preimage hash were confirmed in this temp root. `git apply --check candidate.patch` and `git apply candidate.patch` passed there.
- Source preimage hash: `1D80D22C431068D991955093C2778AC98F39A6BC36A90F6F427FA8665AA67B3B`.
- Replayed source postimage hash: `37536B9598E3EE2414DE2AF787EA1E15C8C52E42558E9679107DB4F3F34C273A` (matches manifest).
- Added unit test was absent before apply; postimage hash: `C5F88209C110CABB57F71003CFF9B56C0DA4D54DB43B3675ECB7414840DE5EF3` (matches manifest).
- Final read-only guard check of the shared checkout found source hash still at the preimage and the new test absent.

## Verification

- Ruff, source plus four focused test modules: passed (`All checks passed!`).
- Pytest command: `python -m pytest -q -c pytest.ini --confcutdir=tests/unit tests/unit/test_ctp_example_support.py tests/unit/test_iteration41_007_live_feed_failclose.py tests/unit/test_iteration41_007_live_broker_failclose.py tests/unit/test_iteration41_007_live_timeout_failclose.py`
  - Result: **7 passed**, 1 existing `PytestConfigWarning` for unknown `asyncio_default_fixture_loop_scope`.
- Independent counting probe: `independent_fake_probe.py`.
  - Frozen preimage: fake Cerebro `run=1`, `runstop=0`; fake Timer construct/start/cancel=3.
  - Candidate: `run=0`, `runstop=0`, Timer calls=0; SDK import guard events=0; socket/network guard events=0; `bt_api_py` not loaded.
  - Candidate retains both module attributes `threading` and `run_cerebro_with_timeout`.
- Static writer scanner outputs: `writer-inventory-pre.json` and `writer-inventory-post.json`, both custom-scoped to all of `examples/007_ctp`.
  - 105 Python files, 59 writer candidates, 5 dynamic candidates, 0 parse errors on each side.
  - `writer_candidates`, `dynamic_execution_candidates`, `parse_errors`, file list, and counts compare identical pre/post, including row locators.

## Call-site audit and limits

Repository search found five calls to this 007 helper. Every call is in one of five live `run.py` files under `_legacy_main()`, whose first statement unconditionally raises `legacy_direct_execution_error`; their `main()` and `__main__` paths are also fenced/config-first. Backtest scripts import `ctp_example_support`, but do not import or call this helper. No repository-local non-live consumer was found. External callers may still have used the module-level helper, so this changes its runtime behavior while preserving its name.

This patch blocks only `run_cerebro_with_timeout`. Public Store/Feed/Broker construction and manually assembled Cerebro execution remain outside this proof. No real provider, CTP SDK, native session, credentials, account, or network route was used or tested. The route stays `NO_WRITE / LIVE_NO_GO`.