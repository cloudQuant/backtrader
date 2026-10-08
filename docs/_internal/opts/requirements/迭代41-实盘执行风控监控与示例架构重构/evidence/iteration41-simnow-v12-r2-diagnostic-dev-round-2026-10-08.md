# SimNow V12 R2 supervised diagnostic: accepted dev round

Repository: `D:/source_code/backtrader`; existing branch: `dev`.
Parent: `d283ec9d9d059846a0845705b2d45f0de57f1cce`.

## Scope and acceptance

This round integrates the complete pinned V12 R2 readonly diagnostic closure: the bounded supervisor reconciliation, Root/front/runner bindings and their exact earlier source prerequisites. Five of its 25 payloads are already committed at their accepted bytes; twenty source paths remain for this round. The six common strategy modules were accepted and committed separately in the parent round.

All 25 current payloads match the reviewed packet's sizes and SHA-256 values. Independent static review passed the Root -> V7 -> V12 loader, source manifest, runner pin, and bounded reconciliation checks. Root's current designated isolated SourceQA run executed the supervisor-reconcile file and shortest C01 typed-plan node: **7 passed in 0.76 seconds**, with one existing pytest configuration warning. Earlier packet test counts are author-reported and do not replace this exact rerun count.

The real readonly diagnostic completed its supervised observation and cleanup. It isolated `funds.BizType / NUL_ONLY` as a failure condition, with five request/callback pairs before the worker exited 2. Outer Jobs reached zero, readers joined, handles closed, and Root host exited 0. This accepts the **diagnostic infrastructure and its failure projection**; the account case remains BLOCKED. Later funds and snapshot changes are separate candidates and are excluded.

Official acceptance remains **12 PASS / 3 BLOCKED / 84 NOT_RUN**; SimNow C01 PASS is zero and optional combinations are 0/16. Source/fake checks and this diagnostic do not establish complete real-account certification.

## Explicit payload closure

