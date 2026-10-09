# OKX M01 Root helper lifecycle R8/R5 independent review

**Verdict: `GO_SOURCE_FAKE_ONLY`.** This review covers the public source and source-fake behavior listed below. It does not establish successful composed cleanup, actual host closure, provider/account behavior, or formal M01 acceptance.

## Frozen review pins

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r8.py` | 75,279 | `c8e6a4caab04d1c813f20036bed231e5d124ad1224227e25a019d8c9bbfca08f` |
| `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r8.py` | 29,972 | `15c0f97ca1403edbdcd8d3d04c8536aeff1495113fa94a61c1d9c654a5bdb035` |
| `scripts/iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r5.py` | 77,188 | `65f0cac34348f992ff960954cc31c24ed339dffb7ae1e3feee336798d15c4fcd` |
| `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r5_source_fake.py` | 41,797 | `7be7b0eb8357129b1fd5ba4e88bd2f606280a2069ef95de277c12d9b8fbfd2e3` |

The integration R2 packet is bound by these public metadata/archive pins:

| Packet member | Bytes | SHA-256 |
| --- | ---: | --- |
| `source-index.json` | 9,970 | `865e93b85e6811d81b58bc876c9cc6883b76d2e619725836f0737a43031417b0` |
| `source.zip` | 152,448 | `55ff96b74f1d4406050ff0cd7f8cc3f9686ea17d2c16963206077cf598850877` |
| `source-map.json` | 2,877 | `07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3` |

The R2 source map matches R1 by SHA-256. ZIP central-directory metadata contains 26 unique entries, reconciles with the index names and sizes, includes the R8 Gate source and test, and excludes the superseded R7 Gate source and test. Archive member payloads were not extracted or read. The packet scope retains the 24 non-Gate members and replaces only the Gate pair.

## Source-fake QA

The designated focused suite had already been run with:

```text
D:/temp/iteration41-main-source-qa-20260926/venv/Scripts/python.exe -m pytest -q -c NUL -p no:asyncio --noconftest tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r8.py tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_r7_root_caller_r5_source_fake.py
```

Result: **45 passed, exit 0**, with two `PytestCacheWarning` messages because `-c NUL` leaves pytest without a writable cache configuration. The test result is source-fake evidence only.

## Review findings

- Gate R8’s output change is narrow: it writes the fixed LF-delimited bytes through `sys.stdout.buffer.write` and bumps the output schema. The fake stream test distinguishes binary output from Windows text-mode newline translation. Root’s separate paired current-host reproduction measured 32-byte CRLF text output versus 31-byte LF binary output for fixed synthetic bytes; that reproduction did not recover or prove the exact bytes emitted by the prior actual Gate child.
- The Gate tests exercise the successful cleanup predicate and retention on uncertain or descendant cleanup. Caller R5 accepts a clean wait sequence only as `[True]` with no fallback, or `[True, True]` with a successful fallback. It requires final `job_count_after_exit` and every `job_count_after_cleanup` value to be zero, along with the other clean facts; failed waits, uncertain cleanup, and nonzero final job counts are rejected.
- CUv2 normal close is conditional on the clean facts and checks the exact generator, a false `__exit__` result, and a reaped frame. Exception or uncertain paths retain source, scope, and module references.
- The full composed caller fixture is failure-only. It loads the synthetic 31-public/3-software source set, CUv2, five modules, and Gate with fake OS leaves; Gate is called once, then a synthetic runtime hash mismatch blocks before `CreateProcess`. The caller returns blocked and retains references. This composition does not demonstrate a successful normal close. Unit tests cover the normal-close primitive and uncertain-close retention separately.

## Limits

No actual/native/SDK/private/provider/account operation, retained-host operation, opaque software payload read, or actual host close was performed for this review. No successful composed CUv2 close or formal M01 PASS is claimed. The result is limited to the frozen public-source and fake-test scope.
