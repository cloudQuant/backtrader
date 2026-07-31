---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - '/Users/yunjinqi/Documents/new_projects/backtrader/tests/functional/strategies'
  - '/Users/yunjinqi/Documents/new_projects/back_trader/strategies'
  - '/Users/yunjinqi/Documents/量化交易框架/backtrader-mcp'
  - '/Users/yunjinqi/Documents/new_projects/backtrader/.agents/skills'
  - '/Users/yunjinqi/Documents/new_projects/backtrader/.agents/skills/bmad-agent-builder'
  - '/Users/yunjinqi/Documents/new_projects/backtrader/.agents/skills/bmad-agent-dev'
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'Standalone Backtrader Skills, MCP, and Agent for AI-assisted data loading and strategy authoring from two local strategy corpora'
research_goals: 'Define three independent, feature-complete iteration plans: backtrader-skills, backtrader-mcp, and backtrader-agent must each work alone for controlled local data loading, corpus retrieval, strategy authoring, validation, controlled execution, testing, repair, and reporting, using the current functional strategy tests and the 1,035 three-file strategy packages as verified evidence without implementing runtime code.'
user_name: 'cloudQuant'
date: '2026-07-29'
web_research_enabled: true
source_verification: true
---

# Research Report: Standalone Backtrader Skills, MCP, and Agent for AI Strategy Authoring

**Date:** 2026-07-29
**Author:** cloudQuant
**Research Type:** technical

---

## Research Overview

This research defines three standalone ways for an AI to load controlled local
data and author Backtrader
strategies:

1. `backtrader-skills`, a repository-local Agent Skills product whose own
   scripts, references, templates, catalog, validators, runners, and reports
   provide the complete workflow without MCP or the standalone Agent;
2. `backtrader-mcp`, a local MCP server whose own resources, prompts, tools,
   catalog, validators, runners, and reports provide the same complete workflow
   without installing the skills or Agent;
3. `backtrader-agent`, a host-discoverable specialist Agent package whose own
   persona, menu, explicit workflow state, scripts, contracts, data loaders,
   catalog, templates, validators, runner, and reports provide the complete
   workflow without MCP or the Backtrader Skills suite.

The products may exchange the same versioned artifact formats, but none is a
runtime, installation, or acceptance dependency of another. This replaces an
earlier complementary-layer assumption.

The evidence combines exhaustive local filesystem/AST/YAML audits, representative
source inspection, collection-only pytest evidence, existing Backtrader API
inspection, and current official MCP, Agent Skills, Python, pytest, and packaging
documentation. No strategy was executed and no runtime code was developed.

### Contents

1. Technical research scope
2. Technology stack
3. Integration patterns
4. Architecture
5. Local corpus findings
6. Independent three-product capability model
7. Implementation approach and staged delivery
8. Risks, decisions, and conclusions

---

## Technical Research Scope Confirmation

**Research Topic:** Standalone Backtrader Skills, MCP, and Agent for AI-assisted
local data loading and strategy authoring from two local strategy corpora

**Research Goals:** Define three independent, feature-complete iteration plans:
one each for `backtrader-skills`, `backtrader-mcp`, and `backtrader-agent`.
Each product must work alone for controlled local data intake, corpus retrieval,
strategy authoring, validation, controlled execution, testing, repair, and
reporting. The current functional strategy tests and the 1,035 three-file
strategy packages are verified knowledge and evidence sources, not code that
may be copied blindly.

**Technical Research Scope:**

- Architecture analysis of a local skill package, an MCP server, and a
  host-discoverable specialist Agent that independently implement compatible
  data and strategy-artifact contracts
- Implementation approaches for strategy discovery, retrieval, scaffolding, static validation, controlled execution, and result reporting
- Technology stack and packaging constraints for Python 3.8+ Backtrader, MCP SDKs, Agent Skills, YAML, AST indexing, and pytest
- Integration patterns across the current Backtrader source tree, functional strategy tests, and the three-file strategy-package corpus
- Performance considerations for indexing and retrieving more than 2,000 strategy artifacts without loading the corpus into every model context
- Security boundaries for AI-authored Python, workspace writes, subprocess execution, data access, and live-trading exclusion

**Research Methodology:**

- Local source and repository structure are the primary evidence for corpus and API claims
- Current official web documentation verifies MCP and Agent Skills protocol/packaging claims
- Representative samples plus full set/count audits are used instead of assuming directory conventions are universal
- Uncertain or unimplemented capabilities are explicitly separated from verified behavior

**Scope Confirmed:** 2026-07-29, including the user's follow-up request to add a
third standalone `backtrader-agent` iteration.

---

## Technology Stack Analysis

### Programming Languages

The Backtrader core remains a Python 3.8+ library. As verified directly on
PyPI on 2026-07-29, MCP Python SDK v2.0.0 is the current stable release and
requires Python 3.10+. This is a hard packaging boundary: adding the SDK to the
core dependency set would drop supported core interpreters. The MCP
implementation should therefore be a separate package with its own Python
3.10+ runtime, importing the local Backtrader package as a dependency. Agent
Skills are Markdown-based workflow packages and do not impose a Python runtime
until one of their optional scripts is invoked.

