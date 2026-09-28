# Independent QA — CTP preflight supervisor review

**Verdict: `NO_GO_IMPLEMENTATION_FOR_CURRENT_G1_WORDING`. G1 remains CLOSED; ordinary 013_3 preflight remains fail-closed.** This review did not modify the main tree or the author package.

## Package and source integrity

- `qa-package.zip` SHA-256: `3ef6d18f4ce3e1f2f28391176c75706acf2e7018a6ea6c0ac66c2605fb9d2b67`. ZIP test passed. All 29 manifest payload paths, byte counts, and SHA-256 values match. The 30th ZIP member is the self-describing `qa-package-manifest.json`, not an undeclared code payload.
- Package manifest SHA-256: `a1495a4e01c7134472696d94521e8608cd906047eb7b4d79ee07fcfec6853060`; source manifest SHA-256: `5bed3eb4197f25ea79af58b5d06801c004f65112e249ec346d91f3cd409fc654`; README SHA-256: `eac8cc77123be84bfc59f4452836f843e558cbdbc26f1d2bf1fc8d68e1e89f7b`.
- All 15 frozen source-manifest records match their archived copies. The three README-cited evidence hashes also match. See `package-verification.json`.

**Replay completeness limit:** the ZIP is not self-contained for these test runs. The frozen inert supervisor imports `scripts/ctp_i13_i15_windows_guardian.py` and launches sibling `scripts/ctp_i13_i15_inert_parent.py`, but neither is among the 29 payloads/source-manifest records. The CLI test also imports runtime support modules outside the manifest. For the rerun only, I copied the missing `.py` support sources into an isolated `replay` tree from the current main tree; the two direct supervisor helpers hash to `70FAA6DA08B6CEAA0D2B618ACECDD5B62E72E77133BA0B61E19558DB79150641` and `FD0A0E35EA34A2C3BE9FC26902AEA49593A470E3025C1AA9DD8798B3ED025117`. The replay-source manifest records all 105 supplemental runtime/script Python files and confirms their copied bytes. The four test modules and the 8 manifest-listed code modules used by replay are exact archived bytes. Main-tree test files were not used after the concurrent Ruff-format notice.

## Inert verification rerun

On CPython 3.11.5, with pytest plugin autoload disabled, I reran the three archived supervisor test modules and the archived CLI gate test in a separate temp copy. The supervisor suite passed **65/65**; the ordinary-preflight gate passed **1/1**. The pytest-process SDK import and socket guards logged no attempted accesses. The replay contained no `.env` or `config.yaml`; the CLI test itself traps config loading, credential resolution, socket creation, and CTP import before asserting zero touches. Process tests use fake Win32 APIs plus local inert Python children/Job operations; they do not exercise CTP SDKs or provider sessions. Results and JUnit are hash-bound in `hash-index.json`.

Three preliminary staging runs are retained: the first could not collect because the ZIP omits the Windows guardian helper; two later full-suite attempts each timed out in five inert-chain cases while waiting for setup JSON. The exact cause of those timeouts was not established. A subsequent complete rerun passed 65/65. Treat that result as one local inert observation, not a hard-time guarantee.

## Whole-command `D` blocker graph

- The current ordinary CLI gate in frozen `backtrader_runtime/cli.py:1485-1497` rejects the registered 013_3 private preflight with `ctp_simnow_preflight_supervisor_required` before config, credentials, SDK, or provider/network access. The focused CLI test confirms this fail-closed behavior; dispatch is later at `cli.py:1552-1565`.
- The strict G1 wording includes the outer CLI process launch and Python bootstrap. The frozen R11 audit requires trusted monotonic `T0` before the externally visible launch; a newly started CLI cannot timestamp before its own `CreateProcessW`. A READY-before-request service would move `T0` to request admission and therefore be a **requirement change**, not fulfillment of current G1.
- Once running, the proposed watchdog makes synchronous backend calls on its custodian thread. `outer_watchdog.py:446-447` invokes `create_suspended_in_job`; `windows_job_backend.py:924-937` calls `CreateProcessW`, and the explicit comment at `1017-1020` says this call cannot be interrupted by its Python caller. If it blocks, the deadline checker cannot return at `D`.
- Cleanup has the same boundary: `TerminateJobObject` at `windows_job_backend.py:481-488` requests termination but is not exit/Job-empty evidence; the watchdog then polls process exit and Job emptiness and synchronously releases controls (`outer_watchdog.py:348-420`, `windows_job_backend.py:439-534`). Query, wait, terminate, and close calls have no proven bounded return in this package. Adding a service/reaper moves the highest synchronous custodian; it does not remove that last-custodian problem.
- The read-only CTP shutdown path also calls `stop_and_wait(timeout=...)` or `stop()` synchronously (`ctp_sdk_readonly.py:148-180`) and later joins a Python thread (`236-263`). A timeout argument cannot bound time spent before the call returns or prove a native call was interrupted.

A prewarmed, READY service could be considered under a separately approved **request-only cooperative SLA**, with `T0` at request admission and `UNKNOWN` on late/missing evidence. That cannot be labeled whole-command G1 and does not justify enabling ordinary preflight. For current wording, retain `NO_WRITE` and `LIVE_NO_GO`.

## Artifacts

- Package verification: `package-verification.json`
- Staged source coverage: `replay-source-verification.json`
- Guard result: `guard-summary.json`
- Replay logs/JUnit: `supervisor-complete.*`, `cli-gate-complete.*`
- Integrity index: `hash-index.json`
