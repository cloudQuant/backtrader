# SimNow C01 V20 delivery builder R2 static review

**Decision:** `GO_STATIC_DELIVERY_REVIEW_ONLY / BUILDER_NOT_RUN`

## Subject

Builder `.codex-tmp/simnow_c01_v20_delivery_builder_r2_20261009.py`: 38,466 bytes, SHA-256 `7222080afd5127df33912eecfbfa723250af45fe95bd28381df7ddb4aef4086c`. R1 remains preserved at 30,768 bytes / `dd5f9ec062c1acbbb2d2cb1779f3708b05a28d70e056d9b5341e3667ce90c011`; its independent review was held for omitted raw QA outputs in `iteration41-simnow-c01-v20-delivery-builder-r1-independent-static-review-2026-10-09/README.md`.

## R2 additive checks

R2 adds an allowlist for exactly four files beneath the recorded R9 external QA artifact directory. Each file is read only after path containment and exact path bindings are checked against the R9 Root/child records and output summary. The child stdout/stderr paths and sizes/hashes agree with the valid child-log attestation, and neither stream was truncated. The external `pytest.ini` path, nine-byte `[pytest]\n` content, hash, and external-origin flag agree across Root and child before/after snapshots. The zero-byte `pytest.log` is bound to Root and child paths and the expected empty-file hash; R2 explicitly identifies that this file is not covered by the child stream attestation.

I independently re-hashed the named external files: stdout 151 bytes / `76a353188503dd30e0e12e20fc22ba3fc2fc76d6b966d08c8495d7ccc34e9b14`; stderr 0 bytes / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`; `pytest.ini` 9 bytes / `8250d20f42b419af40706490ead78aabab9feba93eab09a3f626e3de5256e1f4`; `pytest.log` 0 bytes / the same empty-file hash. The R9 records show the same paths and hashes, status `PASS_SOURCE_FAKE_ONLY`, child exit code 0, and 118 collected/passed calls. R2 copies all four files and verifies each copied payload, then rechecks the four source files after assembly.

The additive path changes raise the copied evidence count from 15 to 19 and the total unique payload paths from 35 to 39. With three authored records, the evidence directory count is 22; the 39 proposed `.gitattributes` rules plus the attributes file account for 40 paths. The README and round record accurately limit this to source-fake selected-module evidence and state formal C01 PASS remains zero.

The inherited candidate closure remains intact: 34 unique source/test pins, split 17 tracked clean dependencies and 17 untracked additions (10 sources, 7 tests). All current file pins and tracked statuses matched, as did all 17 raw `HEAD` checks. The three CRLF checkout exceptions matched their separate raw-blob pins and normalize to the corresponding `HEAD` bytes. The branch is `dev`, current delivery HEAD is `a17f6ce6a4a7e2b69b40b6e5c0a56de16e9286dd`, the index is empty, and `.gitattributes` is clean. The 13 excluded runtime paths receive only before/after Git status checks; the builder does not read or copy their contents. R2 keeps the QA baseline HEAD `8598c2decdff92085a48bc2b89856926a1051670` separate from the caller-supplied delivery HEAD and does not edit source, attributes, or the index.

## Limits

This is an independent static review of the unexecuted R2 builder and the named public QA records/outputs. I did not execute the builder or rerun the 118-test QA. This decision does not claim native/provider/account behavior, actual activation, or formal C01 acceptance.
