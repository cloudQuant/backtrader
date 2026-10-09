# OKX M01 R8/R5 Root driver R2 independent static review

Decision: `GO_STATIC_REVIEW_ONLY` for the frozen R2 driver bindings. This review is limited to public driver source and public pin metadata. It does not authorize or record a driver invocation, native operation, account/provider access, or M01 case acceptance.

## Frozen inputs

- R2 driver: `.codex-tmp/okx_m01_r8_r5_root_driver_r2_20261009.py`, 29,420 bytes, SHA-256 `ddee4f2eb6058c61b0c2ef69964d33fdca82a85ead733e272d391f6f41d3d369`.
- Preparation R4 candidate manifest: `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-r7-five-module-root-gate-preparation-r4-2026-10-09/candidate-pins.json`, 8,232 bytes, SHA-256 `7afb872549da80766d1b3959bb0162e44776046f6be895a573c60c544e89dc6c`.
- Preparation R4 README: `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/iteration41-okx-m01-r7-five-module-root-gate-preparation-r4-2026-10-09/README.md`, 2,493 bytes, SHA-256 `8fddb8f584957c7eb777dd7849c33b0bb3fbd090b627e468d814cc4608366791`.
- R1 comparison baseline driver: `.codex-tmp/okx_m01_r8_r5_root_driver_r1_20261009.py`, 28,993 bytes, SHA-256 `5924ffb8aa829167fa8645376ecf850969c22772208f930197ff7870e3334ad2`.

## Static findings

The R1-to-R2 driver diff is limited to the candidate packet directory, expected checkout HEAD, candidate-manifest hash, and the pre-call Git helper. The candidate R3 and R4 manifests are equal after replacing only R3's `checkout_head` with R4's `checkout_head`. R4 binds `e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b`, matching the R2 driver's expected HEAD and candidate-manifest pin.

The candidate manifest contains 31 unique public pins and three software descriptors. The driver's expected software and review descriptors match the manifest. The R2 driver pins the integration source map, index, and ZIP to the manifest's declared paths, sizes, and hashes. Its precheck validates 19 mapped runtime rows, 26 unique indexed archive members, the exact member set, relative member paths, and every archive member's declared byte count and SHA-256. The 31 public rows are checked against the 26 indexed paths plus five separately bound support paths. I did not read software payload bytes or open/extract the source ZIP.

The Git helper uses the fixed executable `C:/Program Files/Git/cmd/git.exe`, an explicit repository `-C` path, and `-c core.fsmonitor=false`. It constructs a minimal subprocess environment from the allowed system/path/temp variables plus `GIT_OPTIONAL_LOCKS=0`, excludes inherited `GIT_*` settings, and fails if Git emits stderr. Before the one-use call, the driver checks branch, expected HEAD, empty index, pinned inputs, and fresh output paths. Static inspection found no Git or subprocess calls after `caller.run_one`; post-call Git verification is explicitly pending outside the host, and host exit remains disallowed by the driver receipt.

One non-blocking concurrency consideration remains: `.codex-tmp/okx_m01_r7_r5_root_actual_20261009.json` is checked absent during precheck and later written with `write_text`, which is not an exclusive create. If simultaneous duplicate invocations are in scope, reserve that result path atomically. This does not block the stated one-use review scope.

## Review boundary

The driver was not executed, and no tests, Git commands, software payload reads, private-input reads, native calls, or account/provider operations were performed. This is a static driver review only; it does not establish a successful Gate run, cleanup, host exit, provider/account result, or formal M01 PASS. Any actual invocation still requires the exact expected checkout HEAD and a separate outside-host post-call attestation.
