# G4 PE timestamp source-build control audit

**Disposition: NO_EXACT_PIN / NO_G4.** This follow-up is a read-only local audit plus inert wheel ZIP/PE inspection. No new source build was run because the inspected MSVC linker interface and recipes expose no supported control for assigning the target PE timestamp. No binary was modified, installed, or imported; no SDK/provider, credentials, private configuration, or main-tree file was accessed.

## Bound source and pin

- Frozen source archive: D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\archives\bt_api_ctp-i2-28157ce33009f932fbf8b3a78f7e77cb42c9cc4b.tar
- Source commit: 28157ce33009f932fbf8b3a78f7e77cb42c9cc4b
- Source archive SHA-256: 9005a1754210d1dacb02eb1545d2c0718c1fdfd08ee62141566fae4181194821
- Pinned wheel: D:\c41sdki2_audit\wheels\bt_api_ctp-2.0.3+iteration41.i2-cp311-cp311-win_amd64.whl
- Pinned wheel SHA-256: 988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff
- Pinned _ctp.pyd SHA-256: 468eaf9b623f684959922e3d1a2970f7f5ea71c73b7495cd533732f39672ef47; PE COFF and type-13 POGO timestamps both decode as 0x6ab5394d = 2026-09-24 14:53:01 UTC.

## Byte-level replay

The standard-library-only script ran under the existing package-isolated interpreter as:

    D:\temp\iteration41-g4-ctp-native-repro-isolated-20260927\build-tool-venv-65\Scripts\python.exe -I -S D:\temp\g4-msvc-time-control-study-20260927\compare_pinned_wheels.py

It opened each wheel as ZIP bytes, passed ZipFile.testzip(), extracted only the _ctp.pyd member as bytes, and parsed PE headers with struct. site was not imported. Output is timestamp-comparison.json and wheel-byte-replay.log.

The pinned image versus both prior non-/Brepro wheels and controlled strict C has equal length and exactly six differing offsets: 0x120, 0x121, 0x122, 0xa26c54, 0xa26c55, 0xa26c56. The first triplet is COFF TimeDateStamp; the second is the timestamp field in the sole type-13 POGO IMAGE_DEBUG_DIRECTORY entry. The four-byte values are duplicated in both fields:

| Image | COFF and POGO timestamp | UTC |
|---|---:|---|
| Pin | 0x6ab5394d | 2026-09-24 14:53:01 |
| Prior A | 0x6ab8f82c | 2026-09-27 11:04:12 |
| Prior B | 0x6ab8f8d9 | 2026-09-27 11:07:05 |
| Strict C | 0x6ab909e7 | 2026-09-27 12:19:51 |

The exact wheel SHA values are recorded in timestamp-comparison.json. Strict C wheel SHA-256 is 7dad3140ab8a700939022282a78f75b165a612637bac90da5caa7df06f4d64f7; its _ctp.pyd SHA-256 is 06a4e2b158eed8c2766678a69476eb0601593efdbe1979f13383ab7ce0488539.

The /Brepro A/B wheels are identical to each other, SHA-256 70efd2ee7302b0fa197e6709a044ef85d50ab1cbc36f79d9d055d81b289a2ed2. Their _ctp.pyd is 11,889,664 bytes, 512 bytes larger than the 11,889,152-byte pin, and has 627,253 differing bytes in the common prefix. Their COFF/POGO timestamp is 0xb92d3741, not the pinned timestamp. The earlier recipe set SOURCE_DATE_EPOCH=1790261514; the emitted field does not equal that value. This deterministic recipe is therefore not an exact pin reproduction.

## MSVC recipe audit

The recorded strict C recipe, build_legacy_strict.cmd (SHA-256 f57f558ae294ad24c274fad4bb86b589437e30cdfb0ace7d38642aff853a7142), clears CL, LINK, and SOURCE_DATE_EPOCH before invoking pip wheel. Its captured linker command (SHA-256 f519b35b586e72fb8cca06e880d0c93c7e7bd7c5d25066d4674623351149a9ec) includes /INCREMENTAL:NO, /LTCG, and /DLL; it has no timestamp-setting argument. The controlled /Brepro recipe (SHA-256 1a5090b40b0738daaa9a0b25894937327181b12357f5cf1986667a7556c61169) sets CL=/Brepro, LINK=/Brepro, and SOURCE_DATE_EPOCH=1790261514, yet emits the materially different pyd above.

I invoked the exact local linker executable at C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC\14.42.34433\bin\HostX64\x64\link.exe with /?. Its file SHA-256 is f627ee8b9983af24d4b5ab6efab25f4a3be7a02bb09253aa2f5abab3c1fb2c6b; the usage text reports linker version 14.42.34435.0. The help lists /TIME (elapsed link-time reporting) and /LINKREPRO* (link repro capture), but no timestamp-setting switch or SOURCE_DATE_EPOCH input. Help output and observed process status 1100 are preserved in link-help.txt and link-help-exit.txt. The help is evidence of the available documented interface, not proof that every undocumented linker behavior is absent.

## Conclusion and missing provenance

No supported source-build input found in the audited recipes can choose the pinned timestamp. Ordinary linking emitted the link-time timestamp; /Brepro produced a content/toolchain-dependent timestamp and different image bytes. Rebuilding at a forced past system clock or editing timestamp bytes would not establish an acceptable, independently reproducible source recipe, and neither was attempted.

The remaining gap is publisher-side provenance for the pin: the exact linker/toolchain inputs and a supported timestamp-generation method that can reproduce 0x6ab5394d without post-build byte edits. Until those are available and an exact source-built wheel pair matches the pin, keep NO_EXACT_PIN and NO_G4. The corrected archive manifest is a63b3f98f87586f87504db05456935c12aba21390735d09749b3b6ed6bff0241 and its current SHA256SUMS is c25c6c75fb2fd2b8d705d59b46137db4fad51b41f9ddd9493a744a80ee984a0e. Separate QA verified archive integrity and inert PE comparisons; it did not independently repeat the source build.
