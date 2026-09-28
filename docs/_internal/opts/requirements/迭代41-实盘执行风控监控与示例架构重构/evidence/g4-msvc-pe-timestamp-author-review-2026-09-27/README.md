# G4 MSVC/PE timestamp author review evidence subset

This compact evidence subset was copied from the frozen offline workspace
D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927. The controlled
build comparison is author-side review. A separate read-only archive/binary
review is now attached under independent-qa/. Its initial report found the
stale README hash in the nested manifest; the recheck receipt records the
correction and verifies the corrected archive. The independent review did
not run builds, install wheels, load SDK/native binaries, or access providers.

See the [author report](REPORT.md), [PE timestamp analysis](pyd-pe-analysis.json),
[PE section comparison](pyd-section-diff-summary.json), [checksum index](SHA256SUMS.txt),
[initial independent QA report](independent-qa/initial-qa-report.md),
[initial QA results](independent-qa/initial-results.json),
[recheck receipt](independent-qa/RECHECK-RECEIPT.md), and
[recheck results](independent-qa/RECHECK-RESULTS.json).
original-SHA256SUMS.txt preserves the original 64-entry checksum catalog.
The original verifier reported 64 entries and zero errors; its receipt SHA-256
was f17abc08b8358d77ba4387d664fd5814c6412ccee9878d0403e72fa03aabd6cf.

The report identifies six PE timestamp byte differences at 0x120..0x122
(COFF TimeDateStamp) and 0xa26c54..0xa26c56 (the sole type-13 POGO
IMAGE_DEBUG_DIRECTORY timestamp). Both fields hold duplicate timestamps.
All other bytes in the compared pinned and historical non-/Brepro .pyd
images match. The controlled strict C build reproduces the same six-byte
delta. The /Brepro A/B wheels match each other but differ materially from
the pinned image.

Wheels, native .pyd binaries, the 175 MB source tar, expanded source/build
trees, virtual environments, caches, and the 17 MB expanded controlled summary
are intentionally not copied. Their original paths and hashes are recorded in
canonical-subset-manifest.json. This subset does not reproduce the excluded
build outputs by itself.

Disposition remains PE_TIMESTAMP_CAUSE_IDENTIFIED / NO_EXACT_PIN_REBUILD /
NO_G4_ACCEPTANCE. Evidence is offline only; it is not an installed triwheel
closure, native session test, provider test, or production acceptance. No pins
or production routes changed.

SHA256SUMS.txt covers every file in this subset except itself.
## Time-control follow-up

The isolated source-build control audit is in [RESEARCH.md](time-control-study/RESEARCH.md).
It records the local linker help in [link-help.txt](time-control-study/link-help.txt),
inert wheel/PE byte comparison in [timestamp-comparison.json](time-control-study/timestamp-comparison.json),
and its replay implementation in [compare_pinned_wheels.py](time-control-study/compare_pinned_wheels.py).
The [replay output](time-control-study/wheel-byte-replay.log) and
[source checksum receipt](time-control-study/SHA256SUMS.txt) are also retained.
That author-side audit found no supported timestamp setter in the inspected
MSVC interface and did not run another build. The separate second-agent review
covered archive integrity and inert PE comparison; it did not re-run a build.
The nested study checksum receipt covers its seven payload files; this parent
SHA256SUMS covers all files here, including the nested study.

