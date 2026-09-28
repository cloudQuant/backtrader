# CTP Store AccountActorPort wiring candidate (r1)

**Status: `AUTHOR_CANDIDATE / NO_WRITE`.** This isolated candidate is under `D:\temp`; it does not change the main repository's production source or enable a default runtime route. It is not a real AccountActor service, CTP acceptance, or production authorization.

The exact input `BtApiStore` bytes are `input-sources/btapistore.py`, SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`. The candidate preserves mixed line endings in untouched Store lines. Apply the source patch with `git -c core.autocrlf=false apply --ignore-whitespace --whitespace=nowarn evidence/r1-apply.patch` to reproduce the byte hashes in the manifest.

## r1 boundaries

- Explicit known non-CTP provider selectors with matching venue selectors may retain the historical injected `api`/`api_cls` path. Classification does not inspect the injected object's attributes. CTP is still rejected by the pre-client gate if a local client is injected; unknown/custom and contradictory routes remain ambiguous/closed.
- Bare `provider="btapi"` without a known selector remains `AMBIGUOUS`, never `NON_CTP`. A narrow adapter-only path preserves lazy managed-adapter construction only when the provider is exactly `btapi`, backend is `None`/`direct`, an opaque API sentinel is supplied but discarded without attribute reads, route/config kwargs are empty, no route environment selector is present, an explicit managed adapter is supplied, no AccountActor arguments are supplied, and `autostart is False`.
- The adapter-only Store never constructs a provider client and cannot start. Submit/cancel calls revalidate the route before and after invoking the adapter. Its injected legacy dispatch closure revalidates and then raises before local provider dispatch. A route/environment mutation to CTP rejects before the adapter is called.
- The actor slice remains a local fake observation seam: caller-selected context, unkeyed digest, in-memory replay ledger, no authenticated actor, no durable replay fence, no current authoritative epoch lookup, no same-session read/callback feed. It cannot start or grant production write authority.

See `evidence/qa-report.md` for exact tests, compatibility failures, source hashes, and blockers. Earlier r0 logs are kept under `evidence/r0-lineage/` and are not r1 results.
