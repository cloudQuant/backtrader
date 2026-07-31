---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments: []
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'ai-trader and backtrader-mcp capability gap analysis for backtrader'
research_goals: 'Compare the two local projects with the current backtrader checkout, identify capabilities beyond MCP, and turn evidence-backed findings into a new iteration plan.'
user_name: 'cloudQuant'
date: '2026-07-28'
web_research_enabled: true
source_verification: true
---

# Backtrader Application-Layer Capability Research

**Date:** 2026-07-28
**Author:** cloudQuant
**Research Type:** technical

---

## Research Overview

This report compares the checked-out `ai-trader` and `backtrader-mcp` projects
against the current `backtrader` repository. Local source code, tests,
configuration, and dependency manifests are the primary evidence. Current
public documentation is used only to verify protocol and dependency context.

## Technical Research Scope Confirmation

**Research Topic:** ai-trader and backtrader-mcp capability gap analysis for backtrader

**Research Goals:** Compare the two local projects with the current backtrader
checkout, identify capabilities beyond MCP, and turn evidence-backed findings
into a new iteration plan.

**Technical Research Scope:**

- Architecture analysis: package boundaries, runtime topology, and extension points.
- Implementation approaches: exposed APIs, data flows, persistence, and testing patterns.
- Technology stack: declared and actually imported frameworks and dependencies.
- Integration patterns: MCP, LLM, market-data, brokerage, and application interfaces.
- Performance and operational considerations: isolation, determinism, observability,
  security, and maintenance costs.

**Research Methodology:**

- Local source evidence is authoritative for project-specific claims.
- Current public documentation is used for protocol/dependency verification.
- Findings are classified as present, absent, partially present, or not suitable for
  direct migration.
- The final iteration plan will make scope, acceptance criteria, and dependencies explicit.

**Scope Confirmed:** 2026-07-28

## Technology Stack Analysis

### Programming Languages

All three codebases are Python projects, but their support envelopes differ.
The current checkout supports Python 3.8--3.13 and keeps the engine itself
portable. `ai-trader` requires Python 3.11+ and uses a separate application
package; `backtrader-mcp` requires Python 3.10+ and is a single-server program.
The proposed work must therefore keep all application and AI dependencies
optional rather than raising the core engine's minimum Python version.

_Source evidence:_ `/Users/yunjinqi/Documents/new_projects/backtrader/setup.py`,
`/Users/yunjinqi/Documents/量化交易框架/ai-trader/pyproject.toml`, and
`/Users/yunjinqi/Documents/量化交易框架/backtrader-mcp/pyproject.toml`.

### Development Frameworks and Libraries

`ai-trader` combines Backtrader with Click, Pydantic, PyYAML, SQLModel,
yfinance, twstock, TA-Lib, scipy, and FastMCP. Its four MCP tools are typed
wrappers for YAML/CSV backtests, market-data acquisition, and strategy
discovery. FastMCP derives tool schemas from typed Python functions, which is
appropriate for the typed boundary but must not be confused with engine APIs.

`backtrader-mcp` instead depends on the official MCP Python SDK, async CCXT,
pandas, and Plotly. It exposes one asynchronous tool plus one prompt. This is
a useful small-surface prototype, not a reusable framework layer.

FastMCP documents that typed, decorated functions become model-callable tools;
MCP itself treats tools as model-discoverable executable capabilities and
recommends a human ability to deny invocations. These facts reinforce a strict
read-only/default-deny policy for a trading integration.

