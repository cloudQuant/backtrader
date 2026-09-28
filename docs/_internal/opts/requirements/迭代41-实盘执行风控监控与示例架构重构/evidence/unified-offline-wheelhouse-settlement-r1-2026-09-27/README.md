# Unified offline wheelhouse settlement candidate (r1)

**Disposition: `FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED`.** This is an offline disposable packaging candidate. It does not change production code, the default pin, protected configuration, or the runtime route.

The 52-wheel hash-locked install passed in an isolated CPython 3.11.5 Windows x64 venv with `--no-index --require-hashes`; `pip check` reported no broken requirements. Installed RECORD audit verified 13,147 rows with zero errors and all four root PEP 610 hashes matched the local wheel hashes. CTP and native modules were not imported. The settlement source focus was 48 fake-only tests; no provider, network, credentials, account, or native calls were used.

The CTP settlement wheel was built twice with identical SHA-256 `857B06C914CFC4F58BC04A77F11B77AD5DC3C47DC2BE4D9D18B8E2FC805B264D`, using unique version `2.0.4+g4r2.settlement.probe.20260927`. Earlier distinct wheel bytes under `2.0.4+g4r2.probe.20260927` are kept only as collision diagnostics and are excluded from the final wheelhouse/lock. The selected official 7x24 pair retains exact-pair/zero-write behavior whenever current settlement is not proved with exact native provenance; there is no time/set fallback. Main readiness does not consume the settlement-specific evidence builder; G4/G6-S/G7-S and default route remain closed.

- [Review](candidate-review.md)
- [Machine receipt](candidate-receipt.json)
- [Requirements hash lock](requirements-hashes.txt)
- [52-wheel manifest](wheelhouse-manifest.json)
- [Install/RECORD/PEP 610 evidence](install-evidence.json) and [installed-record audit](installed-record-audit.json)
- [pip check output](pip-check.log)
- [Version collision report](same-version-collision-report.json)
- [Candidate file manifest](candidate-files-manifest.json)
- [Raw ZIP](unified-offline-wheelhouse-settlement-evidence-r1.zip), SHA-256 `C140D4C3AC902D4CD5FE51320285467C15D9BE2B58B98D11D8DDCB355AAF568B`; 151 members (150 manifest-listed files plus the embedded manifest), ZIP CRC and all listed payload hashes passed.
- [Copy receipt](COPY-RECEIPT.json), recording 73 sidecar/build-evidence file copies with source/destination SHA-256 and size equality, plus raw-ZIP validation.
