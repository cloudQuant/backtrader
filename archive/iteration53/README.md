# Iteration 53 archive: retired `backtrader_runtime`

This directory preserves, read-only, the source that Iteration 53 removed from
the installable Backtrader distribution and from active import paths.

- `backtrader_runtime/package/` — the retired top-level runtime package.
- `backtrader_runtime/compat-facade/` — the retired `backtrader.runtime` facade
  modules that forwarded to the old package.
- `backtrader_runtime/tests/` — the old package's own unit tests.
- `backtrader_runtime/consumer-tests/` — tests that exercised the old package
  through examples, service observation, managed projection and local-backtest
  entry points.

Nothing here is packaged, installed, imported by `backtrader`, or collected by
the repository test run (`pytest.ini` excludes `archive`). The framework-owned
pieces still required by `backtrader.stores.ctp_managed_projection_bridge` were
moved to `backtrader/stores/ctp_managed_order_contract.py`; the bridge no longer
imports the old package.

The archive is a read-only migration source for the optional `bt_api_runtime` /
provider SDK owners, not a fallback entry point. It is deliberately not laid
out as an importable package and is not runnable without re-homing the files to
their new owner and rewriting imports. Use it for provenance and behavior
reference only.
