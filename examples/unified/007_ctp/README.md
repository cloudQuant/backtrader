# Historical CTP examples

The former `bt-runtime bootstrap/run/doctor` commands have been retired. Their
schema-v4 route only validated a local config and emitted a no-action report;
it did not construct Cerebro or run replay data. There is no equivalent
CTP-specific config-first runtime in the current Backtrader/SDK API. The
retired CLI returns `NOT_SUPPORTED` without reading its config directory.

Backtrader's ordinary local replay APIs remain available independently. The
strategy and historical runner sources in this directory are preserved, but
the retired CTP/SimNow command path does not activate their live provider,
account, order, or cancellation code. In particular, no mode or preset here
grants CTP write access.

`runtime-production/` is retained for migration history and compatibility
review. It is not an operator configuration location. See its
[README](runtime-production/README.md) for the separate production-path status.
