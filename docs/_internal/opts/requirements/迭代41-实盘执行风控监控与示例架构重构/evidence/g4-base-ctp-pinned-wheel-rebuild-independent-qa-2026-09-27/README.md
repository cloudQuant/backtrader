# G4 base/CTP pinned-wheel rebuild QA (compact evidence)

This directory keeps the independent QA report, machine summary, source/member comparison results, build and guard logs, verification scripts, and the four A/B build wheels. It intentionally contains no source `.tar` files. The full source archives remain in the original QA temp workspace, unchanged:

`D:\temp\iteration41-g4-base-ctp-pinned-wheel-rebuild-20260927\archives\`

Original archive identities, checked against the canonical copies before those copies were removed:

- Base `bt_api_base-0.15.5-73e860e2fd8086ec817db254d4c396c2a76eb7d6.tar`: SHA-256 `62dad9c535de47613a15a0e4f64f7af85682628a82c2543649bc723c5ca73f80`.
- CTP `bt_api_ctp-i2-28157ce33009f932fbf8b3a78f7e77cb42c9cc4b.tar`: SHA-256 `9005a1754210d1dacb02eb1545d2c0718c1fdfd08ee62141566fae4181194821`.

`SHA256SUMS.txt` is the replacement checksum index for this compact directory. It supersedes the earlier 32-entry index, which included the two source tar copies; that earlier list must not be used to validate this directory. The new index covers every file here except itself. The report records the exact CTP pin rebuild failure, source/provenance checks, non-hermetic build-tool limitation, and that no install/native/G4 acceptance was performed.
