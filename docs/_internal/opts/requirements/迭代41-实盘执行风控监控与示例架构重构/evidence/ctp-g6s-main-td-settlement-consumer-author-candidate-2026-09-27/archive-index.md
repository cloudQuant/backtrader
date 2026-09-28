# G6-S main TD settlement consumer candidate archive

Status: `AUTHOR_CANDIDATE / FAKE_ONLY / NOT_INDEPENDENTLY_ACCEPTED`.
This evidence copy preserves the isolated candidate’s source manifest, freeze receipt, changed source/test, textual diffs, focused run artifacts, source-origin/optional-SDK guard, static checks, and the SDK G4-r2 input manifest/receipt. The frozen candidate remains at `D:\temp\iteration41-g6s-main-td-settlement-candidate-20260927` and was not modified during archiving. Main production files were not modified.

## Frozen identity

- Candidate root: `D:\temp\iteration41-g6s-main-td-settlement-candidate-20260927`
- Candidate source manifest SHA-256: `1fd47cff2514fa25e4298efe7051989ad97427c8056693374004791d6b983661` (117 payload entries; this archive is a receipt/source-diff copy, not a duplicate of all 117 files)
- Candidate freeze receipt: `freeze-receipt.json`
- Runtime source SHA-256: `368446CE5A8972AF7360039A7C79C42AAA10BA413CEB58F6FFEFF3D03F1F0D41`
- Focused test SHA-256: `2FE41CB9B271F5817B14D6319493D4152786B2F1FABA82866F20216967478794`
- Exact main-tree baseline SHA-256 values are recorded in the receipt; both were verified unchanged after the candidate work.

## Verification record

CPython 3.11.5 at `C:\anaconda3\python.exe`; run from the candidate root with candidate-only `PYTHONPATH`, plugin autoload disabled, and bytecode writing disabled. Exact command is preserved in `evidence/command-and-environment.txt`. Result: **22 passed, 0 skipped, exit 0**. The raw pytest log, JUnit XML, exit code, source-origin SDK-block guard, its output, and static-check log are retained in `evidence/`.

Negative cases assert zero settlement/order/cancel write calls, including absent verifier, stale source digest, verifier failure/wrong evidence type, stale or mismatched evidence, account/day/generation and record mismatch, and malformed/prior write-count conditions. A fake native-shaped row with `ConfirmDate` and no `TradingDay` is accepted under the fake contract. No native SDK was loaded; no provider, account, network, credential, or private-config access occurred.

## Trust boundary and disposition

The verifier is a typed Python injection and its source-manifest digest is a checked claim. This is **not** an OS trust boundary, does not prove the verifier’s implementation or installed SDK bytes, and is not a cross-process signature or durable inbox. No production verifier is present by default; the consumer remains fail-closed without it. The referenced SDK G4-r2 source candidate is copied only as its source manifest and freeze receipt; its independent QA is pending. No G4 or G6-S acceptance is claimed, and no default route, pin, wheel, or production source was changed.

The initial pytest attempt from the main repository CWD imported the main checkout rather than the candidate and is explicitly superseded; that failure is described in `freeze-receipt.json`. The accepted 22-pass run used the candidate as the working directory and has its origin guard output archived.

