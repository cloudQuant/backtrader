# OKX M01 R7 Root caller R2 — independent source-fake review

Date: 2026-10-09  
Verdict: **GO_SOURCE_FAKE_CALLER_ONLY**

## Reviewed pins

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2.py` | 70,462 | `0c5673dfa71cb083a59b15852f087991519bf520c1384392453bac55878cd200` |
| `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2_source_fake.py` | 25,413 | `2a49a7b8102dfa3fe4541d7a9815ca1c761c557f36a69ddc169fe7ffbac9c01f` |
| R2 preparation README | 4,878 | `4e01c6b885a14631b33b11d0e12508f864ef4ab14e8460f97bca54b4d0ed9495` |
| R2 candidate pins | 12,994 | `8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12` |
| R2 source QA result | 1,577 | `74a06755500094b5daf4641e034fc037105557a7aa01436d2f1cd580de1803e5` |
| R2 packet index | 629 | `c63157b5dc362b27d80fba9a382add3aa390b57ebea1f250a7d56209a453a351` |

All 31 public entries in the candidate pin manifest independently matched the repository file sizes and SHA-256 values (31 checked, zero mismatches).

## Independent checks

Ran only the canonical focused command:

```powershell
D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe -m pytest -q -c NUL -p no:asyncio --noconftest tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r2_source_fake.py
```

Result: **18 passed, exit 0**, with two expected `PytestCacheWarning` messages caused by `-c NUL`. Ruff, Black, py_compile, and targeted diff checks are reported by the author as passing; they were not rerun for this independent review.

Static review found the CUv2 snapshot bytes and digest tied to the function code index, exact module globals, canonical imports and builtins, and canonical context-manager wrapper. The wrapped generator and wrapper closure are checked; closure-cell state is included in postchecks. The CUv2 software-path pin is required to equal the same approved source snapshot digest. Fake tests reject changed generator code, detached globals, rebound builtins, wrong software digest, and wrapper closure mutation.

The caller admits exactly 31 public pins and verifies the indexed sources and five production modules against the held bytes. Its code makes one guarded R7 Gate call. It permits normal CUv2 close only after typed clean Gate facts (including zero Job counts at the required observations, EOF/drain completion, closed observed handles, and unchanged empty registries), then requires normal `__exit__` return `False` and a closed generator. Uncertain paths retain Python references and do not permit host exit.

## Root-only use conditions and limits

The fake suite does not call `run_one` or `run_fixed_synthetic_probe`. Before a separate Root invocation, Root must independently bind the loaded caller module to its exact held source bytes **before** calling `run_one`, pass the exact held CUv2 source bytes and 31-entry public map plus software pins, and preserve same-call pre/post source and custody checks. The caller’s internal self-binding occurs only after the function has started.

This review approves only the source-fake caller contract. It does not establish that the actual Win32 Job/Pipe gate passed, actual process cleanup, provider/account behavior, private-input absence, or formal M01 acceptance. No actual/native/process/Pipe/provider/account/private or opaque software-payload operation was run for this review.
