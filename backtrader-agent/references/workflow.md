# Deterministic P0 workflow

The legal write/execute path is:

```text
DatasetManifest -> StrategySpec -> snapshot sources -> private draft
  -> AST/security validation -> validation token
  -> prepare change -> persisted apply request -> local grant/change token
  -> transactional apply/hash check/token consume
  -> persisted execute request -> local grant/run token
  -> controlled child process/token consume -> report -> completion
```

Read-only catalog search can occur at any time. It cannot issue a change or run
capability. Changing source, data, configuration, environment, engine, draft
revision, or target preimage invalidates downstream evidence.

Every state-changing action above writes a legal `SessionStore` transition with
input hashes, effect references, approval token IDs, and idempotency keys.
Multi-file apply additionally keeps a staged transaction journal and backups.
The session journal is the recovery authority. Host conversation memory is not.
