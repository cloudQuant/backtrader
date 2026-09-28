# Iteration 41 G4 triple-wheel candidate checkpoint

**Disposition: `REPRODUCIBLE_ARTIFACT_CANDIDATE / G4_NOT_ACCEPTED`.** This is an offline artifact checkpoint, not a production pin or native-provider acceptance.

## Candidate wheel hashes

| Distribution | Candidate SHA-256 |
|---|---|
| `bt_api_base 0.15.5` | `d003d66b91feba16f3c9a2f523bb4984dc1caf4b44750e44c0c406beca6837d9` |
| `bt_api_ctp 2.0.3+iteration41.i2` | `70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2` |
| `bt_api_py 0.15.7.dev0+r4r3r3.67e54513` | `e43396b1757f0a24055baa19940503ef380cab4359c4bd497c1b400d7653886b` |

Two independent guarded builds produced identical SHA-256 values for all three wheels. Two fresh venvs installed the same local candidate wheelhouse; static checks confirmed installed wheel payloads and hashed `RECORD` entries, and each `direct_url.json` wheel hash matched. Installed RECORD and direct URL hashes matched across both venvs. These checks did not import the SDK or test runtime behavior.

## Source and acceptance limits

The base and CTP build inputs came from frozen sources at commits `73e860e2fd8086ec817db254d4c396c2a76eb7d6` and `28157ce33009f932fbf8b3a78f7e77cb42c9cc4b`. The parent wheel used a manifest-bound 156-file composite snapshot. The current clean parent checkout does **not** match that snapshot: 7 files match, 55 differ, and 94 are missing. Therefore the parent wheel is not established as a rebuild from the current clean source root.

These hashes also do not match the existing code-owned base pin (`1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d`) or CTP pin (`988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff`); no parent wheel pin is currently code-owned. The rebuilt CTP `.pyd` differs from the old pinned native payload. No CTP SDK/native import or native-load call was intentionally run, and no provider start/stop/join/release lifecycle, credentials, account activity, order, or cancel was exercised. Guard logs show only denied local `socket.bind` calls; no forbidden Python import or outbound socket audit event was observed. The Python audit hook does not monitor all native loader APIs.

No code-owned pin or runtime route was changed. Keep G4 `NOT_ACCEPTED` and writes `NO_WRITE / LIVE_NO_GO`.

Detailed logs and machine-readable checks remain in a **nonportable local artifact**: `D:\temp\iteration41-g4-triplewheel-deterministic-candidate-20260928\REPORT.md`.