_Sources:_ [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools),
[FastMCP tools documentation](https://gofastmcp.com/servers/tools), and the
local manifests above.

### Database and Storage Technologies

`ai-trader` implements a SQLite/SQLModel cache beside CSV output. It stores
normalised OHLCV data and has data-management CLI commands. The current engine
has feed abstractions but no generic, provenance-aware local market-data cache.
This is a genuine capability gap, provided a new cache is designed around
immutable source fingerprints and explicit expiry rather than importing the
application's storage implementation wholesale.

_Source evidence:_ `/Users/yunjinqi/Documents/量化交易框架/ai-trader/ai_trader/data/storage/sqlite_storage.py`
and `/Users/yunjinqi/Documents/量化交易框架/ai-trader/ai_trader/cli.py`.

### Development Tools and Platforms

The current checkout already includes the `backtrader.btrun` module, a broad
argument-driven runner, extensive test coverage, plot backends, and HTML/PDF/
JSON report generation. `ai-trader` adds a narrower, discoverable Click CLI and
YAML-based run specifications. `backtrader-mcp` contains no test files; its
single program should be treated as design input rather than an acceptance
baseline.

_Source evidence:_ `/Users/yunjinqi/Documents/new_projects/backtrader/backtrader/btrun/btrun.py`,
`/Users/yunjinqi/Documents/new_projects/backtrader/backtrader/plot/plot_plotly.py`,
`/Users/yunjinqi/Documents/new_projects/backtrader/backtrader/reports/reporter.py`,
and local test inventories.

### Cloud Infrastructure and Deployment

Neither target provides a production deployment topology. `ai-trader` includes
CI/CD workflows and two separately packaged Google ADK examples under
`agentic_ai_trader/`; those examples have their own Python requirements and
should remain external integration examples, not a dependency of the engine.
`backtrader-mcp` is an stdio-oriented local server. No cloud or live-trading
service should be inferred from either project.

### Technology Adoption Decision

Adopt the *patterns* below, not the target packages as a monolith:

1. optional workflow/MCP extras;
2. typed request/result DTOs and stable tool schemas;
3. declarative, versioned experiment specifications;
4. provider-based historical-data acquisition with provenance-aware caching;
5. a curated strategy example registry.

Do not adopt raw strategy `exec`, unrestricted filesystem paths, a hard Python
3.11+ requirement, duplicated plotting/report implementations, or unverified
marketing claims such as funding-rate simulation.

## Integration Patterns Analysis

### MCP Boundary

MCP defines separate tools, resources, and prompts over JSON-RPC, with stdio
suited to a local, single-client process and Streamable HTTP intended for
networked use. Both target projects are local tool servers: `ai-trader` has
four typed tools and `backtrader-mcp` has one tool and one prompt. The current
engine has neither an MCP module nor a stable machine-readable experiment
contract, so an MCP layer should be an optional adapter *above* the engine.

The initial integration should be stdio only. HTTP must be a later, separately
authorised deployment mode because the MCP authorization specification adds
OAuth and transport-security requirements.

_Sources:_ [MCP architecture overview](https://modelcontextprotocol.io/docs/learn/architecture)
and [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization).

### Typed API and Data Formats

The reusable part of `ai-trader` is a typed request/result boundary: request
models identify an experiment, named strategy, data selector, and explicit
overrides; result models return value, return, risk metrics, and duration.
The new boundary must improve it by using a versioned JSON/YAML experiment
schema, canonical analyzer names, an immutable run id, data fingerprint,
package/version provenance, and artifact paths. CSV remains an input/export
format; JSON is the result and MCP transport format.

It must use a named strategy registry. `backtrader-mcp` executes supplied
`strategy_code` with `exec`, while the current checkout has neither of the
non-standard callback/value-history methods used for its progress/chart path.
Therefore arbitrary generated Python is out of scope for the first release.

_Source evidence:_ `/Users/yunjinqi/Documents/量化交易框架/backtrader-mcp/main.py`
(lines 100--204) and
`/Users/yunjinqi/Documents/量化交易框架/ai-trader/ai_trader/mcp/models.py`.

### Historical-Data Providers and Caching

`ai-trader` connects Yahoo Finance/twstock-style providers to CSV/SQLite;
`backtrader-mcp` directly pages `fetch_ohlcv` through an async CCXT object.
The right integration is a provider protocol with an allowlisted exchange/
market selector, normalised OHLCV schema, pagination limits, timeout/retry
policy, and a cache interface. A provider must retain one exchange instance
per session and honour capabilities/timeframes/rate limits. CCXT documents
that rate limiting is instance-scoped and async Python callers should use
`ccxt.async_support` and close instances.

_Source:_ [CCXT manual](https://github.com/ccxt/ccxt/wiki/manual).

### Event, Progress, and Artifact Model

Long runs should emit structured progress events from the orchestration layer:
`data_fetch_started`, `cache_hit`, `backtest_started`, `backtest_finished`, and
`artifact_written`. MCP can relay these as progress notifications, but Backtrader
must not gain a new callback solely to satisfy an external server. Plots and
reports should use existing `Cerebro.plot(backend='plotly'|'bokeh')` and
`ReportGenerator`, with an artifact manifest returned to the caller rather than
an ad-hoc broker value-history API.

### Security and Trust Model

1. Default tools are read-only or operate only under a configured workspace.
2. Remote data providers and storage writes are opt-in, allowlisted, bounded by
   symbol/date/bar limits, and recorded in the run manifest.
3. Cache deletion and any future broker action require a separate destructive
   tool with explicit confirmation; live trading is excluded.
4. Strategy generation is a prompt/resource capability, not code execution.
   If execution is added later, it needs AST policy checks, a constrained
   subprocess, timeout/memory/network controls, and no access to credentials.
5. The MCP protocol itself recommends human control over tool invocations;
   this is especially material for financial workflows.

_Source:_ [MCP tools security guidance](https://modelcontextprotocol.io/specification/2025-06-18/server/tools).

### Scope Decision

No microservice mesh, message broker, OAuth/HTTP deployment, live order
execution, or funding-rate model belongs in this iteration. The goal is a
single-process, reproducible research workflow with an optional local MCP
adapter and clear extension seams.

## Architectural Patterns and Design

### System Architecture Pattern

Use a layered, ports-and-adapters design rather than adding a second Backtrader
framework:

```text
strategy packs / experiment YAML
             ↓
workflow core: validation, registry, run manifest, result normalisation
             ↓
Backtrader engine: Cerebro, feeds, broker, analyzers, plots, reports
             ↓
data/cache adapters                     presentation adapters
(CSV, cache, optional providers)        (CLI, optional local MCP)
```

Only the workflow core may depend on the engine. Data providers and MCP must
not import each other; both are replaceable adapters. This preserves public
Backtrader APIs and prevents the application-layer packages in `ai-trader`
from becoming mandatory engine dependencies.

### Design Principles and Best Practices

- Preserve the existing engine, `btrun`, analyzers, plotters, and report
  generator; adapt rather than fork them.
- Make experiments declarative and namespaced (`schema_version`, data,
  strategy, broker, analyzers, artifacts), then reject unknown fields.
- Resolve a strategy by a built-in/registered identifier, not an arbitrary
  import path or source string.
- Use explicit provider and storage protocols to keep Yahoo/CCXT/Taiwan-market
  dependencies outside the core install.
- Write a run manifest before execution and treat it as the truth for reruns.

Python packaging supports feature-specific extras, so optional workflow,
market-data, and MCP dependencies can be installed without changing the core
install. A later third-party strategy/provider plugin system can use package
entry points, but the first iteration should keep a small reviewed registry.

_Sources:_ [Python Packaging User Guide: optional dependencies](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
and [Python `importlib.metadata` entry points](https://docs.python.org/3.12/library/importlib.metadata.html).

### Scalability and Performance Patterns

The limiting operations are remote pagination, parsing, and Backtrader runs,
not MCP serialization. Cache normalised bars keyed by a canonical data request
and content hash; reuse a provider session; cap maximum bars/page count; and
use a bounded executor for blocking Backtrader runs. Do not introduce a broker
or microservice queue prematurely. Benchmark cache-hit versus cache-miss and
verify that the workflow wrapper does not change analyzer values or order
traces.

### Integration and Communication Patterns

The CLI and MCP server are two clients of the same `WorkflowService` protocol.
They receive an `ExperimentRequest` and return the same `RunResult`/artifact
manifest. The MCP server is only a transport translation layer: it must not
call `Cerebro` directly, add engine callbacks, or invent another plotting path.
Progress is represented by optional event records, not a dependency on a
non-existent engine callback.

### Security Architecture Patterns

Treat every model-provided input as untrusted. Enforce a configured workspace
root, symbol/date/bar budgets, provider allowlists, redacted logs, no credential
passing through tool inputs, and no `exec`. Separate read operations from cache
writes/cleanup with explicit capability metadata and confirmations. The two
targets demonstrate why this must be a foundation: one accepts arbitrary paths,
and the other executes generated source in the server process.

### Data Architecture Patterns

Canonical OHLCV records need instrument, venue/provider, timeframe, timezone,
adjustment mode, requested/received intervals, retrieval timestamp, source
version, and a content hash. Cache metadata must record row counts and exact
coverage but must not substitute coverage for integrity. The `ai-trader`
SQLite design supplies an initial normalisation idea; its model has no database
uniqueness constraint or source fingerprint, so a fresh schema is warranted.

### Deployment and Operations Architecture

Ship a normal core install plus narrowly named extras such as `workflow`,
`data-yahoo`, `data-ccxt`, and `mcp`. The MCP extra runs locally via stdio and
is validated with an inspector/client contract test. Networked HTTP, OAuth,
credential storage, and live broker actions require a separate security/design
review and are deliberately deferred.

## Implementation Approaches and Technology Adoption

### Technology Adoption Strategy

Adopt in vertical slices, retaining an executable engine after every slice:

1. freeze architecture/compatibility decisions and fixture data;
2. ship the experiment schema, local CSV adapter, strategy registry, and
   manifest-only runner;
3. add the SQLite cache and one optional market-data adapter;
4. add structured reports/artifact manifests using existing renderers;
5. add the local, read-safe MCP adapter;
6. consider isolated generated-code execution, HTTP, or live trading only in
   later iterations with their own threat models.

This avoids the target projects' all-at-once application wrappers and makes
each feature independently revertible.

### Development Workflows and Tooling

Use a small API surface in a new workflow package, with samples and fixtures
outside the engine hot path. Keep a reviewed built-in strategy registry first;
add entry-point discovery only after a stable registry protocol and a
compatibility test matrix exist. Package optional functionality as extras.
The Python packaging guide explicitly supports this separation.

_Source:_ [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).

### Testing and Quality Assurance

- Schema: golden YAML/JSON, invalid-field, path-escape, and deterministic
  canonicalisation tests.
- Data: frozen provider responses, normalisation, pagination, retry/timeout,
  cache-hit/miss, content-hash, and transaction rollback tests; no public
  network in unit tests.
- Engine parity: the same experiment must retain final value, analyzer values,
  and trade trace against direct `Cerebro` execution in runonce/runnext modes.
- MCP: generated tool-schema snapshot, invalid request/error contract,
  progress-event contract, workspace-boundary tests, and Inspector smoke test.
- Packaging: clean core install without extras; clean install for each extra;
  optional adapters fail at use with actionable messages rather than making
  `import backtrader` fail.

The local `ai-trader` collection found 331 test cases but stopped on three
missing optional imports (`twstock` and `sqlmodel`) in the current environment.
This is a reminder to make optional integrations lazily imported and to test
the minimal install. Pytest fixtures are a suitable way to give provider and
cache tests reliable, isolated data contexts.

_Source:_ [pytest fixture documentation](https://docs.pytest.org/en/latest/explanation/fixtures.html).

### Deployment and Operations Practices

Use the standard-library `sqlite3` cache first, with parameterised statements,
explicit commit/rollback context, a schema version, and a per-workspace lock.
This avoids a required ORM and supports the current Python floor. The Python
documentation describes SQLite as a lightweight embedded store and recommends
explicit transaction control; the implementation must remain compatible with
pre-3.12 transaction APIs.

MCP deployment is local stdio only. Acceptance includes MCP Inspector testing
of tool schemas, prompts/resources (if exposed), errors, and notifications.

_Sources:_ [Python `sqlite3` documentation](https://docs.python.org/3.9/library/sqlite3.html)
and [MCP Inspector documentation](https://modelcontextprotocol.io/docs/tools/inspector).

### Team Organization and Skills

The work divides cleanly into: engine-parity owner, workflow/data owner, MCP
and security owner, and QA/reproducibility owner. The latter two must review
every provider or tool change because risk is not confined to the transport
layer.

### Cost and Resource Controls

Default to local CSV/cache data; impose max-bars, max-pages, timeout, and
concurrency budgets; reuse a provider session; make chart/report creation
explicit; and avoid public API calls in regression runs. Record cache status
and wall time in each run manifest, enabling later cost/performance decisions.

### Risk Assessment and Mitigation

| Risk | Control |
| --- | --- |
| Core API or result regression | direct-Cerebro golden parity and full project regression gates |
| Dependency bloat/minimum Python drift | extras plus clean-minimal-install test |
| Non-reproducible remote data | source fingerprints, frozen fixtures, immutable run manifest |
| Path traversal/destructive cache action | workspace root, allowlists, confirmations, audit log |
| Remote-code execution from LLM output | no arbitrary code execution in this iteration |
| Exchange bans/partial data | capability checks, bounded pagination, retries, rate limits, session reuse |
| Overclaiming an external prototype | acceptance tests prove each advertised capability; unsupported claims remain out of scope |

## Technical Research Recommendations

### Implementation Roadmap

Create a new iteration focused on reproducible workflow and data capabilities
first, with an optional local MCP adapter last. The detailed story breakdown,
acceptance matrix, and exclusions are recorded in the iteration plan generated
from this report.

### Technology Stack Recommendation

Core: existing Backtrader + standard library. Optional: YAML validation,
market-provider clients, and MCP SDK. Storage: `sqlite3` with a bespoke,
versioned schema. Presentation: existing Plotly/Bokeh/report modules.

### Success Metrics

- Identical engine metrics/traces for direct and workflow runs.
- Every run has an inspectable manifest and data fingerprint.
- A core-only install imports and runs existing tests without optional data/MCP
  packages.
- Cached reruns make no provider request and return the same dataset hash.
- MCP exposes only documented, schema-validated tools and passes Inspector/
  contract tests.

---

<!-- Content will be appended sequentially through research workflow steps -->

## Research Synthesis

### Executive Summary

`ai-trader` is not a competing execution engine: it is a Backtrader application
layer. Its meaningful additions beyond MCP are a declarative workflow, a Click
CLI, 23 concrete strategy examples, five market-data fetcher families, and a
CSV/SQLite persistence layer. The current checkout already provides the engine,
a broad `btrun` runner, analyzers, Bokeh/Plotly charting, and HTML/PDF/JSON
reports; it should reuse those capabilities rather than import a second wrapper.

`backtrader-mcp` is useful as a prototype of AI-facing ergonomics: a prompt,
one end-to-end tool, progress notifications, exchange OHLCV acquisition, and
image output. It is not a safe or compatible implementation to transplant. It
executes supplied code, ignores its documented end-date input, does not
implement its advertised funding-rate simulation, has no tests, and calls two
methods absent from the current engine.

The recommended iteration therefore prioritises a reproducible workflow/data
layer and makes MCP a late optional local adapter. Its success is defined by
engine parity, provenance, bounded external I/O, and security properties--not
by a larger number of tools.

### Table of Contents

1. Research scope and evidence
2. Technology stack analysis
3. Integration patterns
4. Architecture and implementation approach
5. Capability comparison and adoption decision
6. Risk assessment and next steps

### 1. Research Scope and Evidence

**Question answered:** compared with the current Backtrader checkout, what do
the local `ai-trader` and `backtrader-mcp` projects add besides MCP, and what
should form the next iteration?

**Snapshots inspected (2026-07-28):**

| Codebase | Commit | Primary evidence |
| --- | --- | --- |
| Current `backtrader` | `04adc08c2deb02cbf240efbd495e5eee68b375d8` | source, packaging, runner, plot/report code, runtime introspection |
| `ai-trader` | `7681fe331fb638beab1ae20d3552c802bbaa9174` | package, configs, fetchers, cache, CLI, MCP tools, tests, CI |
| `backtrader-mcp` | `348b7ee936a7f8351c97e2f1362988bff0e7a6ac` | single-server implementation, manifest, README |

Project-specific conclusions come from local source. Public documentation was
used only for current MCP, CCXT, Python packaging, SQLite, pytest, and Inspector
behaviour.

### 2. Capability Comparison and Adoption Decision

| Capability | `ai-trader` | `backtrader-mcp` | Current checkout | Decision |
| --- | --- | --- | --- | --- |
| Declarative experiment YAML | Typed config and examples | No | CLI arguments/examples, no canonical experiment contract | Adopt, improve with schema version and manifest |
| User-facing CLI | Click run/fetch/quick/data commands | No | Broad `btrun` module | Add a focused workflow CLI; do not replace `btrun` |
| Curated strategy library | 23 concrete strategy classes, including portfolio rotation | Prompt only | Engine/indicators, no comparable pack | Adopt a small reviewed registry; do not bulk-copy examples |
| Market-data acquisition | US/TW/crypto/FX/VIX fetchers | CCXT OHLCV paging | Multiple feeds, no generic cache/provider contract | Adopt provider port + optional adapters |
| Local persistence/cache | CSV plus SQLite/SQLModel | None | No generic provenance cache | Adopt a new stdlib SQLite schema with hashes/constraints |
| Structured run result | Pydantic result DTO | Formatted text + image | Reports/analyzers but no common run manifest | Adapt existing analyzers/reports into stable DTO/artifact manifest |
| Plot/report output | Delegates to `cerebro.plot()` | Plotly equity image | Bokeh/Plotly and HTML/PDF/JSON reports already exist | Reuse; no duplicate renderer |
| MCP | Four typed tools | One tool + prompt/progress | Absent | Optional, local-only, after workflow core |
| LLM/agent demos | Separate Google ADK projects | Prompt template | Absent | Keep out of core; future integration example only |
| Generated-code execution | No server-side arbitrary code path | `exec(strategy_code)` | N/A | Explicitly reject this iteration |
| Leverage/funding simulation | N/A | Leverage only via commission setup; no funding code | Existing broker commission/margin primitives | Do not claim or port without a validated model |

### 3. Strategic Technical Recommendation

Create an application-layer `backtrader.workflows` package, backed by the
existing engine and exposed through optional extras. It owns the versioned
experiment contract, named strategy registry, provider/cache ports, run
manifest, and result normalisation. A CLI and local MCP server call the same
service. The implementation must never add engine callbacks simply to support
the transport.

### 4. Security and Quality Conclusion

The strongest lesson from both projects is the boundary, not MCP itself:

- no arbitrary `exec` or dynamic imports from model input;
- no unrestricted filesystem request paths;
- providers and cache actions are allowlisted and bounded;
- remote calls never occur in unit regression tests;
- core installation stays free of optional provider/MCP dependencies;
- a failed test/lint/security check is a failed gate, unlike the target CI's
  `continue-on-error` configuration.

### 5. Limitations

The target projects were inspected as local snapshots. No live exchange call,
no real credential, and no target dependency installation was performed. An
`ai-trader` pytest collection in the existing base environment discovered 331
tests but stopped with three missing declared optional dependencies; that is
evidence about import isolation in this environment, not a claim that the
target suite fails after its full install. Assertions about MCP/CCXT behaviour
are verified against current public documentation but should be refreshed when
implementation begins.

### 6. Source Documentation

- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [MCP tools and security guidance](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector)
- [CCXT manual](https://github.com/ccxt/ccxt/wiki/manual)
- [Python packaging extras](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Python sqlite3](https://docs.python.org/3.9/library/sqlite3.html)
- [pytest fixtures](https://docs.pytest.org/en/latest/explanation/fixtures.html)

### Conclusion

The next iteration should create a safe, reproducible research workflow over
Backtrader. MCP is valuable once that contract exists, but it is neither the
only nor the first capability to build. The accompanying iteration plan makes
this decision executable with phased scope, ownership boundaries, and
acceptance gates.
