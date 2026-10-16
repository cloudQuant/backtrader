# Iteration 10 SCN02 013 read-only service entry

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`, test HEAD `0589e9e35cb2ca1b16db6035758f36c6a84c4e79`.

This round adds a shared read-only SDK observation session for the three 013 examples and routes their public `main()` CLI selectors through it when `--backend service` is explicit. Direct remains the default. Service mode rejects `--allow-write` before loading the case configuration, does not read `.env`, and does not construct a Broker, Strategy, or Cerebro. The local Host test uses real SDK clients, GatewayOperatorDeployment, ServiceHost, CURVE transport, account metadata reader, and CTP market provider. Only the native CTP Trader/MD leaves are synthetic.

## Local acceptance

The new public-entry node passed once on CPython 3.11.5, using the committed CTP child source `e9ad8b63cbe531be0410e9e38d15ab020f9e117b`:

```text
C:/anaconda3/python.exe -m pytest -p no:asyncio -q \
  tests/integration/test_scn02_013_service_observation.py
1 passed, 1 warning in 24.68s
```

The warning is the existing `asyncio_default_fixture_loop_scope` pytest configuration warning. All three public selectors returned `OBSERVED`. The test checked their exact original example IDs and instrument/exchange pairs, the complete synthetic account snapshot, exact provider instrument metadata and market events, descriptor/key identity, and clean session/Host shutdown. The result remains observation only: `clock_mapping_qualified=false`, `freshness_qualified=false`, `execution_eligible=false`, `write_capability=UNSUPPORTED`, and `trade_execution=not_run`. No strategy or order path ran, no live venue or real account was contacted, and no formal SCN02 case count is claimed.

The fixture assertions confirm runtime and facades closed without cleanup uncertainty, account-provider `close_count == 1`, both Host deployment threads joined with deployments closed, and zero active market handles. No 014_2 or prior accepted node was rerun.

The helper unit test passed 5 tests with the same existing warning. Ruff passed on the helper and both new tests; `py_compile` passed on the helper, tests, and three example entry files. `git diff --check` passed for the three changed entry files.

The accepted source/test bytes retain one final empty line in the helper and the new integration test. Those exact bytes were used by the recorded QA; the scoped staged whitespace check therefore excludes only `blank-at-eof` while retaining CR-at-EOL and all other whitespace checks.

Pytest output and per-entry summaries are preserved at:
`D:/source_code/backtrader/.codex-tmp/scn02-013-service-entry-e9ad8b63-r1-20261017/`.
The directory contains `stdout.log` (668 bytes, SHA-256 `27b95cc0924860a32c0a47b63d2d97599c459a1eca50bbf190cd3a89f18ebab2`), empty `stderr.log`, `junit.xml` (382 bytes, SHA-256 `96c511df831b917b11cfb33a11352fee57a8f49d8cec9ad7793032905c9aa507`), `exit-code.txt` (`0`), pytest basetemp, and each selector's `run.json`.

| Per-entry evidence | Bytes | SHA-256 |
|---|---:|---|
| `013_1-evidence/run.json` | 3,926 | `56baeee966fcdcf9e78fe32df0a4caf54dc762b5a4a9ae99fdac2ef5be60e152` |
| `013_2-evidence/run.json` | 3,939 | `e8f9382359f6cd65dcc6b50453b62236182f96fd1351461c86d4665d56c77d08` |
| `013_3-evidence/run.json` | 2,680 | `64aa321a63f7e12e6be84110494ecc3ae9fa0727db3f16de8927e385579febed` |

## Exact Backtrader candidate pins

| Path | Bytes | SHA-256 |
|---|---:|---|
| `backtrader_runtime/service_observation.py` | 49,619 | `8032adf807cf9adec8c59091730954ca5d82ff66717db94049fbdb0f9eaff284` |
| `tests/unit/test_service_observation_session.py` | 5,983 | `14c181d69335fd451a34ddd5c5034d2e27c8ab163b31711bcefa5f9d6558a395` |
| `tests/integration/test_scn02_013_service_observation.py` | 11,643 | `203304dc3059a3311692636da09bf7abde5eb8274545e1d93a7a54237ad96f1f` |
| `examples/unified/013_1_midfreq_cross_arbitrage/run.py` | 77,539 | `31cf611df99b11ba9ce2298132583c077f11929b006a9c03dd377d12789d3474` |
| `examples/unified/013_2_highfreq_calendar_arbitrage/run.py` | 78,211 | `0ae6100e98812478f3af984457d0b1110cc7eb1b65d08a6425e26e0aada2be0d` |
| `examples/unified/013_3_sa_midfreq_simnow/run.py` | 78,040 | `d8d69854ef3855a69f4f354f82abc8366787f03aef0ec0c5ccf01ad98ff663ff` |

The test loaded the CTP package directly from its accepted child checkout at `e9ad8b63cbe531be0410e9e38d15ab020f9e117b`. At test time the SDK parent HEAD was `473a8bc90ac3fa32472c0897811b12e3686e30f9` and its CTP gitlink had not yet been updated; this local result therefore pins the child source explicitly and does not imply that the parent link was committed.
