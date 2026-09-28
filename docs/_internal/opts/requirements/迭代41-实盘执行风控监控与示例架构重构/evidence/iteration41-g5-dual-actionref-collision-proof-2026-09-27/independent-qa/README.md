# Iteration 41 G5 dual ActionRef authority collision (fake-only)

This isolated deterministic reproduction uses exact frozen local source inputs and a fresh `:memory:` SQLite database. It exercises the V21 Store order identity API, G5 identity authority, and the V21 Store's internal cancel ActionRef allocator with synthetic identifiers and caller-supplied zero watermarks.

It does not import the native CTP binding, read credentials, create a file-backed database, open a socket, contact a provider, or call an SDK/native send method. Its intended claim is limited to a structural hazard: separate durable ActionRef allocators may return the same value for one synthetic account. It is not evidence of a real provider-side duplicate.

Run with CPython 3.12:

```powershell
& 'C:\Users\yunji\AppData\Local\Programs\Python\Python312\python.exe' 'D:\temp\iteration41-g5-dual-actionref-collision-20260927-candidate\repro_actionref_collision.py'
```

The script verifies the frozen V21 manifest, V21 Store, and G5 identity-authority SHA-256 values before importing or running candidate code. The expected one-run result is `STRUCTURAL_COLLISION_REPRODUCED`, with both refs equal to 1. `run-output.json` contains the captured stdout and the script hash; `source-hashes.json` contains source and artifact hashes.
