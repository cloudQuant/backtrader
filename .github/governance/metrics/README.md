# Weekly Governance Record

Iteration 140 starts its observation window on **2026-08-22**. The triage
maintainer must publish one JSON record per completed Monday–Sunday week using
`../metrics-schema.json`; store the record in the approved internal evidence
location, not in this directory, when it contains contributor-identifying data.

## Required operating record

For each week, retain:

1. The `GovernanceMetrics` JSON record, including a clear source/query note.
2. The GitHub Ruleset Insights result for each long-lived branch.
3. The three GitHub/Gitee branch SHA comparisons and any divergence reason.
4. Links to every `master` hotfix, its `forward-port-required` issue, and its
   independently tested `dev`/`development` resolution.
5. A list of any administrator bypass, including the emergency reason and PR.

The first activation decision is **not before 2026-09-05**. At that review,
the maintainer must also have a complete dry-run record for a normal `dev` PR,
a core `development` PR, and a `master` hotfix PR. Do not create zero-filled
metrics as a substitute for missing operational evidence.

The review must additionally name and verify a second, independent GitHub
maintainer before treating the R2/R3 owner-plus-second-review requirement as
active. The currently confirmed `@cloudQuant` account alone is not evidence of
that separation of duties.
