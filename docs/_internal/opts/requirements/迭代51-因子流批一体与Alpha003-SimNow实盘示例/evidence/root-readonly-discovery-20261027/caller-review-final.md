# I51 Root read-only discovery caller: final narrow static review

**GO for the two previously identified setup/cleanup findings.** Review was limited to those paths in `.codex-tmp/i51_root_readonly_discovery_20261027.py`; no import, test, query, provider call, build, or private-input read was performed.

- Query-finally result persistence at lines 213–218 is now guarded and records only an in-process failure reference plus a finite result flag. It proceeds into Store cleanup regardless of that write failure. The final result write at line 251 is after Store and protected-context closure; if it fails, the top-level handler updates the already-created finite result and makes a best-effort write.
- `NativeOutputMute.enter()` now wraps incremental redirection in rollback at lines 46–61. It runs before entering the protected handoff at line 170 and before Store construction/provider readiness at lines 175–182. Its rollback state is initialized in `__init__`, so the prior partial-entry path no longer bypasses restoration under ordinary OS success.

No remaining actionable defect was found in these two paths in this narrow review. This is a static caller review only; it does not claim a query, cleanup, or live-session outcome.
