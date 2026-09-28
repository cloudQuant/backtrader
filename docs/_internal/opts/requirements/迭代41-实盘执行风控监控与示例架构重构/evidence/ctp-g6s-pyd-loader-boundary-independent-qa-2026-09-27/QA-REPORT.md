# G6-S `.pyd` loader boundary: independent QA

**Disposition: `PARTIAL_PATH_CUSTODY_ONLY / NO_G4 / NO_G6-S`.** The frozen candidate and its local custody tests are reproducible, but the supported CPython Windows extension loader does not consume a retained file handle. It resolves an extension from a path through `_imp.create_dynamic`; CPython 3.11.5 then calls `LoadLibraryExW(path, NULL, flags)`. Microsoft documents the API `hFile` argument as reserved and requiring `NULL`. The probes below do not load a `.pyd`, CTP SDK, or `_ctp`.

## Inputs and hash verification

The frozen audit packet is `D:\temp\iteration41-g6s-pyd-loader-boundary-20260927`. All six payload lengths and SHA-256 values matched its `MANIFEST.json`. The frozen packet says no extension was loaded.

The R2 author candidate was independently verified against the recorded values:

- Source manifest: `4ee9f0258b6b2e575fb2039fe3f31a049d918f2f86f3c5707365d3d37e48b916` (191 payload entries).
- Candidate ZIP: `dbbcbd8a5de4daf5265ae10b5eb114cbd6b2a429dc4ff9535aca5c3de8779d14` (193 entries; CRC clean).
- Every manifest-listed payload file matched path, size, and SHA both on disk and inside the ZIP.
- Binder source SHA: `a7a27a318d4c3efeb5cc781c4c6479d56439da579d46da669c6f9349f96fb049`.
- Windows custody source SHA: `eaf794fceed98ed18bc23d21bc9d1d962575d27ceee9b78bfd84d86b2003f421`.
- Windows custody test SHA: `14a643deca3aa8f259fca54d3c6066dc77817c4537e2e8a0eccbb034685db841`.

## Independent runs

Environment: Windows 10.0.26200 (AMD64), CPython 3.11.5 at `C:\anaconda3\python.exe`. Local `_bootstrap_external.py` SHA-256 was `5b7f704fd3198cb474fea0e74cb21df2d159ceb6bde78aad5db3eb5efa883ccf`.

1. `probe_extension_loader.py` ran under `python -I -S -B`; it reported constructor `(name, path)`, methods `(self, spec)` / `(self, module)`, no handle parameter, and the `_imp.create_dynamic` / `_imp.exec_dynamic` delegates. No extension was imported or loaded.
2. From the frozen R2 candidate directory, the independent command

   `C:\anaconda3\python.exe -m pytest --noconftest tests\unit\runtime\test_ctp_windows_artifact_custody.py -q --tb=short --color=no`

   with `PYTHONPATH` set to the candidate and plugin autoload disabled passed **3 tests**. The one warning is the existing unrecognized `asyncio_default_fixture_loop_scope` pytest option. The tests exercise `.py` source custody and ACL behavior, not `.pyd` loading.
3. A QA-only fake path probe created a text file with a `.pyd` suffix, opened it with `GENERIC_READ` and `FILE_SHARE_READ`, attempted ordinary write and `os.replace`, then closed the handle and retried rename. While held, write failed with `PermissionError` (`errno=13`) and replacement failed with `PermissionError` (`winerror=5`); the placeholder hash remained unchanged. Rename succeeded after close. It was deliberately invalid PE data and was never passed to an extension loader.

The initial fake-probe classifier expected only Win32 sharing-violation codes 32/33 and marked the write attempt false because Python surfaced `PermissionError(errno=13, winerror=None)`; replacement surfaced access-denied 5. After recording those actual errors and adjusting the test assertion to the platform-observed denial, the probe passed. The first run is preserved as a harness-classification diagnostic, not as a product failure.

## Loader chain and conclusion

The CPython 3.11.5 `ExtensionFileLoader` constructor stores only `name` and `path`. Its `create_module(spec)` delegates to `_imp.create_dynamic(spec)` and `exec_module(module)` delegates to `_imp.exec_dynamic(module)`. In CPython's C import code, the extension `spec.origin` is passed as the pathname to `_PyImport_FindSharedFuncptrWindows`; `dynload_win.c` converts that pathname to a wide string and calls `LoadLibraryExW(wpathname, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR)`. No retained Windows handle or file ID is supplied to this loader call. Microsoft specifies `hFile` as reserved and requiring `NULL`.

**Direct retained-handle-to-image binding is not available through this supported call chain.** The fake custody probe demonstrates a narrower fact: one open handle with a restrictive share mask can prevent ordinary replacement operations against that path for the handle's lifetime. It does not show that the image loader consumed that handle or that a mapped module corresponds to its file ID.

Still unproven: an actual `.pyd` image/path/file identity at load time; application redirection behavior for the deployed executable; native dependency and transitive DLL identities; the integrity of the interpreter/loader image; and protection of every relevant path/ancestor in a real installation. Microsoft documents that `LoadLibraryEx` may load dependencies and that directory search policy affects resolution. The normal module `__file__`/spec path alone is not a mapped-image file-ID observation.

No source/default route was changed; no SDK, `_ctp`, provider, account, network, or private config was touched. Default artifact policy remains unset. This packet leaves G4/G6-S closed.

## Primary sources

- Python 3.11 `ExtensionFileLoader` API: <https://docs.python.org/3.11/library/importlib.html#importlib.machinery.ExtensionFileLoader>
- CPython 3.11.5 `Lib/importlib/_bootstrap_external.py`: <https://github.com/python/cpython/blob/v3.11.5/Lib/importlib/_bootstrap_external.py>
- CPython 3.11.5 `Python/importdl.c`: <https://github.com/python/cpython/blob/v3.11.5/Python/importdl.c>
- CPython 3.11.5 Windows loader `Python/dynload_win.c`: <https://github.com/python/cpython/blob/v3.11.5/Python/dynload_win.c>
- Microsoft `LoadLibraryExW` API, including `hFile` and dependency search behavior: <https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw>
