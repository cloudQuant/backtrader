# Independent G4 MSVC/PE timestamp QA

**Verdict: NO_EXACT_PIN_REBUILD / NO_G4.**

## Scope and method

Read-only verification of the author archive at D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\g4-msvc-pe-timestamp-author-review-2026-09-27 and the referenced frozen wheels under D:\temp plus the pinned wheel path recorded in the archive. I verified archive SHA-256 entries and copied-payload hashes, then read wheel ZIP members as inert bytes and parsed PE headers/debug-directory records using Python standard-library zipfile/struct. No .pyd or SDK import/load, wheel installation, build, provider/network/account/private-config access, or repository tests/ access occurred.

## Archive integrity

- SHA256SUMS.txt: 37/37 rows match; file SHA-256 9b5a3ddaeedf53239c59129d2db1423f5158fce53ee63485dd450cf1c557f57e.
- canonical-subset-manifest.json SHA-256 e46b6da3b1540632e4b0830893b88e34ba4ba7c5651d4b450fefd0f6fae39b82; 35/36 copied payload hashes match. The sole mismatch is README.md: nested manifest expects 70ac6456a5fc51d4b0d7b8b5659a4ffb24cd213ca21cef92c9ac79652288f807, current file is c724a966bbf1dd079a60b3540a18127b628b06ea767f06ece749df724ed9d028. The README file itself matches the 37-row SHA256SUMS.txt inventory.
- Author REPORT.md SHA-256 e20890730e61d301e569b740374547677786167ea5506c69519507ec36e5d801.

## Independent binary findings

| Artifact | Wheel SHA-256 | .pyd size / SHA-256 | Result |
|---|---|---|---|
| Pin | 988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff | 11,889,152 / 468eaf9b623f684959922e3d1a2970f7f5ea71c73b7495cd533732f39672ef47 | baseline |
| Prior A | 7759a11487ddb0067e3fb755366c989b1fe55a965f3d712526d59b6bb228817d | 11,889,152 / 53ee9cd5e14a210c01bf96da1f374ea684655a2699587a14e7d7495f9e19b2b4 | exactly six .pyd bytes differ from pin |
| Prior B | 1de546d5c18b439d77d26dd0039e08b4facbbeaf1b0b865a38eafa211c2d46f8 | 11,889,152 / 0651199203a59ea0aa7f75c5f9129d9065ea390a0d1db047f186ac7b389baf86 | exactly six .pyd bytes differ from pin |
| Strict C | 7dad3140ab8a700939022282a78f75b165a612637bac90da5caa7df06f4d64f7 | 11,889,152 / 06a4e2b158eed8c2766678a69476eb0601593efdbe1979f13383ab7ce0488539 | exactly six .pyd bytes differ from pin |
| Brepro A and B | 70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2 (both) | 11,889,664 / e6d4e32740646962c35d96223682f4db0f1b8082398055a88f58ed45ec1ecd78 (both) | wheel and .pyd byte-identical to each other; not pin-identical |

For pin vs prior A, prior B, and strict C, the complete mismatch set is exactly 0x120, 0x121, 0x122, 0xa26c54, 0xa26c55, 0xa26c56. The independent PE parse locates the first triplet at the COFF TimeDateStamp beginning at 0x120; the second is the TimeDateStamp field of the sole PE debug-directory entry (type 13 / POGO), beginning at 0xa26c54. Parsed COFF/POGO timestamps match respectively: pin 0x6ab5394d, prior A 0x6ab8f82c, prior B 0x6ab8f8d9, strict C 0x6ab909e7. Thus the six-byte timestamp explanation is confirmed for equal-size pin/A/B/C native images.

The Brepro pair is reproducible under its recorded recipe, but its native image is 512 bytes longer than the pin and differs broadly; it does not reproduce the pin.

## Toolchain/provenance limit

The strict C script clears CL, LINK, and SOURCE_DATE_EPOCH, and uses pip wheel --no-index --no-deps --no-build-isolation. Recorded package hashes have zero mismatches (1,992 files for setuptools 65, 1,978 for setuptools 75). This is package-isolated evidence, not a hermetic toolchain lock: recorded external inputs include C:\anaconda3 Python runtime/headers/library and a host VS 2022/MSVC 14.42.34433 toolchain. The exact pin timestamp-generation recipe remains unidentified. Brepro A/B equality cannot bridge that gap.

**Disposition:** PE timestamp cause for the narrow equal-length A/B/C comparison is verified, but exact pin rebuild and G4 are not established. No G4/native lifecycle acceptance claim follows.

## Reproducibility record

Independent parsed results: independent-results.json, SHA-256 94fcc2b3d99c368164d88f357e57521aefe011ce0d08325b8436ac1a26a7e1fa.
