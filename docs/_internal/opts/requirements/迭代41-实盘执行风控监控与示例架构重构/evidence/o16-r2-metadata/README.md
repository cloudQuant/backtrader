# Optional16 R33 root-held opaque metadata component

This frozen packet carries a selected-source closure for the transport-only profiler metadata component: Entry R2, Entry Bridge R2, pinned R15 glue, two source-fake tests, and the exact public standard-library/cache metadata indexes read by those tests. It contains no `.blob` or `.pyc` payload bytes.

## Result

`SOURCE_FAKE_COMPONENT_ONLY`: the exact packet passed 8 tests, with 0 failures, 0 skips, and one existing pytest configuration warning. The metadata tests bind three exact transport-only profiler source descriptors and their index rows. They check that those rows use metadata verification, while ordinary `.py` rows still read held bytes and verify SHA-256. The component focus also checks the snapshot `assert_held_or_bytes` behavior, the exact bridge transform anchors, and the R15 closure-transform anchor.

The tests do not run the full Entry/R5/R27/V3 production chain. They do not import or execute the R28 helper, R19, V3, V4, or R29. V3/V4/R29 still have cache-byte reads and/or parsing outside this component review boundary; those production gates were not changed. The existing Root driver R1 review validator remains pinned to its R1 contract, so this component result does not satisfy that validator.

## QA boundary

The tests ran from this packet root using the designated isolated QA interpreter with `-I -S -B -X utf8`, plugin autoload disabled, `PYTHONPATH` removed, `no:asyncio`, `no:cacheprovider`, and a unique repository `.codex-tmp` basetemp. `qa-summary.json` records the exact command and paths. The tests read only source files and the two public JSON metadata indexes. They did not read opaque payloads or private inputs, and did not invoke a process, SDK, native module, WinAPI, provider, account, or trading operation.

`index.json` binds the seven selected-source members. `checkpoint.json` binds the source members and packet documentation. The earlier long-path draft under the same evidence tree is unsealed; use this `o16-r2-metadata` packet as the current candidate.
