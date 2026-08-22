---
title: Branch Governance
description: Three-branch model, PR routing, risk levels, and promotion/hotfix protocols
---

# Branch Governance

> Status: **In rollout** (Iteration 140; rulesets are in a two-week observation period from 2026-08-22)
> Repository: `cloudQuant/backtrader`
> Long-lived branches: `master`, `development`, `dev`

This document is the authoritative source for branch roles, PR routing, review
requirements, and cross-branch fix propagation. It supersedes any earlier
"`development` → `master` release chain" wording. When any other document
(`README.md`, `CONTRIBUTING.md`, `AGENTS.md`, PR/issue templates) disagrees with
this file, this file wins.

## 1. Mandatory branch facts

These definitions are the non-negotiable premise of this repository's
governance. They do **not** follow common GitFlow.

| Branch | Role | Allowed changes | Forbidden |
|---|---|---|---|
| `master` | Original Backtrader baseline | Bug, compatibility, or security fixes that reproduce on the original baseline | Routine features, optimization refactors, routine merges from `dev`/`development` |
| `development` | Improved & optimized version | Optimization capabilities, architecture improvements, regression fixes that only exist in the optimized version, controlled-integration daily development | Being treated as `master`'s release candidate or a reverse-sync source |
| `dev` | Daily development entry | Routine features, ordinary bug fixes, docs, tests, refactors, community contributions | Bypassing review to reach `development`/`master` directly |

## 2. Governance decisions (D0–D4)

Recorded decisions from Iteration 140. Unresolved items are blockers and must
not silently default to an assumption.

| ID | Decision | Outcome |
|---|---|---|
| D0 | GitHub default branch | **Keep `development`** (decided 2026-08-20). Contributors select the target branch explicitly via the PR template and `pr-governance` workflow, rather than relying on the default branch. |
| D1 | GitHub/Gitee authority & sync | **GitHub `cloudQuant/backtrader` is the review authority; Gitee `yunjinqi/backtrader` is a controlled mirror.** The mirror owner verifies long-lived-branch SHAs after every merge (see §8). |
| D2 | Owner team & admin bypass | **Resolved 2026-08-22:** `@cloudQuant` is the real GitHub user with admin access to this repository and is the CODEOWNER. Gitee mirroring uses the real `yunjinqi` account. No placeholder owner is permitted; any emergency bypass must be recorded in the PR. |
| D3 | Branch approval thresholds | `dev`: 1 approval + `Lint` + `Test Summary`. `development`: owner review; R2/R3 require owner + a second maintainer. `master`: R3 only (see §4). Rulesets begin in `evaluate` mode and may not be changed to `active` before 2026-09-05 and the observation evidence is reviewed. **Open exception:** only one real GitHub maintainer has been confirmed, so the second, independent R2/R3 approval is not yet enforceable and blocks active rollout for those paths. |
| D4 | Merge Queue threshold | Not enabled this iteration. Re-evaluate only after ≥3 PRs/day pending merge for 4 consecutive weeks, or recurring baseline conflicts. |

## 3. PR target-branch decision table

| Situation | Default target | Required evidence | Post-merge action |
|---|---|---|---|
| Docs, tests, routine features, ordinary bug fixes | `dev` | Associated tests, fast gate, ≥1 maintainer approval | Candidate for the next `dev → development` promotion |
| Problem that only exists in the optimized architecture, or an optimization-only feature | `development` | Optimization-only minimal repro, risk note, domain-owner approval | Decide whether an equivalent fix is needed in `dev` |
| Real bug / security issue in original Backtrader | `master` | Independent repro on `master`, regression test, original-API compatibility note | Create a forward-port issue; never close `dev`/`development` risk with "fixed on master" |
| Fix whose semantics differ across branches | Separate PRs | Independent implementation + tests per target branch | Cross-link PRs/issues; forbid blind merge or cherry-pick |

## 4. Risk levels (R0–R3)

| Level | Typical paths | Minimum review | Minimum verification |
|---|---|---|---|
| R0 docs/tests | `docs/`, test comments, non-behavioral tooling | 1 maintainer | Format, affected tests, docs build |
| R1 routine module | Localized fix to a single indicator/analyzer/feed | 1 module owner | Fast CI + new/modified regression tests |
| R2 core/compatibility | `lineroot`, `linebuffer`, `lineseries`, `lineiterator`, `cerebro`, `strategy`, `broker`, `brokers/`, `feeds/`, `metabase` | Domain owner + a second maintainer | Fast CI, `make test-strategies`, runonce/runnext or compatibility evidence |
| R3 baseline/security/release | `master` hotfix, supply chain, security, public-API break risk | Explicit core-maintainer approval | Full target-branch suite, minimal repro, regression, release/security check |

## 5. Target workflow

```text
Routine community contribution
fork / feature/*  ── PR + fast gate ──> dev
                                          │
                                          │  controlled promotion PR + full gate
                                          ▼
                                     development

Optimization-only issue
feature/* ── PR + optimization gate ──> development

Real original-baseline bug
hotfix/master-* ── PR + original-baseline gate ──> master
                                              │
                                              └─ create forward-port task: evaluate and port to dev / development separately
```

## 6. Promotion protocol (`dev` → `development`)

A promotion is a **controlled PR**, not a routine merge.

1. Open a `promotion/dev-YYYYMMDD` PR targeting `development`.
2. Describe: change scope, explicitly excluded content, full verification,
   performance/compatibility differences, and the rollback point.
3. Run the full gate (`make test-strategies`, runonce/runnext parity, or
   strategy-baseline comparison) for R2/R3 content.
4. Get owner + second-maintainer approval per §4.
5. Merge; record the promotion in the weekly governance summary (§12).