- `backtrader_runtime/certification_binance_roundtrip_r3_cli.py` — SHA-256 `62b96a9040d530c8ec592471f0595154fb60239ca03bd6d3b56a6c094dfc7c76`
- `backtrader_runtime/certification_roundtrip_private.py` — SHA-256 `b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd`
- `backtrader_runtime/certification_simnow_c01_dependencies_v1.json` — SHA-256 `7cb851df481066ee7622aea0bdd87863d6e04d3372fb520e7685a241411f2324`
- `backtrader_runtime/certification_simnow_c01_interpreter_binding_v1.py` — SHA-256 `a38d00ecfbc7a777edab4b9d090be49ef03a94e7c23340dfe95366bacfd05494`
- `backtrader_runtime/certification_simnow_c01_native_td_read_v12.admission.schema.json` — SHA-256 `0b0f5ebfc45c482c384b78f44e2cc43c8a545e8a2a3c48c7390d28ed6f6f03dd`
- `backtrader_runtime/certification_simnow_c01_native_v2.py` — SHA-256 `9a24ef954a4e192ae2879e657613ff5ca7b1cdf5d7ee116d9e28fbef9d70ce91`
- `backtrader_runtime/certification_simnow_c01_v2_contract.py` — SHA-256 `3892af9a87ab424ceea896f9ebcbc1608515ead5e9d5c89a21ea823ff32de20c`
- `backtrader_runtime/certification_simnow_c01_v2_protocol.py` — SHA-256 `fa1028021a903fdc5602caf1e7375c6f4eb76e46ffbb819ea057b97ef048fc88`
- `backtrader_runtime/certification_simnow_c01_v3_supervisor.py` — SHA-256 `a7361ec642a4b9748fa3181fb2ef6752e3ac93bf69168b8c1240b6016868dba4`
- `backtrader_runtime/certification_simnow_c01_v4_owner.py` — SHA-256 `0c0fc8aac9f9574baca4997afea7ef8b42f89f42c3168fae1f01058459fc9d7d`
- `backtrader_runtime/ctp_front_pair_probe.py` — SHA-256 `d6f92c7d2f6df13480cebcee2c7f864ac305d34d4cda37d1a22c466932d2905f` (already at parent)
- `examples/000_live_certification/simnow_penetration/case_contracts/C01.yaml` — SHA-256 `33d60824f780784f0c391a8212816c6167dd7485dec5b9fc0b461b28e6b4adca`
- `examples/000_live_certification/simnow_penetration/cases/C01/C01_strategy.py` — SHA-256 `c88501fda1ce83cebb334b58566776bee5154a5cfea1c5cc22d717a2e09d3f17` (already at parent)
- `examples/000_live_certification/simnow_penetration/config.private.yaml.template` — SHA-256 `debc71d75b4e04c4e64c38750cdfa2101dc69585ef7898a290c721d882f51db2`
- `scripts/ctp_000_front_handoff.py` — SHA-256 `b08e70e723a5d31f18809129387455dfee3645e6ad9f2b516d7aa2789ffd19f7`
- `scripts/ctp_000_paired_front_selector.py` — SHA-256 `08d4025684503ba89c286699ad0511793c536e09af58333963cbecb40ad49ebb` (already at parent)
- `scripts/ctp_000_render_config.py` — SHA-256 `34bf2a99872f43f0d915bafcb0284827a8ac0c4baf70a2ce5f1046888223eac9`
- `scripts/ctp_i13_i15_outer_watchdog.py` — SHA-256 `31c945c77c7e147a296e66f4f1ec075e0a23f1a88b94fd339884268e79ca251c` (already at parent)
- `scripts/ctp_i13_i15_windows_job_backend.py` — SHA-256 `2566dd55d1a96285473850b1e2c63174696347da56e07d69fb72aa3a6285e381` (already at parent)
- `backtrader_runtime/certification_simnow_c01_native_td_read_v12.sources.json` — SHA-256 `d7ed0ceefdb4be6e228c8cb9c5f00d54ff029e2b2cafac5a61a4704644e7548c`
- `backtrader_runtime/certification_simnow_c01_native_td_read_v12.py` — SHA-256 `0ad7f3ccc5e58e669046cdea808a57858151839ec7b2b9dade0f013654ebcc97`
- `examples/000_live_certification/simnow_penetration/cases/C01/run_v12.py` — SHA-256 `fd0280b7578e8120d67e2114cdcf60221cc87e04aa73999c1b1902181546e7c4`
- `scripts/run_simnow_c01_native_td_read_v12_root_activation_r1.py` — SHA-256 `73953dd68095cce8f3eaacc8c0c6e25a11cd4d19f059da3b54f4ae9dbf1c6945`
- `tests/unit/runtime/test_certification_simnow_c01_v3_supervisor_reconcile.py` — SHA-256 `b56bb9eefffcc4c1d1b7c12646b33320d58f7dfe4d356c93188a248c90548d39`
- `backtrader_runtime/certification_simnow_c01_front_transport_v7.py` — SHA-256 `5342176c77bcffdd61fb232012a1f95c3666362433382b3f2986e978ca6291f5`

## Public evidence staged

- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v12-job-reconciliation-front-loader-r2-2026-10-08/README.md` — SHA-256 `aefe2f58c66430eb6f8e8194c401c4c8ce15a65a77d58fad208ea81a635184e3`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v12-job-reconciliation-front-loader-r2-2026-10-08/payload-pins.json` — SHA-256 `a9f559f4b81a7ef48c13daf5bc8e2315bd6731949acefbc385bfca4c83b7ba23`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-c01-v12-job-reconciliation-front-loader-r2-independent-review-2026-10-08.md` — SHA-256 `9c1fcb98d24133390cd5a66ae342b9e66add7827361020425605346a599afc1d`
- `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-simnow-v12-r2-root-actual-r1-2026-10-08/observation.json` — SHA-256 `b005ea4aa824f359d8d817fd20e88730544c5a0a98addd72e71623402ec6e19a`

Additional staged files are this round record and `.gitattributes`, whose exact per-file rules preserve accepted raw source bytes. No private config, .env, private capture, native SDK payload, duplicate ZIP, V13/V14 successor, unrelated changes or new worktree is included. The containing commit is the round's delivery commit; its hash is recorded in the next checkpoint.
