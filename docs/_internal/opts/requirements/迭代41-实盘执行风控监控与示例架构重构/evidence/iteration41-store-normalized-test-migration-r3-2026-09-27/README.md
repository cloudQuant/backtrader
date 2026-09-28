# Store normalized test migration R3

Disposition: `SAFE_LOCAL_TEST_MIGRATION / NO_WRITE`; this accepts only a test fixture migration, not Store behavior or a CTP route.

R3 is the frozen one-file test patch against Store R5 SHA-256 `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`. It restores public `store.poll_broker_update()` assertions in the trade/event-source test, preserving event source, fee/currency and framework-reference assertions. It also keeps CTP submit/cancel fail-closed assertions at zero fake SDK writes. The 7 focused node cases passed both author and independent runs; import guards recorded zero provider import attempts and zero external sockets (three loopback-only asyncio socketpair calls).

Patch SHA-256 `56E0EEEC9D7F9764E6516CB6ECFCA4AF33FDF351CA19630F8DF32AF9A490D56F`; author test target SHA-256 `C3004A537AED8DF41B106F2A8D03287B02F54720B468E12C423BE2A82A5994F5`; main-tree test snapshot SHA-256 `4A8A7FC5922A77F8356D9A189041C125F8384FABC35A6F09E43BE1E1D6F542DB`. The main snapshot includes the same R3 assertions and a lint-equivalent `dict.fromkeys(...)` cleanup instead of the candidate's dict comprehension; the conversion still maps each optional field name to `None`. It does not weaken the event polling or zero-write checks.

No real SDK/native/provider, account, config, external network or order was used. This is not a Store broad pass or writer-closure evidence. `NO_WRITE / LIVE_NO_GO`.
