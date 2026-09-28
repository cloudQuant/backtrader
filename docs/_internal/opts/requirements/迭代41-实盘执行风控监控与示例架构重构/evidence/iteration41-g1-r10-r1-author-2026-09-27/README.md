# Iteration 41 G1 R10-r1 evidence index

**Status: author-only inert Windows prototype; G1 remains CLOSED.** This archive contains no production route changes.

The final Windows run recorded 15 checks, 0 failed. Frozen R10 source and trials were copied byte-for-byte and their SHA-256 values match the known frozen values. R10-r1 source SHA-256: `dfbe509e030906eebfdd4345cafda453f9ebfee817bfd32df32e10d607a57186`. Final trial SHA-256: `4461d54bf0d938e6d7d2b0c5e40272b04f230d1085d2c9cfb710fe122e16f920`. Candidate manifest SHA-256: `88ec781edc1e6c1155ff993cd4fbb7260791386a133080a674aab9330ebf341e`; receipt SHA-256: `f9c642657a06ddaa0752c539ea169caab46920e3a3f1f42db0bc0c9db8717aac`.

The deterministic QPC cases reject at D and D+1 ticks, poison claim/publication races crossing D, reject reuse of a poisoned slot, and produce one ACCEPTED / seven BUSY outcomes from eight concurrent submitters. Repeated live late admissions began at D+3 QPC ticks and returned EXPIRED with no ticket or worker.

Observed broker UNKNOWN / caller terminal timings were P05 D+1.1751ms / D+1.1799ms, cancellation-stall D+0.2095ms / D+15.4565ms, and join-stall D+12.3462ms / D+27.0124ms. All caller terminal observations were after D; these are explicitly **not** hard-D passes. Cancellation-stall and join-stall reports retained broker/supervisor controls with broker Job ActiveProcesses=1. The outer test Job killed three remaining fixture processes after those reports and reached zero; that teardown is not proof of normal cleanup.

The preserved earlier failed harness run used a millisecond-tick delay against the QPC deadline and invoked at D−4,674 QPC ticks; it correctly returned ACCEPTED before D. The harness was corrected to use the same QPC D. See the raw trial JSON and failure note in `payload/`.

P14, SCM/service behavior, true `CreateProcessW` kernel hangs, a higher custodian, and a hard whole-command D are unproved. The test D starts at a GO barrier after launch and synchronous prewarm. The cancellation failure is injected by skipping `CancelIoEx`; it is not a real Win32 failure. No CTP/native/provider, credentials, private config, account, SDK, network, or default preflight was used. Ordinary CTP preflight remains closed.

## Files

- `payload/r10_custodian.cpp`: isolated R10-r1 source.
- `payload/r10_r1_trials.json`: final 15-check trial record with per-scenario QPC values.
- `payload/R10R1_FINDINGS.md`: detailed findings and limitations.
- `payload/r10_r1_manifest.json` and `payload/r10_r1_receipt.json`: hash-bound candidate receipt.
- `payload/r10_r1_trials_failure-late-admission-tick-mismatch.json`: preserved failed harness run.
- `payload/R10_BASELINE/`: byte-for-byte frozen R10 source, trials, manifest, receipt, findings.
- `r10_r1_author_evidence.zip`: raw archive of this README, index, and `payload/`.
- `SHA256SUMS.txt`: hashes for every canonical file, including the ZIP.

G1 and the ordinary preflight remain closed.
