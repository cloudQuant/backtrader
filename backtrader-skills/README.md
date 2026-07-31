# backtrader-skills

`backtrader-skills` is an offline, independently installable author/review/test product for this
Backtrader fork. It turns a registered local dataset and a typed `StrategySpec v1` into either a
collected pytest strategy or a three-file Python bundle, reviews the candidate without importing it,
and runs approved candidates in separate runonce/runnext child processes.

It does not import or start sibling MCP or Agent products. The bundled catalog snapshot contains
metadata for 1,152 functional strategy tests and 1,035 three-file packages, with 1,032 mapped IDs,
so normal operation does not require either source corpus.

## Install the runtime

From the `backtrader-skills` checkout, activate any supported Python 3.10–3.13 environment and
install the distribution. Conda is optional; for example, `conda activate base` may be used before
these commands:

```bash
python -m pip install .
backtrader-skills --target /path/to/backtrader doctor
```

Runtime state is always `<target>/.backtrader-skills/`. Dataset objects, manifests, draft bytes,
approval-token digests, run evidence, and install manifests remain there. The 256-bit token handle
is returned once to the caller and is never persisted in plaintext. `doctor` records the actual
interpreter and environment used by the installed command; no local machine path is part of the
distribution interface.

## Install the three canonical skills

The same distribution supports four project-level layouts:

| Host | Destination |
| --- | --- |
| Claude Code | `.claude/skills/backtrader-*` |
| Codex | `.agents/skills/backtrader-*` |
| OpenCode | `.opencode/skills/backtrader-*` |
| OpenClaw | `<workspace>/skills/backtrader-*` |

Preview, approve, and apply:

```bash
BT_TARGET=/path/to/backtrader

backtrader-skills --target "$BT_TARGET" \
  install preview --host codex
backtrader-skills --target "$BT_TARGET" \
  approval approve --token-id tok_...
backtrader-skills --target "$BT_TARGET" \
  install apply --plan-id install_codex_... --token-id tok_...
```

Use `claude`, `opencode`, or `openclaw` for the other native locations. Installation is create-only.
For OpenClaw, set `BT_TARGET` to the actual agent workspace root because its native skill directory
is `<workspace>/skills`; the installer does not register an OpenClaw agent for you.
Uninstall is also preview/approval/apply; files whose hash changed after installation are preserved:

```bash
backtrader-skills --target "$BT_TARGET" \
  install uninstall-preview --host codex
backtrader-skills --target "$BT_TARGET" \
  approval approve --token-id tok_...
backtrader-skills --target "$BT_TARGET" \
  install uninstall-apply --plan-id uninstall_codex_... --token-id tok_...
```

Each installed skill has one thin `scripts/backtrader_skills.py` forwarder. Deterministic behavior
lives only in `src/backtrader_skills/`.

## Verify discovery and make the first request

Applying an install plan proves that the canonical files reached the native directory; it does not
prove that an external model session discovered them. Reload the project or start a new host session
after installation. Use the following read-only first request, replacing `/path/to/backtrader` with
the Backtrader project root:

```text
Without writing any files, use the backtrader-strategy-author skill. Run:
backtrader-skills --target /path/to/backtrader doctor
Return the doctor pass/fail result, the no-sibling-product-imports check, and the catalog counts.
```

The expected smoke result has `passed=true`, a passing `no-sibling-product-imports` check, and the
verified catalog baseline `1,152/1,035/1,032`. A host that cannot name or load the skill has not
completed discovery, even if the files exist.

### Claude Code

Confirm `.claude/skills/backtrader-strategy-author/SKILL.md` exists, restart Claude Code in the
project, and send the first request above. Prefixing the request with “use the
`backtrader-strategy-author` skill” is the explicit trigger; keep the returned transcript or host
tool trace as discovery evidence.

### Codex

Confirm `.agents/skills/backtrader-strategy-author/SKILL.md` exists and start a new task in the
project. Invoke the skill explicitly with:

