# V18 Root driver R2 independent review

Verdict: GO_SOURCE_FAKE_ONLY. The final R2 pins were rechecked: driver 4165e23f8f9ebb429df7cac4f26482d4a68383fb1c898661bcf8a21b0eaf2b4a and pins 20b5bca15b9b4d3f6e8f6ef8bb253d3ce7fae7fffa9f06a08c5bca5845b1d359. All 29 public source rows matched the candidate snapshot and current repository, all 18 packet rows and pins matched, and the physical candidate packet contained exactly the 48 declared files. The 29-entry V18 activation map matched the current pinned V18 packet and every candidate source row.

The R1 public diagnostic copy and current public observation file both matched the bound hash. The diagnostic reports a pre-wrapper held-map shape failure at 29 expected public rows versus 31 actual held rows; its follow-on recovery reports all 31 hashes verified, original CUv2 postverify completed, and zero retained references. This supports the bounded R1 failure description only.

R2 builds a normalized expected map from 29 public source pins plus the two exact software pins, rejects public/software path overlap, and requires exact held keys and byte hashes. The dedicated positive fake test yields 29 synthetic public entries plus two synthetic software entries, checks the 31-entry union, invokes the fake wrapper, and verifies normal manager exit and postverify. Negative tests cover software hash mismatch, missing and extra software paths, and normalized overlap. A valid-hold pre-wrapper error exits once and postverifies; an unentered context is not exited; uncertain wrapper cleanup retains the same references and cannot publish PASS. The pinned public CUv2 source snapshot independently shows its public/software pin union and ExitStack scope behavior. These are source/fake checks; no actual CUv2 hold was created.

The focused isolated suite passed 25 tests with one existing PytestConfigWarning. It used the designated source-QA interpreter with isolated flags, plugin autoload disabled, PYTHONPATH removed, and a fresh repository-local basetemp. No actual Root activation, account, provider, native SDK, WinAPI, or production process operation was run. No private input was read.

The driver only reports a profile result. Official C01 PASS remains 0, and actual Root/provider/native acceptance is NOT_RUN. The fake result does not establish physical custody or provider behavior.

## Review artifact pins

- review.json: 73c5f2386a1f37c8fef13bf0d0699cb0509a6837a8c9221e0f4f9a5a2f82f800
- review-bundle.zip: 5c3133b33bd9e0f3c9fb097b3326864750906118a2f13611e4c31083457f5e5d
- review-index.json: 602c21b58ac089be9ad47cd166f197337b17310d8bbb0137163595faa6b9f054
- review-checkpoint.json: 4545ab68f7875b7c40fe94a0fe606a8da505e5934dd2a3c63d9ea250c7685c28

The 55-entry ZIP includes all 29 candidate source payloads, all 18 packet payloads, pins.json, this independent review and QA record, the pinned public R1 observation and current V18 activation pins, and the sanitized public CUv2 source snapshot and metadata.
