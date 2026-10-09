# M01 Gate R8 / caller R5 Root driver R2 draft

Status: **prepared, unexecuted, source-only**. R2 is additive; the R1 driver and preparation-r3 packet remain unchanged.

## Frozen pins

- Root driver R2: `.codex-tmp/okx_m01_r8_r5_root_driver_r2_20261009.py`, 29,420 bytes, SHA-256 `ddee4f2eb6058c61b0c2ef69964d33fdca82a85ead733e272d391f6f41d3d369`.
- Candidate manifest R4: `candidate-pins.json`, 8,232 bytes, SHA-256 `7afb872549da80766d1b3959bb0162e44776046f6be895a573c60c544e89dc6c`.
- R8/R5 independent review: 4,284 bytes, SHA-256 `ea34c7cfd87d20491fe0530d0d0a9613c725e4a9aee1f630ff5cc1e743800246`, verdict `GO_SOURCE_FAKE_ONLY`.

The candidate R4 manifest was copied from preparation-r3 with its only byte change being `checkout_head`: `716ca992dd8a05d7d997d25cd667f212eae5bb1c` to `e0b45398f7f7ff8fcae7931b1fbb28886ee05d7b`. It retains the same 31 public pins, three software descriptors, source-map/index/ZIP pins, review pin, gate/caller/test identities, and output names.

## Driver delta from R1

The driver R2 changes only the candidate packet directory, expected HEAD, candidate manifest digest, and pre-call Git helper. The helper invokes the fixed executable `C:/Program Files/Git/cmd/git.exe` with `-C D:/source_code/backtrader` and `-c core.fsmonitor=false`. It passes an explicit environment containing only available `SystemRoot`, `WINDIR`, `PATH`, `TEMP`, `TMP` values plus `GIT_OPTIONAL_LOCKS=0`, and rejects any inherited `GIT_*` variable. Git checks occur before `caller.run_one`; there is no Git or subprocess call afterward.

The one-use output namespace remains `iteration41-okx-m01-r7-five-module-root-gate-actual-r5-2026-10-09`. Its freshness is checked by the driver precheck. The receipt leaves post-call Git verification `PENDING_OUTSIDE_HOST` and does not permit host exit.

## Verification and limits

A source-only check parsed the R2 driver, confirmed the R1 driver and candidate pins were unchanged, and verified that the preparation-r4 candidate differs from preparation-r3 only in `checkout_head`. No tests, driver precheck, Git command, software payload read, private input, native call, provider/account operation, actual invocation, staging, or commit occurred. Root supplied the current HEAD binding; I did not query Git.

The upstream R8/R5 review and 45-test source-fake result do not review or execute this Root driver. Root must complete a separate static review and perform any outside-host post-Git attestation before making a host-exit decision.