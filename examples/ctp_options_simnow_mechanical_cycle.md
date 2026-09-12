# Shared SimNow mechanical cycle

`ctp_options_simnow_mechanical_cycle.py` is a caller-owned state machine for
Iterations 23/24/25. It does not construct a client, read `.env`, query an
account, or access Store private fields. The launcher injects an already
constructed `BtApiBroker`, owner, and feed mapping.

Before `arm()`, the caller must supply verified settlement, strict bundle
preflight, two identical reconciliation snapshots, and a matching execution
authorization proof. The machine permits one cycle, one to three one-lot
limit legs, and exactly one pending order. It reaches the write boundary only
through the injected broker's public `buy`, `sell`, and `cancel` methods.

Every completion callback must carry native confirmation plus CTP
`OrderRef`/front/session/order-system/trade/generation identity. Local fake
fills, partials, unknown results, reconnects, timeouts, and late fills after
cancel enter `RECOVERY_REQUIRED`; they are never retried blindly. Only two
stable final flat reconciliations produce `CLOSED_FLAT`.

The in-memory journal stores only cycle/intent/ref hashes and statuses. It is
not a strategy, profitability test, HFT qualification, or live launcher.
