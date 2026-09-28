# G6-S R2 `.pyd` loader boundary (read-only probe)

**Decision: `NO_G4 / NO_G6-S`.** CPython 3.11.5's supported Windows extension loader takes a module path; its `LoadLibraryExW` call passes `hFile=NULL`. A retained handle/file ID cannot be supplied to that loader. A no-write/no-delete handle plus protected directory ACL can make the pathname stable against ordinary concurrent replacement while held, but R2 did not load a fake `.pyd` or observe the loaded image path/file identity. This packet does not claim direct handle-to-image binding.

## Scope and inputs

- Frozen R2 author candidate: `D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ctp-g6s-artifact-first-sdk-binding-r2-author-candidate-2026-09-27`
- R2 manifest SHA-256: `4ee9f0258b6b2e575fb2039fe3f31a049d918f2f86f3c5707365d3d37e48b916`
- R2 ZIP SHA-256: `dbbcbd8a5de4daf5265ae10b5eb114cbd6b2a429dc4ff9535aca5c3de8779d14`
- Binder source SHA-256: `A7A27A318D4C3EFEB5CC781C4C6479D56439DA579D46DA669C6F9349F96FB049`
- Custody source SHA-256: `EAF794FCEED98ED18BC23D21BC9D1D962575D27CEEE9B78BFD84D86B2003F421`
- Custody test SHA-256: `14A643DECA3AA8F259FCA54D3C6066DC77817C4537E2E8A0ECCBB034685DB841`
- Local interpreter: CPython 3.11.5, Anaconda, Windows 10.0.26200 (AMD64)
- Local `importlib/_bootstrap_external.py` SHA-256: `5B7F704FD3198CB474FEA0E74CB21DF2D159CEB6BDE78AAD5DB3EB5EFA883CCF`

No CTP/SDK/native extension was imported or loaded. The executable probe only introspected the standard-library `ExtensionFileLoader` Python class. R2's Windows custody test exercises `.py` source import and Windows share behavior, not `.pyd` loading.

## Evidence

1. Python's 3.11 importlib API defines `ExtensionFileLoader(fullname, path)` and documents `path` as the extension module's file path. The exact CPython v3.11.5 implementation stores `name` and `path`; `create_module` calls `_imp.create_dynamic(spec)` and `exec_module` calls `_imp.exec_dynamic(module)`. There is no handle or file-ID parameter.
2. CPython v3.11.5 `Python/dynload_win.c` converts the `pathname` to a wide string and calls `LoadLibraryExW(wpathname, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR)`.
3. Microsoft documents `LoadLibraryExW`'s `hFile` argument as reserved and requiring `NULL`. Its data/image-resource modes do not do normal executable initialization, so they cannot stand in for a CPython extension load.
4. R2's `WindowsArtifactCustody` opens retained files with `FILE_SHARE_READ` only. The R2 Windows test passed 3/3: while a retained file handle is open, ordinary overwrite and `os.replace` fail. The test target is a `.py` file, not a `.pyd`. A separate test confirms a directory handle alone does not block adding a new child name; the protected directory ACL and path/reparse checks are required.
5. Microsoft also documents `LoadLibraryExW` application redirection: a redirection file may cause a path-qualified load to use a same-name module in the application directory instead. A future path-custody acceptance test must explicitly rule out or safely bind that behavior and bind every dependent DLL as well.

## Finding: direct binding vs. pathname custody

**Direct handle-bound load is unavailable through the supported CPython 3.11.5 / Win32 API surface.** CPython delegates to a pathname-based loader and Win32 requires `LoadLibraryExW.hFile == NULL`. A Windows `SEC_IMAGE` mapping from a retained handle is not the same API: mapping alone does not provide CPython's dynamic import resolution and extension initialization sequence. Implementing a custom PE loader would be a separate native-loader project, not a small Python binder adjustment.

**A narrower path-stability design may still be viable.** R2's share-read-only handles demonstrably block regular write/rename of the held file during the lease. If the exact service-owned install tree and every ancestor are protected against writes, deletes, reparse replacement and redirection, and those handles remain open through load/use, then the absolute `spec.origin` path can be made stable against the untrusted owner during CPython's independent pathname open. That would be a path-custody argument, not evidence that CPython consumed the already-verified handle. R2 has not demonstrated the complete chain for an actual extension image.

## Smallest next conformance test

Use a harmless local CPython 3.11 fake extension only; do not involve the SDK. Put the fake `.pyd` and its test dependency in a disposable service-owned directory. Before import, retain verified file and ancestor handles that deny write/delete, verify ACLs/reparse/file IDs/hashes, and keep the lease until unload/process exit. Import through the real standard CPython extension path from its exact absolute origin. During and after import, attempt overwrite, rename, delete, and reparse/path substitution; every attempt must fail before any replacement marker runs. Independently observe the loaded module's actual path (for example through the Windows module enumeration/path API), compare it with the pinned path while custody remains held, and reject any application-redirection or dependency mismatch. Do not infer the loaded path or file identity from `module.__file__` alone. Archive raw module observations, handle/file-ID facts, attempted operation results and both sides' hashes.

This can establish a constrained, path-based assurance if the OS custody facts hold. It still cannot satisfy a requirement that the loader itself be passed the retained file handle or return a kernel file ID for the mapped image. If that direct mapping is mandatory, keep the artifact route closed or move the load into a separately reviewed native loader boundary.

## Reproduction

- `C:\anaconda3\python.exe -I -S -B D:\temp\iteration41-g6s-pyd-loader-boundary-20260927\probe_extension_loader.py` — local constructor `(name, path)`, `create_module(self, spec)`, `exec_module(self, module)`; confirms the source delegates to `_imp.create_dynamic(spec)` / `_imp.exec_dynamic(module)`. No extension loaded.
- From the R2 `candidate` directory with `PYTHONPATH=<candidate>` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`: `C:\anaconda3\python.exe -m pytest --noconftest tests\unit\runtime\test_ctp_windows_artifact_custody.py -q --tb=short` — **3 passed**, one existing unknown pytest asyncio config warning. One initial collection attempt from the main repository CWD imported the main repo's `backtrader_runtime` instead of the R2 copy; rerunning from candidate CWD passed. This setup failure was path selection, not a code failure.

## Primary sources

- [Python 3.11 `ExtensionFileLoader`](https://docs.python.org/3.11/library/importlib.html#importlib.machinery.ExtensionFileLoader)
- [CPython v3.11.5 `importlib._bootstrap_external`](https://github.com/python/cpython/blob/v3.11.5/Lib/importlib/_bootstrap_external.py)
- [CPython v3.11.5 Windows extension loader](https://github.com/python/cpython/blob/v3.11.5/Python/dynload_win.c)
- [Microsoft `LoadLibraryExW`](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw)
- [Microsoft `GetModuleFileNameExW`](https://learn.microsoft.com/en-us/windows/desktop/api/psapi/nf-psapi-getmodulefilenameexw)

Feasibility/boundary evidence only. No main source/default route/R2 artifact was modified; no installed-wheel provenance, real SDK load, G4, or G6-S acceptance is established.
