# Independent QA receipt

**Disposition: PASS, local offline candidate only.**

QA ran in `D:\temp\ac41-63-007-feed-boundary-independent-qa-20260928-final-bb147c59`.
The reviewer initialized a fresh local Git repository, set
`core.autocrlf=true`, and applied the frozen patch with `git apply --index`.
`git ls-files --eol` reported `i/lf w/crlf`.

## Verified hashes

| Artifact | Raw SHA-256 | Line endings | LF-normalized SHA-256 |
| --- | --- | --- | --- |
| Preimage helper | `9F0DFE02F156B820B1158A7E317C2EFCEEBD59301A141E242A30144BDBFC554E` | frozen source | — |
| Applied helper | `1D80D22C431068D991955093C2778AC98F39A6BC36A90F6F427FA8665AA67B3B` | 739 CRLF, 0 bare LF/CR | `C1F4D77885A1D9787EB9D2D7C2FF3275379BBD14A7E60FB2516494B981F1A94F` |
| Applied feed test | `34C19391CD3B3EB7152EB78E8B569C8DEF5A7995C39215D296CACD74AD12AF49` | 168 CRLF, 0 bare LF/CR | `78A319EE397E48E4A460808DD758D1498BE66BB2ABF1400B6EB0CD2B89C0D2D6` |
| Patch | `BB147C59F0E95287C13A8ADD85D2CDE1D516477D6E6C0C5E56695AE5DD69C053` | — | — |

## Verification

- `ruff check examples/007_ctp/ctp_example_support.py tests/unit/test_iteration41_007_live_feed_failclose.py` — passed.
- `python -m pytest -q -o addopts= tests/unit/test_iteration41_007_live_feed_failclose.py tests/unit/test_iteration41_007_live_broker_failclose.py tests/unit/test_ctp_example_support.py` — **6 passed**, one Quandl deprecation warning.
- The corrected baseline probe loaded the frozen helper preimage and reported `FAKE_ONLY_BASELINE_REPRODUCED` with events `helper.returned_feed`, `cerebro.adddata`, `store.start`, `store.register`, `store.fetch_history`, and `store.subscribe`. Provider/native imports, sockets, and `.env` access were guarded; `os.getenv` was guarded after local Backtrader import.

Two preliminary QA harness invocations were discarded: one selected global site-packages, and another's blanket `os.getenv` guard intercepted `PSUTIL_DEBUG` during dependency import. The corrected probe used the local package and passed. These preliminary failures do not change candidate source or test results.

## Residual scope

`add_live_feeds` rejects before reading caller objects. `run_cerebro_with_timeout`
still invokes a supplied `cerebro.run()` after setting a timer, and public
Backtrader Store, Broker, and Feed constructors remain available elsewhere. This
is a narrow retired-helper fail-close; it does not establish general writer
closure or authorize writes. Keep `NO_WRITE / LIVE_NO_GO`.
