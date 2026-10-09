# OKX M01 root helper lifecycle integration R2

This additive packet replaces the two lifecycle Gate R7 support members in integration R1 with the frozen Gate R8 source and fake test. The 19-row public M01 runtime source map is byte-identical to R1. The 26-member public source archive retains the other 24 members and carries Gate R8 under its new source/test paths.

Gate R8 writes the fixed synthetic stdout payload through `sys.stdout.buffer.write`, which avoids platform text newline translation. Root's bounded Windows reproduction (`.codex-tmp/okx_m01_fixed_stdout_windows_reproduction_20261009.py`, 1,710 bytes, SHA-256 `5125ba5fb0312598552a9e8cfaadaa9a9b13437ab6c600afb1dc8921691b0310`) observed text output translated from LF to CRLF and binary output preserving LF. That reproduction establishes the behavior for the fixed synthetic bytes; it does not recover or prove the exact bytes from the prior actual Gate child.

The caller R5 accepts one successful process wait without a fallback wait only when the bounded final Job observation is zero, or a successful fallback wait with final zero. It still rejects nonzero final Job count, failed waits, uncertain cleanup, output mismatch, changed source bindings, incomplete pipe EOF/drains/joins, or nonempty registries.

## Source pins

- `source-map.json`: 2,877 bytes, SHA-256 `07f0eb60d60f37919c75cc3ec6833b41653fdbc9952c8478dbbc36ba0cda1ff3` (identical to R1).
- `source-index.json`: 9970 bytes, SHA-256 `865e93b85e6811d81b58bc876c9cc6883b76d2e619725836f0737a43031417b0`; 19 runtime rows and 26 public archive members.
- `source.zip`: 152448 bytes, SHA-256 `55ff96b74f1d4406050ff0cd7f8cc3f9686ea17d2c16963206077cf598850877`.
- Gate R8: 75279 bytes, SHA-256 `c8e6a4caab04d1c813f20036bed231e5d124ad1224227e25a019d8c9bbfca08f`.
- Gate R8 fake test: 29972 bytes, SHA-256 `15c0f97ca1403edbdcd8d3d04c8536aeff1495113fa94a61c1d9c654a5bdb035`.

## Scope

This is public source/fake evidence only. No actual gate, retained host, native API, account/provider, private document, environment file, or software payload was read or invoked in this work. The Root owner alone controls any future one-shot actual gate and normal custody close.

## Source-fake QA

The prescribed focused suite passed 45 tests with exit 0 and two expected `PytestCacheWarning` cache-path warnings under `-c NUL`. See `qa-command.txt` and `source-qa-result.json`. Static checks also passed: `py_compile`, Black `--check` (Python 3.11, line length 100), and Ruff. These results cover Gate R8 and caller R5 fake leaves only.

Frozen reviewed candidate pins for this packet:

- Gate R8 source: 75279 bytes, SHA-256 `c8e6a4caab04d1c813f20036bed231e5d124ad1224227e25a019d8c9bbfca08f`.
- Gate R8 test: 29972 bytes, SHA-256 `15c0f97ca1403edbdcd8d3d04c8536aeff1495113fa94a61c1d9c654a5bdb035`.
- Caller R5 source: 77188 bytes, SHA-256 `65f0cac34348f992ff960954cc31c24ed339dffb7ae1e3feee336798d15c4fcd`.
- Caller R5 test: 41797 bytes, SHA-256 `7be7b0eb8357129b1fd5ba4e88bd2f606280a2069ef95de277c12d9b8fbfd2e3`.
