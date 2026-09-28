# Archive replay receipt — AccountActorPort Store wiring r0

Date: 2026-09-27 (Asia/Singapore)

## Frozen input identity

- Evidence archive: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-r0-evidence.zip`
  - SHA-256 `9d3453faa8093d4b8e01fd14aeffb400b3e2e72a6d7de5babaa6f9f37b654ebf`
  - 2,277,083 bytes; `ZipFile.testzip()` returned `None`; 615 members.
- Candidate manifest: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r0\evidence\candidate-manifest.json`
  - SHA-256 `ef68998d2b8b75a2125f85bb5720c2e8ba737c818b9d76217767b627cb8b6d14`.
  - Sidecar SHA-256 `be1a792e8f5411920e9d6a964fc31bcaa0e7f0ff0b5936273824506aa35bbee8`.
- Independent extraction: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-archive-smoke-final2`.
  - 613 manifest payloads checked for exact size and SHA-256; all matched.
  - Manifest sidecar matched; archive duplicate/traversal names absent.
- Candidate Store SHA-256 `e41dd9189059911a180e7fb27bde546cb90a1f7bd2a0c59df6ed624f12c3e179`.
- Copied r4 actor-port module SHA-256 `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48`.
- Candidate test SHA-256 `19afe01afbe3679018a861ca00c16f5aa0ddd1f4c32823b52812bccce6ccfcdf`.
- Baseline Store input and current main Store both SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826` (780,123 bytes). No main production source was modified by this task.

## Independent replay

From the extracted archive, ran:

`python -B -m pytest tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py tests/unit/runtime/test_runtime_live_dispatch_guard.py -q --tb=short`

Result: **11 passed**, one existing Quandl deprecation warning, 7.00s. Raw log: `D:\temp\iteration41-ctp-account-actor-main-store-wiring-archive-smoke-final2\evidence\archive-smoke-pytest.log`, SHA-256 `fa9b7aad0c8457959928619a77a45d81b49e0ed150fed75e39669d58c6c934cf`.

Ruff passed using the repository's explicit configuration:

`python -B -m ruff check --config D:\source_code\backtrader\pyproject.toml backtrader/stores/btapistore.py backtrader/stores/ctp_account_actor_port.py tests/unit/stores/test_ctp_account_actor_store_wiring_candidate.py`

Log: `...\evidence\archive-smoke-ruff.log`, SHA-256 `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0`.

`py_compile` passed for those three Python files. Status log: `...\evidence\archive-smoke-pycompile.log`, SHA-256 `ce4ca94f5ecfd22c90fe0bcb8c4b90bc812315804fa2c99053277854e575a47e`.

The first Ruff replay omitted the repository config because the evidence archive intentionally does not include `pyproject.toml`; it invoked Ruff defaults and reported baseline-wide style differences. This was a harness invocation error, not an accepted Ruff result. The explicit-config run above passed.

## Scope / verdict

Archive and copied payload replay are intact. This is an isolated, fake/offline Store wiring candidate; it keeps runtime registry/CLI defaults NO_WRITE and has no route-authorizing fallback. Its synthetic DTO/port receipts do not establish external actor identity, current per-action authority, durable replay protection, cross-host fencing, or a same-session read/callback feed. An externally authenticated authoritative AccountActorPort service supplying those contracts is indispensable for real production acceptance. No CTP/provider, credential, native SDK, network, real broker, or gateway was used. No G1/G5/F14 or production acceptance is claimed.

