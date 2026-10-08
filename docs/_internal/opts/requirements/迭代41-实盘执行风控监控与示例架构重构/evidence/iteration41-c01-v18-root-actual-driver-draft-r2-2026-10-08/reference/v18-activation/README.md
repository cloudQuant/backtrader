# SimNow C01 V18 Root activation wrapper — R2 source-fake packet

Status: public-source and fake-only review packet. No account, provider, native, or actual Root run was performed by this packet. It does not establish a real account PASS.

## Activation path

The outer activation CLI is fixed to `--activate-c01-v18-td-read --expected-wrapper-sha256 <64 lowercase hex>`. The outer Root driver launches this fixed CLI after its own source/custody holds. The wrapper validates the exact 27-row V18 entry source map, derives the V18 entry self row from held bytes (28 entry rows total), and is pinned by the outer driver last (29 source rows for the completed outer closure). Its software pins are the two fixed interpreter executable/DLL rows in `pins.json`.

The wrapper selects and revalidates the complete front pair and protected config, creates its fresh 32-hex admission ID internally, writes the bounded admission, closes the credentials lease, and launches this same wrapper in internal `--root-child-v18` mode under the bounded Windows Job. The child loads the held V18 closure and invokes the exact same-process Root entry. It serializes the opaque receipt only into the protected private artifact. Its stdout is a five-field storage marker. The parent accepts a public PASS only after normal child exit, empty Job, stdout/stderr EOF, empty stderr, closed Job handles, joined reader threads, and a bounded post-Job ACL/identity/receipt verification.

The wrapper's public output is restricted to the exact 22 allowlisted fields in `public-result-schema.json`; no `front_id`, `session_id`, `trading_day`, credential binding, path, raw exception, or complete receipt is emitted. An invalid or incomplete path returns `BLOCKED`/exit 2 with the same finite key set and only safe bounded reason strings. The outer Root driver owns the separate CUv2 held-source context; the wrapper neither reads nor pins the external CUv2 helper.

## Source-fake verification

The four-file isolated source-fake suite passed 42 tests. The tests run the actual V18 entry and `_run_candidate` with synthetic source/runtime/artifact/OS/provider leaves. Test-only custody/receipt functions are injected for the integration fixture; the `PASS` receipt payload in that fixture is synthetic and is not official C01 authority. The new wrapper tests cover exact seven-value production source wiring, constructor keyword pins, `main()` child-mode dispatch, private-receipt/public-projection separation, the production `_run_v18_job` method with a fake backend/session for clean drain and unclean-drain rejection, and the core's fail-closed behavior when cleanup or postverify is absent.

The fake Job test does not launch a process and does not invoke WinAPI. The production Windows Job/pipe lifecycle remains for the Root-owned actual invocation and has not been established by fake tests.

Exact focused command and output are recorded in `qa/`. One existing pytest configuration warning remains: `asyncio_default_fixture_loop_scope` is unknown to the dedicated source-QA environment.

## Freeze order and pins

The public dependency order remains: V7 owner/helper/protocol closure → issuer V18 → front V12 → custody producer → V16 Root bridge → V18 entry (27 non-self rows plus held-derived self row) → this Root activation wrapper → outer Root driver. The wrapper has no entry-source back-edge; the driver pins the wrapper only after its source bytes are frozen. `pins.json` contains all 29 public source rows, exact software pins, review-copy hashes, wrapper/test pins, and the isolated QA result.

The next acceptance gate is independent R2 source review followed by the Root-owned actual bounded invocation. No source-fake result is substituted for that gate.
