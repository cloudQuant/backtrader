# OKX M01 V3 R2 coherent dev-round record

## Scope and base

This is a public delivery plan and evidence record for the R2 source-fake component only. It is not an account, protected-map, WebSocket, provider, native, or formal M01 acceptance result. The M01 acceptance count remains 0.

Repository: D:/source_code/backtrader; branch dev; base HEAD 565cb93298a53703c47390a05eb23a1ff4985b09. The index was empty when this record was prepared. The 20 current public source/test files all match the frozen source-index pins.

Root canonical fixed-path gate result fabafb: 13 passed, 0 failed, exit 0, 0 warnings; all 20 source/test pins matched before and after. The earlier relocated full-file gate 64cc81 recorded 10 passed and 3 failed, exit 1, because fixed canonical source-origin contracts are not relocatable; it is not a clean relocated pass. The frozen packet snapshot focus passed 4 tests with its existing PytestConfigWarning. Independent canonical R2 review passed 13 source-fake tests with its existing warning.

## Candidate source/test whitelist

The proposed stage set is 16 files: 14 runtime files with modified or untracked status, one runtime file whose status is clean but whose checked-out bytes differ from the committed HEAD blob, and the untracked source-fake test. Four other clean runtime files remain byte-identical to HEAD. Current file hashes and sizes were recomputed from the exact 20 source-index paths; every row matches its frozen pin.

| Path | Status | Bytes | SHA-256 | Scope |
| --- | --- | ---: | --- | --- |
| backtrader_runtime/certification_roundtrip_private.py | clean | 17537 | b866194bdc56d91cc7a6678e83b0af8e4e018ee53a2c136325344c2ee8a5ecfd | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/__init__.py | clean; checkout differs from HEAD | 66 | a55f2a221bc45d1b840c15ca9ec8e5f46579e011728ec9e7c3b0748eacc7f7dc | inherited_r1_runtime; preserve pinned CRLF bytes |
| examples/000_live_certification/okx_penetration/_certification/cases.py | clean | 5569 | 0e0d7618846975db37551222f3c902ceee2b975f4be0b8236dcf021508492762 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/config.py | modified | 19369 | 3b5141a3c903e8c7eb0388d2907906c06c54ac41657e32fb9f11360e7efdeae3 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/evidence.py | clean | 5491 | 05916efcd52a49fbd6303d315e17b8f57a3f411b3557872250e899636ffb9217 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/fixed_owner_routes.py | untracked | 2152 | fe22dfca3b902c0b04855acd89f947d5d8de72a2475090ea92179eb415dad401 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/m01_private_monitor_v2.py | untracked | 25108 | 1c319502dcec4da91a7166ad1a532e4610319ca837ac93f2391f21fda87ae1db | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/models.py | modified | 6526 | f6db3e492fb8681bb156a577515b73e9966142e447f9d857ad4ec8a024389362 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_certification/runner.py | modified | 83470 | b25dbccd2ea745433d1f646d217c98d970207a6e861f9da45b9c0d40a0b340e5 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/__init__.py | untracked | 56 | d7cbd961ed06466f6bd2388d44a5951f92b0bb9f61d930cc9d26ec21be8d1a5c | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/current_types.py | untracked | 7364 | cd896051b0580195baa569989622c18fec594afc3772e7ea4af9e4cf226778ea | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/job_supervisor.py | untracked | 71188 | 188b929b4e74b6e16a54d21093b6d52a7471849b161b2777945561e6d8d62e82 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v2/worker.py | untracked | 60000 | aea9651c571d4bbd93592ccbd06c630a2a73df8286e9425a357433d598ca4f41 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/__init__.py | untracked | 50 | ae66c18bb4d289dd2e09e9ac637af8a6ef017f4f6cc5edec4a23ee23d7e560e6 | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/current_reader.py | untracked | 63711 | b350e0d0110a3c87f6fc44a841b9df12e229eff2efac1060d66b598c17cbc734 | direct_r2_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/entry.py | untracked | 5952 | a5ac85ff1b4c19a542abff56e728696eedee3959e5e7e4df8d6ac7cec0332575 | direct_r2_runtime |
| examples/000_live_certification/okx_penetration/_m01_readonly_monitor_v3/issuer.py | untracked | 43112 | afdfb863dc8917ef07dbf844183b6216df578a85d3477dda1c32c9226cdb9ad8 | direct_r2_runtime |
| examples/000_live_certification/okx_penetration/cases/M01/M01_strategy.py | clean | 480 | 2ce73442c1e1ed0be95b3065e5434fb95b16d2b6026ed86e20b07a8e6ba97afc | inherited_r1_runtime |
| examples/000_live_certification/okx_penetration/cases/M01/run.py | modified | 1992 | 95db64019fb4f7e6124e15ead558b2686c70c8987d2b4ec941467e269ff0fc92 | direct_r2_runtime |
| tests/unit/live_certification/test_okx_m01_readonly_monitor_v3.py | untracked | 32737 | 9d66d25310f5ee1b29943b222854e2a9d9b8ba48adcfe9848037f7afcb297a0d | direct_r2_test |

