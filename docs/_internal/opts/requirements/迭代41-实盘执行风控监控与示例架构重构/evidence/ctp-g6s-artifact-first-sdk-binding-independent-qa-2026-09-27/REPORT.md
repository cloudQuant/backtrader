# Independent G6-S artifact-first binding QA

Status: `FAKE_LOCAL_CONTRACT_ONLY / NOT ACCEPTED FOR G4 OR G6-S`.

**Blocking finding:** the verification-to-import file race is executable on a writable install tree. This candidate is not a safe artifact gate unless the package path is protected against replacement or verified through a retained, race-free source handle.

## Frozen candidate identity

- Candidate: `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927`
- Candidate source manifest SHA-256: `bbf863557deb20dcadf766fcb98eeabca97922c0cc72e543f5468e59fce480c4`
- Independently verified payload: 139 files; all manifest paths, lengths and SHA-256 values matched. No missing manifest payload files were found. The frozen directory also contains 216 unlisted generated tool-cache files (190 pyc, 14 Ruff cache files, 12 pytest cache files); these are not in the 139-file manifest payload and were excluded from the QA copy.
- QA copy: `D:\temp\iteration41-g6s-artifact-first-sdk-binding-independent-qa-20260927-r1`; only this copy received QA logs and one QA-only adversarial test file.

## Test replay

Interpreter: `C:\anaconda3\python.exe` (CPython 3.11.5). Environment: `PYTHONPATH` set to the isolated QA copy, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONDONTWRITEBYTECODE=1`.

Command:

```powershell
python -m pytest --noconftest tests\unit\runtime\test_ctp_sdk_artifact_binding.py tests\unit\runtime\test_ctp_simnow_td_trading_readiness.py tests\unit\runtime\test_g6s_adversarial.py -q --tb=short --junitxml=evidence\independent-qa\combined-junit.xml
```

Result: **45 passed, exit 0** (36 frozen-candidate tests plus 9 QA-only adversarial tests). Raw stdout and JUnit are stored alongside this report.

## Findings

1. **Default path fails closed.** `_CODE_OWNED_ARTIFACT_POLICY` is `None`; the no-argument pre-client gate rejects with `sdk_artifact_release_pin_unavailable` before any `bt_api_ctp` module is loaded. Public readiness has no verifier/policy parameter and rejects without the pre-client gate before reading client attributes. Tests also show the private fake-artifact policy is installed only by test monkeypatching; it is not a public argument. This is local process behavior, not a protected code boundary.
2. **Nominal ordering is correct.** The preflight validates import machinery, search paths, unique package/dist-info, metadata, pinned RECORD bytes, RECORD member hashes/sizes, package inventory, critical file hashes and extension bytes before its first `importlib.import_module` for the SDK evidence module. After import it checks exact module specs/loaders/origins and source hashes, tracks module object identities, and compares evidence using exact class identity. Pre-existing SDK entries in `sys.modules` reject. Empty path entries and archive paths reject. The `_ctp` checker validates inert module origin/hash without executing an extension.
3. **BLOCKER — installed-file TOCTOU is demonstrated.** A QA-only race probe swaps the fake evidence source after distribution/hash verification but immediately before `importlib.import_module`. The replacement source executes its harmless marker side effect; only afterward does the verifier reject with `sdk_artifact_loaded_module_hash_mismatch`. The implementation uses ordinary path checks and file reads, without retained handles/ACL enforcement. Therefore the pre-import scan does not protect against concurrent replacement by a writer to the installed tree, and must not be used as a security gate on a writable install path. The README acknowledges the lack of an OS trust boundary.
4. **Post-gate import policy is not rechecked.** A QA-only probe replaces `sys.path`, `sys.meta_path`, and `sys.path_hooks` after the verifier cache is established; `verifier.assert_current()` still succeeds. The candidate rechecks artifact bytes and loaded module identities but does not rerun the standard import-chain/search-root gate on cached use. This leaves lazy imports/external dependency resolution outside the demonstrated artifact binding.
5. **Client construction order is a caller contract.** The candidate exposes a separate pre-client gate and documents that callers must invoke it before SDK client/native construction. The readiness entrypoint checks the gate before touching the supplied object, but it neither constructs nor validates the exact SDK client class and cannot prove when that already-supplied client/credentials were created. No real composition is accepted in this candidate.
6. **Artifact identity is incomplete for release use.** `source_manifest_sha256` is only format-checked/copied from the policy; the code does not independently resolve the referenced source-manifest bytes. No approved installed wheel/pin exists. The candidate has no protected-handle or ACL checks. The synthetic `.pyd` bytes are inert and were never loaded.

The same-name/module evidence class spoof, replacement of the loaded SDK module object, replacement of the evidence class attribute, nested `sys.modules` contamination, valid ZIP import-root, empty `sys.path` entry, and native-extension digest mismatch all rejected in the expected fake-only probes.

## Scope limits

No real SDK wheel was built or installed. No `_ctp` extension, SDK/native code, provider, account, credential, private config, or network was accessed. This QA does not establish race-free artifact loading, external dependency integrity, an OS trust boundary, G4, G6-S, or authorization to enable a default route.

