---
title: 'Backtrader MCP independent P0'
type: 'feature'
created: '2026-07-30'
status: 'done'
baseline_commit: '0e812ef7d8c250d61e092536d2a1b61e712193fb'
context:
  - '../AGENTS.md'
---

<frozen-after-approval reason="user-owned intent">

## Intent

**Problem:** Backtrader has no independent, host-neutral MCP product that can safely turn local
datasets and typed strategy intent into validated, reviewable, approved, reproducible backtests.

**Approach:** Build a source-distributed Python package using MCP Python SDK v2. It owns immutable
data, private drafts, validation, approvals, application, durable execution, and reports while
treating Backtrader only as a registered subprocess runtime.

## Boundaries & Constraints

**Always:** Stay inside `backtrader-mcp/`; use local stdio with clean stdout; bind validation and
change tokens to exact hashes; require trusted local CLI approval before apply; use immutable CAS,
confined roots, fixed subprocess argument vectors, durable SQLite state, locks, idempotency, and
restart recovery; validate candidate code without importing it in the server.

**Ask First:** Network transports, live trading, arbitrary package installation, arbitrary Python
execution, writes outside configured target roots, or changing repository-wide documentation.

**Never:** Import or read sibling Skills/Agent products; use `exec`, `eval`, shell execution,
pickle, caller-provided executable paths, in-memory object transfer, or MCP-client assertions as
authorization.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| Data intake | Confined CSV plus explicit column map | Canonical immutable dataset and manifest | Reject traversal, symlinks, malformed rows |
| Draft flow | Typed StrategySpec and profile | Private 7-archetype scaffold | Reject unknown archetype/profile |
| Validation/apply | Exact revision, validation token, preimage hashes, local approval | Prepared diff and idempotent confined apply | Reject stale token/hash/approval |
| Run | Validated draft, CAS dataset, registered runtime | Durable job, bounded subprocess, JSON/Markdown result | Cancel, timeout, or recover state explicitly |

</frozen-after-approval>

## Code Map

- `src/backtrader_mcp/` -- product services, MCP protocol surface, CLI, and worker.
- `tests/` -- service, security, recovery, protocol, and end-to-end acceptance.
- `examples/hosts/` -- Claude, Codex, OpenCode, and OpenClaw stdio examples.

## Tasks & Acceptance

**Execution:**
- [x] Package SDK v2 distribution metadata and legal/readme material.
- [x] Implement data CAS, catalog/spec/scaffolds, drafts, AST validation, tokens and approvals.
- [x] Implement exact-hash prepare/apply, durable jobs, subprocess reports and recovery.
- [x] Expose typed MCP tools/resources/prompts and four host configurations.
- [x] Add independence audit plus protocol, API, security, and end-to-end tests.

**Acceptance Criteria:**
- Given a confined CSV, a client can register, derive, scaffold, validate, locally approve/apply,
  run, poll, cancel, and read a result without server-process candidate imports.
- Given traversal, stale hashes, forged tokens, unapproved changes, dangerous AST, or duplicate
  idempotency keys, the service fails closed with stable errors.
- Given MCP SDK 2.0.0, the server lists and invokes its typed surface over the SDK protocol.

## Verification

**Commands:**
- `conda run -n base pytest -q` -- all product tests pass.
- isolated `mcp==2.0.0` target plus protocol tests -- SDK contract passes without changing base.
- `backtrader-mcp audit-independence` -- no sibling dependency or forbidden implementation.

## Suggested Review Order

1. [README and security/workflow contract](README.md)
2. [Canonical product contracts](src/backtrader_mcp/contracts.py)
3. [Data CAS](src/backtrader_mcp/data.py)
4. [Draft validation and change authorization](src/backtrader_mcp/validation.py)
5. [Durable run control](src/backtrader_mcp/jobs.py)
6. [MCP v2 surface](src/backtrader_mcp/server.py)
7. [Acceptance evidence](IMPLEMENTATION_REPORT.md)