Proposed index whitelist: the 14 modified/new runtime rows, the clean-status `_certification/__init__.py` byte-preservation row above, and the untracked test. Its frozen checkout pin is 66 bytes with SHA-256 `a55f2a221bc45d1b840c15ca9ec8e5f46579e011728ec9e7c3b0748eacc7f7dc`; the committed HEAD blob is 65 bytes with SHA-256 `dc6242322955db538276366944d6359193d4f23fbdf7d085ea5db97b7b26f12c`. The four other clean dependencies are byte-identical to HEAD. Stage the exact checkout bytes after the scoped `-text` rule is in effect. This record does not stage any path.

The five source-index rows with clean Git status need exact path-scoped -text rules to preserve byte pins across checkouts. One of these, `_certification/__init__.py`, must also be staged because its pinned checkout bytes differ from the committed HEAD blob. Proposed rules are listed below; none was applied:

- backtrader_runtime/certification_roundtrip_private.py -text (current text attribute: set)
- examples/000_live_certification/okx_penetration/_certification/__init__.py -text (current text attribute: unspecified)
- examples/000_live_certification/okx_penetration/_certification/cases.py -text (current text attribute: unspecified)
- examples/000_live_certification/okx_penetration/_certification/evidence.py -text (current text attribute: unspecified)
- examples/000_live_certification/okx_penetration/cases/M01/M01_strategy.py -text (current text attribute: unspecified)

The existing .gitattributes file has separate dirty protected-rebind rules, which are excluded. No .gitattributes content was edited. Root owns the attribute/index changes while committing.

The shared models.py row is exactly the inherited R1-pinned SHA-256 f6db3e492fb8681bb156a577515b73e9966142e447f9d857ad4ec8a024389362. The later L04 formal_proof hunk is excluded. config.py and runner.py are also inherited R1-pinned closure rows; fixed_owner_routes.py is a required inherited dependency.

## Public packet count correction

The frozen packet README previously listed `source-index.json` as 11,125 bytes. The exact file is 11,314 bytes (SHA-256 `abc6e49afab4fad7d44dc70474cfc993e212e71c56270b7d065374da63da9bc8`). The README byte count was corrected only; the map, index, archive, runtime rows, test pin, and QA outputs remain unchanged. The corrected README hash and size are recorded in `delivery-whitelist.json`.

## Frozen review and source dependencies

Frozen R2 packet directory: docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-v3-reason-preservation-r2-selected-source-qa-r4-2026-10-09. Its seven public files and exact pins are recorded in delivery-whitelist.json. The packet carries the 19-row runtime map and 20-row source/test index.

Inherited R1 source archive: examples/000_live_certification/okx_penetration/evidence/okx-m01-readonly-monitor-v3-source-candidate-r1-2026-10-03. Its exact checkpoint, INDEX, README, and source.zip pins are listed in delivery-whitelist.json; source.zip SHA-256 is 02f9605429a5e230dfe9f252a08f8d48af311f0b3833891676415bab8551cdde and it contains 20 indexed members (19 runtime sources plus test).

Inherited R1 independent review: GO_SOURCE_FAKE_ONLY, with all five review artifact members pinned in delivery-whitelist.json. Direct R2 independent review: GO_SOURCE_FAKE_ONLY, with its README and review.json pins listed there. These reviews do not establish protected deployment admission or account readiness.

## Root QA artifacts and result boundaries

The two Root QA artifacts copied into this directory are exact byte copies of .codex-tmp/okx_m01_r2_root_source_qa_20261009.py and .json. Their source/copy SHA-256 and size checks passed. The verifier script was not run by this archive task.

The Root canonical result is SOURCE_FAKE_COMPONENT_ONLY, with exact 20 source/test pins verified before and after the selected gate. The older relocated full-file failure is preserved as a limitation, not represented as a clean relocated acceptance. Packet-only and independent-review test results remain source-fake evidence only.

No protected map was read or updated; no account, WS, provider, native, or actual M01 operation was performed. Retained host 90344 was left untouched. The new metadata/account gate remains outstanding.

The protected-rebind helper/test and the two dirty attribute rules associated with that separate unaccepted round are explicitly excluded. No source or attribute edits, stage, commit, test rerun, or broad dirty-file enumeration occurred.

See delivery-whitelist.json for the machine-readable current 20-path pin/status table, inherited review/archive member pins, QA summaries, and proposed path-scoped attribute rules. archive-pins.json pins the exact bytes of this record and the two copied Root artifacts; it excludes itself.
