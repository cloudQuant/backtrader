# AC41-63 007 live-feed helper fail-close

**Disposition: LOCAL_OFFLINE_ONLY / NO_WRITE / LIVE_NO_GO.** This archive
records a narrow rejection at the retired 007 `add_live_feeds` helper. It does
not establish general writer closure or enable CTP/SimNow execution.

## Change and hashes

The frozen preimage helper SHA-256 is
`9F0DFE02F156B820B1158A7E317C2EFCEEBD59301A141E242A30144BDBFC554E`.
The integrated helper’s exact CRLF SHA-256 is
`1D80D22C431068D991955093C2778AC98F39A6BC36A90F6F427FA8665AA67B3B`; its
Git/LF-normalized SHA-256 is
`C1F4D77885A1D9787EB9D2D7C2FF3275379BBD14A7E60FB2516494B981F1A94F`.
The new feed test SHA-256 is
`34C19391CD3B3EB7152EB78E8B569C8DEF5A7995C39215D296CACD74AD12AF49`. Patch
SHA-256:
`BB147C59F0E95287C13A8ADD85D2CDE1D516477D6E6C0C5E56695AE5DD69C053`.

The helper now raises the standard retired-entrypoint error before reading
`cerebro`, `store`, or `config`. `BtApiFeed` remains explicitly exported from
the support module. Frozen artifacts are [preimage](preimage/ctp_example_support.py),
[integrated postimage](postimage/ctp_example_support.py), [new test](tests/test_iteration41_007_live_feed_failclose.py), and
[patch](patch/iteration41-007-live-feed.patch).

## Fake-only baseline and independent QA

The [baseline probe](baseline/baseline_probe.py) loads the frozen preimage,
uses the actual feed start method, and supplies only fake Store/Cerebro objects.
It recorded `cerebro.adddata`, `store.start`, `store.register`,
`store.fetch_history`, and `store.subscribe`; provider/native imports, sockets,
`.env`, and helper environment reads were guarded. See the [captured trace](baseline/baseline_probe_result.json).

Independent QA applied the patch in a separate local Git repository with
`core.autocrlf=true`. The applied source and test bytes matched their hashes;
`git ls-files --eol` reported `i/lf w/crlf`. Targeted Ruff passed and the three
file focus passed **6 tests** with one existing Quandl deprecation warning.
See the [QA receipt](qa/independent-qa-receipt.md).

## Main-workspace verification

The guarded main-workspace focus passed **6 tests**, with one existing pytest
configuration warning. Ruff and `git diff --check` passed. The final guard log
has empty `events` and `native_modules_loaded` arrays. See the [JUnit output](main-focus/focus.xml),
[guard log](main-focus/guard-16488.json), and [summary](main-focus/result-summary.json).

The official static collector scanned 355 files with 363 writer candidates,
97 dynamic candidates, and zero parse errors. The current 460-row inventory
and locators were unchanged. The official verifier passed 460/460 rows; all
460 remain `REVIEW_REQUIRED`, with six historical tombstones. Its boundary is
`STATIC_DISPOSITION_INTEGRITY_ONLY_NOT_LIVE_ADMISSION`. See the
[collector output](scanner/collector-inventory.json), [verifier output](scanner/verifier-output.txt),
[scanner summary](scanner/result-summary.json), and the [inventory inputs](scanner/current-inventory/live-execution-inventory-candidates.json)
and [writer dispositions](scanner/current-inventory/live-execution-writer-dispositions.json).
Collector, verifier, and controlled-scope sources are included under
[scanner/tools](scanner/tools/collect_iteration41_writer_inventory.py).

## Residual scope

`run_cerebro_with_timeout` remains available and invokes the supplied
`cerebro.run()` after arranging a timer-based stop. Direct public Store, Broker,
and Feed construction paths remain available elsewhere. The patch closes only
this retired helper route; it does not prove arbitrary writer closure or
authorize any route. No real provider/native session, network, credential,
account, order, or cancel was used.

## Integrity files

- [Artifact manifest](ARTIFACT-MANIFEST.json)
- [SHA-256 sums](SHA256SUMS.txt)
