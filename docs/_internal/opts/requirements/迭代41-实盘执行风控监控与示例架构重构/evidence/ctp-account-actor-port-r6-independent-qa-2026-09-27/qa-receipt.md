# AccountActorPort r6 independent QA receipt

Verdict: `LOCAL_FAKE_CONTRACT_PASS_WITH_LIMITS`.

## Frozen input and isolation

- Candidate root: `D:\temp\iteration41-ctp-account-actor-port-r6-local-fake-20260927`
- Candidate manifest SHA-256: `c410b68aa39f476818afe517a0974bbbf428497236c20174d1d61a0830440d59`
- Independently rehashed: 23/23 manifest payloads and 25/25 entries in `SHA256SUMS.txt`; manifest sidecar matches. The r5 base manifest at `D:\temp\iteration41-ctp-account-actor-port-r5-20260927\hashes\manifest.json` independently hashes to `73521009058983a0e34172c4ca0020c5f32f4cbf25da7b1fb554f4d68baaa4bd`, matching r6's declared base.
- Tests ran from this independent copy: `D:\temp\iteration41-ctp-account-actor-port-r6-independent-qa-20260927`.
- Module-origin check resolves all three candidate modules from the independent `source` copy. Its `sitecustomize.py` is from the copied tripwire directory. The tripwire explicitly blocked a `bt_api_py` import and `socket.getaddrinfo`; no `_ctp`/`bt_api_py` module was loaded.
- Read-only search of main Python source roots found no code references to `store_boundary_harness_testonly` or `LocalFakeStoreBoundaryHarness`. No main production code, SDK/native module, private config, credentials, network, provider, or order was accessed.

## Independent results

- `python -B -m unittest discover -s tests -v`: 44 passed.
- `python -B -m pytest -p no:cacheprovider -q tests --junitxml independent-evidence\independent-junit.xml`: 44 passed, 0 failed/skipped.
- Ruff over the 3 candidate source modules and the candidate test file: All checks passed.
- The independent hostile route/factory probe is `r6_adversarial_probe.py`; its JSON output is preserved in `adversarial-probe.log`.

The prior r5 constructor TOCTOU is closed for the observed stable route mutation: a credential resolver changes `IB_WEB` to CTP and installs an opaque API object; constructor rejects with `store_route_changed_after_construction`, gateway factory calls 0, API factory calls 0, and the opaque object's descriptor is not read. Independent probes also show same-kind and nested CTP changes after the resolver reject before gateway factory (0 calls). The built-in suite covers hostile Mapping rejection, stale epoch/account/session binding, ordinary default no-dispatch across a fresh subprocess, and typed receipt/replay checks.

A gateway factory that mutates the route to CTP is itself called once, because the snapshot is valid immediately before entering that injected callback. The post-callback check then rejects construction; no API factory runs and its returned object is not published. A resolver that transiently changes the route to CTP and restores the original canonical route before returning is accepted, after which the gateway factory runs. Thus the implementation proves synchronous before/after state equality, not callback confinement or detection of every transient mutation. Arbitrary concurrent mutation is also outside the snapshot contract.

The ordinary `StoreBoundaryHarness` rejects a supplied fake actor as `trusted_durable_remote_actor_unavailable` and leaves fake submits/legacy calls at zero. The explicitly imported `store_boundary_harness_testonly.LocalFakeStoreBoundaryHarness` does dispatch one local fake command when supplied the in-memory ledger; this is caller-controlled test plumbing. Its isolation is by separate module/default non-reference, not a security mechanism, and its ledger has no durable or cross-process uniqueness. These facts match the candidate's stated limit.

## Acceptance boundary

Accepted only as the isolated `LOCAL_FAKE` state-check/harness contract and the r5 stable-mutation fix. This does not establish a trusted or durable external AccountActor, live/provider integration, callback confinement, production Store integration, G6-P, F14, or any live/write acceptance. A separately authenticated Actor must own durable idempotency, epoch/account/session validation, read/callback facts, and cross-host fencing before production integration.

## Raw evidence

Raw logs, probe script/output, origin/tripwire output, command, JUnit and Ruff output are in this directory's `independent-evidence/`. `input-verification.txt` records the candidate manifest and payload checks. `qa-manifest.json` hashes this receipt and the preserved raw files.
