# AccountActorPort r4 independent QA archive

Disposition: ACCEPTED_WITH_LIMITS_FOR_FAKE_LOCAL_CONTRACT_ONLY

This is a fake-only verification archive for candidate r4. It does not establish G6-P, a trusted external actor, production integration, or any write route.

The frozen source manifest was verified at SHA-256 8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8, with all 9/9 payload entries and no unlisted files. The baseline suite passed 34 tests; the independently expanded suite passed 41 tests.

## Explicit gaps

- Route mutation gap: an OKX route is classified as NON_CTP at StoreBoundaryHarness construction. Mutating its shared config dictionary to CTP afterward leaves the cached NON_CTP classification in place and lets a later submit enter the legacy path.
- Cross-process replay gap: a new process with a fresh in-memory FakeLocalActorReplayLedger accepts an intent already claimed in another process.
- The SHA-256 command digest is unkeyed and recomputable. Context and actor epoch are caller-supplied. None of these values authenticates an external actor or proves current account authority.

## Contents

- candidate-copy: exact independent copy of all 9 frozen payloads.
- candidate-original: original r4 manifest, manifest sidecar, receipt, and receipt sidecar.
- baseline-unittest.log and independent-unittest.log: raw test output.
- qa-probes: added isolated adversarial tests, including route mutation and cross-process replay.
- qa-receipt.json, qa-evidence-manifest.json, and review.md: machine record, hash-bound evidence inventory, and QA narrative.
- SHA256SUMS.txt: SHA-256 for every packaged file other than the sums file itself.

G6-P is NOT ACCEPTED. No SDK, account, provider, credentials, network, native code, or default route was used.
