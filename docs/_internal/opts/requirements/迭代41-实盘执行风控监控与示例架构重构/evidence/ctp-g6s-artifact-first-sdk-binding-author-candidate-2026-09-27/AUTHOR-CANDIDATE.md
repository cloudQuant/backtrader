# G6-S artifact-first SDK binding — AUTHOR_CANDIDATE / NO_WRITE

**Status:** `AUTHOR_CANDIDATE/NO_WRITE`; independent review is pending. This page records a candidate only. It does not grant write authority and is not G4 or G6-S acceptance.

## Frozen inputs and archive

- Isolated candidate: `D:\temp\iteration41-g6s-artifact-first-sdk-binding-candidate-20260927`
- Source manifest: [`candidate-source-manifest.json`](candidate-source-manifest.json), SHA-256 `bbf863557deb20dcadf766fcb98eeabca97922c0cc72e543f5468e59fce480c4`, 139 payload files.
- Freeze receipt: [`freeze-receipt.json`](freeze-receipt.json), SHA-256 `79b633ff8bac9d9c18e3cfacd4c54382db1d9c8e999d133a7edc20080f4e0738`.
- Archive index: [`ARCHIVE-INDEX.json`](ARCHIVE-INDEX.json), SHA-256 recorded in [`archive-bundle-receipt.json`](archive-bundle-receipt.json).
- Source/evidence ZIP: [`artifact-first-candidate.zip`](artifact-first-candidate.zip), SHA-256 is recorded in [`artifact-first-candidate.zip.sha256`](artifact-first-candidate.zip.sha256).

The archive contains the exact 139 manifest payload files, the candidate manifest and receipt, this page, and the archive index. ZIP integrity and payload byte hashes were rechecked after copy.

## Change summary

The isolated candidate removes caller-supplied verifier/policy parameters from the public readiness path. A no-argument pre-client gate requires a code-owned artifact policy; that policy remains `None` by default. If a policy is later code-pinned, the bridge checks unique package/dist-info identity, metadata, RECORD and member hashes/sizes, package inventory, critical source and extension digests, import path/hook state, module specs/origins/loaders, and exact imported evidence class identity. Fake tests exercise tampering and same-name/module spoofing. The native extension is not loaded in the tests.

## Verification

- CPython 3.11.5, candidate-root `PYTHONPATH`, plugin autoload disabled, bytecode writes disabled.
- Focused suite: **36 passed, 0 failed, 0 skipped**. Exact stdout and JUnit are under `evidence/artifact-first-run/` in the archive.
- Fresh-process guard found both candidate module origins under the isolated tree, code-owned pin unset, and zero `bt_api_ctp` modules loaded.
- The first path-hook test iteration failed because its fixture had not cleared fake SDK modules from `sys.modules`; the failure and correction are recorded in `evidence/artifact-first-run/intermediate-run-note.md`. The final run is 36/0/0.

## Limits

No production SDK wheel, code-owned release pin, native hash pin, independently signed source provenance, protected file handles, or ACL verification is present. The fake test policy is not production authority. Main repository production files and the SDK candidate were not modified. No native code, provider, network, account, credentials, or private configuration was accessed. Independent SDK and consumer review remains pending.

