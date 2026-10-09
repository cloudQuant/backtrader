# OKX M01 R8/R5 dev-delivery proposal

**State:** delivery proposal only. No files were staged or committed in this round, and the existing .gitattributes was not changed.

## Proposed delivery

The proposal carries the frozen Gate R8 and Root caller R5 sources and source-fake tests, the integration R2 map/index/archive and QA records, the independent source-fake review, Root's sanitized R5 actual support records, and the exact R5 candidate-pin manifest. It includes the six untracked source/pin additions needed to make the reviewed caller/gate set and source packet available in dev.

The complete path, size, SHA-256, source pin, and base-HEAD status inventory is in delivery-manifest.json (SHA-256 1d65a59367a4cb3b2e976c84d8fe8bd828d123aae71bc641d4eabe9deb43c930, 35443 bytes). byte-preservation-rules-proposal.txt (SHA-256 236e0da3859ed9785614b985148cf8f53cc88ee1018301fa26bc6b1b179d2c61, 3624 bytes) proposes exact -text rules for the 21 proposed artifact paths; the actual shared attribute file remains unchanged.

## Checkout and source inventory

- Repository/branch/base: D:/source_code/backtrader, dev, e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b; the staging index was empty at inventory time: True.
- All 31 declared public input pins match the current checkout. 25 are already present with exact bytes at the base commit; 6 are untracked delivery additions: the Gate R8 source/test, caller R5 source/test, and integration R2 source map/index.
- The R2 ZIP contains 26 indexed members. Independent review verified central-directory names and sizes against the index. Twenty-four member source/test paths are already present with exact bytes in the base commit; the two R8 Gate source/test members are part of the six-file addition set.
- The index records checkout_head 716ca992dd8a05d7d997d25cd667f212eae5bb1c for the earlier source capture. The actual R5 invocation used base e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b. Those provenance points remain separate; the reviewed packet is not rewritten.
- The ZIP is retained as a frozen source/test fixture archive. It is not evidence that every archived module is imported in runtime execution.

## QA and review already completed

The designated source-fake suite passed 45 tests, exit 0, with two expected PytestCacheWarning messages from -c NUL. The run is not repeated here. Static checks passed in that round. Independent disposition is GO_SOURCE_FAKE_ONLY, pinned in the review README listed in the manifest.

The source-fake composed caller reaches the production Gate once but intentionally stops before CreateProcess because its synthetic runtime bytes fail the pinned hash. The review therefore does not claim a successful composed caller close or host exit.

## Root actual support

Root performed one separate credential-free local synthetic gate in fresh host 39102 (tool f6d251) against base e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b. It returned LOCAL_SYNTHETIC_CHILD: output matched, stderr was empty, the bounded process wait succeeded once without fallback, observed handle closes completed, pipe EOF/drain/join facts were true, Job accounting reached zero, and the registries were empty. CUv2 normal postverify close passed for 31 public and three software pins; Root's post-call checks passed, and the host exited normally with code 0. The four sanitized support JSON files are pinned in the manifest.

This is ROOT_LOCAL_SYNTHETIC_GATE_ONLY. It establishes neither account/provider behavior nor a formal M01 pass; formal M01 remains 0. The source-fake tests and archive fixtures do not upgrade that evidence level.

## Proposed byte-preservation step

At delivery time, refresh the existing .gitattributes from its recorded baseline pin and add the exact path-specific rules listed in byte-preservation-rules-proposal.txt. This proposal does not edit that shared file or stage any unrelated worktree changes.