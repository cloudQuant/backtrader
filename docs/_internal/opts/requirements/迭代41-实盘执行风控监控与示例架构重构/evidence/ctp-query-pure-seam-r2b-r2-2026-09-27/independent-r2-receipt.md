# Independent R2 package QA receipt

## Verdict

PACKET_COMPLETE / PACKAGING_QA_PASS.

The r2 bundle repairs r1's packaging defect. The 15 indexed payload paths now exist literally in the package root and all indexed SHA-256 and byte-size values match. The ZIP contains exactly the 15 indexed payloads plus SHA256SUMS.txt, package-manifest.json, and verify_r2_package.py; all members are unique, CRC validation passed, and archived member bytes equal the package directory.

This is packaging acceptance only. It does not expand the underlying pure-query seam's scope or establish I22, SDK, Actor, CTP, or production acceptance.

## Inputs and identity

- Frozen package directory: D:\temp\iteration41-ctp-query-pure-seam-r2b-20260927-r2.
- ZIP: D:\temp\iteration41-ctp-query-pure-seam-r2b-20260927-r2.zip.
- ZIP SHA-256: 2840372130889784F6C691F0B7DE8CCC90812823FAC15E2871547E1C7463AC74.
- package-manifest.json SHA-256: AD6106E0542FABAD44A16D86F7AEE8A39B4EBE6342A152BCCAD491960C9A0C5E.
- SHA256SUMS.txt SHA-256: 41387433B6F0997991711059C5CC0456EE3643C11AE6EA2812D39F1730569014.
- The manifest's declared r1 SHA index matches the retained r1 index.

## Independent checks

1. ZIP SHA matched the supplied value. ZIP CRC test returned None (no bad member).
2. The ZIP had 18 unique names, exactly the manifest's 15 payload paths plus the checksum index, package manifest, and verifier.
3. All 15 literal payload paths exist. Every payload hash and byte length matched the manifest and checksum index.
4. Each of the 18 archived members was byte-identical to its corresponding package-directory file.
5. I compared all 15 r2 payloads byte-for-byte with r1's mapped payloads. All are unchanged, including the original test base, modified I22 test, new pure test, patch, 157-row CSV, report, r2b Store source and analysis summary.
6. I extracted the ZIP into a new QA directory and ran the packaged verifier from that unpacked copy with the frozen ZIP as input. Exit code 0; output reported 15 payloads, 1 support file, 15 checksum entries, 18 verified ZIP members, exact bytes, and verification PASS.
7. The bundled canonical I22 path-form nodeid and both core incomplete-result assertions are present. This source-contract payload is unchanged from r1.

The r1 independent run separately reported 19 passing focused tests and three route probes rejecting before the trap API was read or called. This packaging-only QA did not rerun those tests; byte-for-byte payload equivalence preserves that prior result for the same test sources. It does not claim the 157 remaining I22 query/evidence cases are fixed.

No main repository production code, private CTP config, real SDK/native module, provider, account, or network was used.

## Independent evidence

Raw checks and the unpacked verifier run are under D:\temp\iteration41-ctp-query-pure-seam-r2b-r2-independent-qa-20260927:
- qa_r2_verify.py
- qa-r2-verify.log
- independent-r2-result.json
- unpacked-verifier.stdout.txt
- unpacked-verifier.stderr.txt
- unpacked-verifier.exit.txt
- unpacked\ (fresh extraction used for verifier run)
