# Iteration 41 version collision and source identity audit

Classification: read-only local planning evidence. No source, tags, pins, or wheels were changed; no network or provider access was used.

## Frozen inputs checked

- Execution R3r3+V21 composite: source manifest SHA256 00577665667A33C9A7D62D331C0CAD99B0B660790D0B475D0BD8C1B6CAA6E2DD, metadata version 0.2.0. V22 candidate manifest SHA256 8244038AB975F30DE6C0BA56C140F033DDD5B5CE5FB3CABC9E60ABB7BF24066D; its exact src/bt_api_execution/store.py SHA256 is 1C7EDD065B0167D7C50442762F99A29E4972752BD77636EB7052F022DCEFECB6, replacing the V21 store hash 799319096DE17D4FE60560240C9424F249B3AFED34A2DAED1DBCC07D486D605D. The V22 manifest labels itself SOURCE_ONLY_CANDIDATE_NOT_G5_ACCEPTANCE; it records 309 passed / 2 skipped, while explicitly limiting the result to injected fake verifier tests, with no production Windows process-exit verifier or G5 acceptance.
- A local V22 probe wheel already exists as bt_api_execution-0.2.2.dev0+v22.8244038ab975-py3-none-any.whl, SHA256 BFA0583BE8F97CC62F979B5848D7B798D440789617BF3DEC813BE53641D0702A. Three local build copies have the same bytes. This is a pre-release/local version, not stable 0.2.2.
- Risk cancel-resolution source: manifest SHA256 B5B066E901E656E3CE42599E0701B731DF16BE742121A43604B58D69E35DED5D, current metadata 0.1.0, pyproject SHA256 DB1EB4FEECED90358F2367CED58720C8C367663D8183FAE45F0362BA040FEAAB.
- Parent cancel-control r2: evidence manifest SHA256 B52E918A07195847B4011D1F68B476486AB4FB17E6DCFF8E49EAAABE1BABAE3D, current metadata 0.15.5, pyproject SHA256 7AA5FAD4C7C5408199457836FD659E19EC85445460EFE5F867359C5E6E28AA39. Parent issuer r2 is a separate snapshot, manifest SHA256 50B0D8B99AFDACDAF2055246010E5766BBE630BC66D71C2AEEACA117BAF3CE7A; the two are not a merged parent source. Parent r3 remains in progress and is not treated as frozen input.

## Local collision scan

Scanned local D:\bt_api* Git repositories and nested parent execution/risk repositories for tags containing 0.2.2, 0.1.1, or 0.15.7; no matching tags were found. Scanned pyproject metadata under D:\temp, D:\q, and the D:\bt_api* project trees; no exact target-version projects were found. Scanned existing wheel files under D:\temp, D:\q, D:\bt_api*, and the user Temp tree; no exact final wheels bt_api_execution 0.2.2, bt_api_risk 0.1.1, or bt_api_py 0.15.7 were found. The V22 development wheel above is the only target-family version hit observed.

This local-only absence does not prove that a version is unallocated in external registries, unscanned caches, or other machines. Do not treat 0.2.2, 0.1.1, or 0.15.7 as confirmed free release versions. Use only temporary, manifest-keyed probe versions until owners confirm release allocation; for example 0.2.2.dev0+audit.8244038ab975 for a distinct execution probe, 0.1.1.dev0+audit.b5b066e901e6 for the frozen risk input, and a parent .dev0+audit.<merged-parent-manifest-prefix> only after the control and issuer sources are merged and frozen. The existing 0.2.2.dev0+v22.8244038ab975 identifier is already occupied locally.

## Minimum composite source lock

Bind one artifact-set ID and, for every distribution, the canonical package name, exact PEP 440 version, complete sorted source-file manifest SHA256, source commit plus tree SHA256 (or source_commit: null with immutable evidence reference and complete archive/source manifest), pyproject SHA256, and all merge-input manifest hashes. Bind the build backend and build-tool versions, Python/platform/tag, exact direct and transitive dependency versions and wheel SHA256s, wheel filename and byte SHA256, embedded METADATA fields (Name, Version, Requires-Python, exact Requires-Dist), and RECORD hash. Record installed distribution metadata and module import origins against the expected wheel/RECORD. Link each package and composed consumer test command, JUnit/stdout hashes, skips, and source-lock hash. For execution, include schema/migration lineage and the V22 store digest above. Lock the exact selected CTP/base/monitor artifacts too; the previous audit records a main-vs-consumer CTP hash mismatch that still needs one reconciled identity.

## Release blockers retained

V22 is not G5 acceptance. The main runtime has no typed cancel-resolution wiring; parent control and issuer are separate sources; risk remains metadata 0.1.0; parent r3 is not frozen; there is no final combined source manifest, reproducible final wheel set, installed-origin/RECORD proof, or composed fake consumer acceptance. No real provider session or release is claimed.
