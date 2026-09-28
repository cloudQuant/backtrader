# AC41-63 scanner-expansion independent QA — r1

**Disposition: NEEDS_REVISION.** The scanner-only r1 patch correctly surfaces the indirect syntax candidates and preserves the original inventory, but it breaks the checked-in disposition gate and introduces 9 Ruff findings relative to its exact base. This is coverage-only analysis; no writer closure, runtime reachability, or route authorization is claimed.

## Frozen input and isolation

- Author package: `D:\temp\ac41-63-writer-dynamic-audit-20260927`.
- Author `source-hashes.json` SHA-256: `E66A531F71AFD93F41F310DEA74405A1EC3A5CCA8ACD43DD720052D7D6152505`.
- Author `candidate.patch` SHA-256: `EC17E49D18C7BD9869AB799A4B0C90FDB7979581EB7BA3E71F2A80F5AE464021`.
- Candidate scanner SHA-256: `F5A38B56BC932B891DEC9AF885C6BA532638F6A8A33ECF858D9260B584FFFD48`.
- New contract test SHA-256: `9A86C2E4CAB14314D4DA79DC355B95518A6BE167261FC78FD3C35D885E42B71C`.
- All 349 source preimage hashes and the three declared analysis inputs matched. Strict `git apply --check --whitespace=error-all` and application passed in `D:\temp\iteration41-ac41-63-scanner-expansion-qa-20260927\isolated-source-r1b`; main source files were not changed by this QA.
- The source hash manifest contained no file under `runtime-ctp-private`; the isolated mirror included only the fixed directory summary and an inert synthetic sentinel. Instrumented `Path.read_text`, `Path.open`, `builtins.open`, and `io.open` recorded zero private-path accesses. No credential, provider, SDK, native module, network, or order operation was used.

## Scan identity

The independent base scan and frozen candidate agree on the original inventory. Stable verifier ID digest for the original 389 is `e482c7b95050c4573e10d0ee46829470877936cdd9f87f228772f82cf0327f7e`. The candidate preserves all 389 records and their relative order, then adds 56 records: 17 writer-alias candidates and 39 dynamic-alias/forwarder candidates. The candidate output matches the author's frozen `candidate-inventory.json`.

Both scans cover the same 349 Python source files. Candidate coverage reports 211 discovered paths, 0 missing baseline paths, 0 unclassified paths, 0 parse errors, and no scanned file from the private runtime subtree. All 56 supplemental rows retain `REVIEW_REQUIRED / NOT_AVAILABLE`.

## Functional and integration checks

Environment: CPython 3.11.5, pytest 8.0.0, Ruff 0.16.2. With top-level repository `conftest.py` excluded using `--confcutdir=tests/unit/scripts`, the existing collector tests, new indirect-dispatch test, and verifier tests produced **12 passed, 1 failed**. The only failure is the existing `test_checked_in_disposition_checklist_covers_current_inventory`: the 389-entry checked-in list cannot cover 445 scanner records.

The verifier CLI rejects the old checklist with exactly 56 `candidate_disposition_missing:*` reasons, `checklist_inventory_counts_mismatch`, and `checklist_inventory_digest_mismatch` (exit 2). In the isolated copy, generating a fresh conservative 445-entry review-required checklist returned `GENERATED_REVIEW_REQUIRED`, and verifying that generated skeleton returned `PASS`; all 445 entries remained review-required. The failing integration test is therefore fixed by a conservative checklist migration, not by weakening/skipping the test.

`py_compile` passed. Ruff comparison on the same pre-existing four files reported 71 findings at base and 80 with r1. The 9 new findings are 8 `UP006` type-annotation findings in newly added scanner code (`Dict`/`List`/`Tuple`) and one `I001` on the new test's imports. Existing lint findings are not attributed to this patch.

## Alias / getattr precision probes

In an inert fixture, the scanner correctly reported conditional `broker.buy`/`broker.sell` aliases and a fixed `getattr(..., "cancel_order")` call as writer candidates. A nonconstant conditional `getattr` whose branches include a writer name was surfaced as `indirect_callable_alias`, so the call is review-visible but the detector does not resolve which method is selected. A conditional `getattr` restricted to two read-only query names is also surfaced as a dynamic candidate: conservative overclassification, not a safety bypass.

Two additional conservative false positives were observed: a resource object's `.close` alias is treated as the `close` writer name; and an alias initially assigned `api.submit_order`, then rebound to `logger.info`, remains marked as `submit_order` because the local alias table accumulates names and does not kill entries on reassignment. These add review noise only while records remain review-required. The new author test covers the buy/sell and generic getattr cases but not these negative/rebinding cases.

## Conclusion

R1 is **NEEDS_REVISION** because its unchanged checked-in checklist fails the mandatory coverage gate and the patch adds 9 Ruff findings. The scanner's 389→445 expansion is useful and identity-preserving, but apply only after a frozen follow-up includes all 56 conservative checklist entries and removes the new lint delta. Even after that, disposition remains scanner-coverage-only and cannot be described as AC41-63 writer closure or route acceptance.

Raw outputs, scripts, comparison records, and logs are retained in this QA directory. The individual artifact SHA-256 values are listed in `r1-SHA256SUMS.txt`.
