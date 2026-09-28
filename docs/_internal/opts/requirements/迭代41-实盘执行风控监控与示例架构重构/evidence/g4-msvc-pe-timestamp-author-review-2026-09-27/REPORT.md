# G4 MSVC timestamp / deterministic-build probe

**Disposition:** `PE_TIMESTAMP_CAUSE_IDENTIFIED / NO_EXACT_PIN_REBUILD / NO_G4_ACCEPTANCE`.

This probe was limited to offline wheel construction and static PE/ZIP byte inspection. It did not install a wheel, import `bt_api_ctp` or `_ctp`, load a provider DLL, open a session, use credentials/private configuration, or permit outbound networking. The repo and code-owned pins were not changed. All newly created artifacts are under this `D:\temp` workspace.

## Source and repeatable baseline

The input CTP source archive was `D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\archives\bt_api_ctp-i2-28157ce33009f932fbf8b3a78f7e77cb42c9cc4b.tar`, SHA-256 `9005a1754210d1dacb02eb1545d2c0718c1fdfd08ee62141566fae4181194821`, for commit `28157ce33009f932fbf8b3a78f7e77cb42c9cc4b`. The archive contains 260 source files / 64 directories; its recorded source tree digest is `b332edcf5b86b0447b07ea0d9b5a82d0293ab6e25513c24a0b99ae103bf176b8`. Four separate extractions were byte-identical at extraction, and post-build verification found all 260 original payload files unchanged in each build source root.

The pinned wheel is `D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl`, SHA-256 `988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff`. Its `_ctp.cp311-win_amd64.pyd` is 11,889,152 bytes, SHA-256 `468eaf9b623f684959922e3d1a2970f7f5ea71c73b7495cd533732f39672ef47`.

## Six-byte mismatch fully decoded

The prior offline, non-hermetic build A produced wheel SHA-256 `7759a11487ddb0067e3fb755366c989b1fe55a965f3d712526d59b6bb228817d`; its native member SHA-256 is `53ee9cd5e14a210c01bf96da1f374ea684655a2699587a14e7d7495f9e19b2b4`. Compared with the pinned `.pyd`, the size is identical and exactly six byte positions differ:

| File offsets | PE field | Pin bytes | Prior build A bytes |
|---|---|---|---|
| `0x120..0x122` | PE COFF `TimeDateStamp` | `4d 39 b5` | `2c f8 b8` |
| `0xa26c54..0xa26c56` | `TimeDateStamp` in the sole `IMAGE_DEBUG_DIRECTORY` entry | `4d 39 b5` | `2c f8 b8` |

The shared fourth timestamp byte is `6a`; decoded field values are pin `0x6ab5394d` and build A `0x6ab8f82c`. Prior build B has the same six-byte-only relationship to the pin, with timestamp `0x6ab8f8d9`; prior A and B differ from each other at these same two timestamp fields and `RECORD` consequently differs. The PE debug entry is type `13` (POGO), size 848, with the `GCTL` POGO payload. It is not a CodeView type-2 PDB record. The timestamp in the POGO entry equals the COFF timestamp in every examined image. Thus the previously unexplained second three-byte site is the duplicate timestamp field, not a second unknown binary delta.

The old pin-vs-build-A section hashes match for `.text`, `.data`, `.pdata`, `.rsrc`, and `.reloc`; `.rdata` differs where the debug-directory timestamp resides. This establishes same native payload bytes apart from the two timestamp fields for this comparison. It does not identify the original pin's exact build timestamp recipe.

## Isolated no-`/Brepro` confirmation

I made a fresh venv at `build-tool-venv-65` with `include-system-site-packages = false`, Python 3.11.5, pip 23.2.1, setuptools 65.5.0, and wheel 0.43.0. The setuptools files (243 non-cache package/metadata files) and wheel files (34 non-cache files) match their local source copies by SHA-256. The venv's pip and package paths exclude global `site-packages`.

This is package-isolated, not fully hermetic: the interpreter/base prefix and Python headers/library remain under `C:\anaconda3`; the MSVC/Windows SDK dependency set is version/path recorded but not exhaustively locked. The build input capture is `toolchain65-manifest.json` (SHA-256 `1fc908eaa71a26252f3885926ccef3993f35ce4e89addda403491496b33fbe2c`); a post-build recheck in `toolchain-manifest-verification.json` has zero package/tool hash mismatches.

A fresh source extraction was built with `cmd.exe /d /c D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\build_legacy_strict.cmd`. That recipe explicitly clears `CL`, `LINK`, and `SOURCE_DATE_EPOCH`, calls the fixed VS 2022 `vcvars64.bat`, and runs `pip wheel -v --no-index --no-deps --no-build-isolation --no-cache-dir`. Internal build exit was 0. Build C wheel SHA-256 is `7dad3140ab8a700939022282a78f75b165a612637bac90da5caa7df06f4d64f7`; its `.pyd` SHA-256 is `06a4e2b158eed8c2766678a69476eb0601593efdbe1979f13383ab7ce0488539` and has the same 11,889,152-byte length. Relative to both the pin and the earlier non-`/Brepro` build A, this isolated build again differs in the `.pyd` at exactly those six timestamp bytes and nowhere else. The four wheel payload differences versus the pin are `RECORD`, `_ctp.pyd`, `bt_api_ctp/__init__.py`, and `bt_api_ctp/ctp/client.py`; the Python-file differences are the previously documented line-ending variation.

