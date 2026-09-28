# Independent wheel probe QA review

**Result:** All four independent offline fake suites pass, and the disposable execution/parent dual-wheel consumer checks pass. Scope remains local QA only; no production route or release is accepted.

- Candidate source manifest: `01fa737d2a0f385dec8ce6187d95c4a104c13cce9dde6d693152df7dd94ef4b6` (843 declared files; every declared file independently hashed and matched).
- Raw author ZIP: `9510abeffcf040bf4a7ea8b8e0524e93cfe1046a8b9498dbc7e26626adbb2c46`. ZIP integrity check passed. Its index binds 1,015 payload members; total ZIP members are 1,016 because `ARCHIVE-INDEX.json` is the byte-identical self-index, SHA `0492df7ea055116c96519b8500d00b85f081da8d96c6dd69a1d88f2c05f0e569`.
- Author live candidate directory had 472 unmanifested main-overlay cache/bytecode files at input capture. Those files are excluded from source manifest counts and were not treated as frozen source.
- Wheel A/B hashes match exactly: execution `b2a74d5ec4bce72db66ed5698709a8f986de02b54d72fb5e08a181c2983b6217`; parent `5e6e846d26b5038c0916fa15d3ce3f7a1c1334fd0aa160cd263d2d0397c07b0f`. Fresh isolated venv verified every wheel payload against installed bytes and RECORD; PEP 610 direct_url SHA-256 matched both local wheels; source-only-base `pip check` was clean.
- Independent fake suites: 73 + 20 + 6 + 44 passed; 0 failed, 0 errors, 0 skipped. Tests ran from extracted frozen sources and copied, hash-bound source adjunct roots.
- Guard logs: 13 files, `{'guard-started': 13, 'source-import': 1031, 'source-namespace': 7}` events; blocked network/native/private-config/origin events all zero, native import lists empty, no `bt_api_ctp` source import.
- `bt_api_base` remains SOURCE-ONLY: runtime distribution wheel removed; source-only metadata and copied source root used. No provider, credentials, native session, or remote endpoint was touched.

Limit: this does not accept G1/G4/G5, authorize trading, change the default pin, or constitute release evidence. The Python-level guard provides local test evidence, not OS-enforced isolation.

Raw QA archive: `D:\temp\iteration41-coordinated-release-probe-independent-qa-20260927\independent-qa-evidence.zip` (SHA256 `6f90ed890e0eb638f3e4b141fa0433c1cce854cc25661bf07fcccfbfb2ac9ddd`). External member index: `D:\temp\iteration41-coordinated-release-probe-independent-qa-20260927\independent-qa-archive-index.json`.
