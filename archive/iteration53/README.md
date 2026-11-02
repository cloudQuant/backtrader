# Iteration 53 archive: retired `backtrader_runtime`

This directory preserves, read-only, the source that Iteration 53 removed from
the installable Backtrader distribution and from active import paths.

- `backtrader_runtime/package/` — the retired top-level runtime package.

Nothing here is packaged, installed, imported by `backtrader`, or collected by
the repository test run (`pytest.ini` excludes `archive`). The former CTP store
bridge and contract are no longer present in the active Backtrader source.

The remaining runtime files are a migration reference, not an importable
fallback. The SDK's CTP credential binding still needs a direct trust source;
these archived files do not provide a runnable verifier. Retired compatibility
facades, tests, store, example and CI archives have been removed.
