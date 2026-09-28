# AC41-63 scanner expansion r2c2 — independent QA receipt

Verdict: **SAFE_TO_APPLY_SCANNER_COVERAGE_ONLY**. This permits scanner/checklist coverage integration only. It does not close any writer, prove reachability, authorize a live route, or imply production acceptance.

## Frozen input and exact-base replay

- Candidate: `D:\temp\ac41-63-writer-dynamic-audit-20260927\candidate-r2c2`
- Final manifest `source-hashes.json`: SHA-256 `58dd6bc0301696ab41d8ce2663e1e8361707b95857e7ad0ae59fe1045f5345fd` (this supersedes the earlier pre-validation manifest SHA `e8fae722…b5fb870`).
- Patch `candidate-r2c2.patch`: SHA-256 `0222705fd2898c3cf2eded9f8bb7591d0a4a4ad6ace4577ed0450a1bc8788bd5`.
- Verified all 349 scanned-source preimage hashes and all five analysis-input hashes against the current main input. No `runtime-ctp-private` source file was in the candidate manifest. Isolated replay root: `D:\temp\iteration41-ac41-63-scanner-expansion-qa-20260927\isolated-source-r2c2`.
- Strict `git -c core.autocrlf=false apply --check --whitespace=error-all` and apply both succeeded. All four raw target files matched author hashes exactly:

| Target | SHA-256 |
| --- | --- |
| `scripts/collect_iteration41_writer_inventory.py` | `b37ed7a309c057b4f97ab8e96fe20d3e840d54084b6bca8edbef3491230ab6e3` |
| `tests/unit/scripts/test_collect_iteration41_writer_indirect_dispatch.py` | `be777538ac686463edf07c96d3848715b714d368126a160e42888c4331931db6` |
| `tests/unit/scripts/test_verify_iteration41_writer_dispositions.py` | `e1e9a96a040ac510b4bb48a13195651d71199d9c4b7071083eb617b14f3b3f49` |
| `docs/_internal/opts/requirements/迭代41-实盘执行风控监控与示例架构重构/evidence/live-execution-writer-dispositions.json` | `e6ece21e16af6c6a6220431dd0c2669d81206a136b500dfd5214ca766818e841` |

The checklist output is 454,683 bytes, LF-only (9,837 LF, zero CRLF), preserving the exact-base main checklist's LF convention. This resolves r2b's whole-file CRLF rewrite; r2b itself remains `NEEDS_REVISION` and is not the accepted replay target.

## Independent checks

- Focused scanner, alias-dispatch, and disposition-verifier tests: **14 passed**.
- Checklist CLI verifier: **PASS**, 445 discovered / 445 checklist / 445 `REVIEW_REQUIRED`; all dispositions remain `NOT_AVAILABLE`.
- Scanner: 349 files, 344 writer candidates, 101 dynamic candidates, 211 discovered paths, zero parse errors, zero missing baseline paths, zero unclassified paths; status remains `CANDIDATE_DISCOVERY_ONLY`.
- Old 389 checklist records preserved semantically and in order; old ID digest remains `e482c7b95050c4573e10d0ee46829470877936cdd9f87f228772f82cf0327f7e`. The 56 suffix records exactly match new scanner candidates and all are `REVIEW_REQUIRED / NOT_AVAILABLE / UNRESOLVED_POTENTIAL_LIVE_WRITE`. Candidate digest: `33ec3e5bcd575cab2bf63a4300c535016c0095d514c67d351c0d0af302c0a973`.
- `py_compile` and project-config Ruff passed on the changed/new Python files.
- Inert AST probe caught direct `buy`/`sell` aliases, fixed `cancel_order` `getattr`, and a conditional writer-or-query `getattr` as a dynamic candidate. The probe also records conservative false positives: read-only conditional `getattr`, `resource.close`, and a stale writer alias after rebinding. These remain review-only entries, not safety bypasses.
- Private-state check used a synthetic sentinel only in the isolated mirror; zero actual private files were copied. The scanner omitted the sentinel and private source paths, reported the private state summary as omitted, and the instrumented `Path.read_text`, `Path.open`, `builtins.open`, and `io.open` hooks saw zero private-path reads.
- No SDK/provider imports, credentials, network, or write actions were used. Main repository and frozen author candidate were not edited by this QA.

## Reproduction evidence

Raw command outputs, exact-byte replay summary, scanner output, verifier output, alias/private probe, and the QA-only scripts are listed in `r2c2-SHA256SUMS.txt` in this directory. The focused test log includes its exit code; it reports `14 passed in 15.37s`.
