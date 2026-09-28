# G6-P Account Actor independent review (2026-09-27)

**Disposition:** `DESIGN / NEGATIVE REVIEW ONLY`; `G6-P F14_STRICT_BLOCKED / G8-P NOT_RUN / NO_WRITE / LIVE_NO_GO`. No external actor, credential/network/provider, native session, or production route was used or accepted.

The source manifest in the raw bundle pins the bytes reviewed at capture time, including the then-current matrix. Later matrix/checkpoint edits are separate from this review artifact.

This archive records an independent review of AccountActorPort r2 as a fake-only interface. Its freeze manifest is SHA-256 `ac45026c48d247b66f0da18e59211c7bd2e610cdaa5e7bd605a89cf1625f7a76`. The independent copy verified all 9 candidate payload hashes, and its offline suite passed 15/15 with py_compile and Ruff clean. The candidate is not wired to BtApiStore and proves no service identity, cross-host epoch, sole credentials/egress, common account snapshot, final native dispatch, or bypass denial.

**Preserved r2 integration counterexamples:** an unknown provider with `api_cls` classified as `non_ctp`, passed the unavailable-actor gate, and invoked a local factory (`unknown_provider_with_api_cls_route_kind=non_ctp`, `unknown_provider_unavailable_actor_gate=allowed`, `unknown_provider_factory_calls=1`). For an injected `btapi` object, a custom `exchange_kwargs` property ran before rejection (one read during classification, two after the gate). Integration must use an explicit code-owned non-CTP registry and reject unknown/injected clients without introspection.

The strict snapshot requirement remains externally blocked: independent public CTP terminal query callbacks do not prove one full-account revision. A trusted provider snapshot or equivalent complete, gap-detected authoritative event ledger is required. ADR-41-16 Option B remains proposed and does not close G6-P or authorize SimNow/production writes.

## Frozen artifacts

- [Full independent review — SHA-256 `0b2f7a67076efdce1077501f1ffd368e29a110a37191816644a877ca54ab1dcb`](ctp-g6p-account-actor-independent-review-2026-09-27.report.md)
- [Independent QA manifest — SHA-256 `866529ab1a4815e521109cdc4203890ac437165d291bf1703b08fd2817830495`](ctp-g6p-account-actor-independent-review-2026-09-27.qa-manifest.json)
- [Complete 37-entry raw QA bundle — SHA-256 `e7780f52babc1a6b899a125562c3257ff39c30b1c3cc626785c605aa68cbb925`](ctp-g6p-account-actor-independent-review-2026-09-27.raw.zip)

The raw bundle contains the verified r2 source/test copy, original candidate manifest and receipt, both negative probes with logs, independent test/py_compile/Ruff logs, and main/external source hash records. SHA-256 sidecars accompany the report, QA manifest and archive.

