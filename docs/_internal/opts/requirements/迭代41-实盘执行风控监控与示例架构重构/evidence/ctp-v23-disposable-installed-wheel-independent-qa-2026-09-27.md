# V23 disposable installed-wheel probe — independent QA

Date: 2026-09-27  
Disposition: **Local disposable wheel build/install evidence verified. G1 and G5 remain closed; the default route is unchanged.** No candidate/main source, pin, credential, provider, or native module was changed or used.

## Identity and independent reproduction

The frozen V23 source manifest is SHA-256 `f94b924e1e20fba6ccfe5bc028d88a0ad541022afb8e9c7a5f66a597687ab330`; its 44 payload files total 1,748,219 bytes. The original probe artifact manifest is `9fa563a58225e715b955a524d2e06a141e78adc684bcb852e70bdf7b56cd9a14`, and its archive is `fd2656dc2347daa6badf592764bd856a628c756291cd1c26d575e5dba327a312`. The 133 manifest entries were rehashed; archive `testzip()` passed.

Two fresh, separate build roots were reconstructed from the hash-verified source payload. Both emitted the same 177,694-byte wheel, SHA-256 `9f7f61cc0ddea8953070fcfdfa6ac41e70d3bd594c2ceda35f9377db57419591`. This wheel identifies itself as `0.2.3.dev0+audit.v23.f94b924e1e20`, a unique disposable audit version, not a release. Both wheel ZIPs passed integrity and RECORD checks (18 rows, 17 hashed, 14 package members byte-identical to source).

A fresh venv with `include-system-site-packages = false` installed the rebuilt wheel and six locally supplied test-tool wheels with pip `--no-index`; `pip check` passed. Installed origin and distribution version resolved within that venv. Installed RECORD verification passed: 34 rows, 20 hashed, 13 pip-generated unhashed pyc rows, and all 14 package files byte-matched the wheel.

## Offline test and guard results

The installed wheel passed the focused suite (**186 passed, 2 skipped**) and full package suite (**322 passed, 2 skipped**); the JUnit reports show zero failures/errors. Three fresh-process guard receipts record 0 external connect/DNS/sendto attempts and 0 loaded native roots. The test processes used 26 local loopback connections for Windows asyncio socketpair; four `bt_api_ctp` import attempts were blocked, and no native module loaded. The Python-level guard allows loopback and blocks external destinations/DNS; it is not an OS firewall attestation. Pip used only local wheels.

The original failed guarded attempt is preserved: **180 passed, 2 skipped, 12 setup/teardown errors**. Its traceback attributes the errors to the initial guard denying the local loopback used by Windows asyncio `ProactorEventLoop.socketpair()`. The final guard permits loopback while denying external destinations/DNS. The original failed attempt's log SHA-256 is `c8f6c047d66f6844b5272076e0d96e6319ab628de110b9db103b8171cd348be1`; JUnit SHA-256 is `fe83f80a5fa7a417d248f9c96c8a4846498ee284c534154c6d869b04bb0d55d2`. The initial all-connect-deny guard source is absent from the freeze, so the failed attempt is preserved and explained but cannot be replayed from that exact source.

## Scope and raw evidence

This independently verifies a local unique-version wheel build, offline installation, RECORD/origin, and fake/offline package tests. It does not prove release provenance, deployed installation, real CTP/native behavior, a provider session, bounded service containment, G1/G5 authority, or any live route. **G1/G5 acceptance are false; the default route was not changed.**

The raw archive is [ctp-v23-disposable-installed-wheel-independent-qa-2026-09-27.raw.zip](ctp-v23-disposable-installed-wheel-independent-qa-2026-09-27.raw.zip), SHA-256 `1b3992c976d3af7b59d24e88af401bca10f988e8199f541e41cea991400f6df8` (2,434,697 bytes). Its [external index](ctp-v23-disposable-installed-wheel-independent-qa-2026-09-27.raw.zip.index.json) binds the archive hash and reports ZIP integrity passed; the archive also contains a SHA-256/size index for every internal entry. The independent QA receipt SHA-256 is `3822d825840035388f9e9abee7a8849bc2efa81743663e20e4d1f42306c1e5da`; the source-freeze and test receipts, scripts, build wheels/logs, installed RECORD and venv config, guard receipts, test logs/JUnit, and original failed-attempt log/JUnit are inside the archive.
