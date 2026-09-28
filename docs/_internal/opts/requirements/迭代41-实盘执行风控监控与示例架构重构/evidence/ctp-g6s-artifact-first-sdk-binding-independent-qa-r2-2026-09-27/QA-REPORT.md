# Independent QA — G6-S SDK artifact binding R2

Disposition: **`PARTIAL_CUSTODY / NO_G4 / NO_G6-S`**.

R2 closes the specific R1 post-gate importer-global replacement probe, and its test suite reproduces. The candidate remains a fake/local custody slice: the code-owned artifact policy is `None`, no trusted release pin or deployment root exists, and no native extension was loaded.

## Frozen input and copy integrity

- Candidate: `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927-r2`
- Manifest: `candidate-source-manifest.json`, SHA-256 `4ee9f0258b6b2e575fb2039fe3f31a049d918f2f86f3c5707365d3d37e48b916`, 191 payload files.
- Freeze receipt: SHA-256 `624ba96440e9099dc667fe840b5d73b0fac8aec28d88355506302fe5944b90ee`.
- Candidate ZIP: SHA-256 `dbbcbd8a5de4daf5265ae10b5eb114cbd6b2a429dc4ff9535aca5c3de8779d14`, 193 entries, no duplicate names, CRC passed. Manifest/receipt hashes match their ZIP members, and all 191 listed payloads match declared size and SHA-256 both in the source and the independent copy at `D:\temp\iteration41-g6s-r2-independent-qa-20260927`.
- Author sidecar SHA-256: `7b1bc78ab5e0159fa30698b95b20ad41d4f132b0ce3e2641aadab7859010eedb`.

## Independent test results

Interpreter: `C:\anaconda3\python.exe`, CPython 3.11.5. The isolated copy was used as `PYTHONPATH`; `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and `PYTHONDONTWRITEBYTECODE=1`.

Exact focus:

```powershell
python -m pytest --noconftest `
  tests\unit\runtime\test_ctp_sdk_artifact_binding.py `
  tests\unit\runtime\test_ctp_windows_artifact_custody.py `
  tests\unit\runtime\test_ctp_simnow_td_trading_readiness.py `
  -q --tb=short --junitxml=evidence\r2-independent-qa\pytest-focus.junit.xml
```

Result: **52 passed, 0 skipped** in 3.36 s.

The R2 import-guard tests run separately passed **5/5**: post-gate `ExtensionFileLoader` replacement; `ModuleSpec`, `module_from_spec`, and `PathFinder.find_spec` replacement; and replacement during the retained `.pyd` hash read.

## Independent adversarial probes

1. **R1 hook replay now rejects.** Replayed the R1 sequence against R2: after the gate, replace `importlib.machinery.ExtensionFileLoader` with an inert fake and request `_PinnedSdkImporter._spec_for('bt_api_ctp.ctp._ctp')`. It rejects with `sdk_artifact_importlib_machinery_changed`; fake loader construction/create/exec callbacks remain at zero. No `.pyd` was loaded.
2. **Independent importlib mutation matrix.** After the gate, separately replaced `ExtensionFileLoader`, `ModuleSpec`, `module_from_spec`, and `PathFinder.find_spec`. Every case rejected with `sdk_artifact_importlib_machinery_changed`, before the replacement callback ran (0 calls in all four cases).
3. **Retained `.pyd` file custody.** A fake `.pyd` containing inert text resisted overwrite (`PermissionError`) and `os.replace` (`PermissionError`, Win32 error 32) while the lease was held; retained bytes remained unchanged. No native image was loaded.
4. **Path-based native loader remains.** The candidate’s `_PinnedExtensionLoader` still constructs `_TRUSTED_EXTENSION_FILE_LOADER(fullname, origin)` and invokes its captured `create_module`/`exec_module` method descriptors (source lines 594–625). The delegate receives a pathname and there is no retained-handle argument for OS image mapping. The wrapper re-reads and hashes bytes via custody immediately before delegation, but no actual `_ctp` image was loaded and the mapped image was not independently proven identical to those retained bytes.
5. **Context gates still pass.** The 52-test focus includes `sys.path`, `sys.meta_path`, `sys.path_hooks`, importer-cache and `sys.modules` mutation rejection. The fresh default gate remains fail-closed because the release policy is `None`.

## Limits and conclusion

R2 materially improves the tested same-process import-hook checks: it binds the importlib module, `ModuleSpec`, `module_from_spec`, finders, and `ExtensionFileLoader` class/method identities, then rejects the tested post-gate mutations before use. Windows retained handles block the tested file overwrite and rename attempts.

The native extension still enters through CPython’s pathname-based `ExtensionFileLoader`; this snapshot does not demonstrate handle-bound OS loading or mapped-image verification. The code-owned pin is unset, and there is no approved wheel/signature, protected deployment trust root, or complete trusted runtime closure. No real SDK, `_ctp`, account, credentials, private config, provider, or network was accessed.

**Conclusion: `PARTIAL_CUSTODY / G4 BLOCKED / G6-S BLOCKED`.** No production/default route is enabled.
