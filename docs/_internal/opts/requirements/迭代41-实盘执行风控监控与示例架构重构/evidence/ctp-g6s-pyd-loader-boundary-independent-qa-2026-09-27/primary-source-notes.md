# Official source notes (reviewed 2026-09-27)

CPython source was checked at the explicit v3.11.5 tag, matching the local 3.11.5 interpreter family:

- `Lib/importlib/_bootstrap_external.py`: `ExtensionFileLoader.__init__(name, path)` stores `self.name` and `self.path`; `create_module` delegates `_imp.create_dynamic(spec)`; `exec_module` delegates `_imp.exec_dynamic(module)`.
- `Python/importdl.c`: dynamic module loading reads `spec.origin` and passes that object to `_PyImport_FindSharedFuncptrWindows` on Windows.
- `Python/dynload_win.c`: `_PyImport_FindSharedFuncptrWindows` turns its `pathname` into a wide string and calls `LoadLibraryExW(wpathname, NULL, LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR)`.
- Microsoft `LoadLibraryExW` reference: `hFile` is reserved and must be `NULL`. Its dependency-search remarks describe the `.dll` directory, application directory, explicitly-added user dirs, and System32 when corresponding flags are present; the same page documents application redirection behavior when a redirection file applies.
- Python 3.11 importlib docs describe `ExtensionFileLoader(fullname, path)` and define `path` as the extension module file path.

URLs:

- https://github.com/python/cpython/blob/v3.11.5/Lib/importlib/_bootstrap_external.py
- https://github.com/python/cpython/blob/v3.11.5/Python/importdl.c
- https://github.com/python/cpython/blob/v3.11.5/Python/dynload_win.c
- https://docs.python.org/3.11/library/importlib.html#importlib.machinery.ExtensionFileLoader
- https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-loadlibraryexw

This records the documented/source call chain. It is not runtime observation of a `.pyd` mapping.
