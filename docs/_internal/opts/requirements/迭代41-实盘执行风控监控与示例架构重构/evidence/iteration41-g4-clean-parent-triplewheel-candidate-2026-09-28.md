# Iteration 41 G4 clean-parent triple-wheel candidate

**Disposition: `REPRODUCIBLE_ARTIFACT_CANDIDATE / G4_NOT_ACCEPTED`.** This checkpoint is artifact identity evidence, not native-provider or lifecycle acceptance.

## Candidate identities and clean inputs

| Distribution | Version | Wheel SHA-256 | Embedded RECORD SHA-256 |
|---|---|---|---|
| `bt_api_base` | `0.15.5` | `d003d66b91feba16f3c9a2f523bb4984dc1caf4b44750e44c0c406beca6837d9` | `a9701f83db9ca37e231005945d69ebe9696fd449cca4e5bb26e4981811899b13` |
| `bt_api_ctp` | `2.0.3+iteration41.i2` | `70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2` | `17ef1594fe0606c3c3b33c99616d495ee79a3a1f8fc58ed29b4abfa1c163dfd0` |
| `bt_api_py` | `0.15` | `ceaca0f24d2c36ff7df54aa7b80ab78fc5efe9d87c81efa8d05e934445011ab3` | `326943185204cbf59c40daf8972ad04e1ebfdeb89a711a07694ef8acfcb88e04` |

Build C/D used base source `73e860e2fd8086ec817db254d4c396c2a76eb7d6`, CTP source `28157ce33009f932fbf8b3a78f7e77cb42c9cc4b`, and clean parent source `7a5335017bffff35d433bdb8d475a66e50aa50f6`. The parent root had zero Git status entries and 2,867 tracked files; each independent build copy matched all 2,867 file hashes. All three wheel pairs were byte-identical. An earlier composite parent snapshot still has the recorded 7 matching / 55 different / 94 missing files against that clean root; this checkpoint is a new build from the clean root.

## Static install checks and blockers

Two fresh venvs installed the same local candidate wheelhouse offline. Static checks found all wheel payload files byte-identical after installation, verified every hashed installed `RECORD` row, and matched each `direct_url.json` wheel SHA-256. Installed `RECORD` hashes matched across venvs: base `a5184c22a1abd682436acc8f149ea0ff25b9f971474c6d4971dd5c36d72664aa`, CTP `2798c7f1de71dcc0852546d18790e804a2fea6d95703cd2ae84a79d5caff2993`, parent `3f36d89f253fd9530d4b55bb8ffcee8fcda39756d618cd1fa816eef0d888f9a0`. This was filesystem/metadata verification only; no SDK import, runtime test, `pip check`, or native load.

The clean parent wheel is version `0.15` and statically lacks `runtime_plugins`, `_ctp_credential_binding`, and `_ctp_execution_authorization`; it also lacks `ManagedCancellationReconciliationControlPort`. These do not satisfy current managed runtime/CTP source references. The wheel embeds native `.pyd`/DLL payloads, including CTP `_ctp` SHA-256 `1f46f3614feeedd20d14bbd5c4171dda25a701228e03bb14b307ca36c911f92d` and a second Cython extension SHA-256 `fb1f2551376974ed78a25b9dab6b0ac081cebbcf79c47c2b205de82bee6b9c81`. The separate CTP wheel's `_ctp` is SHA-256 `e6d4e32740646962c35d96223682f4db0f1b8082398055a88f58ed45ec1ecd78`, differing from the existing pinned native payload `468eaf9b623f684959922e3d1a2970f7f5ea71c73b7495cd533732f39672ef47`; the new candidate is A/B deterministic but does not reproduce the pin. New base/CTP wheel hashes also differ from existing code-owned pins; no parent pin is code-owned.

The build-only NumPy shim was needed because stock setup failed with `ModuleNotFoundError: numpy`; this adaptation is part of the candidate recipe. Guard logs observed and blocked `socket.bind` audit events (three per build; one per install), with no selected SDK import or outbound socket audit event observed. The hook does not monitor native loader APIs. **No native load was intentionally run.** No provider lifecycle, credential, account, order, or cancel behavior was tested.

G4 remains `NOT_ACCEPTED`; keep `NO_WRITE / LIVE_NO_GO`. Detailed nonportable local artifact: `D:\temp\iteration41-g4-clean-parent-triplewheel-20260928\REPORT.md`.

## Local evidence seal

The nonportable local candidate directory includes `SHA256SUMS.txt`, covering 87 selected evidence files: the report and machine-readable manifests/results, build/verification scripts, guard and NumPy shim/header inputs, build and guard logs, C/D and wheelhouse copies, plus installed `RECORD` and `direct_url.json` files. All 87 entries were independently rechecked with PowerShell SHA-256. Sidecar SHA-256: `354d6efa18d8f4718919fb94e97a6171758e24caef433e395d32ac3e2d83ba74`. Path: `D:\temp\iteration41-g4-clean-parent-triplewheel-20260928\SHA256SUMS.txt`.
