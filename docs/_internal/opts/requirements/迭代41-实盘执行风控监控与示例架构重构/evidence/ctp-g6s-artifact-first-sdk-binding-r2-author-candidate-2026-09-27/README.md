# G6-S artifact-first SDK binder R2 author candidate

Status: **AUTHOR_CANDIDATE / NO_G4 / NO_G6-S**. This is an evidence-only
archive of the isolated R2 candidate. The main production tree, default route,
and default artifact pin were not changed.

- Candidate source manifest: `candidate/candidate-source-manifest.json`
- Manifest SHA-256: `4ee9f0258b6b2e575fb2039fe3f31a049d918f2f86f3c5707365d3d37e48b916`
- Freeze receipt: `candidate/freeze-receipt.json` (SHA-256 `624ba96440e9099dc667fe840b5d73b0fac8aec28d88355506302fe5944b90ee`)
- Raw candidate ZIP: `artifact-first-r2-loader-identity-candidate.zip` (SHA-256 `dbbcbd8a5de4daf5265ae10b5eb114cbd6b2a429dc4ff9535aca5c3de8779d14`)
- Focus JUnit: `candidate/evidence/r2-loader-identity/pytest-focus.junit.xml` (52 passed, 0 skipped)
- R1→R2 source delta: `candidate/evidence/r2-loader-identity/source-diff-from-r1.patch`
- CPython loader source note: `candidate/evidence/r2-loader-identity/cpython-extension-loader-source.txt`

R2 adds fail-closed identity checks for ExtensionFileLoader and the captured
import path after gate and during retained `.pyd` hashing. Fake tests reject a
substituted loader before the replacement hook runs. CPython 3.11.5's standard
ExtensionFileLoader still takes `(name, path)` and delegates through
`_imp.create_dynamic(spec)` / `_imp.exec_dynamic(module)`; no same-handle OS
image-load proof is claimed. No actual SDK/native module was loaded. No approved
wheel, external pin, or deployment trust root exists. The default remains
fail-closed; **NO_G4 / NO_G6-S**.

`ARCHIVE-INDEX.json` records every copied candidate file and hash. Its SHA sidecar
binds that copied inventory. The embedded R2 manifest covers 191 payload files;
the ZIP contains 193 files including the manifest and freeze receipt. ZIP CRC
and every member byte were verified before the copy. Independent QA is pending.
