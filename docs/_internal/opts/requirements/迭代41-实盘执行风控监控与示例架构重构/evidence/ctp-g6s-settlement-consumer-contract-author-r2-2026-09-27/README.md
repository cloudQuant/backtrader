# G6-S settlement consumer contract r2 — isolated author candidate

**Disposition: `FAKE_ONLY / NO_RELEASE / G6-S CLOSED / G7-S CLOSED`.** This r2 candidate tightens the frozen r1 shape validator after independent QA found four bool-as-int admissions. It is still an injected-attestor consumer contract, not provider evidence, settlement authorization, or a runtime integration.

## Frozen parent and preserved counterexamples

- Frozen r1 author tree: `D:\temp\iteration41-g6s-settlement-consumer-contract-candidate-20260927`.
- r1 manifest SHA-256: `d39dbfa40185bd8f12704cd158c59a35d6737ef6a8d58d0a0aa165a144128486`.
- r1 raw candidate ZIP SHA-256: `9f4e2f169384c56dd2b95e755074c4035684c0140946d7dba623114c1236e8bb`.
- r1 author focus: 35 passed. Its original source, test, stdout, exit file, source snapshots, manifest, and ZIP are retained here as `r1-*` / `evidence/` lineage; those files were not modified.
- Independent r1 guardian QA: frozen target 35 passed and QA-only adversarial target 21 passed. The QA source, stdout/JUnit/exit files, report, candidate copy, and initial harness-error log are retained under `lineage-r1-independent-qa/` unchanged. The 21-case r1 QA includes the two deliberate reproductions showing that `True` generation values and `False` zero codes were admitted by r1; those are historical defect demonstrations, not valid r2 inputs. Its first fixture setup attempt produced 20 ACL setup errors and 1 pass; the raw log is retained, and the corrected 21-case run passed.
- Guardian QA archive SHA-256: `546cd325f670629e6d56798f6abd6c444bcf1d954e589c10860b3696d4f84749`; index SHA-256: `a72de98eebe0976708e88d4c103492f46f89aac5750d6f663167a589b48a51a2`; archive SHA256SUMS SHA-256: `517af45573d7dd3c0d70ed687b61656d851b9e49c46b919f11d842bc9eee0bd2`.

## r2 change

`ctp_simnow_settlement_consumer.py` now requires exact built-in `int` types for both query and current connection generations, requires both to be positive, and then compares each to the expected current generation. It treats native error/submit code as acceptable only when `None` or exact built-in integer zero. Python booleans therefore fail closed even though `bool` subclasses `int`.

The prior focused suite remains intact with four added parameterized negative cases: query generation `True`, current generation `True`, `error_code=False`, and `submit_code=False`. All are rejected before a fake write call. The r2 focused result is 39 passed; `py_compile` and guarded import smoke pass. Original r1 and independent-QA logs remain separately preserved for comparison.

## Settlement scope and constraints

- Only consume the already selected exact MD/TD pair. If exact current settlement cannot be shown from native provenance, the required behavior is fail closed with zero write; there is no time/set fallback, retry, or selection of another pair.
- The expected session TradingDay and connection generation are separately bound. The vendor settlement-confirmation row has `ConfirmDate` but no `TradingDay`; r2 checks `ConfirmDate` against the expected TradingDay without claiming it is a native TradingDay field.
- The fake attestor is injected. Consumer acceptance means only that the modeled contract fields are well-shaped and match the expected scope. It does not authenticate the attestor or independently recompute source/history digests.
- The SDK's clean G4-r2 settlement query path already passes filter intent and reads back native filter getters, but the settlement-specific source/callback history evidence builder and the main readiness consumption path remain separate gaps. Query-history digest is in-process evidence, not durable provider provenance. Do not extend the promoted result into an accepted certificate or source trust claim.
- This candidate is not imported by `backtrader_runtime`, registered in inventory, exposed by CLI, or wired to any writer. The returned flags remain `consumer_contract_satisfied=true`, `provider_source_trusted=false`, `execution_authorized=false`.
- No real SDK or `_ctp` import, native/provider call, credential/private config read, network use, order, settlement write, OS writer fence, or cross-query snapshot authority was exercised or established.

## Reproduction

The exact command, interpreter, import blocker, stdout, JUnit XML, and exit code are under `evidence/r2-*`. The disposable consumer environment and blocked modules are detailed in the command record. Candidate source and tests are the only functional changes from the copied r1 consumer/test pair; this tree is still an isolated, non-authorizing contract candidate.