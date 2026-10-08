# R7 public source input snapshot

This archive contains byte-for-byte copies of the 45 paths in the R7 `pins.json` pytest import/source closure. It contains source and test files only; it is provenance for a Root-owned materialization gate, not an accepted R7 production-source change, actual cleanup result, or clean-source QA pass.

`public-source-snapshot.zip` preserves each original repository-relative path under `sources/`. `snapshot-map.json` binds every copied path, byte length and SHA-256 to the R7 manifest and includes the archive pin.

The current QA result remains isolated-interpreter source QA in the shared canonical `D:/source_code/backtrader` checkout: 28 passed, with one existing unknown pytest configuration warning. The pinned CUV2 source hard-codes `ROOT = Path('D:/source_code/backtrader')`; its real generator builds source paths from that value, whereas the R7 fixture derives expected keys from the helper location. A relocated test root therefore cannot be advertised as clean-source acceptance without changing that path behavior. No such rewrite is made here.
