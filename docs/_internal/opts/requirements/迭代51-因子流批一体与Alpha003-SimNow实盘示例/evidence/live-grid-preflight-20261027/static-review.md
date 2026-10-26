# I51 live-grid preflight static review

Review result: **GO_SOURCE_FAKE_LIVE_GRID_PREFLIGHT_ONLY** for the two-file live-grid preflight change. The focused fake QA has already completed 8/8; no further QA is required for this narrow source round. This is not real-provider or account acceptance.

Reviewed diff scope is limited to:

- examples/unified/028_alpha003_simnow_minute/run.py — 251,148 bytes; SHA-256 b08a2245071df823c2be0c875d590432e0841c07a1829cc6982933122412fee5
- tests/unit/test_alpha003_simnow_runner.py — 209,641 bytes; SHA-256 27a771ae2b383aa5ec2164b10c8feece0ab52c3b04e26328813ba65e48ac5679

The targeted diff was reviewed against dev HEAD e29aff79. Delivery parent is now 4d61b059; that archive adds an independent login record while the reviewed source/test pins and 8-pass QA remain unchanged. The new _remaining_live_grid_minutes helper derives bucket_start as close_time minus one minute and retains minutes when bucket_start is equal to begin_at; only starts strictly earlier than now are removed. _calendar_slots delegates to this same helper, so the initial preflight and actual cohort calendar use the same inclusive boundary rule. The helper also adds an isinstance(minute, PlannedCommonMinute) check that was not present in the old _calendar_slots loop; it accepts valid PlannedCommonMinute entries and rejects other grid records.

In run_live, the empty-remaining-grid check raises LIVE_GRID_HAS_NO_REMAINING_COMMON_MINUTES before restart-identity work and before decision-tape, journal, or broker creation. Store creation can precede this point for selection/query setup; the expired-grid path is expected to close that Store. The new expired case asserts no tape file, journal, or broker was created, reports those resources as NOT_CREATED, and checks the Store close and cleanup result.

The time reads remain fresh at the relevant boundaries: preflight calls clock.utc_now(); saved-history validation still receives a later clock.utc_now(); cohort creation still uses saved_history.first_bucket_start when history exists and otherwise makes a later clock.utc_now() call. The existing saved-history first-bucket behavior is untouched in this diff. The cross-boundary case advances the fake clock by one microsecond after the last bucket start; cohort construction then rejects the now-expired schedule instead of reusing that slot, and the test checks cleanup.

The supplied focused QA artifacts report 8 passed, one pytest configuration warning, and exit 0. The command runs the parameterized test_live_setup_failures_close_every_created_resource node. It covers expired, exact-boundary, one-minute-remaining, and crossing cases. The boundary and remaining cases intentionally fail the fake Store readiness check after the new preflight has allowed them through; they do not establish a successful live session or provider interaction. That is a limited coverage boundary, not a source blocker here, because the shared helper is also used when building the cohort calendar and the cross-boundary case exercises cohort construction.

QA artifact pins:

- console.txt: 643 bytes, SHA-256 d02aaa8dfabd78296aa764a0e2e6fcd0893e51a27aa6c00032607ba8c3a73f24
- live-grid-preflight.xml: 1,720 bytes, SHA-256 731f3c03350b24b59f690e54d32a3617449f2e48b676c680647f0786494a124c
- command.txt: 239 bytes, SHA-256 93a686da34d375c1ec9e3f3bd5cd0228b5f23a22d0daabdd12e75fc2063340c8
- exit.txt: 3 bytes, SHA-256 13bf7b3039c63bf5a50491fa3cfd8eb4e699d1ba1436315aef9cbe5711530354
- source-pins.json: 370 bytes, SHA-256 5212454f23877ec7c973ec1328f9f4375209fe25ac52deb6a547a3efd3836cb9

The reported pytest warning is the existing unknown asyncio_default_fixture_loop_scope configuration option. Earlier r1/r2 failures remain unaccepted and were not used as evidence. No tests, imports, builds, provider/API operations, private inputs, or additional QA runs were performed for this review.
