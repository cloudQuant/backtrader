# Alpha003 AC50-17a / AC50-18a evidence

Decision: **PASS for the Alpha003-only subitems 17a and 18a at source/composition level.** This does not pass parent AC50-17 or AC50-18: 17b and 18b were not run. The known separate Alpha7 gap failure is outside this Alpha003 result and remains open. No full-101 conclusion follows.

The captured run completed on 2026-10-24 with Python 3.11.5 and pytest 8.0.0. It collected three tests; all passed in 117.664 seconds, with one existing `PytestConfigWarning` for the unknown `asyncio_default_fixture_loop_scope` option. There were no failures, errors, or skips. The captured stdout identifies the exact collected test nodes below; its original command line was not present in the log.

| Collected node | Result | Relevant coverage |
|---|---:|---|
| `tests/integration/test_live_alpha003_parity.py::test_alpha003_live_cohort_matches_independent_oracle_and_batch_paths` | PASS | Real Cerebro, BtApiFeed, cohort, LiveFactorSet, and production Alpha003 graph. Native/build at 320, 640, and 1,280 rows; batch runnext/runonce and live runnext; per-asset and logical-node comparisons against the independent formula oracle, including values/reasons and finite witnesses. The same test perturbs future inputs/availability, reorders feeds/targets/registration, and compares the 400-row history + 240-row live suffix with continuous live execution in both modes. |
| `tests/integration/test_live_alpha003_edges.py::test_live_alpha003_ties_degenerate_ranks_grouping_and_sealed_prefix[build]` | PASS | Build mode; grouped tied ranks, constant/degenerate ranks, singleton group, independent oracle, and a future suffix perturbing all OHLCV fields plus arrival times. Previously sealed prefix values/status/reasons remain equal. |
| `tests/integration/test_live_alpha003_edges.py::test_live_alpha003_ties_degenerate_ranks_grouping_and_sealed_prefix[native]` | PASS | Same edge coverage in native mode. |

For 17a, the parity case verifies future-only changes and delayed availability do not rewrite the sealed prefix, and that suffix changes have a nontrivial witness. Its reordered run compares by asset identity across feed, target, and registration order. The two edge cases perturb `open`, `high`, `low`, `close`, and `volume`, and compare the grouped live prefix for both modes. Tie and degenerate cases are explicit: tie ranks are checked against exact expected midranks; constant ranks and a singleton cross-section must not fabricate finite correlation outputs.

For 18a, each mode compares a continuous all-live run against a run sourced from 400 qualified history bars followed by 240 live bars at the 640-row horizon. The test verifies receipt source roles, complete batches, LIVE_READY suffix, exact suffix output equality, factor-graph values/reasons, and each run's independent oracle result. Reconstruction uses the feed's history path and ordinary engine processing; it does not pickle or restore Strategy/Indicator objects.

The replay clock and bar sources are deterministic synthetic leaves. The execution is a real local Cerebro/Feed/cohort/factor composition, not a real market connection or account test. This evidence does not cover all 101 formulas, Alpha7's current gap issue, 17b/18b, benchmark/external fields, installed-package acceptance, performance, or account/provider behavior. The parity node also executes existing 15a comparisons; this archive adjudicates only the 17a/18a subitems and does not change any other formal status.

## Frozen inputs

The owner reports launch/end revision `092486d` and exit code 0. JUnit starts at 2026-10-24 23:51:57.646 local and the log was finalized around 23:53:55. The following SHA-256 pins were read from the reviewed checkout; they are a review inventory, not a claim that every listed file has a retained pre/post-run hash receipt. The original command line and complete launch pin list were not saved with the log; the exact collected nodes above identify the exercised cases. Paths are repository-relative.

| Path | SHA-256 |
|---|---|
| `tests/integration/test_live_alpha003_parity.py` | `0cdc70af601d15b78b5048a6b6b762b88c44101065bc983edfd6c5449054ea73` |
| `tests/integration/test_live_alpha003_edges.py` | `c8732d9d75fe4e643256f33bb47dc2d25de5b96d640f30ce4a97ac76541fe3ce` |
| `backtrader/research/alpha101/alpha003.py` | `108966393560c22da47eb3fd924c997280d851d47ad24f7cc0e66792bea8cf53` |
| `backtrader/research/live.py` | `778654019646ee87884547202a4177bde5de17f24d6be4e19a18a2133223529a` |
| `backtrader/research/live_cohort.py` | `a9d5744aef9903594bf797e63d29b71e058b9248c03382b7744c3a2998bc0d25` |
| `backtrader/feeds/btapifeed.py` | `cbfc755c934e8b5dc091a19f42e5e989cbbee2bf4eaf5e3178642705e3a8a229` |
| `backtrader/_cerebro/runnext.py` | `d0a12a6558f3418249cc0ff9d9f35336698b5be7330929c05d02c2d1921511b9` |
| `backtrader/cerebro.py` | `efc293f196ccb2c690c15476f97aa922fc7272440a478a628a9fdaf9c415e076` |
| `backtrader/research/factor_indicator.py` | `2fb3d2f5404691ba876983965adb78ecca7d87bd718819a44710716f13de275e` |
| `backtrader/research/operators.py` | `fbf6d142f40564ade20a0a4f160fffde6876c343d9943f4e74671dbac70dfb42` |
| `backtrader/research/_helpers.py` | `046163e66e056558071d5e109bd3411da4c9b3275e450e7ae07c26f43dfc74a3` |
| `backtrader/research/alpha101/_metadata.py` | `d559cf0dcc03df2ca4e10deafe7af485708e0cea054c67d448846649bbab56ee` |
| `tests/test_utils/alpha101_native_harness.py` | `bfce8a9c61ac50107055721c14436939264a3c146aaa97d8e5ee178fa63eeeca` |
| `tests/test_utils/alpha101_trace_validation.py` | `ea2a60e30b12670d61c8699f8eef239dff2322508acb4a7569f9acbb33b1ba28` |
| `tests/test_utils/alpha101_full_reference.py` | `1d449d115d948a57cfdec0dd62e1574d65a4f7d3945d011a73748d0b56512b7a` |

The original captured artifacts are preserved byte-for-byte alongside this record:

| File | Bytes | SHA-256 |
|---|---:|---|
| [`pytest.xml`](pytest.xml) | 699 | `f612a85e98d33faa3d76943565adc3bae73eb8902ae84f04ba4f42b7b4da45ec` |
| [`pytest-output.txt`](pytest-output.txt) | 1,362 | `9422e9a331c12fe032ea88eeb419f0a1a2298f0eac66455390eeb5adf8cedbb2` |