```text
$backtrader-strategy-author Perform the read-only doctor smoke described above.
```

Record the resolved skill name and command output. A filesystem-only check is not a Codex discovery
test.

### OpenCode

Confirm `.opencode/skills/backtrader-strategy-author/SKILL.md` exists, reload the project, and ask
OpenCode to “load and use the `backtrader-strategy-author` skill” before sending the first request.
Retain the skill/tool trace and the doctor JSON result as evidence.

### OpenClaw

Set `BT_TARGET` to an existing, explicitly registered OpenClaw agent workspace before installation,
then confirm `skills/backtrader-strategy-author/SKILL.md` exists below that workspace. Reload the
registered agent and ask it to “use the workspace skill `backtrader-strategy-author`” for the first
request. This installer does not create or register the agent itself.

OpenClaw was not installed in the environment used for the current acceptance snapshot. Its layout,
metadata, forwarders, conflict handling, and protected uninstall are statically tested; live
discovery must remain unchecked until an installed OpenClaw agent completes the smoke above.

## Register local data

P0 accepts only offline local files inside explicitly registered, read-only roots. Portable
manifests contain an opaque root ID and relative path, never the local absolute path.

```bash
backtrader-skills --target "$BT_TARGET" \
  data root-add --directory /path/to/fixtures --root-id prices
backtrader-skills --target "$BT_TARGET" \
  data inspect --feed-spec feed.json
backtrader-skills --target "$BT_TARGET" \
  data register --spec data-spec.json
backtrader-skills --target "$BT_TARGET" \
  data preview --dataset-id 'ds_<64hex>' --rows 5
```

`DataSpec` supports multiple named feeds, roles, timeframe/compression, timezone, explicit column
mapping, deterministic transforms, and `intersection|left|explicit_asof` declarations. Registration
normalizes header-based CSV/tabular inputs to UTF-8 canonical CSV, validates timestamps, finite
OHLC, ordering and duplicates, and stores content-addressed objects. Formats are
`generic_csv`, `backtrader_csv`, `yahoo_csv`, `mt5_csv`, `pandas`, and
`pandas_custom_lines`; Pandas profiles consume a safely materialized CSV, never pickle or a callable.
Any source-byte change invalidates the manifest and its approvals.

## Author and apply

Search the shipped catalog and create a scaffold:

```bash
backtrader-skills --target "$BT_TARGET" \
  catalog search --query "multi timeframe momentum" --archetype multi_timeframe
backtrader-skills --target "$BT_TARGET" \
  spec scaffold --archetype multi_timeframe --output-profile python_bundle \
  --dataset-id 'ds_<64hex>' --feed-count 2 > strategy-spec.json
```

Validate the JSON after removing any surrounding CLI presentation, then use the two-phase writer:

```bash
backtrader-skills --target "$BT_TARGET" \
  spec validate --spec strategy-spec.json
backtrader-skills --target "$BT_TARGET" \
  render preview --spec strategy-spec.json
backtrader-skills --target "$BT_TARGET" \
  render validate --draft-id draft_...
backtrader-skills --target "$BT_TARGET" \
  approval approve --token-id tok_...
backtrader-skills --target "$BT_TARGET" \
  render apply --draft-id draft_... --token-id tok_...
```

Bundles are created under `strategies/generated/`. Collected generated tests are created under
`tests/functional/strategies/generated/`. Existing files require an explicit expected hash.
Multi-file apply stages every byte first and uses a journal plus rollback, so a later-file failure
does not leave a partially applied bundle.

All seven archetypes—single-data indicator, multi-indicator, multi-asset allocation,
multi-timeframe, pairs/spread, order/risk, and precomputed/ML signal—use the same restricted
Expression/Action/StateRule IR for both output profiles. Direct `bt.Strategy` templates intentionally
do not call `super().__init__()` in this fork.

## Review, repair, and run

