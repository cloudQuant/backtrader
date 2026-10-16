# Iteration 10 SCN02 014_2 service live backend source round

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`, base HEAD `31fa10ff116aa658065d03ca6c5ad889867fb20f`.

This round wires the existing 014_2 `run_live` entry to an explicit read-only service backend, retaining the direct backend as the default and refusing unsupported service selections before direct setup. The CTP path consumes authenticated market source descriptors, checks shared clock identity and typed contract multipliers before subscription, and keeps unqualified clock mapping blocked. Cleanup reports a failed close instead of treating it as successful. The source round is not a provider or account acceptance.

## Acceptance evidence

Four newly affected focused nodes passed on CPython 3.11.5 with the restored shared environment:

```text
python.exe -m pytest -p no:asyncio -q \
  tests/unit/test_0142_service_backend_selection.py::test_service_candidate_multiplier_must_match_each_typed_market_contract \
  tests/unit/test_0142_service_backend_selection.py::test_unstarted_broker_still_closes_store_owned_service_proxy \
  tests/unit/test_0142_service_backend_selection.py::test_store_close_failure_remains_an_explicit_cleanup_error \
  tests/unit/test_0142_service_backend_selection.py::test_shared_market_descriptor_requires_one_clock_implementation
....                                                                     [100%]
4 passed, 1 warning in 0.34s
```

The existing warning is the repository's `asyncio_default_fixture_loop_scope` pytest configuration warning. The auto-loaded `pytest-asyncio` hook was disabled because its collector hook fails against the installed pytest version before collection; that initial attempt ran zero tests. No package installation or global environment change was made. Twenty-nine earlier source tests are historical evidence only and were not rerun in this round.

Independent static review returned `GO_STATIC_FOR_CANONICAL_QA` on the six source pins below. `git diff --check` passed. The three-leg ServiceHost/CURVE integration candidate is deliberately excluded from this source commit and has not run on the current CTP epoch implementation; it remains a later local synthetic acceptance node after the CTP owner patch receives static GO.

Evidence level: focused source/fake checks and static review only. No live CTP provider, account, credentials, external venue, order write, or formal SCN02 PASS was exercised.

## Exact source scope

| Path | Bytes | SHA-256 |
|---|---:|---|
| `backtrader/stores/service_read_proxy.py` | 50,326 | `079c1099c594041b0df07d170fee5b13c0a13332f4c2c29185ee3dd66a530125` |
| `examples/unified/014_2_ctp_options_midfreq/run.py` | 53,761 | `57ee63cd41aac7f2f85579ae032338c5f3907311c76fb1bf07bbc4c5b6ab082e` |
| `examples/unified/014_2_ctp_options_midfreq/service_live_backend.py` | 46,065 | `0f22894941a1a1834c68e3d272a656e4fe38b7c01758895f8dab92fd4f0ab21b` |
| `examples/unified/014_2_ctp_options_midfreq/README.md` | 13,891 | `1af38b524bdbcea38554ee7cbea7b2f2f7ff9a2693c3e4b50ca757729307f603` |
| `tests/test_service_read_proxy_ctp_ticks.py` | 17,121 | `8a081018efc03dae0b2deb1350e69c23972264367a9aecfa42da0dbddb40863b` |
| `tests/unit/test_0142_service_backend_selection.py` | 9,228 | `1faa73546f60cf99cd4b5ec1bc86a346e1ab1a066fda499eb23cf30826603f5b` |

The new `tests/integration/test_0142_service_backend_ctp_host.py` remains outside this round. The exact commit hash for this record is authoritative in Git history because a commit cannot embed its own object ID.
