# AccountActorPort r5 — independent QA archive

Disposition: `PARTIAL / NEEDS_REVISION`, local fake only. The author’s 40/40 tests pass, but the independent constructor-time TOCTOU test remains a blocker: a fake credential resolver mutates a shared route descriptor from NON_CTP to CTP after route snapshot and before gateway construction; the fake gateway factory is called once. A later submit rejects the changed route, but that does not undo earlier construction.

The test-only local replay ledger also permits the same command ID to be accepted in two fresh processes; the ordinary harness refuses dispatch, while a directly imported test-only harness can receive an injected actor. These are not external authority or cross-process replay guarantees. G6-P/G6-S/G7-S and Store integration remain closed.

Raw author and QA trees are retained in `author-r5.raw.zip` and `independent-qa-r5.raw.zip`. `ARCHIVE-INDEX.json` hashes every raw member and copied reference file.
