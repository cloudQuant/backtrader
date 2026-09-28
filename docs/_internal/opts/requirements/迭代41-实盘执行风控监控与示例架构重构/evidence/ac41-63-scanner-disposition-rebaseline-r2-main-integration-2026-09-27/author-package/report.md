# AC41-63 writer disposition rebaseline, 460 candidates

## Result

The fresh read-only collector found 460 active candidates: 363 writer calls and 97 dynamic execution calls across 355 files, with zero parse errors and zero unclassified paths. The exact scanner artifact is `target/live-execution-inventory-candidates.json` (SHA-256 `D81C98A73E32B8D2CFB39034FCC1DCEAD7EA5434CDF38C8ADC30AB6B47A60710`). Its scope baseline is unchanged; the new G6 directory is included in the scanner's already-classified path set.

This r2 packet proposes an official-inventory/checklist rebaseline only. It preserves `NO_WRITE / LIVE_NO_GO`; all 460 active rows and six historical tombstones remain `REVIEW_REQUIRED / NOT_AVAILABLE`. The evidence remains static inventory/disposition integrity and grants no writer closure, route admission, or write authorization.

## Reconciliation

- The prior official checklist had 445 rows. Six IDs disappeared from current static discovery and are retained as tombstones, leaving 439 prior IDs active.
- G6 integration adds 21 newly discovered IDs (20 writer candidates and one dynamic execution candidate), producing 439 + 21 = 460 active rows.
- All previous 445 rows remain available in the active checklist or tombstone archive with their original dispositions. The baseline 389 ordered IDs and canonical payload digest are preserved in checklist metadata; the recorded 389 payload SHA-256 is `AEC51E6B4E4C186FE959C86868A96BDFB8E14C5BBF1DA539793EE48B89D54D27`.
- The six tombstones are: i41-writer-53c79013abdaf0c12bb1, i41-writer-78a383b74fdb54d3cd7d, i41-writer-8eb4d6d3af6bfe6363a8, i41-writer-c365b35e32c5c8eb3c54, i41-writer-d23e870f6f57d76a755e, i41-writer-fbe05d71d70ed65a9838.
- The 21 G6 IDs are: i41-writer-033a6d3492e283a6cab0, i41-writer-0839d47b1ee5e48be7f4, i41-writer-1026c45e4c9156f811ba, i41-writer-1ea0d830505fd8dc9cc5, i41-writer-4ca5fc53348f1f008a7a, i41-writer-5f5016356e1caeee411f, i41-writer-698985163dc6a866fbaa, i41-writer-6b8d23074a58e4a3a228, i41-writer-6c0a36772443adc4bac6, i41-writer-71930b2c039462578bbf, i41-writer-7efb437579fca2e99980, i41-writer-7f73319f511d87e45de3, i41-writer-8b49231c5a71f5759c11, i41-writer-8c75f3ada8308e550962, i41-writer-b1d03654fed3c00d68a4, i41-writer-baf12e0c3aa8e5672a67, i41-writer-d9cb3917dfd979c14f07, i41-writer-e23724e1fbe73d86b09c, i41-writer-e7052d2b9d1eda1be714, i41-writer-ea3b383559b59127b2f0, i41-writer-fbc7eb19201080da507e.

## Source and patch identity

- Patch SHA-256: `D5DE326F61EDE3D4776392C158587B89A7098B38274C8B6C0E7AB7B0BB0D319D`.
- Exact main preimages and target hashes for all four changed files are in `rebaseline-patch-manifest.json`.
- Collector SHA-256: `B37ED7A309C057B4F97AB8E96FE20D3E840D54084B6BCA8EDBEF3491230AB6E3`.
- Scope-baseline SHA-256: `C473B4390D70477978C0EB9673E267244D78A57D0ACB2E8DF6D5F7D3BFA60DD7`.
- G6 r4 manifest SHA-256: `8BFCFB67C5D8DE21D56E3D03D63478F81375E65F86B0F8C98E144A197B7F994F`; G6 addition patch SHA-256: `E9C3996CC836C2D7628BA92C569060CFA78C140768CF612DB7F395F66CF2CA22`.
- All six G6 scanned Python source hashes match the integrated r4 source hashes. One test-only file changed after r4 (`tests/unit/runtime/test_local_fake_account_actor_candidate.py`): r4 `67FE20C2CBDE93CD2B29B21E85472C4675A4D43DDB50A6DF546B442CA3B99018`; current `4FCE80027D16D4618B82BD9C6CBC93CFD05A3C45301B4453227C21BB08923EE5`. It is not scanned and does not alter the 460 rows.

The collector was rerun after the test-only edits. The frozen inventory is that fresh output; candidate records remain identical to the prior post-G6 scan. Current counts and zero-unclassified result are embedded in the inventory and bound by its raw hash.

## Verification

- Candidate focused suite: `6 passed in 8.05s`, including missing/null preservation, missing lineage, and malformed `null`/unhashable baseline, previous-ID, tombstone, and new-ID inputs returning rejection reason codes rather than raising.
- Checklist CLI: `PASS`, 460 discovered / 460 checklist rows, six tombstones, and all 460 active rows review-required.
- `py_compile`: exit 0. Project-config Ruff: all checks passed.
- Black check: the installed Black version cannot parse project `py312` target metadata. Explicit Python 3.11/100-column checks return nonzero on both pristine preimage and candidate because of existing unchanged spans; newly added/changed lines are Black-formatted and introduce no new Black diff. The exact baseline/candidate observations are in `test-results/black-check.txt`.
- Strict `git -c core.autocrlf=false apply --whitespace=error --check` passes on current main and the exact-base replay. The replay produces the four exact target SHA-256 values in the patch manifest. This packet did not apply the patch to main.

## Replay instructions for independent QA

From `D:\source_code\backtrader`, first verify the four preimage hashes in `rebaseline-patch-manifest.json`, then run:

```powershell
git -c core.autocrlf=false apply --whitespace=error --check D:\temp\iteration41-writer-inventory-disposition-rebaseline-460-r2-20260927\writer-inventory-dispositions-460-r2.patch
```

Replay in a disposable exact-base checkout and verify the four raw target hashes before running the focused pytest command, the CLI command recorded under `test-results`, `py_compile`, and Ruff. Do not apply this patch to the shared main tree before independent QA. The new checksum index uses actual newline delimiters and covers each packet file except itself.
