# QA harness corrections

The initial static verifier expected a RECORD-row count field in the wheelhouse manifest and searched an outdated settlement function name. The initial install-audit command also used one incorrectly normalized root distribution key. A source readback assertion used incorrect getter names. These were reviewer-script mistakes, not candidate failures. The checks were corrected after inspecting frozen manifests and source; corrected checks passed.

The initial stdout/exit-code logs for these attempts are preserved under `logs/*initial*`. The initial static audit JSON was overwritten by the corrected report before it was copied aside; therefore that initial JSON is not retained. The error details remain in `logs/artifact-static-audit-initial.log`. Candidate bytes, lock, wheelhouse and main production sources were not modified.
