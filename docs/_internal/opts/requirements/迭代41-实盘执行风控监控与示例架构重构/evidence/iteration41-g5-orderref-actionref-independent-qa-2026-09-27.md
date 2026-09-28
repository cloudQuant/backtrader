# G5 OrderRef / ActionRef unified authority: independent QA

**Disposition: `LOCAL_FAKE_CONTRACT_REPRODUCED / G5_NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`.** The frozen candidate’s fake contract passed independent reruns, but its caller-supplied OrderRef/ActionRef watermarks do not prove native account state or collision-free allocation. The proposed Backtrader request builder also requires `stage_prepared_dispatch(..., action_identity=...)`, which the current worker port does not accept. The current Store still raises for managed CTP OrderRef allocation at `backtrader/stores/btapistore.py:15431`; the managed legacy submit/cancel dispatchers reject at `:7915` and `:8223`. The default route remains closed.

## Frozen inputs and independent reruns

The candidate input manifest SHA-256 is `79BAB5C0C0E136B722EF5F55C74F93ABA2920F138A629B9AB8B4506D29003827` (50/50 entries verified). The copied SDK snapshot is submodule HEAD `2700cb5454ef4c3d1780eda28b6f33307a860998` with untracked `README.md`, `pyproject.toml`, `src/`, and `tests/`; it is not a clean reviewed SDK pin. Its output manifest SHA-256 is `6DB92F8FD9700EF9BC903C41FCAD0C34BD3012830370B37AFA50E37FAB11450F` (87/87 entries verified). Independent copy comparison found no mismatches; all eight frozen Backtrader input files match current main checkout bytes.

Independent offline test results:

- G5 fake candidate focus: **14 passed**.
- SDK dispatch/store focus: **27 passed**; full frozen SDK tests: **57 passed**.
- Four-file main focus with repository plugin defaults: collection fails with the installed pytest-asyncio `Package.obj` AttributeError. With only that plugin disabled: **49 passed, 47 skipped**; 34 integration, 1 bridge source smoke, and 12 parent source-only cases skip because the reviewed source candidates are unavailable.
- The original author page reports **54 passed / 47 skipped**. The exact node selector and JUnit were not retained; both independent runs of the four manifest-listed files produced **49 / 47**. The difference remains unexplained.
- An added eight-process synchronized SQLite fake allocated unique ActionRefs **43–50**, confirmed readback after reopen, and denied UNKNOWN command claims from a child and after reopen. The fake Store bridge persists and reads back an exact typed local `QUEUED` receipt before fake dispatch; that receipt is not provider acknowledgement, and the fake persistence-failure/UNKNOWN cases dispatch nothing.
- Current worker-port signature rejects `action_identity=` with `TypeError`; an exact-signature negative spy had zero method-body calls. The proposed builder reserves the local ActionRef before attempting the unsupported call, so a local ActionRef gap may remain; no worker staging or provider send occurs on that incompatibility path. Full builder integration was unavailable due missing exact I9/parent source candidates.

The original author candidate raw ZIP was retained unchanged and independently checked: 111 members, ZIP integrity clean, and all indexed member hashes match. This QA does not establish a native MaxOrderRef/ActionRef source, OS-process writer fencing, live/native lifecycle, or real account authorization.

## Evidence and hashes

- Detailed QA receipt and all copied raw stdout/negative-test files: [`iteration41-g5-orderref-actionref-independent-qa-2026-09-27/qa-receipt.md`](iteration41-g5-orderref-actionref-independent-qa-2026-09-27/qa-receipt.md)
- Structured QA receipt SHA-256: `EDA16FE9621E8D19E9302A1A21AEA896E29BB435FDCA097F03CC4D0B15B74BEB`
- Raw QA archive: [`iteration41-g5-orderref-actionref-independent-qa-2026-09-27.raw.zip`](iteration41-g5-orderref-actionref-independent-qa-2026-09-27.raw.zip)
- Raw ZIP SHA-256: `2446F2A97094E7CD36C319F627C7CE189E951EAC35288CDBAFEB37373D1AF966`
- Member index: [`iteration41-g5-orderref-actionref-independent-qa-2026-09-27.raw.zip.index.json`](iteration41-g5-orderref-actionref-independent-qa-2026-09-27.raw.zip.index.json)
- Index SHA-256: `1D71A059FDECDF20DEE3B262161704A48109AC1655E21D0504DC41282AFD4B1E`
- Independent QA manifest SHA-256: `37FEAC2934A3863C2BCDD5157C153D49D492F7B445F1936F6C7D7A13D76A7D1F`

The raw archive has 45 members. A post-write check reported `testzip()` clean, all 45 indexed member sizes/hashes correct, and matching ZIP/index sidecars. It includes the original frozen author ZIP/reference index, candidate manifest verification, all independent test stdout and exit codes, the pytest collection failure and skip breakdown, the multiprocess run, the worker incompatibility negative, and scripts. Its external index contains SHA-256 and byte size for every ZIP member.


