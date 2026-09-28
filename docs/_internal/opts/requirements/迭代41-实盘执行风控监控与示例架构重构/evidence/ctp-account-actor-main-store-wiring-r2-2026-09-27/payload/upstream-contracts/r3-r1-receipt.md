# r3-r1 isolated candidate receipt

- Frozen snapshot: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-r1`
- Editable candidate origin: `D:\temp\iteration41-ctp-account-actor-port-candidate-20260927-r3`
- Revision: r3-r1 adds recursive inspection of route selector fields nested inside `exchange_kwargs` venue options. The earlier immutable r3 snapshot remains preserved at `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-frozen`.
- Manifest SHA-256: `417ebef0fc2a85b4e37ee22122024b0118211c161795abb79dac438840b960a1`
- Scope: offline route classifier and tiny fake Store boundary harness only. No main-repository source was edited.

## Implemented

The r3 classifier uses exact code-owned selector sets. `ctp` and `ctp_gateway` remain CTP regardless of environment selectors. `okx` and `binance` are the direct non-CTP selectors. `btapi` requires explicit route facts whose complete discovered venue set is non-CTP. `gateway`, `ib_web_gateway`, and `mt5_gateway` need explicit matching `IB_WEB`/`MT5` selectors; missing generic gateway selection is classified as CTP because the main wrapper defaults to CTP. `futu`, `oanda`, and `vc` are explicitly unsupported. Unknown provider strings, arbitrary `_gateway` suffixes, malformed selectors, and raw `api`/`api_cls` injection are rejected as ambiguous.

The classifier does not read attributes on injected API objects/classes. Top-level and nested `symbol_routes` and `exchange_kwargs` selectors are checked; explicit CTP anywhere in these route maps takes precedence. Environment provider changes never upgrade an unknown route to non-CTP and never downgrade a raw CTP selector.

The default actor remains `UnavailableCtpAccountActorPort`. Fake submit/cancel tests exercise typed DTO plumbing only. The harness asserts zero local API/gateway construction, connection, or native calls when the CTP actor is absent. One fixture intentionally constructs a fake API before Store entry to show the gate cannot undo caller-side construction; it does not connect or submit.

## Verification

From the frozen directory:

- `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v` — 24 passed.
- `RUFF_CACHE_DIR=D:\temp\ruff-cache-ctp-actor-r3-r1-freeze python -m ruff check account_actor_port.py store_boundary_harness.py tests\test_store_boundary_harness.py` — clean.
- In-memory `compile()` check for all three Python files — clean; no bytecode generated.

Full output is in `test-results.txt`, `ruff-results.txt`, and `compile-results.txt`. `MAIN_SOURCE_INVENTORY.md` lists the inspected main-source paths, line references, and hashes. The manifest covers every source, test, inventory, and result file in this snapshot; its digest is in `manifest.sha256`.

## Compatibility and remaining blockers

This candidate is not wired into Backtrader. The main public example `BtApiStore(provider="okx", api=...)` is deliberately rejected here because the injected object is opaque; raw `api_cls` and custom providers are rejected too. The selector registry is intentionally narrow and does not claim exhaustive compatibility with all historical BtApiStore providers or backend combinations.

`ActorCommandReceiptV1` validation is only a local DTO-type/command-id check. It does not bind a trusted account, expected epoch, authenticated service identity, or replay ledger. Stale epoch, wrong-account and duplicate-command receipts remain integration blockers; the DTO is not authority. No external actor, credentials, provider session, read feed, callback feed, handoff, or native API is implemented. F14 claim/recheck admission remains distinct from an external execution transport.

The harness cannot establish production safety: arbitrary in-process code can bypass it, and it does not create any main Store, SDK client, provider connection, credentials, or native call. Independent QA has not been recorded in this receipt.
