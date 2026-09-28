# Corrected guarded Runtime rerun

Result: 2010 passed, 30 skipped, 14 exact nodes deselected, 2 xfailed, 0 failures, exit 0 (108.14s). JUnit records 2042 executed cases, zero failures/errors, and 32 skipped outcomes. The 14 excluded nodes are in `deselected-nodeids.txt`; they are the CTP-import cases that were guard-blocked in the preceding diagnostic.

The guard recorded 32 process logs, 1 blocked `bt_api_ctp` import event at optional-import collection, zero loaded native modules, and 0 network/DNS events. This is a guarded Runtime subset with explicit CTP-import exclusions, not full Runtime acceptance or SDK/native/provider acceptance.
