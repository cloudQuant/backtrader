# SimNow C01 V20 source-fake component delivery

Classification: SOURCE_FAKE_SELECTED_MODULE_NAMESPACE_ONLY.

This delivery preserves the R7 candidate packet, its source reviews, the exact consumed R9 Root source-fake QA inputs and results, and the four public R9 stdout/stderr/config/log files. The canonical source and test additions are listed in delivery-manifest.json; their bytes are checked against both the frozen R7 candidate map and the R9 input inventory.

R9 Root QA passed 118 selected source-fake calls with zero failures, skips, xfails, xpasses, warnings, or collection errors. It verified all 26 source and 8 test inputs, the reviewed selected-module namespace, exact origins, zero initializer compile/execute counts, and zero forbidden-operation counter delta. QA ran against dev HEAD 8598c2decdff92085a48bc2b89856926a1051670. The delivery parent recorded in the manifest may be a later dev commit; those two heads are kept separate.

The R7 packet's qa/result.txt is the pre-Root-QA preparation record marked NOT RUN; the consumed R9 result is archived separately. R5/R6 failures and the R7 stale-harness-pin HOLD are summarized in round-record.md; those old outputs are not presented as passing evidence.

The stdout and stderr bytes are pinned by the child log attestation and summary; pytest.ini is bound to the recorded external pre/post path, content, and hash. pytest.log is copied from its Root-referenced path and is zero bytes, but is not listed in the child log attestation.

This is source-fake component evidence only. It does not establish native process or pipe cleanup, provider/account behavior, a real activation, or a formal C01 PASS. Formal C01 PASS count remains zero. The 13 metadata-only runtime paths in the R9 inventory, including ctp_simnow_operator.py, are excluded and preserved.
