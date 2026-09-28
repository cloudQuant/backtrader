# Parent R4 + R3r3 composite QA

- Snapshot: `iteration41-parent-r4-r3r3-composite-20260927-r1`
- Source manifest SHA-256: `751717a2ec7a579f2823fbdc93036a65063f0dd3c3cfc9227dd8ff55161bf131`
- Parent fake issuer/control focus: **44 passed**, 0 skipped.
- Main bridge original nodes: **3 passed**, 0 skipped.
- Main bridge five-file focus: **73 passed**, 0 skipped.
- Additional main cancellation-control file: **20 passed**, 0 skipped.
- R4 implementation retained; R3r3 source and unmodified tests preserved under `provenance/r3r3-original`. Only test/fixture adaptations are present in the candidate, with unified diffs under `provenance`.
- Source-origin/native/network guard recorded no rejection, native import, non-loopback network attempt, or protected-config read in successful runs. Imported packages were parent, base, execution, risk, and monitor from the explicit map.
- Parent package still says `0.15.5`; this composite has unique source bytes under that occupied distribution version. No package version, default pin, wheel, or production route was changed. **Release remains blocked.**
- Initial flattened-overlay setup failure is retained in `main-three-r1.*`; corrected exact reruns pass.
- Ruff: selected EFI check reports three test import-order findings; default source check reports two existing `S110` findings in `cancellation_control.py`. No frozen production edits were made.

See `commands.txt` for exact run commands/environment. See `composite-source-manifest.json` for source identities, package hashes, JUnit/log hashes, guard counts, source-only metadata versions, and limitations.
