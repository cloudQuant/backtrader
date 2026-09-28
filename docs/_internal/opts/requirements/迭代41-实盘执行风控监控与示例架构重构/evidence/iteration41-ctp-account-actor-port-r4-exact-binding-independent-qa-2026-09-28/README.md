# AccountActorPort r4 exact-binding candidate evidence

**Disposition: ISOLATED_FAKE_ONLY / NO_TRUSTED_ACTOR / NO_AUTHORITY / NO_WRITE / LIVE_NO_GO**

## Scope

This archive records the isolated AccountActorPort r4 candidate and its independent exact-patch replay. It contains the patch, candidate/base manifests, receipts, and test transcripts. It does not include candidate source modules or the full prior freeze.

Candidate manifest SHA-256: b9ab1042bbf9ad71490ffac9524d5bba6834d32bd5c05b3a64e9524eb0858167  
Base r3-r1 manifest SHA-256: 417ebef0fc2a85b4e37ee22122024b0118211c161795abb79dac438840b960a1  
Independent QA receipt SHA-256: e47bd8ab06b55d0c51002d340291eeb5af6d4dedbee6039d028cd6ecb3770fb5

## Candidate and replay results

The candidate binds each logical submit/cancel intent to a local account/runtime/mode/config/session/front/session-generation/actor-epoch context. It checks returned receipts for operation, command ID, exact context, and command digest. An in-memory replay ledger claims each command ID before the actor-port call. The fake downstream receipt sink is called only after receipt validation.

The isolated candidate suite passed 36 tests. Ruff passed, and three files compiled in memory. Independent QA replayed the exact patch from the verified r3-r1 freeze in a fresh directory; after normalizing Windows line endings, all three source/test files matched the frozen candidate byte-for-byte. The independent full suite passed 36/36 and the focused adversarial selection passed 7/7.

| Input or result | Fake actor calls | Downstream fake sink calls |
|---|---:|---:|
| Stale account or epoch intent | 0 | 0 |
| Duplicate command ID after one valid attempt | 1 total; replay rejected before a second call | 1 total |
| Mismatched returned receipt (account, epoch, command, digest, or operation) | 1 | 0; no local fallback |

A receipt mismatch is observable only after the actor-port response. These checks gate the downstream fake sink; they do not prevent the actor-port call for a bad returned receipt.

## Trust boundary

G6-P trusted external AccountActor is absent. Account/session/epoch expectations are caller-supplied, the digest is unkeyed, and replay state is in-memory and process-local. This evidence does not authenticate actor identity, establish current actor/account state, provide durable or cross-host idempotency/fencing, or prove provider state. The candidate is unintegrated and grants no write authority.

No provider, SDK/native module, credentials, network, runtime configuration, real actor/account, or real order/cancel route was used. No main source or shared status document was changed for this candidate.

## Artifacts

- [Candidate patch from the r3-r1 freeze](changes.patch)
- [Candidate manifest](candidate-manifest.json) and [manifest sidecar](candidate-manifest.sha256)
- [Base manifest](base-manifest.json) and [base sidecar](base-manifest.sha256)
- [Candidate receipt](candidate-receipt.md), [candidate full-suite transcript](candidate-test-results.txt), [Ruff result](candidate-ruff-results.txt), and [compile result](candidate-compile-results.txt)
- [Independent QA receipt](qa/receipt.md), [commands and exit codes](qa/commands-and-exits.txt), [full suite stderr](qa/full-suite.stderr.txt), [focused selection stderr](qa/focused.stderr.txt), plus separate stdout captures
- [Artifact manifest](ARTIFACT-MANIFEST.json), [manifest SHA-256](ARTIFACT-MANIFEST.sha256), and [SHA-256 index](SHA256SUMS.txt)
