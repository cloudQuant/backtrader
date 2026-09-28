# Provenance correction addendum

The original independent QA report and receipt correctly identified a mismatch in the r1 manifest's `r0_candidate_base.git_commit` field. The corrected candidate manifest is `../candidate/candidate-manifest-r1-corrected.json` (SHA-256 `39f4922be5ed43bc021b0813ae84ef0e99fa2b8c5c2e0352b6a3a595502bffd9`).

The r0 repository HEAD was independently confirmed as `103facd51aebf2e47cccb2d22640dec091d23030`; `103facd` resolves to a commit and `213574e` is absent from that repository's object database. The corrected manifest now records `103facd` and a correction note. Its prior manifest SHA-256 was `ff9b2ac5e8e688c10fb22d95328b923d8f4c7dc972db2068c1a6106d5254f7ef`.

Independent recheck by `g1_host_qa` found only the provenance fields changed. Patch SHA-256 remains `339c8450722f18c9061d4960377ca0939032c2dc7f0453592d05674f18f093a4`; author JUnit SHA-256 remains `79fe3a868619062271fbbd8c0c0d02f4d8a0bcee9b704a4261c8404630a5cc27`; all four target payload hashes remain unchanged. Tests were not rerun during this metadata-only correction; the independent 28-test and 5-test adversarial results remain bound to unchanged code/test bytes. See `correction-receipt.json` and `verification.txt` for the independent pointer check.

This correction changes provenance metadata only. It does not strengthen the evidence into an authenticated snapshot, migration tool, account authority, or trading authorization.