## 7. `master` hotfix forward-port protocol

Every `master` fix must produce a **linked forward-port issue** before the fix
is considered governance-complete.

1. Reproduce on `master` independently; land `hotfix/master-*` PR (R3 gate).
2. Create a `forward-port-required` issue describing the fix.
3. Evaluate `dev` and `development` **separately** for whether each is affected.
4. For each affected branch, implement an **equivalent port with independent
   tests** — never a blind cross-branch merge or cherry-pick.
5. Mark `forward-port-complete` only after each affected branch is verified.

A hotfix that has not completed forward-port is **not** governance-done.

## 8. GitHub / Gitee mirror consistency

- GitHub is the review authority; Gitee is a controlled mirror.
- After each long-lived-branch merge, verify both remotes report the same SHA:

```bash
git ls-remote --heads https://github.com/cloudQuant/backtrader.git master development dev
git ls-remote --heads https://gitee.com/yunjinqi/backtrader.git master development dev
```

- The mirror owner is the same maintainer using GitHub `@cloudQuant` and Gitee
  `yunjinqi`. Any divergence must raise an alert and be resolved by that owner.
  A documented reason is required for any recorded difference.

## 9. Labels

Standardized label taxonomy (applied via GitHub; see the runbook in §10):

| Prefix | Values |
|---|---|
| `target:*` | `target:dev`, `target:development`, `target:master-hotfix` |
| `type:*` | `type:bug`, `type:feature`, `type:docs`, `type:tests`, `type:refactor` |
| `area:*` | `area:core`, `area:broker`, `area:feeds`, `area:indicators`, `area:analyzers`, `area:observers`, `area:tests`, `area:docs`, `area:ci` |
| `risk:*` | `risk:R0`, `risk:R1`, `risk:R2`, `risk:R3` |
| `status:*` | `status:triage`, `status:review`, `status:blocked` |
| Action | `needs-repro`, `needs-tests`, `ready-to-merge`, `blocked`, `backport-or-forward-port-required`, `forward-port-required`, `forward-port-complete` |

## 10. External setup runbook (manual, admin-only)

The repository-internal artifacts below (manifest files, `CODEOWNERS`, and the
verification script) express the expected GitHub configuration. Applying the
real settings requires admin access and is done manually via UI/API — **CI never
holds admin credentials.**

### 10.1 Default branch (D0)

No change: keep `development` as the default branch. Target-branch selection is
enforced by the PR template and the `PR Governance` workflow, not the default.

### 10.2 Rulesets (D3)

Apply one ruleset per long-lived branch, matching
`.github/governance/rulesets/{dev,development,master}.json`:

1. Repository → Settings → Rules → Rulesets → **New ruleset**.
2. Set the target to the branch (or `fnmatch` pattern) per manifest.
3. Start with `evaluate` enforcement until 2026-09-05. The manifests require a
   pull request, ≥1 approval, `Lint`, `Test Summary`, `PR Governance`, and
   `Tiered Validation`; they also block force-push/deletion and require resolved
   conversations.
4. GitHub Rulesets cannot natively decide a PR head-branch naming convention or
   require a label. After observation, the required `PR Governance` check is
   the enforcement point for `hotfix/master-*` and `target:master-hotfix` on
   `master`; the template and human review require the minimal repro and R3
   evidence.
5. Apply the JSON through the repository Rulesets API or UI, then verify it with
   `scripts/ci/verify_github_governance.py`. Do not give the CI workflow an
   admin token.

The current manifests intentionally require one approval because only one real
GitHub maintainer (`@cloudQuant`) has been confirmed. They do **not** make a
single person count as the required second independent maintainer for R2/R3.
Add and verify a second maintainer before enabling active rules for those paths;
until then, record the exception and keep the Rulesets in observation mode.

### 10.3 CODEOWNERS (D2)

`.github/CODEOWNERS` uses the confirmed GitHub user `@cloudQuant`, not an
organization placeholder. It has repository-admin access as of 2026-08-22;
the Gitee `yunjinqi` identity is intentionally not a GitHub CODEOWNERS entry.
After the file reaches the default branch, verify the GitHub
`codeowners/errors` response is empty.

### 10.4 Labels

Create the labels in §9 once (Repository → Issues → Labels). The
`classify_pr_risk.py` script emits suggested labels; maintainers retain final
override authority.

## 11. Verification

```bash
# Export read-only API responses without committing them.
gh api --paginate repos/cloudQuant/backtrader/rulesets > /tmp/backtrader-rulesets.json
gh api repos/cloudQuant/backtrader/codeowners/errors > /tmp/backtrader-codeowners-errors.json

# Ruleset + CODEOWNERS consistency. `evaluate` is expected during observation.
python scripts/ci/verify_github_governance.py \
  --rulesets-json /tmp/backtrader-rulesets.json \
  --codeowners-errors-json /tmp/backtrader-codeowners-errors.json \
  --expected-enforcement evaluate

# PR risk classification
python scripts/ci/classify_pr_risk.py --paths backtrader/cerebro.py

# Unit tests for both scripts
pytest tests/unit/scripts/ -q
```

## 12. Observation and activation record

The administrator creates the three Rulesets with `evaluate` enforcement and
keeps `GOVERNANCE_BLOCKING=false` through **2026-09-05**. During that period,
record all Rule Insights, missing check contexts, mirror drifts, and PR routing
exceptions in the weekly governance record. Only after a maintainer reviews
that evidence may the administrator change the three Rulesets to `active` and
set `GOVERNANCE_BLOCKING=true`; the activation commit/PR must link the evidence.
This is intentionally not an automatic time-based switch.
