# Independent AccountActorPort r4 QA

## Frozen-input verification

- Frozen directory: D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4
- Expected and observed manifest.json SHA-256: 8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8
- Manifest payload entries: 9/9 present; every byte count and SHA-256 matched.
- Frozen directory inventory: exactly the 9 listed payload files plus the four expected metadata sidecars (manifest.json, manifest.sha256, receipt.md, receipt.sha256); no unlisted payload files.
- Receipt SHA-256: ee5fb7d0d3362a7f4d82bbf03d846c92ae542365b6207c173f799ec498293a4f; sidecar matched.
- The independent test copy and probes are under this directory. The frozen candidate was not modified.

## Independent fake-only verification

Interpreter: CPython 3.11.5. No SDK, account, provider, credentials, network, or native client was used.

- Baseline command: python -B -m unittest discover -s tests -v — 34 passed.
- Expanded command after adding tests/test_independent_actor_port_qa.py in the isolated copy: python -B -m unittest discover -s tests -v — 41 passed.
- Probes cover stale epoch, wrong account, wrong receipt action, same-process duplicate intent, fresh-process replay, unkeyed digest tampering/recomputation, injected-object property non-read, and post-construction route descriptor mutation.

## Findings and disposition

Local fake-boundary result: accepted with limits. The exercised harness rejects stale epoch and wrong-account intent contexts before invoking the actor; rejects wrong-action and tampered-digest receipts without local/native fallback; claims an intent once within a shared ledger instance; and does not read the injected object's trap property before rejecting an ambiguous route.

Two material limitations were reproduced:

1. Cross-process replay: after one process claims an intent, a fresh process with a new FakeLocalActorReplayLedger successfully claims the same intent ID. The ledger is in-memory/process-local, not durable idempotency.
2. Route descriptor TOCTOU: StoreBoundaryHarness constructed with provider=okx and config.exchange_type=OKX caches NON_CTP. Mutating the referenced config dictionary to exchange_type=CTP after construction leaves route_kind NON_CTP, and a later submit enters the legacy route. This isolated fake harness does not reclassify or freeze the route descriptor. It is a candidate harness route-mutation gap; the 34/41 passing tests do not establish dynamic route safety or G6-P.

The command digest is plain deterministic SHA-256 with no secret key. Validation detects a changed digest against the locally expected intent, but an actor/message forger able to change the logical payload can recompute it. The digest is not actor authentication or keyed message integrity. ActorCommandContextV1 and actor_epoch are caller-supplied local bindings and do not prove current account/session authority.

No external trusted actor, durable server-side replay store, account-wide writer fence, common provider snapshot, or production route is established. This QA does not accept G6-S/G7-S or any live/write path.
