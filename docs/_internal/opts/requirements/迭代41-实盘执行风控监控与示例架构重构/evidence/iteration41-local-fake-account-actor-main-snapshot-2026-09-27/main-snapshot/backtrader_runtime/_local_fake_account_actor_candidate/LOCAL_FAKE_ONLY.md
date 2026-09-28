# Local fake-only account actor protocol candidate

This package is an isolated integration candidate. The service child owns a
SQLite ledger and in-memory fake sink; the caller sends typed intents over
local stdio JSON-lines and receives an unauthenticated local receipt. The
runtime registry, CLI, default runtime imports, and `BtApiStore` do not import
or construct this candidate.

Response lines and aggregate queued output are bounded. Outgoing requests are
capped at 64 KiB and use a write deadline. If shutdown requires forced child
termination, the client closes its streams and reports
`actor_service_cleanup_uncertain`: no OS Job Object or process-group supervisor
verifies descendant cleanup.

The child and caller share one OS principal; the SQLite file is locally
writable. Snapshot proof, account/session values, epochs, and fake sends are
synthetic. This package contains no provider, credential, network, native SDK,
external actor identity, cross-host writer fence, or real account snapshot.
`StoreBoundaryHarness` is a toy ordering model; it does not import or modify
`BtApiStore`. The candidate is not registered, not a Store route, and not write
authority. G6-P/F14 remain unresolved; `NO_WRITE / LIVE_NO_GO` is unchanged.
