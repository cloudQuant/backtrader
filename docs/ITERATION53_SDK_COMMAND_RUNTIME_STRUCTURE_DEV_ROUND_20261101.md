# Iteration 53: SDK command runtime structure

Repository: Backtrader, branch: dev.

Scope: introduce the provider-neutral command scheduler and Broker completion
inbox as one state owner. The Store integration is a separate, still-uncommitted
structural change; this round does not claim that the live Store uses the module.

Acceptance for this structural round: independent static source review of the
single-owner boundary and proposed Store integration. No tests or account
operations were run. During later acceptance, investigate the worker top-level
exception path and the lock-held callback/reentrancy contract; functional,
lifecycle, and account acceptance remain pending.

The commit containing this record identifies the structural round.
