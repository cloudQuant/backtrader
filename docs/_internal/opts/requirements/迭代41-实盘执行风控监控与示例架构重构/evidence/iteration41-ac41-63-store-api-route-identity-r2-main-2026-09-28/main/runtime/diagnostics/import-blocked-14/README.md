# Initial guarded Runtime diagnostic

Raw result: 2010 passed, 30 skipped, 2 xfailed, 14 failed, exit 1. The 14 exact cases were blocked when explicit CTP imports reached the tripwire. This was a guard-policy diagnostic, not 14 code regressions and not 14 passes. The raw JUnit and 31 per-process guard logs are retained. The subsequent corrected run excludes the same 14 nodes and is separately preserved; neither result establishes full Runtime or SDK/native acceptance.