_Source: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[MCP on PyPI](https://pypi.org/project/mcp/),
[Agent Skills Specification](https://agentskills.io/specification)_

### Development Frameworks and Libraries

The official stable MCP Python SDK v2 provides tools, resources, prompts,
structured results, progress/logging, `stdio`, and network transports and
supports the 2026-07-28 protocol revision. The initial implementation should
use an explicit `mcp>=2,<3` compatibility range plus a reproducible lock. The
implementation gate must still re-check the selected SDK and client versions
and run protocol compatibility tests rather than relying on an unverified
future release.

The first Backtrader MCP release should use `stdio` only and typed structured
output. The skills implementation should follow the open Agent Skills format:
a required `SKILL.md`, optional deterministic `scripts/`, focused `references/`,
reusable `assets/`, and optional client metadata. OpenAI's current documentation
confirms that repository skills are discovered from `.agents/skills`, that
skills use progressive disclosure, and that optional `agents/openai.yaml`
metadata can declare an MCP dependency. This design deliberately does not
declare such a dependency because Skills must pass standalone acceptance.

_Source: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[MCP on PyPI](https://pypi.org/project/mcp/),
[Build skills](https://learn.chatgpt.com/docs/build-skills),
[Agent Skills Specification](https://agentskills.io/specification)_

### Database and Storage Technologies

The two source corpora are filesystem-first. An initial index does not require a service database or vector database: approximately two thousand source artifacts can be represented by deterministic JSON/JSONL manifests plus content hashes and searched by normalized IDs, categories, indicators, order APIs, data count, and free-text tokens. A local SQLite index is an optional cache, not a system of record. Source files and their hashes remain authoritative.

_Source: local corpus structure; [Python `sqlite3`](https://docs.python.org/3/library/sqlite3.html)_

### Development Tools and Platforms

Python's `ast.parse()` can extract classes, parameters, imports, indicator use, order methods, and suspicious syntax without importing or executing strategy code. Pytest fixtures provide deterministic local data and runtime contexts for validation. If generated strategy code is executed, it must run in a child process with an argument allowlist, a controlled working directory/environment, output capture, and a timeout; Python documents `subprocess.run()` as the standard high-level API and supports killing timed-out child processes.

_Source: [Python `ast`](https://docs.python.org/3/library/ast.html), [Python `subprocess`](https://docs.python.org/3/library/subprocess.html), [pytest fixtures](https://docs.pytest.org/en/latest/explanation/fixtures.html)_

### Deployment and Packaging

The skills suite installs under the repository's `.agents/skills` tree for local
discovery. The MCP server should live in an isolated distribution such as
`integrations/backtrader-mcp/`, with an independent `pyproject.toml`, console
entry point, and Python 3.10+ constraint. The Agent's tracked canonical source
belongs under `skills/agent-backtrader/` and installs to
`.agents/skills/agent-backtrader/`; the install target is ignored local state,
not canonical source. Because the repository's broad `assets/` ignore also
matches nested Agent assets, implementation needs a narrow exception and
distribution-manifest checks. The Backtrader core package keeps Python 3.8+ and
gains no mandatory MCP, Skills, or Agent dependency. Cross-client distribution
can be considered later; it is not required for the local first release.

_Source: [Build skills](https://learn.chatgpt.com/docs/build-skills), [Python packaging optional dependencies](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)_

### Technology Adoption Decision

Adopt three feature-equivalent but independently implemented products:

1. `backtrader-skills` bundles its own deterministic catalog, templates,
   validation scripts, controlled runner, tests, and report normalizer behind
   an Agent Skills workflow;
2. `backtrader-mcp` bundles its own catalog, templates, validation service,
   controlled runner, tests, and report normalizer behind typed MCP resources,
   prompts, and tools;
3. `backtrader-agent` bundles its own specialist persona, menu, explicit
   artifact-backed state, local data intake, catalog, templates, validators,
   controlled runner, tests, and reports behind product-owned deterministic
   actions.

They use seven compatible schema documents—`StrategySpec`, `DatasetManifest`,
`CorpusManifest`, `StrategyArtifactManifest`, `ValidationReport` (including
`Diagnostic`), `RunManifest`, and `RunResult`—so artifacts can be moved between
them, but no product loads, invokes, or requires another. There is no required
delivery order. No model API is embedded in any product; the connected host
model remains responsible for generating source text.

---

## Integration Patterns Analysis

### Compatible Contract Boundary

All three deliverables independently implement the same published data
contracts:

- `StrategySpec`: the user's strategy intent, data/feed contract, typed parameters, entry/exit rules, risk rules, target artifact format, and validation profile;
- `DatasetManifest`: resolved, immutable facts for controlled local data—
  opaque root and relative source, source and normalized hashes, feed
  names/roles, parser/column mappings, time semantics, transforms, data-quality
  findings, `intersection | left | explicit_asof` alignment, and provenance.
  Its JSON Schema contains a versioned
  `$defs/DataSpec` typed request with its own `spec_hash`; DataSpec is not an
  eighth top-level public schema;
- `CorpusManifest`: source corpus, relative source reference, category, class, parameters, indicators, data count/timeframes, order APIs, imports, expected metrics, source revision, dirty-state marker, and content hash;
- `StrategyArtifactManifest`: the rendered files, artifact profile, expected
  hashes, source references, and bounded write target;
- `ValidationReport`: static findings, import/collection result,
  runonce/runnext parity, normalized `Diagnostic` entries, and token inputs;
- `RunManifest`: approved command profile, source/data/config/environment
  hashes, engine provenance, timing, and artifact references;
- `RunResult`: normalized metrics, comparison outcome, diagnostics, and report
  references.

The schemas are an interoperability specification, not a shared runtime
dependency. Each product must pass the same contract fixtures and produce the
same normalized results from the same inputs. This prevents incompatible
definitions of “valid data” and “a valid strategy” without requiring the
products to run together.

### MCP Primitive Mapping

MCP's three server primitives map cleanly to the strategy-authoring problem:

| Primitive | Backtrader use | Control model |
| --- | --- | --- |
| Resources | Authoring contract, API rules, catalog summaries, selected strategy metadata/source snippets, templates, validation reports | Application-selected/read-only context |
| Tools | Search catalog, create a constrained draft workspace, preview/save files, statically validate, run approved targeted tests, inspect results | Model-invoked actions with client confirmation |
| Prompts | Author a strategy, convert between artifact formats, repair a failing strategy, review for look-ahead/risk issues | Explicit user-selected workflow templates |

The server must return deterministic tool ordering and typed input/output schemas. Long-lived draft or validation state uses explicit opaque `workspace_id`/`run_id` handles; it must not depend on connection-local implicit state.

_Source: [Understanding MCP servers](https://modelcontextprotocol.io/docs/2026-07-28/learn/server-concepts), [MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)_

### Corpus Adapter Pattern

The current functional-test corpus and the external three-file package corpus require separate adapters behind one read-only indexing protocol:

```text
FunctionalTestAdapter ─┐
                       ├─> normalized CorpusManifest ─> search/read/template selection
ThreeFilePackAdapter ──┘
```

The adapters preserve source-specific fields instead of flattening away important differences. A functional test includes a strategy, deterministic data loading, Cerebro setup, analyzers, and assertions in one module. A three-file pack distributes these responsibilities across YAML configuration, strategy source, and a runner. Similar Backtrader strategy syntax does not make the artifact contracts interchangeable.

### Agent Skills Standalone Pattern

The skills use progressive disclosure:

1. concise name/description triggers the correct strategy workflow;
2. `SKILL.md` loads the authoring/review/validation sequence;
3. only the required contract, pattern guide, selected source examples, template, or deterministic script is loaded.

The skills operate directly on configured local corpora through scripts shipped
with the skill package. Those scripts build/search the catalog, create bounded
drafts, validate artifacts, invoke the controlled child-process runner, compare
results, and render reports. The skill metadata must not declare
`backtrader-mcp` or `backtrader-agent` as a required dependency. Optional future
interoperability may be documented, but it is excluded from standalone
acceptance.

_Source: [Agent Skills Specification](https://agentskills.io/specification), [Build skills](https://learn.chatgpt.com/docs/build-skills)_

### Standalone Backtrader Agent Pattern

The local Agent convention is also implemented as a host-discoverable Agent
Skill, normally with `SKILL.md` for activation/persona/menu routing and
`customize.toml` for metadata. Existing `bmad-agent-*` packages commonly
delegate menu entries to external BMad skills, so they are interaction
references rather than a valid independence template.

The Backtrader Agent should be a stateless specialist at the host level:

- it does not require BMad memory, PULSE, First Breath, a model SDK, or an API
  key;
- it routes each menu action to its own references and deterministic scripts,
  never to `backtrader-skills` or MCP;
- task state is explicit in `AgentSessionManifest` and an append-only local
  event journal, not hidden model memory;
- it can resume an explicitly selected session artifact, while a fresh
  activation remains usable without prior conversational state;
- write and execute actions use independent approvals and hash-bound tokens.

The OpenAI Agents SDK documents a general agent as instructions plus tools,
guardrails, optional session state, and human approval. Those concepts support
the design, but the SDK is not a P0 dependency: this repository's Agent is a
portable host-loaded package whose deterministic actions run locally.

_Source: local `.agents/skills/bmad-agent-*` and Agent Builder packages;
[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/),
[Agents](https://openai.github.io/openai-agents-python/agents/),
[Human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/),
[Sessions](https://openai.github.io/openai-agents-python/sessions/)_

### Controlled Local Data Intake Pattern

All three products need data loading as a first-class workflow, not an implicit
detail inside a generated runner:

```text
configured read-only root
  -> inspect local source without importing strategy code
  -> normalize and approve DatasetManifest v1 `$defs/DataSpec`
  -> materialize immutable DatasetManifest
  -> preview bounded rows and quality findings
  -> build only an allowlisted Backtrader feed plan
  -> bind manifest hashes into validation and run evidence
```

P0 covers local Generic/Backtrader/Yahoo/MT5 CSV files, explicit PandasData
mappings, product-owned custom-line DataFrame templates, single/multiple feeds,
and controlled resample/replay. Yahoo means an already downloaded local CSV,
not network access. Pickle, arbitrary Python loaders/transforms, generic
JSONL/NPZ/tick ingestion, databases, live streams, credentials, and downloads
remain outside P0.

`DatasetManifest` records source and normalized hashes, parser versions,
explicit datetime/OHLCV/custom-line mappings, timeframe/compression,
timezone/session/bar semantics, ordered transforms, row/time bounds, duplicate
and missing counts, OHLC/finite validation, feed roles, and multi-feed
alignment. The same data and mapping must produce the same cross-product
semantic-manifest hash; product/version/timestamp and local display-path
provenance remain recorded but are excluded from that semantic hash. Any
source, mapping, transform, environment, or engine change invalidates prior
validation and run approval.

### Communication and Data Formats

- Agent Skills metadata and instructions: YAML frontmatter plus Markdown.
- Specialist Agent metadata/menu: `SKILL.md` plus metadata-only
  `customize.toml`; explicit JSON session/event artifacts for resumable tasks.
- Strategy intent and validation: versioned JSON Schema-compatible objects.
- Data intake: canonical `DatasetManifest v1#/$defs/DataSpec` request and
  immutable resolved `DatasetManifest` JSON.
- Three-file strategy configuration: source-compatible YAML with a canonical normalized JSON representation for hashing.
- Corpus index: JSONL as the portable source-of-truth artifact; optional SQLite cache for MCP filtering.
- MCP transport: local `stdio` for the first release; structured tool output plus resource links.
- Validation execution: allowlisted argument arrays, never shell strings.

### Security Integration Pattern

AI-authored Python cannot be considered safe merely because it passed AST parsing. Static analysis and execution are separate gates:

1. parse and inspect without import;
2. preview a bounded change set;
3. allow a user-invoked create/update operation to write only into a
   product-private, reversible draft root;
4. require explicit host/user approval before applying that draft to a user
   workspace, with create-only defaults and expected-hash updates;
5. require a separate approval before child-process execution;
6. execute only an allowlisted validator/test command with sanitized
   environment, local fixtures, timeout, and captured output;
7. never expose credentials, live feeds, live brokers, arbitrary shell, or
   unrestricted filesystem paths.

The first local runner documents that subprocess timeout, environment filtering,
and rejection of known network APIs are controls, not a complete OS or network
sandbox. P0 may execute only locally generated/user-approved candidates; unknown
third-party code remains validate-only. Strong network/process isolation is an
optional container backend and must not be claimed until tested. The current MCP
specification requires server input validation, access control, rate limiting,
output sanitization, and client confirmation for sensitive operations.

_Source: [MCP Tools security considerations](https://modelcontextprotocol.io/specification/2026-07-28/server/tools), [Python `subprocess`](https://docs.python.org/3/library/subprocess.html)_

---

## Architectural Patterns and Design

### System Architecture Pattern

Use three parallel standalone stacks with contract compatibility:

```text
Functional tests + three-file packages
             │
       ┌─────┴──────────────────────┬─────────────────────────┐
       ▼                            ▼                         ▼
backtrader-skills              backtrader-mcp            backtrader-agent
own data/catalog stack         own data/catalog stack     own data/catalog stack
own templates/scaffolder       own templates/scaffolder   own templates/scaffolder
own validator/runner           own validator/runner       own validator/runner
own reports/evals              own protocol tests         own menu/state/evals
       │                            │                         │
       └────────────── compatible public v1 schemas ─────────┘
```

Contract schemas contain no MCP SDK types and no client-specific skill metadata.
Shared test fixtures may be copied from a normative contract-fixture directory
at release time, but the installed products remain self-contained. A later
deduplication refactor is allowed only if it preserves offline, independent
installation and acceptance.

### Design Principles and Best Practices

- Source-backed generation: every suggested pattern points to a source reference and hash; an AI must distinguish copied pattern, adapted pattern, and newly authored logic.
- Target-specific rendering: one strategy intent may render to a self-contained functional regression test or a `config.yaml + *_strategy.py + run.py` package, but each renderer preserves its own acceptance contract.
- Progressive context: catalog search returns metadata and a short rationale first; full source is read only for selected examples.
- Deterministic mechanics: cataloging, scaffolding, static checks, test command construction, result normalization, and hashing are scripts/services rather than prose-only instructions.
- Model independence: no deliverable embeds an LLM client or API key.
- Explicit data provenance: strategies bind to an immutable
  `DatasetManifest`, not an arbitrary local path or implicit DataFrame.
- Explicit Agent state: resumability comes from task artifacts and an event
  journal, not hidden memory or autonomous background behavior.
- Evidence before claims: generated tests do not invent expected metrics. Functional regression expectations come from the designated master baseline and are then checked on `dev`; package results retain their own Python reference artifacts.

### Scalability and Performance Pattern

The corpus size is small enough for a local manifest but large enough to overflow model context. Build the index once from AST/YAML/source parsing, then query metadata. The search response should default to at most five candidates and explain why each matched. Full corpus refresh is content-hash incremental. Embeddings, a vector database, and remote retrieval infrastructure are deferred until lexical/structural retrieval has a measured recall problem.

### Security Architecture Pattern

Define three capability tiers:

| Tier | Capability | Default |
| --- | --- | --- |
| Read | catalog search, resource inspection, template and contract reads | enabled |
| Write | create draft workspace, preview and apply bounded files | explicit user/client approval |
| Execute | static import-free checks, then allowlisted child-process tests | separate explicit approval; local fixtures only |

The MCP server never evaluates source with in-process `exec()` or `eval()`. A generated Python strategy may only be run by the controlled validation backend after the write is complete and approved. Live brokers, stores, credentials, external network data, and shell command composition are outside the first release.

### Data Architecture Pattern

Each corpus snapshot records:

- adapter/schema version;
- source repository identity, commit, branch, dirty flag, and scan timestamp;
- source-relative path and content SHA-256 for every artifact;
- normalized strategy ID, category, class names, parameters, dependencies, data/feed requirements, indicators, order APIs, analyzers, and expected outputs;
- completeness and parse/validation status;
- cross-corpus links with match method and confidence.

Never record only a Git commit for a dirty source tree. The working-tree content hash is required to make the research and future catalog reproducible.

Each data snapshot separately records:

- an opaque configured root plus source-relative path;
- file size and SHA-256, parser and transform versions;
- explicit feed, column, time, timezone/session, and custom-line semantics;
- source and normalized hashes, row/time bounds, duplicate/missing/finite/OHLC
  checks;
- multi-feed roles, alignment, resample/replay rules, and minimum overlap.

mtime and size may accelerate caching but cannot replace content hashes or the
canonical normalized-data hash.

### Deployment and Operations Architecture

- Skills: installed into `.agents/skills` from a tracked distribution,
  specification-validated, no daemon, with self-contained scripts and an
  isolated local artifact directory.
- MCP: separate Python 3.10+ package and executable, local `stdio` transport,
  with its own service implementation and artifact directory.
- Agent: tracked canonical source under `skills/agent-backtrader`, installed as
  `.agents/skills/agent-backtrader`, with metadata-only customization,
  product-owned references/scripts/assets, and an isolated session/artifact
  root. Neither `_bmad` nor Agent Builder is a runtime dependency.
- Catalogs: each product independently builds an equivalent index from
  configured roots; committed configuration contains no hard-coded user paths.
- Data: each product independently inspects, registers, and builds feeds from
  allowlisted local sources using its own DatasetManifest implementation.
- Clean-install mode: each product ships a versioned metadata snapshot, seven
  current-fork archetype templates in both output profiles, and curated
  reference excerpts. This mode supports the complete authoring workflow
  without the sibling corpus checkout.
- Source-attached mode: configured local roots enable full-source inspection
  and catalog refresh. Rebuilding the verified 1,152/1,035/1,032 counts is an
  acceptance fixture for this repository, not an undocumented clean-install
  prerequisite.
- Tests: skills trigger/eval cases and direct script tests accept Skills with
  MCP/Agent absent; in-memory client, real `stdio`, and MCP Inspector tests
  accept MCP with Skills/Agent absent; activation/menu/state/route and direct
  script tests accept Agent with MCP/Skills absent.
- Observability: each product writes its own structured local audit log for
  write/execute operations, with normalized paths and removed secrets.

---

## Local Corpus Findings

### Reproducibility Snapshot

| Source | Snapshot | Working-tree scope used |
| --- | --- | --- |
| Current Backtrader | branch `dev`, commit `0e812ef7d8c250d61e092536d2a1b61e712193fb` | `tests/functional/strategies` clean |
| Three-file packages | branch `codex/iter54-swig-interface`, commit `0ea70a7dfccb8b66632eb48e96c071053a3b362e` | `strategies` subtree clean |
| Reference MCP | branch `main`, commit `348b7ee936a7f8351c97e2f1362988bff0e7a6ac` | repository clean |

The external `back_trader` repository has unrelated working-tree changes
outside `strategies`. The research therefore records both the repository
revision and the scanned subtree state and does not treat the whole repository
as clean.

### Functional Strategy-Test Corpus

`tests/functional/strategies` contains 1,152 `test_*.py` files across 30
categories. Collection produced 1,271 pytest items:

- 119 files are parameterized across `runonce=True` and `runonce=False`;
- 1,033 files collect one case each;
- all 1,152 files parse with Python AST and contain assertions;
- 1,148 add at least one analyzer, 1,151 configure initial cash, and 932
  configure commission;
- the most common analyzers are SharpeRatio, TradeAnalyzer, DrawDown, Returns,
  and SQN.

There are two important artifact families:

1. 119 framework-style regression modules that are self-contained and
   explicitly exercise runonce/runnext parity;
2. approximately 1,033 migrated modules that inline a prior
   `config.yaml + run.py + strategy source + expected result` package.

The corpus provides excellent executable examples, data fixtures, Cerebro
assembly, analyzers, and assertion patterns. It does not justify assuming that
all 1,271 cases test both run modes.

### Three-File Strategy-Package Corpus

`/Users/yunjinqi/Documents/new_projects/back_trader/strategies` contains exactly
1,035 canonical two-level strategy packages across 21 categories. Every package
has a root `config.yaml`, `run.py`, and at least one `strategy_*.py`.

The apparent count of 1,036 configuration files is misleading:
`grid_trading/0008_1196_random_robot/cpp/config.yaml` is a nested C++ artifact,
not a separate Python strategy package.

The convention has real exceptions:

- 1,033 packages have one root `strategy_*.py`;
- two `1168_ea_aml` packages have both `strategy_aml.py` and
  `strategy_ea_aml.py`, so the canonical source must be resolved from the
  runner import rather than a filename glob;
- one `0054_0177...tm_plus` package imports a sibling strategy directory and is
  not fully self-contained;
- configuration has seven top-level shapes and 105 observed `data` key shapes;
- configuration IDs, display names, and class names are not globally unique.

The only reliable canonical key is:

```text
category/complete_strategy_directory_name
```

All 1,035 `py_result.json` files share an 11-field metric shape, but nullable
trade counts occur in 54 files and nullable Sharpe ratios occur in six.
Normalized acceptance therefore permits documented `null` values but rejects
NaN and Infinity.

Generated pybind11/SWIG variants, result artifacts, caches, C++ subdirectories,
backup files, and non-canonical strategy modules must be excluded from the
authoring index.

### Cross-Corpus Mapping

The deterministic mapping is:

```text
strategies/<category>/<directory>/
    -> tests/functional/strategies/<category>/test_<directory>.py
```

Results:

- 1,032 of 1,035 source packages have an exact current test path;
- the three missing targets are
  `mean_reversion/0191_0960_super_trend`,
  `trend_following/0193_0395_expotest`, and
  `volatility_systems/0027_0838_wlxbw5zone`;
- 120 current test files do not map back to the 1,035 packages;
- 1,031 mapped tests still contain the class selected by the source runner;
- two independent informal AST-normalization audits produced 469 and 471
  equivalent classes after ignoring docstrings and parameter declarations.
  Because the transformation was not yet frozen as a script and fixture, no
  exact AST-equivalence count is accepted as a reproducible baseline.

The mapping proves common lineage, not current code identity. Retrieval must
show source revision, source path, current test path, mapping status, and
content hashes rather than silently selecting one as canonical truth.

### Current-Fork Compatibility Gap

The largest generation hazard is initialization. The current repository rule is
to call `super().__init__()` before accessing `self.p`, lines, or data aliases.
Only one of 1,153 Strategy classes in the functional corpus explicitly does so,
and none of the 1,034 directly parsed canonical package strategies do so.

Therefore:

- old strategy bodies are logic references, not copy-ready templates;
- templates must be newly written against the current fork;
- static validation must enforce the current initialization rule;
- retrieval must return the relevant feature-engineering function, feed-line
  schema, Strategy class, runner assembly, and test assertions when those parts
  jointly implement the idea.

Optional dependencies also require explicit metadata. The package corpus uses
pandas in 1,023 modules and NumPy in 292, with much smaller sklearn, hmmlearn,
statsmodels, and SciPy populations. Default generation must prefer core
Backtrader patterns and may select optional dependencies only when the strategy
spec and environment both authorize them.

### Baseline and Test Semantics

An AI cannot invent expected portfolio metrics. New generated artifacts use two
gates:

1. structural and behavioral validation: schema, AST, imports, finite/null
   metrics, nontrivial activity where appropriate, runonce/runnext parity, and
   deterministic fixtures;
2. regression baseline approval: run the same candidate against the designated
   `master` baseline in an isolated checkout, record the fresh result and source
   provenance, obtain approval, then verify `dev`.

The historical `py_result.json` files and migrated assertions are reference
evidence; they do not replace a fresh candidate run.

Comparison uses a versioned policy. Counts, booleans, enums, IDs, and hashes are
exact. Floating metrics use `math.isclose(rel_tol=1e-7, abs_tol=1e-9)` unless a
named metric has an approved narrower or wider override. `null` equals only
`null` for fields declared nullable; NaN and Infinity always fail. A baseline
override records metric, old/new tolerance, reason, approver, timestamp, and
policy hash. All three products must ship and test the same default policy
independently.

The existing `scripts/inline_regression_tests.py` documents the migration
lineage but has destructive success paths that delete source artifacts. It must
not be reused by any product. All three plans require a new non-destructive
renderer.

---

## Independent Product Capability Model

### Required End-to-End Capability

Each product independently implements this loop:

```text
intent
  -> inspect/register local data and freeze DatasetManifest
  -> clarify and normalize StrategySpec
  -> search/select source-backed examples
  -> choose current-fork template
  -> render single-test or three-file package
  -> preview bounded writes
  -> static/security validation
  -> approved controlled execution
  -> runonce/runnext and target tests
  -> normalized metrics/report
  -> diagnose and repair
```

Installing only one product must be sufficient. “Available when either of the
other two products is present” does not satisfy any acceptance criterion.

### Functional Parity Matrix

| Capability | Standalone Skills | Standalone MCP | Standalone Agent |
| --- | --- | --- | --- |
| Environment doctor | deterministic script | typed `doctor` tool | `DR` menu + own doctor action |
| Local data inspect/materialize/register/load | data scripts + DatasetManifest | typed tools/resources + DatasetManifest | `DI` workflow + own data actions |
| Corpus build/refresh | local indexing script | catalog service/tool | Agent-owned catalog action |
| Search and inspect | scripts + focused references | resources + typed tools | `CS` librarian workflow |
| Requirement clarification | authoring skill | prompt + contract tools | Specifier mode + state |
| Seven archetypes | product templates | server-owned templates | Agent-owned templates |
| Single-test output | standalone renderer | server-owned renderer/tool | Author mode + renderer |
| Three-file output | standalone renderer | server-owned renderer/tool | Author mode + renderer |
| Preview/apply writes | change manifest + approval | two-phase prepare/apply tools | draft service + approval ledger |
| Static/security checks | validator script | server-owned validator | Reviewer mode + own validator |
| Controlled backtest | child-process runner | server-owned runner | Test mode + fixed runner action |
| Test/parity comparison | test/compare scripts | typed test/compare tools | test/compare workflow |
| Fresh master/dev baseline | testing workflow | compare services | baseline workflow |
| Repair workflow | repair skill + reports | repair prompt + tools | Repairer state loop |
| Results and artifacts | normalized JSON/Markdown/HTML | structured content + links | Analyst mode + local reports |
| Audit/provenance | artifact manifests/log | run resources/audit | session journal + immutable runs |
| Resumable task state | explicit artifact manifests | draft/run IDs | native explicit session manifest |
| Independent acceptance | no MCP or Agent | no Skills or Agent | no MCP or Skills |

### Strategy Archetypes

All three products must cover the same seven initial archetypes:

1. single-data indicator strategies;
2. multi-indicator systems;
3. multi-data asset allocation;
4. multi-timeframe strategies;
5. pairs and spread strategies;
6. order/risk-management strategies;
7. precomputed-signal or optional machine-learning strategies.

Each archetype must render both target profiles:

- `single_test`: a self-contained functional pytest module;
- `python_bundle`: `config.yaml + strategy_<slug>.py + run.py`.

### Catalog Record

Each independent catalog records at least:

- canonical `category/directory` key and aliases;
- source adapter, revision, path, dirty-state evidence, and content hashes;
- display name, config ID, primary runner-imported module/class;
- data files, symbols, feeds, lines, timeframes, and preprocessing functions;
- parameters and inferred types;
- indicators, order APIs, exits/risk hooks, sizer, commission, analyzers;
- run signature/mode and output metric schema;
- optional dependencies;
- source/test cross-link and match status;
- quality flags and most recent real acceptance evidence.

Search returns a small ranked set—normally one template and two or three
examples—with match rationale. It does not dump the corpus into model context.

---

## Implementation Approach and Staged Delivery

### Standalone Skills Approach

The skills product should contain three focused entry skills:

- `backtrader-strategy-author`;
- `backtrader-strategy-review`;
- `backtrader-strategy-test`.

Their package includes references for the package contract, current-fork rules,
archetypes, data/order safety, validation, and test policy; assets for the seven
archetype templates and two output profiles; and deterministic scripts for
doctor, local data inspection/registration, index, search, scaffold, validate,
run, compare, and report.

Progressive disclosure keeps `SKILL.md` concise while scripts provide the
complete execution functionality. Trigger tests must prove that authoring,
review, and testing intents select the correct skill and unrelated Python tasks
do not.

### Standalone MCP Approach

The MCP product should be a separate Python 3.10+ distribution under
`integrations/backtrader-mcp`, leaving the core Python 3.8+ constraint intact.
It owns all domain services it needs and starts with local `stdio`.

Resources expose contracts, catalogs, templates, selected examples, validation
rules, datasets, and run artifacts. Prompts cover authoring, review, repair,
regression test creation, and result explanation. Typed tools cover doctor,
local dataset inspection/registration/preview, catalog refresh/search/inspection,
draft creation, preview/apply, validation, controlled backtest, target tests,
comparison, result retrieval, and report rendering.

A validation token binds candidate source, configuration, selected data, and
environment hashes. Any file change invalidates the token before execution.

### Standalone Agent Approach

The Agent's tracked source should live under `skills/agent-backtrader` and be
installed as `.agents/skills/agent-backtrader`. P0 uses a metadata-only,
stateless Agent rather than the current BMad pattern that invokes external
skills or requires `_bmad` customization at runtime.

`SKILL.md` defines the complete specialist persona, direct-intent routing,
approval rules, and stable menu. `customize.toml` contains current Agent
metadata only. Internal references cover data intake, specification, corpus
retrieval, authoring, review/repair, testing, and reporting. Product-owned
scripts perform every deterministic action. Menu routes may load only those
internal references or invoke those scripts; they may not invoke
`backtrader-skills` or MCP.

The Agent remains stateless with respect to hidden model memory but persists
explicit task state in `AgentSessionManifest` plus an append-only event journal.
This supports crash/resume and idempotent actions without requiring memory,
PULSE, an autonomous loop, or a model SDK.

### Common Security Boundary, Independently Enforced

Each of the three products must enforce the controls itself:

- normalize and confine all paths; reject traversal and symlink escape;
- parse without importing before execution;
- reject `exec`, `eval`, `compile`, dynamic import, subprocess/shell/network
  APIs, credentials, absolute data paths, and live broker/store access;
- use import and dependency allowlists;
- preview writes and require explicit approval;
- run only already-written, hash-validated candidates;
- use argument arrays, sanitized environment, controlled cwd, fixed local
  fixtures, timeout, captured output, and artifact quotas;
- separate write approval from execute approval;
- redact traceback paths and secrets in user-visible results.

A child process is not claimed to be a full OS sandbox. Container isolation is
deferred until implemented and tested.

### Recommended Delivery Order

There is no cross-product dependency. Within each iteration, use the same
internal order:

1. freeze evidence and acceptance fixtures;
2. define product-local schemas and seven current-fork templates;
3. implement controlled local data intake and DatasetManifest;
4. build the deterministic catalog and retrieval;
5. implement two renderers and bounded workspace changes;
6. implement static/security validation;
7. implement controlled execution, comparison, and reporting;
8. complete independent end-to-end acceptance.

The iterations may be executed in any order or in parallel. Contract fixture
compatibility is tested after multiple products exist, but it is not a release
gate for any standalone product.

---

## Risks, Decisions, and Conclusions

### Key Decisions

1. All three products are complete authoring systems, not complementary parts.
2. No product requires either other product at install, runtime, test, or
   release.
3. The two corpora are evidence and retrieval sources, not direct templates.
4. `category/full_directory_name` is the canonical corpus identity.
5. Runner imports determine the primary strategy source.
6. New templates follow current-fork initialization and clock rules.
7. Both output profiles and all seven archetypes are mandatory in every
   product.
8. Expected metrics require fresh, provenance-bearing baseline evidence.
9. Controlled local data intake and `DatasetManifest` are P0 capabilities in
   every product.
10. The Agent is stateless with explicit artifact-backed workflow state; memory
    and autonomous operation are P1.
11. No raw in-process code execution, arbitrary filesystem access, live trading,
   credentials, or remote market-data access is allowed in the initial release.

### Principal Risks and Mitigations

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Copying legacy initialization | generated strategy fails or bypasses lifecycle | current-fork templates plus AST rule |
| Treating mapped corpora as identical | stale behavior is copied | dual provenance, hashes, mapping confidence |
| Picking files by glob/ID/name | wrong strategy selected | canonical path key plus runner-import resolution |
| Invented expected metrics | false regression confidence | approved fresh master baseline, then dev |
| Regex-only look-ahead checks | false positives/negatives | AST/object-aware rules plus runtime tests |
| Optional dependency leakage | collection/import failures | catalog tags and environment allowlist |
| In-process code execution | arbitrary code execution | approved, hash-bound child process only |
| Feature drift between products | inconsistent AI results | shared fixture format and parity matrix, not runtime coupling |
| Agent degrades to a persona/router | missing deterministic capability | own scripts/state/runner and Agent-only acceptance |
| Hidden Agent memory or duplicate actions | stale state or repeated writes/runs | explicit session journal, idempotency keys, stateless activation |
| Data drift or ambiguous feed semantics | irreproducible or look-ahead results | DatasetManifest, source/normalized hashes, explicit time/alignment rules |
| Context overload | poor generation quality and cost | ranked metadata-first retrieval |

### Final Recommendation

Proceed with three separate iterations and judge each against the full parity
matrix:

- Iteration 17: `backtrader-skills`, accepted only when its own scripts complete
  the workflow with MCP and Agent absent;
- Iteration 18: `backtrader-mcp`, accepted only when its own server completes
  the workflow with Skills and Agent unavailable;
- Iteration 19: `backtrader-agent`, accepted only when its own persona/menu,
  data/actions/state/scripts complete the workflow with MCP and Backtrader
  Skills unavailable.

Optional interoperability and a cross-product parity scoreboard are later
enhancements and must never conceal a missing standalone capability.
