# SimNow C01 V20 source-fake component delivery round

Scope: SOURCE_FAKE_SELECTED_MODULE_NAMESPACE_ONLY. Status: candidate source/test and evidence packet ready for scoped review; no formal C01 acceptance.

## Baselines and inputs

The consumed R9 Root source-fake QA ran on branch dev at HEAD 8598c2decdff92085a48bc2b89856926a1051670 with an empty index before and after. This builder requires the caller to supply the current delivery HEAD separately; that head may include an independently accepted commit made after the QA. It requires branch dev and an empty index, and it records the current .gitattributes bytes without editing them.

The frozen R7 map has 26 source rows and 8 focused-test rows. Seventeen are already tracked, byte-pinned dependencies; seventeen are new untracked component paths (10 production source files and 7 tests). The three tracked CRLF-normalized checkout inputs are backtrader_runtime/ctp_front_pair_probe.py, scripts/ctp_i13_i15_outer_watchdog.py, and scripts/ctp_i13_i15_windows_job_backend.py. Their R7 checkout pins and raw HEAD blob pins are recorded separately; they remain unstaged and must not be renormalized.

## QA and review

The consumed R9 Root receipt is PASS_SOURCE_FAKE_ONLY: 118 collected and passed calls; zero failed, skipped, xfailed, xpassed, warnings, or collection errors; exact call reports; candidate input state unchanged; all source-origin checks complete; initializer compile/execute counts zero; forbidden-operation counter delta empty. The R9 independent static review is GO_STATIC_REVIEW_ONLY / EXECUTION_NOT_RUN. The R1 composition review remains a source-fake baseline review. The R7 static review HOLD is preserved as history: it found stale R7 harness inventory constants, which the reviewed R9 harness corrected. The raw stdout and stderr copies match the Root and child output attestations; the external pytest.ini matches its pre/post snapshots. The zero-byte pytest.log is Root-referenced but is not part of that child log attestation.

Earlier R5 had a temporary-directory harness failure, and R6 passed its 118 calls but failed the parent postcondition because two test-owned V17 module aliases survived fixture teardown. R7 changes the function-scoped test fixture to restore prior sys.modules bindings in finally. Those earlier outputs are not included as passing QA. The R7 candidate packet's own qa/result.txt still says NOT RUN because the successful consumed result is the separate R9 record.

## Exclusions and acceptance boundary

All 13 metadata-only runtime paths listed in R9 input-inventory.json are excluded, including the dirty backtrader_runtime/ctp_simnow_operator.py and initializer support. Their path-level Git status is checked before and after packet assembly; their file contents are not read or copied. Unrelated worktree changes are preserved. No candidate module is imported and no test, native, provider, account, process, or pipe operation is performed by this builder.

R9 source-fake QA is not real activation evidence and does not establish native cleanup, provider/account behavior, or a formal C01 result. Formal C01 PASS remains zero.
