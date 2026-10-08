# Optional16 Entry R2 component independent review

**Verdict: `GO_SOURCE_FAKE_COMPONENT_ONLY`.** This review covers the frozen Entry R2 metadata snapshot component, Bridge R2 source transform, the pinned R15 closure AST anchor, public metadata indexes, and two sourcefake tests. It does not authorize the frozen Root driver or an actual invocation.

The refreshed candidate packet at `../o16-r2-metadata` is pin-consistent in both its packet copy and current checkout. The packet contains seven source-closure members and no `.blob` or `.pyc` payload files. The public indexes classify the three profiler source rows as hash/size transport-only with no parse/import/execute, and classify the three `.pyc` rows as a public fixed-hash cache snapshot. I read the public metadata only; no opaque payload bytes were opened.

Entry R2 binds exact path, digest, size, and role for the indexed profiler source/cache rows. Unindexed `.py` software and `.pyc` pins fail closed; ordinary public `.py` bytes remain SHA-checked. The R15 closure transform locates one exact generator predicate and substitutes the sealed R5 snapshot assertion. The tests cover wrong digest, missing opaque proof, opaque bytes unexpectedly supplied, and ordinary-byte mutation. Bridge R2 is rebased to Entry R2; the test compiles transformed public source but does not execute the full chain.

The isolated QA run returned **8 passed, 0 failed, 0 skipped**, exit 0, with the existing unknown `asyncio_default_fixture_loop_scope` warning. Its interpreter, flags, disabled plugin autoload, cleared `PYTHONPATH`, disabled asyncio/cacheprovider plugins, and unique basetemp are recorded in `review.json`.

## Limits

Full Entry/R5/R27/V3/V4/R29 production composition remains **UNVERIFIED**. The actual V3 `verify_pin` path reads and hashes opaque held handles and was not invoked. No provider, native, WinAPI, process, network, or actual Root operation occurred. The frozen R1 Root driver validator does not consume this R2 component review. Formal Optional16 remains **0/16**.