# M01 R4 source-close / R3 Git attester static review

Decision: `GO_STATIC_SOURCE_ONLY` for the bounded normal source-scope close, subject to Root using the reviewed local Git environment. This is not an M01 PASS, provider/account acceptance, or permission to exit the Root host.

## Reviewed exact public pins

- R4 close helper: `.codex-tmp/okx_m01_r7_r4_source_scope_normal_close_root_20261009.py` — 31,084 bytes, SHA-256 `ed7ccb5f54c8b0c13eb6483d1a6cbbcf78731b2783ffa3fb1971655926b199df`.
- R3 outside-host attester: `.codex-tmp/okx_m01_r4_outside_git_attestation_root_r3_20261009.py` — 4,832 bytes, SHA-256 `fc7fd837124c799d82d3085a2e95a337da7230dc6d3dcc0fc72906826a82d281`.
- Prior R2 attestation, which R3 verifies and preserves: `evidence/iteration41-okx-m01-r7-five-module-root-gate-actual-r4-2026-10-09/root-git-attestation-before-close.json` — 2,556 bytes, SHA-256 `2db029f905d6f413b6762f1271fb7dd8ef3a8703879b2caed6562d64d7311227`.
- R4 sanitized observation: 3,565 bytes, SHA-256 `504539719ebc67350de6f1c1bfc2ba3da8b9709c4de668aec149f1dbc39ac689`.
- Attestation-bound source rows: Root driver `3520ea0515e2f1fef8e4e70c4e495436cce13d60c1062977c1a22c7c44590f01`; caller `c081b85b553c3600b3949d1da33d4449b047fa5668d1b7e3ab9426388cf30451`; caller test `d4a42fecb701c3e371798a22db59a3060036d96adb07abaefb2d8669cc2e9741`; CUv2 snapshot `e856be8e4056835d4a7e54f5c6b449c69ab3f1c2ebb049bcbcc1c95a9ad3f246`; candidate manifest `8a84e0bb29e2aabf3338078b66e3e44ef13428b3c334c505300cbf1334486e12`; caller review `61887b6d14b5f93ef9ea2a3f8f901cf437916bd9dd9a1ee3e716e4f36f580fbe`.

## Static findings

R3 invokes the fixed Git executable by absolute path, fixes `-C` to the repository, disables `core.fsmonitor`, and supplies a deliberately small child environment. It rejects any inherited `GIT_*` override other than `GIT_OPTIONAL_LOCKS=0`, and requires the expected `dev` branch, HEAD, and empty index observations. It validates the exact seven public source rows, observation nonce, and held-map digest required by the R4 helper. Before writing, it checks the prior receipt’s exact size/hash and absence of the preservation target, renames that receipt to a distinct preserved filename, and uses exclusive creation for the new receipt.

The R4 helper validates the canonical 10-key attestation shape and exact host/repository/nonce/map/source bindings before the close. Its one-shot record is set before calling the original CUv2 generator context’s `__exit__(None, None, None)`. It checks the normal return, closed generator, unchanged blocked result and retained row, module/function bindings, and public source hashes. CUv2’s original exit performs its own public and software-pin postchecks. The helper does not retry the Gate, close native handles, change the `OUTPUT_MISMATCH` result, or permit host exit.

The R3 attester’s `PATH`, `TEMP`, `TMP`, `SystemRoot`, `WINDIR`, the Git executable bytes, and system/user Git configuration are local-environment inputs rather than independently pinned data. The static approval assumes Root uses the fixed local Git installation and the reviewed host environment. The attestation is evidence of the bounded local Git queries only; no helper, attester, tests, or actual/native/provider path was executed during this review.

## Scope limits

The Gate remains `OUTPUT_MISMATCH`; stdout did not match the fixed expected output. The caller remains `BLOCKED`, the Python retained row remains present, and the post-close Root/Git observation plus explicit Root lifecycle decision are still separate. This review establishes no provider/account acceptance, no M01 `PASS`, and no host-exit authorization.