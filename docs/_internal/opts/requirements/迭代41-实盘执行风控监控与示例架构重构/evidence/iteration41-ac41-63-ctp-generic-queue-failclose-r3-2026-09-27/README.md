# AC41-63 CTP generic queue fail-close r3

## Status

`MAIN_MERGE_REJECTED_BROAD_13_FAILURES`. The candidate remains an isolated,
non-authorizing proposal. Main was restored to the exact A028 Store source
preimage; r3 is not accepted and does not establish writer closure or write
authority.

Historical boundary: the A028 preimage and the MAIN_MERGE_REJECTED_BROAD_13_FAILURES decision describe the r3 rejection checkpoint only. A later r4 compatibility integration changed main after that checkpoint; this archive makes no claim about the current main Store hash. The candidate-manifest field named current_source_preimage is historical in this archive, not a current-checkout assertion. The r3 source, patch, focused fake test, and QA evidence remain in
the temp packet and are retained here as historical candidate identity only.

## Candidate identity

- Source preimage: `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`
- Proposed source target: `00D31700B8554E954C52A748E2DBA09CB781DAED403EEC82AA750D1844513F55`
- Patch: `C1550368359A159F18CE6777F6377CCA83DA7F948DE81B99D8DE86BEEE6CCAD3`
- Candidate contract test: `3201896CBC984054BB8124CBBB1489A207DB349AE6CEB74CEB701DA08F21D29A`
- Candidate manifest: `A37388BA20649D7C402E119F0E74838A45F84830BE8AC1597EFA6619F7F34D6F`
- Independent narrow QA: [report](qa/independent-qa-report.md), SHA-256 EB7A5D5A445B0DA1D7888B2AF53A6759AEF18B109F25B0A375C536E433953169.
- Broad r3 integration run: [pytest log](qa/main-broad/pytest.log), [JUnit](qa/main-broad/junit.xml), and [exit code](qa/main-broad/exit.txt). Exact source and copied hashes are recorded in [archive verification manifest](archive-verification-manifest.json).

The audited inventory rows are `i41-writer-a5104365b2d37af86d15`
(`_invoke_sdk_command`, indirect SDK writer dispatch) and
`i41-writer-716fa6d57bd60cca1c95` (`_cancel_managed`, cancel alias). Their
official status remains `REVIEW_REQUIRED / NOT_AVAILABLE`.

## Rejection evidence

The r3 Store/Runtime integration attempt reported 13 failed, 2724 passed, 43 skipped, 2 xfailed, and exit code 1 in its frozen pytest log. The JUnit aggregate records 2,782 tests, 13 failures, 0 errors, and 45 skipped (including the two xfailed cases). Eight failures were caused by r3's new early rejection
of typed managed CTP cancellation; r3 also changed the forwarding legacy
adapter's expected rejection, broke two existing budget-capability passthrough
contracts, and changed two recovery-exit dispatch-failure contracts. These
regressions require an r4 candidate and independent review before any new
integration decision.

The narrow r3 QA did verify the candidate patch replay and focused fake probes,
but that result does not override the broad regression failure. R3 must not be
represented as accepted or integrated.

## Limits

R3 did not change official writer dispositions or authorize execution. No real
API, SDK, native CTP, network, private config, account, order, or cancel was
used. The classifier snapshot and generic-fallback scope limitations recorded
in the isolated r3 report remain part of its historical evidence only.


## Archive integrity

The broad output sidecars are copied from the frozen r3 temp run and are byte-identical to their source files. The independent narrow QA report is also copied byte-for-byte. The archive verification manifest records source paths, source hashes, copied hashes, the historical Store identities, and replay limits. SHA256SUMS.txt binds every archive file except itself. Verification does not replay the candidate against current main.
