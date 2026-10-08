# Optional16 R2 metadata component scoped dev delivery

## Decision and scope

Independent review returned GO_SOURCE_FAKE_COMPONENT_ONLY for the exact metadata snapshot component, Bridge R2 transform, and R15 closure-transform AST anchor. The reviewed source-fake focus passed 8 tests. This delivery is limited to that component; it does not accept full Entry/R5/R27/V3/V4/R29 composition, confer Root authority, or establish any provider/native/account operation. Formal Optional16 remains 0/16. The existing Root driver review validator is still bound to its prior R1 pins/schema and cannot consume this component review.

The complete whitelist is the manifest below: seven canonical component members, the 11-file frozen source-fake packet, three independent-review files, this round record, and .gitattributes with exact-path -text rules. Stage only those exact paths. Do not add the containing evidence directories, the long-path unsealed draft, .codex-tmp, opaque payload files, or the broader production chain.

## Worktree and byte handling

The checkout is on dev; core.autocrlf=true. The byte-preservation rules are scoped to this round whitelist. This round adds exact-path -text rules in .gitattributes for every path in this whitelist, so Git will preserve the reviewed bytes on add/checkout. git check-attr text returned unset for every listed path after the rules were added, and git diff --check -- .gitattributes passed. The seven canonical members were all untracked before delivery; there were no staged or tracked hunks on those paths. In particular R15 glue was untracked and matched the exact accepted R15 pin, so there were no unrelated tracked edits to separate.

## Verification

Before delivery preparation, the exact packet-root source closure passed 8 tests (0 failed, 0 skipped; one existing asyncio_default_fixture_loop_scope pytest configuration warning) with the designated isolated interpreter. The canonical repository source tests also passed 8/8 under the same isolation after the byte rules were added. Both runs used -I -S -B -X utf8, disabled pytest plugin autoload, removed PYTHONPATH, disabled asyncio and cacheprovider plugins, and used unique repository .codex-tmp basetemp directories. The packet includes both required original JSON metadata indexes and the pinned R15 glue. No .blob/.pyc payload is present in the packet.

A post-commit clean-checkout run remains a delivery gate for Root: rerun the same two canonical tests and the two packet copies from the new checkout after staging/commit. Use exact file paths below, not directory-wide collection. The pre-commit tests above do not substitute for that post-checkout check.

## Exact whitelist

| Scope | Repository path | Bytes | SHA-256 |
|---|---|---:|---|
| canonical component | scripts/iteration41_optional16_r33_root_held_entry_r2.py | 108188 | 80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead |
| canonical component | scripts/iteration41_optional16_r33_root_held_child_bridge_r2.py | 40283 | da4c5c24cadc0bc768c43533d64cd0159d062bca19fbf9f3a122c9d84720556b |
| canonical component | scripts/iteration41_optional16_r33_root_held_glue_r15.py | 17658 | f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98 |
| canonical component | tests/unit/scripts/test_iteration41_optional16_r33_root_held_entry_r2_source_fake.py | 8399 | e3b2edac19ca7fdef881dc2962833672758982849a0ac9ece46d7c12fc2ca792 |
| canonical component | tests/unit/scripts/test_iteration41_optional16_r33_r5_same_child_composition_r2_source_fake.py | 8662 | cad6cb3fd3bdd8f44a5b6521fd54a663a7a5f1c564e5d1ee00e15f9ae6643876 |
| canonical component | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-public-profiler-stdlib-opaque-snapshot-r1-2026-10-08/index.json | 991 | b6c355a4f3b5befe33f9fe0cc5880dfcbde711879d546c876c9b48d2013b1dec |
| canonical component | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-public-profiler-cache-opaque-snapshot-r1-2026-10-08/index.json | 1418 | 9916da11d480bfbaee1a5c741240abe186b3a0ec920e7ba75a2e3580e43aecf0 |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/README.md | 2072 | 24dd22087f8becb3d52a5209b3d5056fbb9d820ea86aed9631cccc5514312713 |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/index.json | 3582 | 97c2fb2e63493744d0ffec2bc512d58d508821917f9e8292bdc22500bfdd86b0 |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/qa-summary.json | 1982 | 34223425f844e48a0905e5153d8167d0674cb6547128d3988bc2e2c435567d2c |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/checkpoint.json | 2839 | dba62112f9e0b3e9f541e4148ec6b86f554285961560071a99b6c265f37052af |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/scripts/iteration41_optional16_r33_root_held_entry_r2.py | 108188 | 80295025d0145893f4f63745182042812284434e4e7e5b4388b89d82623c2ead |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/scripts/iteration41_optional16_r33_root_held_child_bridge_r2.py | 40283 | da4c5c24cadc0bc768c43533d64cd0159d062bca19fbf9f3a122c9d84720556b |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/scripts/iteration41_optional16_r33_root_held_glue_r15.py | 17658 | f9c9a5332a9d2456db8179d7a7e63103269c16feb2712a2b039479d97fe2dd98 |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/tests/unit/scripts/test_iteration41_optional16_r33_root_held_entry_r2_source_fake.py | 8399 | e3b2edac19ca7fdef881dc2962833672758982849a0ac9ece46d7c12fc2ca792 |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/tests/unit/scripts/test_iteration41_optional16_r33_r5_same_child_composition_r2_source_fake.py | 8662 | cad6cb3fd3bdd8f44a5b6521fd54a663a7a5f1c564e5d1ee00e15f9ae6643876 |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-public-profiler-stdlib-opaque-snapshot-r1-2026-10-08/index.json | 991 | b6c355a4f3b5befe33f9fe0cc5880dfcbde711879d546c876c9b48d2013b1dec |
| source-fake packet | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata/docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-optional16-public-profiler-cache-opaque-snapshot-r1-2026-10-08/index.json | 1418 | 9916da11d480bfbaee1a5c741240abe186b3a0ec920e7ba75a2e3580e43aecf0 |
| independent review | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata-independent-review-r1-2026-10-09/README.md | 2043 | 297cb4db855316bbaa4b8f06e39574ae0ccd4d2bc9419be117db7604538e7c63 |
| independent review | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata-independent-review-r1-2026-10-09/checkpoint.json | 632 | 4e57a62b5c2011f995d2149eb37e48d2028b066d872373cb44fba863523d3e92 |
| independent review | docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/o16-r2-metadata-independent-review-r1-2026-10-09/review.json | 8383 | 1862c947d2baf3b8f758977f37017f19b53fe018a06045f4ff74371d8cb2e283 |
| byte-preservation rules | .gitattributes | 21525 | d6547efcb74ddbaf17dfb9e5bbfb81fbb7afd64309b8703c52c6dcd95ec68572 |
## Remaining acceptance work

The full Entry/R5/R27/V3/V4/R29 path still requires a reviewed opaque-metadata contract through the real production verifiers and a coherent post-checkout integration. Current V3/V4/R29 code reads and/or parses cache bytes; this component does not bypass, mock, or alter those validators. Root-owned actual execution, cleanup, and provider/native evidence are separate and were not performed here.

No files were staged or committed. The packet plus this manifest are delivery inputs for Root explicit whitelist staging.