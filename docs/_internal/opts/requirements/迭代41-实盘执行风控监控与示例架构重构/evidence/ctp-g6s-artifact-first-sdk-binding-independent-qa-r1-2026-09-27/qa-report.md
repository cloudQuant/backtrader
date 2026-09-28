# Independent QA — G6-S SDK artifact binding R1

Disposition: **`PARTIAL_CUSTODY / G4 AND G6-S BLOCKED`**.

This review used the frozen R1 candidate only. It does not accept a release pin, live SDK binding, native extension load, G4, or G6-S.

## Frozen input and copy integrity

- Candidate: `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r1`
- Candidate manifest: `candidate-source-manifest.json`, SHA-256 `4cda34fadd2c73efb999a0411657eb625b30caa2adce5a0e56ef7527a90f8080`, 141 listed payloads.
- Candidate ZIP: `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r1.zip`, SHA-256 `d5aa16bec66c7618f58b1039f87c7a774ec9958a848cbd29a94e7527887e84f0`; ZIP CRC passed.
- All 141 listed files matched both declared size and SHA-256 in the frozen source and the independent copy at `D:\temp\iteration41-g6s-r1-independent-qa-20260927`.

The author’s freeze receipt is `freeze-receipt.json`, SHA-256 `9e42739f3357032cd4c0c8d67b493bd52a2a114272c45b3223ce38874b331473`.

## Independent tests

Interpreter: `C:\anaconda3\python.exe`, CPython 3.11.5. The run used the isolated QA copy as `PYTHONPATH`, with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `PYTHONDONTWRITEBYTECODE=1`.

The final frozen command was run as:

```powershell
python -m pytest --noconftest `
  tests\unit\runtime\test_ctp_sdk_artifact_binding.py `
  tests\unit\runtime\test_ctp_windows_artifact_custody.py `
  tests\unit\runtime\test_ctp_simnow_td_trading_readiness.py `
  -q --tb=short --junitxml=evidence\r1-independent-qa\pytest-focus.junit.xml
```

Result: **47 passed, 0 skipped** in 2.74 s. The frozen packet calls this the 47-test focus; it supersedes the original 46-test expectation.

A targeted adversarial rerun covering the Windows retained-source mutation, post-custody source replacement, four import-context mutations (`sys.path`, `sys.meta_path`, `sys.path_hooks`, and importer cache), `sys.modules` spoofing, and the default no-pin gate passed **8/8** in 1.41 s.

## Independent probes

1. **Retained native-file custody works for tested mutations.** With a fake distribution whose `.pyd` file contains inert text, a write attempt while custody was held raised `PermissionError`; `os.replace` raised `PermissionError` with Win32 error 32. The retained bytes remained unchanged. No native image was loaded.
2. **Post-custody source replacement is rejected.** The candidate’s marker test verified that a source swap after handle acquisition could not replace the leased source or run its marker. The focused Windows custody test separately asserted overwrite denial and the exact rename sharing violation.
3. **A same-process loader hook remains mutable.** After the candidate gate installed its importer, a QA-only probe replaced `importlib.machinery.ExtensionFileLoader` with a fake inert loader. `_PinnedExtensionLoader` accepted that replacement: it read/hash-checked the retained fake `.pyd` bytes, then delegated to the patched loader, which set a marker. No `.pyd` was mapped or executed. The importer snapshots `sys.path`, `sys.meta_path`, `sys.path_hooks`, importer cache, and SDK `sys.modules`; it does not bind the `ExtensionFileLoader` global. This is an in-process boundary gap, consistent with the candidate’s own statement that same-process Python state is not a hostile-code isolation boundary.
4. **The native loader remains pathname-based.** `_PinnedExtensionLoader` constructs `importlib.machinery.ExtensionFileLoader(fullname, origin)` and delegates `create_module`/`exec_module` by path after checking the retained file digest (`backtrader_runtime/ctp_sdk_artifact_binding.py`, lines 547–567). The retained no-write/no-delete-share handle blocks the tested ordinary overwrite/rename races, but the candidate does not prove that the OS-mapped native image was loaded from those same handle bytes or independently verify the loaded image. The only extension fixture is inert bytes; no actual `_ctp` load was attempted.
5. **Default gate remains closed.** A fresh-process QA probe observed `sdk_artifact_release_pin_unavailable` while `_CODE_OWNED_ARTIFACT_POLICY` was `None`; no `bt_api_ctp` package module appeared in `sys.modules`.

## Limits and conclusion

R1 materially improves file custody: it retains exact files and ancestors, reads Python sources from those handles, blocks tested concurrent file replacement, and rejects the tested importer/cache mutations. Directory custody still does not prevent creating a new child; the manifest map rejects unlisted SDK modules, but this is not a complete immutable dependency closure.

The same-process loader substitution probe and pathname-based extension load remain unproven boundaries. More fundamentally, there is no code-owned SDK pin, approved wheel/signature, or protected deployment trust root; the production pin is still `None`. No real SDK, `_ctp`, account, credentials, private config, provider, or network was accessed.

**Conclusion: `PARTIAL_CUSTODY / G4 BLOCKED / G6-S BLOCKED`.** Default routes remain fail-closed.
