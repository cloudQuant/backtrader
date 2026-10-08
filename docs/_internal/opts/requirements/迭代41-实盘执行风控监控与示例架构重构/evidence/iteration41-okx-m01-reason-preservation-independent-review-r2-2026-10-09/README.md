# M01 V3 reason-preservation R2 independent review

Decision: `GO_SOURCE_FAKE_ONLY`.

This review covers the exact five public source and test pins listed in
[`review.json`](review.json). It verifies the proof-less failure branch
preserves the first fixed failure reason, releases admission once, and reports
uncertain custody if that release fails. The actor-start uncertainty branch
continues to retain custody. The full V3 source-fake test file passed 13 tests,
including the existing clean-PASS fake path.

The test run used the designated isolated QA interpreter with isolated mode,
site initialization disabled, no inherited `PYTHONPATH`, pytest plugin
autoload disabled, asyncio and cache plugins disabled, and a fresh repository
`.codex-tmp` basetemp. Result: 13 passed, 0 failed, exit 0, in 0.33 seconds;
one existing unknown pytest configuration warning remained.

This review does not read the protected deployment map, ignored `.env`, private
configuration, external C01 helper, or any provider/native input. The earlier
V3 R1 candidate archive remains unchanged and is not a bundle of the R2 source
bytes. Root must bind the updated four source rows and review reference in the
protected deployment map before any route admission. The earlier Root
admission preflight predates these edits and does not attest R2. No M01
account readiness or case acceptance is claimed.
