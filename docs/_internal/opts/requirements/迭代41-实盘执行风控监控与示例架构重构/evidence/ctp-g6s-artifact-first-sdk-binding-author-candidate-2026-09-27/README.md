# G6-S TD settlement consumer with artifact-first SDK binding (isolated candidate)

Status: `ISOLATED_SOURCE_FAKE_ONLY / NO_ACCEPTANCE`. This candidate lives only at `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927`; main runtime source, default registration, pins and the preceding frozen candidate were not modified.

## Bridge shape

The public `verify_ctp_simnow_td_trading_readiness` no longer accepts a caller-supplied verifier. It requires a no-argument `require_trusted_ctp_sdk_artifact_before_client()` preflight first. The preflight reads only code-owned policy; this candidate's `_CODE_OWNED_ARTIFACT_POLICY` is deliberately `None`, so it fails before importing `bt_api_ctp`. The public readiness function likewise refuses before touching its client unless that pre-client step established the process-local binding.

When a reviewed policy is eventually added as code, the bridge first rejects empty `sys.path` entries, present archive paths, nonstandard path hooks, and nonstandard cached finders, then checks exactly one `bt_api_ctp` package and one matching `.dist-info` across the remaining roots. It validates exact Name/Version, a code-pinned RECORD digest, all RECORD member hashes and sizes, exact critical source/native-file digests, no unrecorded package files or bytecode cache, and the standard meta-path import chain. After import it verifies exact module specs/loaders/origins and source hashes; it holds the exact evidence class object and compares with `type(evidence) is expected_type`. It rechecks the RECORD/inventory and loaded module identities before use. `_ctp` origin and hash are checked without importing an extension in the tests.

Existing fake readiness-contract tests call the explicitly private `_verify_ctp_simnow_td_trading_readiness_with_test_verifier`; it is a test seam, not a production entrypoint. Fake artifact tests exercise the installation validator against inert source and placeholder extension bytes only.

## Limits

No final SDK wheel or independently approved external artifact pin is available, so the code-owned policy remains unset and no real SDK verifier is constructed. The fake policy exists only inside tests. The source-manifest digest is a future code-owned identity field; in this candidate it is not independently resolved to a source-manifest artifact. This is not G4 or G6-S acceptance. The Python module/cache and digest checks do not create an OS trust boundary; the candidate does not retain protected file handles or verify installation ACLs, and it has no signed release pin. A production integration still needs the exact wheel/RECORD/native-extension pin and a protected, immutable load path before constructing any SDK client/API. No native extension was imported or executed; no account/provider/network/credential/private-config access occurred.

## Verification

CPython 3.11.5, candidate-root `PYTHONPATH`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONDONTWRITEBYTECODE=1`. Focus command and raw results are in `evidence/artifact-first-run/`; result is **36 passed, 0 skipped, exit 0**. New bridge source and bridge tests pass Ruff; I001/UP035 pass across the four changed source/test files. Fresh-process guard verified both candidate module origins and zero SDK modules loaded. The preceding 22-test candidate receipt is preserved in `evidence/parent-freeze-receipt.json`.
