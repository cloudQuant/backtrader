# CTP Store AccountActorPort wiring candidate (r2)

**Status: `AUTHOR_CANDIDATE / NO_WRITE`.** This candidate is isolated under `D:\temp`; it does not edit or enable the main production Store route.

The exact input `BtApiStore` bytes are `input-sources/btapistore.py`, SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`. The patch preserves mixed line endings in untouched Store lines. Reproduce all three target hashes with `git -c core.autocrlf=false apply --check r2-apply.patch` followed by `git -c core.autocrlf=false apply r2-apply.patch`.

## R2 safety boundary

- Explicit known non-CTP provider/venue selectors can retain raw `api`/`api_cls` injection. Route classification does not inspect injected client attributes; unknown, contradictory, nested-CTP, and environment-conflicted routes remain closed.
- Bare `provider="btapi"` remains ambiguous. Its strict adapter-only compatibility case requires empty config/route maps and no route environment selectors; it discards the opaque API, cannot start, and gives the supplied adapter only a callback that revalidates then raises before local dispatch.
- **Every CTP Store construction fails closed with `external account actor unavailable`, even if a caller supplies a `CtpAccountActorPort` subclass, caller context, and fake in-memory ledger.** The typed actor/receipt DTOs remain offline contracts, but BtApiStore does not dispatch through them in r2. The CTP gate ignores the supplied implementation before type/receipt/API resolution.
- No local CTP SDK queue, native client, forwarding client, or managed local adapter is reachable from a constructed CTP Store. No external actor, credentials, provider, network, or default route is present.

The exact-base three-file patch is `r2-apply.patch`, SHA-256 `6e8575874cefeab4c693f6fedd5f3fc89dcec935005f5ad3a0d64f0e1284f90f`. Its exact-base replay is recorded in `evidence/r2-patch-replay.txt`. The separate r1 legacy audit classifies 8 cases as fail-closed assertion migrations, 13 as future external-Actor migrations, and 0 as ordinary NON_CTP defects. Audit report SHA-256 `c2133a92cbc83a0a4b4c9cd3f10cccc2f7e4f7287026fddabb7bd1f6065cbd00`; original audit ZIP SHA-256 `4fa06de543221c3457088ee32a62ec81dbc25ab9359dbd85cd488e9a59891152`; see the Iteration 41 evidence README. R1 source/test/logs are preserved in `evidence/r1-lineage/`.
