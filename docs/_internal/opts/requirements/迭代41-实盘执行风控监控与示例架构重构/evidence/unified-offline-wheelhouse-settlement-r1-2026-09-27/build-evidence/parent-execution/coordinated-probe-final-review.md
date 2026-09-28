# Iteration 41 coordinated wheel probe — final receipt

**Result:** both disposable wheels built twice byte-identically, passed installed RECORD/origin checks and clean `pip check`; the selected installed-wheel fake suites ran 143 cases (123 unique node IDs, 20 repeat executions), all passed, zero skips. This is not a release or G1/G4/G5 acceptance.

## Exact inputs and identities

- Final source manifest: `D:\temp\iteration41-coordinated-release-probe-20260927-r1\coordinated-probe-source-manifest-final.json` — SHA256 `01fa737d2a0f385dec8ce6187d95c4a104c13cce9dde6d693152df7dd94ef4b6` (843 files across parent source, execution project, main overlay and SOURCE-ONLY metadata).
- Execution input: V23 manifest `f94b924e1e20fba6ccfe5bc028d88a0ad541022afb8e9c7a5f66a597687ab330`; distribution `0.2.4.dev0+v23r3r3.f94b924e1e20`.
- Parent input: base commit `76d5e0e60883263e0e79b67df321e7053ed46179`, R4 manifest `60b020202ed89169e24afca30b1b1b16680151a11c6f52c518d0f5bbfa7fab0d`, R3r3 issuer manifest `50b0d8b99afdacdaf2055246010e5766bbe630bc66d71c2aeeaca117baf3ce7a`; distribution `0.15.7.dev0+r4r3r3.67e54513`.
- Dual-build source inputs: execution `36/36` files exact match; parent `156/156` exact match.
- Wheel verifier: `D:\temp\iteration41-coordinated-release-probe-20260927-r1\wheel-dual-build-verification.json` SHA256 `3dbb35f1736eb8c61b2d44e40ab829158993f313be7f6031eea281e7012c74f8`. Execution wheel SHA256 `b2a74d5ec4bce72db66ed5698709a8f986de02b54d72fb5e08a181c2983b6217`; parent wheel SHA256 `5e6e846d26b5038c0916fa15d3ce3f7a1c1334fd0aa160cd263d2d0397c07b0f`.
- Private venv: `D:\temp\iteration41-coordinated-release-probe-20260927-r1\venv-installed-wheel-v3-clean`; Python 3.11.5. Both wheels' installed origins are under that venv; installed RECORD payloads verified (Execution 17 members, parent 143 members). `pip check`: exit 0, “No broken requirements found.” `bt_api_base` remained SOURCE-ONLY metadata with an explicitly mapped source tree.

## Installed-wheel fake suites

Runner: `D:\temp\iteration41-coordinated-release-probe-20260927-r1\run_installed_suite_v3.ps1` SHA256 `1829ff731ef100112880a60ed4b9380652a4fda7ed3bacd4999ed853042217b1`. It sets `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, explicit `BT_API_TEST_SOURCE_ROOTS`, fixture basetemp, guarded imports/network, then calls `pytest.main` with `--import-mode=importlib -q --basetemp ... --junitxml=...`. Exact per-suite argv and JUnit/log hashes are in the final JSON receipt.

- Main bridge and L2: 73 passed, 0 skipped; 1 existing Quandl deprecation warning.
- Main cancellation control: 20 passed.
- Main artifact-set pin check: 6 passed.
- Parent issuer/control: 44 passed.

Four invocations total 143 test executions; 20 node IDs were repeated across main/parent cancellation-control packages, leaving 123 unique node IDs.

Final clean guard logs: {'guard-started': 13, 'source-import': 1031, 'source-namespace': 7}. `NATIVE_MODULES_LOADED` was `[]` for each suite. No network-blocked, native-import-blocked, private-config-blocked, or origin-rejected event occurred in these final four suites. The candidate CTP source path was mapped but no `bt_api_ctp`, `_ctp`, or `ctp_wrap` module was loaded. Absence of native imports does not constitute G4 acceptance.

## Preserved diagnostic failures

- An earlier main bridge attempt had 67 pass, 5 fail, 1 skip; guard blocked a site-packages `bt_api_base` origin that shadowed its required source tree. A separate fixture L2 runner failed in that attempt. The clean isolated venv removed the installed base distribution, and the final installed-wheel run passed all 73 with the required mapped source origin.
- The first copied parent suite failed collection (exit 2) because the copied test harness referenced missing root/fixture paths; the v3b installed-test copy corrected that setup, and final suite passed 44.
- Two earlier wheel builds failed and are retained: one staging layout lacked required `src/`; a second used a PEP 440 tag whose wheel path exceeded Windows temporary-path limits. Final v4 builds used the required src layout and shorter unique disposable tags.

## Limits

These are disposable local versions, not release tags: `0.2.4.dev0+v23r3r3.f94b924e1e20` and `0.15.7.dev0+r4r3r3.67e54513`. Default production pins and tracked main source were not changed in this probe. The parent authority is fake-only; the Execution process-boundary implementation uses a fake attestor. There was no provider, credentials, native session, remote endpoint, or default CTP route. No G1/G4/G5 or release acceptance is implied.

Machine-readable receipt: `D:\temp\iteration41-coordinated-release-probe-20260927-r1\coordinated-probe-final-receipt.json`