```bash
backtrader-skills --target "$BT_TARGET" \
  review --file "$BT_TARGET/strategies/generated/.../strategy.py"
backtrader-skills --target "$BT_TARGET" \
  repair --draft-id draft_...
backtrader-skills --target "$BT_TARGET" \
  run prepare --candidate "$BT_TARGET/strategies/generated/.../strategy.py" \
  --dataset-id 'ds_<64hex>'
backtrader-skills --target "$BT_TARGET" \
  approval approve --token-id tok_...
backtrader-skills --target "$BT_TARGET" \
  run execute --run-id run_... --token-id tok_...
```

When a diagnostic requires a semantic change, revise the typed spec and bind it to the failed
ValidationReport:

```bash
backtrader-skills --target "$BT_TARGET" \
  repair --spec revised-strategy-spec.json --validation-report failed-validation.json
```

The controller never imports candidate code. It proves the candidate is an unchanged artifact from
an approved render/apply, recomputes candidate, dataset, source-data, and environment hashes,
consumes a separate execution approval, and invokes the distribution's active Python interpreter
with `-I` for each mode.
Approval capabilities expire after 15 minutes by default and end in
`CONSUMED`, `REVOKED`, or `EXPIRED`. Reports are stored as JSON and Markdown.

The 11 metrics have frozen units: six integer bar/trade counts; account-currency `final_value`;
nullable dimensionless `sharpe_ratio`; nullable ratio `annual_return`; percent `max_drawdown`; and
percent `return_rate`. Integers and normalized events compare exactly. Floats use `rel_tol=1e-7`,
`abs_tol=1e-9`, with a documented amount override. Null equals only null; missing, NaN, and Infinity
fail.

## Security and current limits

- P0 runs only product-generated and explicitly approved candidates. Unknown code may receive a
  static review but cannot receive a run token.
- Generated candidates may import only top-level `backtrader`. AST gates reject controller and
  filesystem imports, dynamic execution/import, subprocess, known network clients, sockets, live
  stores, absolute paths, traversal, and positive line offsets.
- `python -I` child isolation is not a complete OS sandbox. P0 has no network namespace, container,
  seccomp, or resource cgroup.
- Data is offline and header-based. No download, database, API key, pickle, live feed, or arbitrary
  loader/callable is accepted.
- Alignment (`intersection`, `left`, or `explicit_asof`), resample, and replay intent is frozen in
  the DatasetManifest and validated before feed assembly. The P0 runner delegates bar-clock
  advancement to Backtrader and does not silently fill missing bars or change calendars.
- The automated P0 runner proves runonce/runnext parity. A separately checked-out, human-approved
  master/dev financial baseline remains an explicit release workflow, not an inferred expected
  return.
- Host-client UI discovery cannot be emulated without each client binary. Product tests verify all
  four native paths, canonical skill metadata, forwarders, conflicts, and protected uninstall.

## Verify the distribution

Run these commands from the `backtrader-skills` checkout with the intended environment activated.
Repository maintainers use the Anaconda base environment required by the repository's `AGENTS.md`,
but that machine-specific executable path is not part of the public commands:

```bash
python scripts/doctor.py
python scripts/build_catalog.py --check
python -m pytest tests -q
python scripts/run_acceptance.py \
  --matrix all --require-no-mcp --require-no-agent
```

The acceptance command builds a wheel, installs it into an isolated directory, exposes only the
Backtrader source package to a clean fixture repository, and runs the full 7×2 matrix from that
installed distribution with the source checkout absent from `sys.path`. The seven archetypes use
seven distinct DatasetManifests covering all six declared adapters; multi-data, resample, and
precomputed custom-line semantics are recorded per cell. Every cell records independent runonce
and runnext hashes plus comparison results. Multi-data, multi-timeframe, and precomputed/ML
representative cells must also pass a structured failure → typed-IR repair → revalidation →
approved dual-mode backtest gate.

The wheel contains seven named JSON Schemas, `comparison-profile-v1.json`, the full metadata
snapshot, four host adapter manifests, and all three canonical skills. `manifest.json` records every
published file hash and compatibility range.
