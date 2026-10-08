# Optional16 preparation source reconciliation R4 independent review

**Verdict: `GO_SOURCEFAKE_ONLY`.** This review accepts the frozen public
sourcefake repair for further separately authorized review. It does not
authorize or establish a Root cleanup call, account/provider access, or an
Optional16 pass.

## Frozen inputs

| File | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_optional16_preparation_source_reconciliation_r4.py` | 88,531 | `bd5b8adf47edabbdcf5faf475ce11fa0dd6b936ad03c7e4be3cd991a26773760` |
| `tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4_source_fake.py` | 46,299 | `fd6bc283ec1a286d6ea2b315ff2dd904a239777468ed62b71cee532c429ffacd` |

The helper's frozen dependency pins were independently checked against the
current public files: R1 `5277b470…09e4ba`, R2 `b3323d01…1567efd`, R3
`769f6af0…0332ca`, Call R1 `762cf58e…ae4ef8e`, Driver R1
`7930bb76…d62d71c`, Entry R2 `80295025…23c2ead`, V3
`f3270495…99a7677`, V4 `138c86e2…0c0e830`, Root runner
`5fb9fb55…f8f7dd35`, and the public CUv2 snapshot
`e856be8e…d9ad3f246`. No `D:/temp` file or software payload body was read.

## Review and verification

R4 preserves the consumed R1/R2/R3 registries and records and checks their
module/source bindings, original Root references, and expected blocked phases
before release. The corrected V3/V4 reference path compiles V3 from the
verified bytes, temporarily binds that module at the canonical aliases, and
uses Call R1's pinned `_make_module` to execute the unchanged V4 bytes. A
`finally` block restores both aliases. The helper does not disable Root's
audit hook or rewrite V4 code.

The last isolated sourcefake regression installed the Root runner's actual
audit function over a code map compiled from the fixture's held public bytes.
It confirmed the R3 AST-transformed V4 source is rejected with
`v4_reference_compile_failed`, then confirmed the R4 exact-source path closes
the fake inner scope and outer CUv2 context once. It also checked alias
restoration, unchanged R1/R2/R3 records, no retry, and rejection of an altered
R3 module alias before inner reads or release. Other focused cases cover
source/pin/registry mutations, outer callback and generator drift, and retained
scope behavior after a synthetic read failure.

Guarded command from the repository root used the designated interpreter in
isolated mode, plugin autoload disabled, `PYTHONPATH` removed, and a fresh
basetemp:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue; & 'D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe' -I -S -B -X utf8 -c "import sys; sys.path[:0] = [r'D:\temp\iteration41-main-source-qa-20260926\venv\Lib\site-packages', r'D:\source_code\backtrader']; import pytest; raise SystemExit(pytest.main([r'tests/unit/scripts/test_iteration41_optional16_preparation_source_reconciliation_r4_source_fake.py', '-q', '-o', 'asyncio_mode=auto', '-p', 'no:asyncio', '-p', 'no:cacheprovider', '--basetemp=' + r'D:\source_code\backtrader\.codex-tmp\reconcile-r4-independent-20261009-7f2a']))"
```

Result: **47 passed**, one existing `Unknown config option:
asyncio_default_fixture_loop_scope` warning.

## Limits

All scope, file/API, and opaque executable/DLL leaves in this check were
synthetic; CUv2 source came only from the public snapshot. This is sourcefake
evidence, not evidence that a real held lease was postverified or closed. The
receipt correctly retains `historical_run_assignment_identity_proven: false`.
No actual Root call, private input, credential, provider, network, native API,
process/Pipe, or WinAPI operation was performed.
