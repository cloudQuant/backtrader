# G5 worker handoff follow-on candidate archive

Status: `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`; G5 is **not accepted**.

This archive preserves the isolated follow-on candidate that addresses the
worker `stage_prepared_dispatch(..., action_identity=...)` call-shape gap found
in the earlier OrderRef/ActionRef candidate. The author candidate ZIP contains
the source snapshot, tests, generated patch, manifests, README, and evidence.
Detached copies of the key review artifacts are provided here for direct
inspection:

- [Candidate ZIP](worker-handoff-candidate.zip)
- [Candidate output manifest](output-manifest.json)
- [Frozen input manifest](frozen-input-manifest.json)
- [Backtrader follow-on patch](worker-handoff.patch)
- [Author candidate README](author-candidate-README.md)
- [Copy hash verification](copy-hash-verification.json)
- [Focus tests](focus-tests.log), [frozen SDK tests](frozen-sdk-tests.log),
  [Ruff](ruff.log), [py_compile](pycompile.log), [patch application](patch-apply-check.log),
  [patch stat](patch-stat.log), and [frozen input integrity](frozen-input-integrity.log)

## Frozen identities

- Candidate output manifest SHA-256: `D9641AAF6757CF5AEFF4A5246C42EDB36B4BF6036268E05FF2134F41235D0E62`
- Follow-on patch SHA-256: `331B5AD8BE656815DBFD72D743587BB641767011B414C82A0CE4DCAF156A1F6D`
- Candidate ZIP SHA-256: `92B3ADD8E73DC51E7552A1C439D2663EBB20053E755C4DCF9194CAB39C53B4B3`
- Frozen input manifest SHA-256: `79BAB5C0C0E136B722EF5F55C74F93ABA2920F138A629B9AB8B4506D29003827`
- Archived independent QA manifest SHA-256: `37feac2934a3863c2bcdd5157c153d49d492f7b445f1936f6c7d7a13d76a7d1f`

The source identities are Backtrader `ad2c142b9a8b42cede85886528c681abdfcb8096`
and SDK snapshot `2700cb5454ef4c3d1780eda28b6f33307a860998`. The preceding
[independent QA report](../iteration41-g5-orderref-actionref-independent-qa-2026-09-27.md)
reproduced the old worker keyword `TypeError`; it predates this follow-on and
is not independent acceptance of this archive.

## Candidate checks

The author-run follow-on focus reports **21 passed**; the frozen SDK suite
reports **57 passed**. Targeted Ruff and `py_compile` passed. `git apply
--check` and application succeeded for the two-file Backtrader patch, and the
applied files match the candidate files after LF normalization. The focus
covers one-argument submit, typed ActionRef staging, pre-stage retry,
projection readback/target mismatches, receipt persistence failure, uncertain
sender receipt, and crash after claim. UNKNOWN remains terminal and no replay
is observed in those fake cases.

## Limits

The frozen SDK snapshot lacks the target-projection producer, durable
projection table, and readback API. The worker tests install a same-Store fake
readback port; that is not the real target ledger, native query verifier, or a
reviewed SDK pin. Caller-supplied OrderRef and ActionRef seeds remain assertions,
not native account watermark evidence. No provider or real account was used.
The candidate is not registered, installed, or a trading route; this archive
does not establish G5 or production acceptance. Default managed CTP writes
remain closed.
