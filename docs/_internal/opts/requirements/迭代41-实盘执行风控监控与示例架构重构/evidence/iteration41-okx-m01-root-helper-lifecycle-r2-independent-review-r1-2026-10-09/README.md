# OKX M01 root-helper lifecycle R2 independent source-fake review

Date: 2026-10-09

## Verdict

`GO_SOURCE_FAKE_ONLY`. The four frozen public files below were reviewed and the focused gate and patch tests passed independently. No source defect was found within this scope.

## Frozen files

| File | Bytes | SHA-256 |
|---|---:|---|
| `scripts/iteration41_okx_m01_root_helper_lifecycle_gate_r2.py` | 42,137 | `0c9067ba1a759a6843bc7249ffbe38a09f30c6d5f7e5ab1612cd60846d83e976` |
| `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py` | 20,224 | `d6df3de0af5695d6842c711597dddd998dc3f394144be89d720c851e1c600848` |
| `scripts/iteration41_okx_m01_root_helper_lifecycle_patch_r2.py` | 13,625 | `c53833b20238cb82d491bf7972508a604e56c8ad3158cada7060f9910629a78e` |
| `tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_patch_r2_source_fake.py` | 7,396 | `c413205ebd5053d13396368dd23c88b9e7ac431881802f9319c2425eb559bfc5` |

The gate binds the pinned reader, supervisor, worker, their function globals and source origins. Its fake Win32 leaves execute the source-pinned worker bootstrap and cover integer-zero/WinError-109 EOF, the exact reader error, process exit versus Job counts, and uncertain cleanup retention. The patch transformer accepts only the pinned reader source and compiles a deterministic replacement into isolated held globals. Its tests distinguish root-process cleanup, terminated descendants, surviving descendants, and close failure while preserving the primary reader error. Uncertain Job/thread/pipe/handle state retains references.

## Independent QA

Command, from `D:\source_code\backtrader`:

```powershell
& 'D:\temp\iteration41-main-source-qa-20260926\venv\Scripts\python.exe' -m pytest -p no:asyncio -c NUL tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_gate_r2.py tests/unit/scripts/test_iteration41_okx_m01_root_helper_lifecycle_patch_r2_source_fake.py -q --tb=short
```

Result: 14 passed, exit 0, 2 `PytestCacheWarning` notices caused by the Windows `-c NUL` cache location, 1.13 seconds. Root separately reports its guarded source QA passed 14 with exit 0 and no warnings, exact reader/supervisor/worker origins, matching pre/post pins, and an empty staging index on the current `dev` checkout.

## Limits

This is public source and fake-leaf evidence only. It does not establish actual Windows Job accounting, an actual local child lifecycle, cleanup of any retained host, provider/account behavior, or formal M01 acceptance. The transformed reader function is not integrated or accepted by this review. Any Root caller must use its already-held exact source/module objects and verify source, function and global identities before and after its call. A failed gate remains uncertain even when a source registry is empty; retain its context, compiled objects and host/TTY until separately proven safe.
