# G4 r2 disposable wheel probe

Classification: disposable SDK lifecycle wheel probe only. This is not a release artifact, native-session acceptance, G4 acceptance, or default pin.

## Frozen inputs

- Base SDK source: clean D:\q\e, HEAD 29f8ff171f61a71038328a7067e0909bf44774b2.
- G4 r2 source: D:\temp\iteration41_g4_native_lifecycle_receipt_candidate_20260927_r2.
- G4 r2 freeze manifest SHA256: E55D077572EE7F071D3D0AD0FD74522618E1E338A6E38E9963ED6EF76D2F15EE.
- Only overlays: client.py SHA256 C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF and test_ctp_native_lifecycle_receipt.py SHA256 6CB3837065BBF3A78ADDE5771CF26EF4593A7FEBF7ED8CBC5D0DEBDDB74CA320.
- Disposable metadata version: 2.0.4+g4r2.probe.20260927. Source copies change only this version field in addition to applying the two overlays.

## Build and consumer result

Two clean archive copies were built using the captured MSVC 2022/Windows SDK toolchain and /Brepro environment flags. Both commands exited 0 and produced byte-identical 5,433,813-byte wheels, each SHA256 00e0c0c56574f60013115ee6010e531f72a8c811780f27dfcba3249cdafb5384. Each wheel has 90 entries; ZIP integrity and 89 non-RECORD payload hashes were verified. A/B build logs and the member-level comparison are preserved here.

The strict consumer venv has include-system-site-packages=false. It installed the probe wheel, accepted bt_api_base wheel and the offline test dependencies. pip check reported no broken requirements. Installed distribution metadata, direct_url wheel hash, package/client import origins and installed RECORD payload bytes were verified. The fake-only lifecycle/shutdown/MD-startup target passed 66 tests with one existing pytest configuration warning.

A meta-path test guard blocked both attempted imports of bt_api_ctp.ctp._ctp before extension loading. No provider, account, private configuration, network endpoint or live/native session was used.

## Limitations

- The wheel is a disposable probe identity, not an intended release version.
- Fake tests do not establish real mapped DLL loading, same-generation native Join/Release behavior, or a clean real-session close.
- The bounded Windows Job supervisor/G1 acceptance remains absent. G4 remains CLOSED.
- No default pin, production source tree, or frozen r2 input was changed.
