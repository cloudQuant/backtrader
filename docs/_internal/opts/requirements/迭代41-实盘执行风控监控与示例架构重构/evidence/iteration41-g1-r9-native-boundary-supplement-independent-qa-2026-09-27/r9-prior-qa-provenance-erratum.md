# Erratum — prior R9 independent QA artifact identity

Date: 2026-09-27

This is a separate correction; the earlier independent QA report, receipt, and archive are retained unchanged.

The author archive/index verify cleanly (author ZIP SHA-256 `2055fb8329a06d80abe8fc52ae2d2fec25674686300defe96192faf3a4e44f3a`; entry-index SHA-256 `1957b0bdc47c26903de96eed6a8c08bb4d25613d56d495de2c3add2198852665`). In the prior writable QA extraction, the R9 C++ source, Python test driver, and Popen helper were byte-identical to the archive. The build batch changed only the `TEMP`/`TMP` roots; the VS and `cl` command lines were the same.

The rebuilt executable was not byte-identical to the archived EXE: SHA-256 `b5b8fb4d…` versus `6db48747…`. The files are the same size. A byte comparison found only four differing offsets, all copies of the PE link timestamp; zeroing only those four offsets made the files byte-identical, and `.text` section hashes match. The rebuilt object likewise differs in COFF timestamp and absolute temporary path/debug/checksum metadata; all `.text*` section contents match. Therefore the previous replay is valid as **6/9 on an isolated source-equivalent rebuild**, but it is not an exact-hash replay of the archived EXE. Any statement implying execution of the byte-exact archived executable is withdrawn.

The prior temp copy's `r9_manifest.json` SHA (`060931b2…`) and `R9_FINDINGS.md` SHA (`92775275…`) differ from the canonical author ZIP members (`98a8110a…` and `ceb6ba5d…`). Generated receipt/trial metadata also differ. The mutation origin is unknown. These prior files were not rewritten by this supplement, and the supplement's candidate basis was freshly extracted from the verified raw ZIP/index into `frozen-input\canonical-candidate\`.

The exact per-file comparison and PE/COFF section results are in `run\prior-copy-comparison.json`. This erratum does not change the original negative deadline findings and does not make G1 accepted; G1 remains CLOSED.
