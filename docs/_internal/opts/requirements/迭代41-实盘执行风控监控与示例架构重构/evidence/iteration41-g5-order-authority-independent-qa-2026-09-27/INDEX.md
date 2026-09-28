# G5 OrderRef / ActionRef worker-handoff independent QA archive

**Disposition: G5 NOT ACCEPTED / NO_WRITE / LIVE_NO_GO.** This archive covers an isolated, offline candidate only. It does not accept or enable the default CTP route.

## Review result

- Frozen candidate: 50 input entries and 91 output entries were independently hash-checked. Candidate ZIP SHA-256: `92b3add8e73dc51e7552a1c439d2663ebb20053e755c4dcf9194cab39c53b4b3`.
- Independent run: candidate focus `21 passed`; frozen SDK package focus `57 passed`; adversarial fake-only probes `3 passed`; Ruff clean on the six changed files.
- The candidate-positive cancel path depends on a test-only monkeypatch that provides `_VerifiedTargetProjection` and an in-memory `read_ctp_order_target_projection`. The exact frozen Store has no target-projection type, producer, or durable readback API. With that API absent, the real frozen Store rejects cancel staging before creating a command or handoff row.
- The positive fake seam demonstrates consumer-side checks only. It is not evidence of a persisted target ledger, native callback/session verification, provider state, SDK release integration, or accepted OrderRef/ActionRef authority.
- No native SDK, provider, account, credential, private config, network, or real trading route was touched. No main production file/default route was changed.

## Files

- [Full independent QA report](packet/README.md)
- [Original independent QA packet ZIP](independent-qa.raw.zip), SHA-256 `d47c64ac32837cdc89a00a3839d70199de76c003c4983d42b74e637c81c11540`
- [Frozen candidate ZIP](packet/candidate.zip), SHA-256 `92b3add8e73dc51e7552a1c439d2663ebb20053e755c4dcf9194cab39c53b4b3`
- [Packet manifest](packet/packet-manifest.json), SHA-256 `f6d0807ee682fbda6cda61e2255fd17d91a58b0f079f4aed67de295070021bf3`
- [Copy receipt](copy-receipt.json) and [per-file verification](copy-verification.json)
- [Archive manifest](archive-manifest.json) lists each archived file's size and SHA-256. `SHA256SUMS.txt` is a convenience digest list; it does not hash itself.

The independent QA source copy, test logs, module origins, static producer scan, patch-application log, fake probes, frozen input/output manifests, and candidate ZIP are retained under `packet/`.