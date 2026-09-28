# G4 author-evidence archive recheck

**Result: corrected archive hashes and links verified; disposition remains NO_EXACT_PIN_REBUILD / NO_G4.**

Rechecked the author archive at D:\source_code\backtrader\docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\g4-msvc-pe-timestamp-author-review-2026-09-27 read-only. The corrected canonical manifest SHA-256 is 159a0b2df96646c47fa2f2eb7ec3e2015997a94ba4df2c5555c4edd24d0c7716; the current SHA256SUMS.txt SHA-256 is c1e98c27e9860d58daeaf9de9f5f3aae2a8fd0dea4804c6d28ff6d6041aba842.

- SHA256SUMS inventory: 37/37 entries match.
- Manifest copied payloads: 36/36 entries match.
- README.md manifest row: c724a966bbf1dd079a60b3540a18127b628b06ea767f06ece749df724ed9d028; actual SHA-256 c724a966bbf1dd079a60b3540a18127b628b06ea767f06ece749df724ed9d028; match.
- Relative Markdown links: 4/4 resolve within the archive.
- REPORT.md and the canonical manifest both explicitly retain NO_EXACT_PIN_REBUILD and NO_G4 disposition markers.

This resolves the first-pass stale README manifest row recorded in the earlier independent report (SHA-256 9d11413cc87c2f6f31b6479daf5a4281fc58d6aa9272a2a170b9ba17562e53d7). The corrected evidence integrity does not change the independently established wheel result: exact pin rebuild and G4 remain unaccepted.

Scope was evidence-only. No SDK/native import or load, build, install, network, credentials, private configuration, or repository tests were accessed.
