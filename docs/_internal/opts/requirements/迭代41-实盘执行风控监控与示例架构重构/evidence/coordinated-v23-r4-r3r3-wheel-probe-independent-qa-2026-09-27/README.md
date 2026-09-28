# Coordinated V23 / R4 / R3r3 wheel probe: independent QA

**Result:** `FAKE_ONLY / NO_RELEASE / G1-G5_NOT_ACCEPTED`. This QA does not change default pins, enable a route, or authorize trading. No provider, credentials, CTP native module, remote endpoint, or live execution was used.

The frozen author input source manifest is SHA-256 `01fa737d2a0f385dec8ce6187d95c4a104c13cce9dde6d693152df7dd94ef4b6`; the author evidence archive is SHA-256 `9510abeffcf040bf4a7ea8b8e0524e93cfe1046a8b9498dbc7e26626adbb2c46`. Its ZIP contains 1,015 indexed payloads plus one byte-identical `ARCHIVE-INDEX.json` self-index, 1,016 members total. The live author candidate directory had 472 unmanifested main-overlay cache/bytecode files at capture; those are excluded from the 843-file frozen source manifest.

Independent fresh-venv runs passed 73 main bridge/L2, 20 cancel control, 6 artifact-set, and 44 parent issuer/control tests: 143 executions, 123 unique node IDs, 20 repeat executions, zero failures/errors/skips. Execution and parent build A/B wheel pairs were byte-identical; installed wheel payloads and RECORD values, PEP 610 direct URLs and hashes, and `pip check` were verified. `bt_api_base` remains SOURCE-ONLY: its runtime wheel was removed; tests used a copied source root and source-only metadata. All four runner outputs reported `NATIVE_MODULES_LOADED []`; guard logs showed zero blocked network/native/private-config/origin events.

## Base uninstall correction

The initial `pip uninstall` ran with `PYTHONPATH` set to the source-only metadata root. Pip resolved `bt_api_base` metadata outside the venv, reported “Not uninstalling … outside environment,” and found no venv files to remove; its exit code was zero, but this was **not** counted as a successful uninstall. The preserved log is [pip-uninstall-base-initial.log](pip-uninstall-base-initial.log). The correction cleared `PYTHONPATH` for uninstall; the preserved [corrected log](pip-uninstall-base-corrected.log) shows successful removal. `PYTHONPATH` was then set to source-only metadata for the corrected [pip check](pip-check-corrected.log), which reported “No broken requirements found.”

See [independent review](independent-qa-review.md), [machine receipt](independent-qa-receipt.json), and [raw QA ZIP](independent-qa-evidence.zip) (SHA-256 `6f90ed890e0eb638f3e4b141fa0433c1cce854cc25661bf07fcccfbfb2ac9ddd`). The ZIP index is [independent-qa-archive-index.json](independent-qa-archive-index.json) (SHA-256 `f0d3db483b402ab440a09badb6969ab384dc3ca3c845b1e3a91b3c6b05a8fcd4`). Copy source/destination hashes are in [COPY-RECEIPT.json](COPY-RECEIPT.json); the per-file archive checksums are in [SHA256SUMS.txt](SHA256SUMS.txt).

This remains local offline fake-only evidence. It does not accept G1/G2/G3/G4/G5, release the wheels, or authorize real CTP trading.
