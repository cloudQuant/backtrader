# Independent G1 R10-r1 inert Windows QA receipt

Status: independent offline/fake review only. G1 remains CLOSED; no hard-deadline or shutdown acceptance is claimed.

## Frozen provenance

- Candidate directory: D:\temp\iteration41-g1-r10-r1-deadline-shutdown-20260927
- Candidate manifest SHA-256: 88ec781edc1e6c1155ff993cd4fbb7260791386a133080a674aab9330ebf341e
- Canonical author evidence ZIP SHA-256: 79e761efa7720cf377f2febea09782ac66f17e4dae4f14da5d270364cc4ddc60; all 31 entries passed ZIP CRC. Its 29 indexed payload members matched the index and exact hashes.
- Final R10-r1 source SHA-256: dfbe509e030906eebfdd4345cafda453f9ebfee817bfd32df32e10d607a57186; baseline R10 source SHA-256: 4f16dc02d960488e1d36dc9a0cc48d8d3a273630fa504c21de9894869fe01ef3.
- Frozen final-trials SHA-256: 4461d54bf0d938e6d7d2b0c5e40272b04f230d1085d2c9cfb710fe122e16f920.
- Test runner SHA-256: 5360b235b7d0046696512e9840ee9a5c1695716328f508fcfc88e08a906cb9ee; R10 backend/watchdog harness SHA-256: 6871645b9cecf3fd6d8d0d3520776814d4dc3ab683d6a09d8424146a39ddef7b. These files were extracted from the verified archive; neither was edited.

## Runs

1. In an isolated extracted copy, exact command python .\run_r10_r1_trials.py completed with exit 0: 15 checks, 0 failures. The runner rebuilt the EXE from frozen source using its local MSVC helper. Rebuilt EXE SHA-256: 371b5e839bb7a69b4482dfb7f4482839aab3e4618be2928e72c76db61482e15f; it differs from frozen ZIP binary SHA-256 829d7956c1acd2c70184d549bfcff39d4f107881189f256b83becebaa26368aa. Source stayed at dfbe509e030906eebfdd4345cafda453f9ebfee817bfd32df32e10d607a57186; compiler/linker provenance is insufficient to claim byte-reproducible output.
2. Against the untouched, hash-verified frozen EXE (829d7956c1acd2c70184d549bfcff39d4f107881189f256b83becebaa26368aa), the exact candidate harness ran through a separate QA-only no-rebuild shim. It completed 15 checks, 0 failures. Trial JSON SHA-256: 9c89f6d18570818424deb8adecf17a87bdffc1c4a0f36e6b3540070062747bf8.
3. Targeted inert probes: outer-job stuck mode observed active count 4 to 0 after successful TerminateJobObject in 16 ms; a synthetic invalid parent PID forced outer job-control duplication failure (exit 81) and emitted only R10_OUTER_SETUP_FAILED duplicate, with no supervisor or R10_READY. Scripts and raw outputs are included.

## Findings and limits

- Deterministic admission probes use one QPC domain: D-1 tick accepts; D and D+1 reject before slot mutation; claim/publication races crossing D poison/UNKNOWN. Live late-admission results are recorded per binary: source-rebuild trials started at D+2 and returned at D+8 / D+9 QPC ticks; pinned frozen-artifact trials started/returned at D+61/D+68 and D+3/D+10 ticks. At 10 MHz all starts and returns were post-deadline by microseconds. Every call returned EXPIRED without a ticket or worker submission. These are narrow harness observations, not a hard caller-return SLA.
- In the hash-pinned artifact run, P05 ticket UNKNOWN was D+12.878 ms and caller observation was D+28.725 ms. Writer was pending at UNKNOWN, later completed, and broker Job reached empty. The source-rebuild run also observed caller UNKNOWN after D (D+6.997 ms). Thus the caller may receive UNKNOWN after D.
- Cancel-stall injection skips the CancelIoEx call; it is not a real Win32 API failure. The source-rebuild run retained pending writer/context and broker Job active=1 until outer Job teardown. The artifact run had caller UNKNOWN at D+1.599 ms; broker controls stayed retained.
- Join-stall reports writer completion, then parks its thread. The broker's 100 ms writer join wait times out; broker Job stays active=1 and controls are retained. Caller UNKNOWN was D+14.471 ms in the pinned-artifact run and D+21.215 ms in the source-rebuild run. Outer Job teardown kills the retained process tree and reaches active=0; this is fixture cleanup, not normal shutdown proof.
- Caller-death trials show the broker owns pending 2 MiB overlapped pipe I/O after the caller is killed; ordinary cancellation completes and allows broker Job empty. Injected cancel-stall retains OVERLAPPED/event/buffer/pipe ownership while pending.
- Job-control failure coverage is narrow. The duplication-failure probe proves that branch starts no supervisor. Static source shows self-assignment failure returns before SupervisorMain spawn, but that failure was not injected. R10_OUTER_JOB_CONTROL_READY is printed before self-assignment and is not proof of Job membership. Pre-marker CreateJobObjectW/handle duplication/assignment may block before an external Job handle is available; there is no verified whole-command custodian around this synchronous setup. No CreateProcessW hang or real Job API failure was injected.
- No explicit channel-close fault or real duplicate provider receipt is tested. The harness tests one-slot duplicate submissions and a simulated late-success CAS after UNKNOWN, not an external receipt channel.
- The prior millisecond-tick mismatch is preserved in the frozen ZIP: the old driver waited against GetTickCount64 but submitted at QPC D-4,669 ticks, so that attempt was pre-deadline and correctly accepted. This was a test-clock mismatch, not a post-D acceptance.
- P14 TerminateJobObject/query/close failures, higher-custodian failure, SCM/service lifecycle, true kernel hangs, OS preemption, and whole-command setup deadline remain untested. No CTP/native provider, SDK, credentials, account, private config, network, default route, or ordinary preflight was used.

**Decision: G1 remains CLOSED.** This shows only selected inert admission boundaries and retained-control behavior under injected local stalls.
