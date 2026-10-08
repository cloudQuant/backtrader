# SimNow V19 R2 readonly repair: accepted dev round

Repository: `D:/source_code/backtrader`; existing branch: `dev`.
Parent: `5bcd3b6170a0792d5375f28649b85b48020291ac`.

## Scope and acceptance

This round accepts the current readonly repair after the V12 diagnostic: canonical native snapshot fields and bindings, the owner's protected evidence ACL expectation, and checked rewinds of retained admission, consumed-marker and claim handles before their bounded rereads. The new V19 closure preserves identity, ACL and exact-byte checks. Shared private-input reader and CLI source are unchanged.

The R2 packet contains 25 exact core files and a 19-row source manifest. Thirteen core prerequisites are already clean at the parent. This commit adds twelve V19 core files and three frozen V17 files used only to reproduce the EOF regression. It does not add the older V15 test closure or accept a historical failed profile.

Independent source review verified all core and test-support pins and reran the focused test: **8 passed**, with one existing pytest configuration warning. It uses the production bounded reader with synthetic OS/ACL leaves; source testing alone is not account evidence.

Root's actual V19 readonly profile returned **PASS / read_only_candidate_complete** in 23.328 seconds. It completed authentication, login, three baseline queries and three final queries with a typed worker receipt, worker exit 0 and progress record 94. Reported order/cancel counts were zero. Two outer Jobs reached zero, EOF, joined readers and closed handles without forced termination. Root postverified and closed its outer physical source/runtime leases; tool session 1311 exited 0 with no retained references. No late private capture was read.

This accepts the bounded readonly repair round. Formal SimNow C01 still needs the same-process Root custody/ledger bridge. Official totals remain **12 PASS / 3 BLOCKED / 84 NOT_RUN** and optional combinations **0/16**.

Clean-source QA passed **8 tests in 0.72 seconds**, with one existing pytest configuration warning. The temporary non-Git snapshot `.codex-tmp/v19-clean-source-qa-20261008-r1` contains tracked code from parent HEAD plus only the exact V19 payload and three V17 baseline support files. All 28 files matched their pins; `git cat-file --filters HEAD:path` reconstructed the thirteen tracked prerequisites with accepted checkout line endings. The designated source-QA Python used `-I -S -B`, explicit snapshot and approved site paths, disabled plugin autoload and no ambient `PYTHONPATH`. A shorter `.codex-tmp/v19q` basetemp resolved the first run's synthetic Windows path-length failure during consumed-marker creation. No additional source dependency was needed.

## Explicit new source closure

- `backtrader_runtime/certification_simnow_c01_front_transport_v13.py` — SHA-256 `636b1ecbd72c4a6b3c7d0911dd221ae08d684efa29f97042e168cd9b9bbff43a`
- `backtrader_runtime/certification_simnow_c01_native_td_read_v19.admission.schema.json` — SHA-256 `95f0c05c0b6e3f80f9b6b0d7a23532ed28ddc84ffc7e8f03cfe827f4a6db30c2`
- `backtrader_runtime/certification_simnow_c01_native_td_read_v19.py` — SHA-256 `3de1024b233a0eee55fba7c30df69f04afa38746c9a0e88996e0db7df283fd40`
- `backtrader_runtime/certification_simnow_c01_native_td_read_v19.sources.json` — SHA-256 `fec7bc9d0ea5f90c1b2d0a7b8ec8bb663422ff0c2a8763fece6427a45091e5d1`
- `backtrader_runtime/certification_simnow_c01_native_v4.py` — SHA-256 `66666d2addc3bddbf0f13a9a30fab9fea83479d7cac7328879552e13baea5a66`
- `backtrader_runtime/certification_simnow_c01_v3_contract.py` — SHA-256 `19d8b13bda11e54a5ca037387b6abc884035ec02c05fb099f2398b99319d8fb0`
- `backtrader_runtime/certification_simnow_c01_v3_protocol.py` — SHA-256 `c48b41272ae6378060b0b65188b56ef613f001b53d13db7aceaf13489d398160`
- `backtrader_runtime/certification_simnow_c01_v4_supervisor.py` — SHA-256 `daf2cf99cbc5d977e27f59efb0f27087abdf3493c9d959d5c3d253744f869da1`
- `backtrader_runtime/certification_simnow_c01_v7_owner.py` — SHA-256 `ee492f115c60ca14f770a055061014f30b7b9cc1cecdfd09cae17f75aabf55e9`
- `examples/000_live_certification/simnow_penetration/cases/C01/run_v19.py` — SHA-256 `e2d8e0481969c01a169a313de09cc1f31bd3042af46f3392130fd6c74448e05f`
- `scripts/run_simnow_c01_native_td_read_v19_root_activation_r1.py` — SHA-256 `167b638cf84ac9e19c430497e1930d56714c5a68f928e0b3842b300034475b29`
- `tests/unit/runtime/test_certification_simnow_c01_v19_admission_rewind_contract.py` — SHA-256 `db74fe6640a0ec1fe62e73fe0be29e9fb86dd05b15a66ac3f4d8f9a76de26854`
- `backtrader_runtime/certification_simnow_c01_native_td_read_v17.py` — SHA-256 `fa202e00da45fced059b6409e17c2ea9d41b0f8e0f1666f56491735a7f39b795`
- `scripts/run_simnow_c01_native_td_read_v17_root_activation_r1.py` — SHA-256 `1c1b2a09c39d680b3c5cf2687dc2514a57c2faa71d8e9191cdf1444f106d650c`
- `examples/000_live_certification/simnow_penetration/cases/C01/run_v17.py` — SHA-256 `9d34964cae9eb4b6a7435cb77a641dab6fb4c08a38eb4ac4e357a81c007cbd9d`

## Public evidence

- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v19-admission-rewind-source-r2-2026-10-08/README.md` — SHA-256 `26a6ae5486193f589b5d852c27d074919d541834cd197eb63f0be7212e93be15`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v19-admission-rewind-source-r2-2026-10-08/payload-pins.json` — SHA-256 `2b16886181798ed85486504693baa3e894faac7604365951b54e2b5be09e0738`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v19-admission-rewind-independent-review-r1-2026-10-08.md` — SHA-256 `133fba6ed30483464a87cc3ce00c04745b1f1eae6c62cd178d3e483c7ab4a606`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-v19-r1-root-actual-r1-2026-10-08/observation.json` — SHA-256 `66988070dbc9dbf75373a18c245cf1af2634c8be87938eeaa41ec9a6bf0021f2`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-v19-r1-root-tool-observed-host-exit-r1-2026-10-08/observation.json` — SHA-256 `1e2a27c3d45c4790d7af5fe2cc937c61db7c728461473f54d9a70a3d14b73107`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-v19-r1-root-tool-observed-host-exit-r1-2026-10-08/README.md` — SHA-256 `4e60fba3241f6c66d2a99a9be2758e6eb2995619ffede89f366bb3b700dad7e8`

The only other staged paths are this round record and `.gitattributes`. Raw-byte rules preserve the fifteen new source files and public records; explicit CRLF checkout rules restore the two already tracked watchdog helpers from their LF Git blobs to the manifest's exact bytes. No private config, .env, capture, native SDK, duplicate ZIP, V18 successor, unrelated changes or worktree is included. The containing commit is this round's delivery commit; its hash is recorded in the following checkpoint.