The captured compile command uses `/O2 /W3 /GL /MD` and `setup.py` adds `/std:c++14 /utf-8` (`setup.py:178`, extension source at `setup.py:244-247`). The linker command uses `/LTCG /DLL`, does not show `/DEBUG` or `/PDB`, and the build produced no `.pdb` file. That is consistent with the observed POGO PE debug-directory entry; no PDB was opened or consumed. It still does not prove which linker timestamp behavior produced the pinned value. We did not alter or retimestamp any output. The compile/link tools and selected Python inputs reverified against `toolchain65-manifest.json`; all 1,992 recorded venv package files and all nine selected external binaries/headers/libraries matched their hashes.

## `/Brepro` A/B result and comparison limit

Two more independent roots were built using the no-system-site venv pinned to setuptools 75.8.0/wheel 0.43.0, fixed `vcvars64.bat`, `CL=/Brepro`, `LINK=/Brepro`, and `SOURCE_DATE_EPOCH=1790261514`. Both commands logged internal `BUILD_EXIT=0`. The A invocation outer tool session reported exit code 1 despite the batch result/log reporting successful build; B and C outer command exits were 0. This status discrepancy is retained in `run-statuses.json`. The `/Brepro` script’s preliminary `cl /Bv` emits D8003 (no source-file argument) because the environment also supplies `CL=/Brepro`; that diagnostic is from the version probe, and the subsequent compile/link and wheel build succeed. Their wheels are byte-identical: SHA-256 `70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2`, 5,401,614 bytes, 87 members. Embedded `RECORD` validation passed for every row; its SHA is `17ef1594fe0606c3c3b33c99616d495ee79a3a1f8fc58ed29b4abfa1c163dfd0`. The two `_ctp.pyd` payloads are byte-identical at SHA `e6d4e32740646962c35d96223682f4db0f1b8082398055a88f58ed45ec1ecd78`, with equal COFF and POGO timestamps `0xb92d3741`.

This demonstrates a byte-reproducible A/B under that particular recipe, not reproduction of the code-pinned wheel. The venv manifest recheck reports all 1,978 recorded package files and selected external inputs matching their pre-build hashes. The new `/Brepro` `.pyd` is 512 bytes larger than the pin, has 627,253 differing bytes in the common prefix, and differs in `.text`, `.rdata`, `.pdata`, and `.reloc` section hashes. The comparison is confounded by the changed build-tool versions, `/Brepro` settings, `SOURCE_DATE_EPOCH`, and bootstrap route; it does not justify attributing this broader delta to one flag. The source inputs were the same frozen archive, and the pre-existing old A/B remain the precise timestamp-only comparison for the pin.

## Bootstrap / diagnostics

An earlier environment probe hit a Conda `AutoRun` temporary-directory error after clearing two Conda variables while `CONDA_SHLVL` remained set; that attempt was stopped and not counted as a build. Final A/B/C scripts use `cmd.exe /d` where captured, the fixed `vcvars64.bat`, and their saved vcvars logs show VS 2022 17.12.3 x64 initialized. A standalone `import setuptools` diagnostic also raised the Anaconda stdlib `distutils` override assertion; `pip wheel` itself completed, and the exact package versions and files are recorded. The probe was not used as a build result.

## Guard and exact limit

All builds used no package index/dependency installation and an audit hook denying SDK/native imports and socket operations. There were zero SDK/native import events and zero `socket.connect`, `connect_ex`, `getaddrinfo`, or `sendto` events. The hook denied local `socket.bind` attempts: 210 in the first `/Brepro` A log, 1 in `/Brepro` B, and 2 in isolated no-`/Brepro` C. Their caller purpose was not identified; they were blocked, not treated as successful network access. No wheel was installed and no current installed `RECORD` or package-origin claim is made.

**Decision:** the two duplicate PE timestamp fields fully explain the initial six-byte `_ctp.pyd` delta, and both strict no-`/Brepro` and prior builds confirm the rest of that native image is identical to the pin. Exact CTP pinned wheel reproduction remains unproven because wheel/container bytes differ (including Python EOL and `RECORD`), the original timestamp-generation recipe is unavailable, and this host's Python/MSVC/Windows SDK inputs are not a complete hermetic lock. No timestamp was patched to force a match. G4, the triwheel closure, and native lifecycle remain `NOT_ACCEPTED`.

## Replay/evidence files

- `/Brepro` A/B command: `cmd.exe /d /c D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\build_repro.cmd a` and then `... b`.
- Isolated no-`/Brepro` C command: `cmd.exe /d /c D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\build_legacy_strict.cmd`.
- Exact source, toolchain, wheel/member/RECORD, PE offsets, post-build source hashes, raw logs, and scripts are indexed in `SHA256SUMS.txt`; source archives are referenced by path and SHA-256 above, not copied into this workspace.
