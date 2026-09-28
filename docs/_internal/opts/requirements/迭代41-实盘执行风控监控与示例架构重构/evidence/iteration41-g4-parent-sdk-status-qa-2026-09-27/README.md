# G4 parent SDK status QA — disposable artifact integrity archive

**Disposition: DISPOSABLE_PARENT_ARTIFACT_INTEGRITY_ONLY / THREE_PACKAGE_PIN_NOT_AVAILABLE / G4_CLOSED / NO_WRITE.**

This canonical directory preserves the frozen parent SDK status QA package and selected review, status, installed RECORD reproduction, and archive receipt artifacts. The source QA result is DISPOSABLE_PARENT_WHEEL_VERIFIED / THREE_PACKAGE_PIN_NOT_AVAILABLE / G4_CLOSED. The parent wheel is a disposable candidate; it is not an accepted SDK pin.

## Integrity checks

- Raw QA ZIP SHA-256: cfd48c7ee40633d2315b6cd4f46db9378892144fc0d942865cfc1d29c338a02c.
- Independent review SHA-256: 91d534800b6ebdc9f2df43fe8cb20d5b60175c08b17c4395c8a894533822d3a2.
- Status audit SHA-256: b88ab5c2fa84fd25ecb4dbe8bdabc9d6012e35dd2a27540ba5e3c466a01091f6.
- Two-venv installed RECORD reproduction JSON SHA-256: d9034eb52f3b5e91c414b337fa34b48ac3bddfb2a7311aba744047f904e0c928.
- Original QA archive receipt SHA-256: 525356e9ad714de0c7fb1d40f1b289b4f74f0558508c77bcfa0555c518b97a3c.

The copied source and destination hashes/byte counts match for all selected files. Independent ZIP verification returned clean from ZipFile.testzip(). The embedded ARCHIVE-INDEX lists 40 payloads; the ZIP has 42 entries because ARCHIVE-INDEX.json and SHA256SUMS.txt are two control members outside that index. All 40 payload sizes/hashes matched the index, and the two embedded control files matched the copied external counterparts. The original QA archive receipt recorded zip_testzip as null; [zip-validation.json](zip-validation.json) records the independent result.

## G4 status and limits

The review remains closed for G4: the main code pin catalog lacks bt_api_py, and a three-package installation matching the pinned base/CTP pair with accepted installed RECORD, PEP 610, and import-root evidence is unavailable. The disposable parent wheel's reproducible build and installed RECORD evidence do not supply that missing pin. Native lifecycle/provider/account acceptance and default CTP writes remain closed. This archive only checks artifact integrity; it does not change SDK pins, production files, private configuration, or environment.

## Preserved evidence

- [Raw independent QA ZIP](g4-parent-sdk-independent-qa.zip)
- [Independent review](independent-review.md)
- [Status audit](status-audit.json)
- [Installed RECORD reproduction JSON](two-venv-installed-record-reproduction.json) and [reproduction script](reproduce_installed_record.py)
- [Original archive receipt](g4-parent-sdk-independent-qa.archive-receipt.json), [archive index](ARCHIVE-INDEX.json), [SHA sums](SHA256SUMS.txt)
- [Copy/hash receipt](COPY-RECEIPT.json), [evidence manifest](evidence-manifest.json)
- Two-run installation and pip-version logs are preserved for RECORD reproduction.
