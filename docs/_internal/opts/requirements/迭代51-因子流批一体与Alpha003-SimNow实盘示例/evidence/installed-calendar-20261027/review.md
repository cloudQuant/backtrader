# I51 installed-calendar consumer static review — 2026-10-27

**Decision: GO — `LOCAL_INSTALLED_CALENDAR_CONSUMER_ONLY`.** The public run
manifest is 31,157 bytes, SHA-256
`3feb86ea10abbb3bbd5c4f236f8de617e6eebd301c1c78b4b8a15a4e6d55dd9a`, and
binds source commit `ae218c04ca521aaad3ef8c6aa38f17f6c334444d`. Its recorded
steps all completed with exit code 0 and no timeouts, including source
preflight/archive, wheel build, source-to-wheel verification, fresh consumer
venv creation, offline install, `pip check`, installed RECORD/origin/native
checks, and installed payload/calendar checks. This is a static review of
those artifacts; no command or test was rerun.

The source archive is 2,432,660 bytes (`146845c640fe904aae80c3a552de25f82c6b21c4f4aff4a5927dd8d6153f8ba3`).
The source-to-wheel verifier reports 662 Python files on each side, with no
missing, extra, or hash-mismatched Python payloads. The installed-payload
verifier then compares package files and hashes against the three pinned wheel
archives. It reports the new Backtrader wheel as 2,441,813 bytes,
SHA-256 `c560ed79d34c87e0baec015ed9e3b55f8d82ee5e79f157eaf2df3a4063812f16`;
the reused `bt-api-base` wheel is pinned as
`b579a73531281d74f6e1630d447717b9f87e38bf507d82178d9ad46745017f39`, and the
reused `bt-api-ctp` wheel as
`b72a48d09c80420ffdaaa7eadb51a135287ac4313caaa235d749e3b39b52796f`.

The fresh Python 3.11.5 environment reports all three package origins under
its own `site-packages`; hashed installed RECORD entries verify for
Backtrader 1.4.0 (676), `bt-api-base` 0.15.8 (103), and `bt-api-ctp`
2.0.4+iteration41.i9 (96). The CTP native extension also resolves inside that
environment and is reported loaded. `pip check` reports no broken
requirements. These checks support the installed-wheel consumer claim; they
do not establish a provider login or account operation.

The installed calendar verifier imports the installed module from that same
venv and checks expected-rule-derived calendars for six representative
products: CFFEX IF, CZCE SR, DCE M, GFEX LC, INE SC, and SHFE CU. It checks the
target product and TradingDay `2026-10-26`, the recorded retrieval time and
rule-manifest digest, digest stability when retrieval metadata changes, and
the expected public source references. The manifest digest is
`4706e2a77d6cb6844706f9425c89d4b3f823b9bfb2ef363c90d36faa7173d051`. The
source projection contains no raw source hash field. This establishes the
recorded six-product installed-consumer checks, not a full product/exchange
matrix or live trading-day discovery.

Scope limits: the consumer installation used `--no-index` and the pinned
local wheelhouse, but the wheel-build command is configured with the public
PyPI index for build dependencies, so the complete run is not demonstrated to
be offline. The manifest explicitly says the CTP wheel was reused, no accepted
matrix was rerun, and no formal account acceptance is claimed. Accordingly,
this GO covers only the fresh installed-consumer and calendar checks evidenced
here.
