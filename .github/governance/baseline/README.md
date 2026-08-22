# Governance Baseline

This directory records **how** the pre-iteration governance snapshot was taken,
and **where** the evidence lives. It intentionally stores **no sensitive API
responses, tokens, or private credentials**.

## Snapshot commands

Run the following with a read-only / minimal-scope credential before any
governance change, and record the output to an external, non-committed store:

```bash
# Default branch
gh repo view cloudQuant/backtrader --json defaultBranchRef

# Rulesets
gh api repos/cloudQuant/backtrader/rulesets

# Labels
gh label list --repo cloudQuant/backtrader --limit 100

# Long-lived branch SHAs
git ls-remote --heads origin master development dev
```

## Snapshot record

| Item | Timestamp | Summary | Evidence location |
|---|---|---|---|
| Default branch | 2026-08-20 | `development` | `gh repo view ... --json defaultBranchRef` output (external) |
| Rulesets | 2026-08-20 | none configured | `gh api .../rulesets` output (external) |
| Branch protection | 2026-08-20 | none configured | not captured (see rulesets) |
| CODEOWNERS | 2026-08-20 | absent | repo state at `.github/CODEOWNERS` (added in Iteration 140) |
| Long-lived branches | 2026-08-20 | `master`, `development`, `dev` all present | `git ls-remote --heads origin` |
| D2 owner confirmation | 2026-08-22 | GitHub `@cloudQuant` is a real repository admin; Gitee mirror identity is `yunjinqi` | `gh api user`, collaborator-permission response, and configured push URLs (external) |
| Mirror comparison | 2026-08-22 | `master` and `dev` matched; `development` diverged (GitHub `95c7302f`, Gitee `d8b6da88`) | paired `git ls-remote --heads` output (external); tracked as a rollout repair item |
| Rollout start | 2026-08-22 | Rulesets are created in `evaluate`, not active, mode; blocking policy remains disabled through 2026-09-05 | Rulesets API response and Rule Insights (external) |

> **Do not commit** API responses containing user lists, teams, or any token-like
> values. Commit only the command, the timestamp, the one-line summary, and a
> pointer to the external evidence store.

## Re-baselining

When any D0–D4 decision changes, or when rulesets/labels/CODEOWNERS are
modified, append a new row to the table above rather than editing history.
