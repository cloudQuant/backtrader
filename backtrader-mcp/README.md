# Backtrader MCP

Backtrader MCP is an independent, local-first MCP server for building and
running reproducible Backtrader strategies. It turns confined CSV files into
immutable datasets, typed strategy intent into private drafts, and reviewed
drafts into bounded subprocess runs with durable status and reports.

P0 is deliberately offline and backtest-only. It does not expose brokers,
stores, credentials, live orders, arbitrary Python execution, or network
transports.

## Distribution contract

- Python 3.10 or newer.
- MCP Python SDK `2.0.x`, using `MCPServer` and local stdio.
- Independent wheel/source distribution; Backtrader is a separately registered runtime.
- SQLite/WAL state, content-addressed CSV data, private draft files, HMAC
  capabilities, filesystem locks, idempotency records, and startup recovery.
- Product-owned `prepare_strategy_run`, `start_strategy_run`,
  `get_run_status`, `cancel_strategy_run`, and `get_run_result` tools. MCP SDK
  v2.0.0 does not provide the Tasks extension, so this product does not claim
  it.

The wheel includes seven JSON Schema contracts under
`backtrader_mcp/schemas/` and the deterministic comparison policy under
`backtrader_mcp/policies/`. It also includes its own immutable full metadata
snapshot: 1,155 unique records covering 1,152 functional tests, 1,035
three-file strategy packages, and 1,032 verified mappings. The fourteen
current-fork template entries (seven archetypes by two output profiles) remain
separate from those corpus records.

## Install without changing the base environment

From this directory, create and activate a dedicated virtual environment, then
install the package. `python` may be any supported Python 3.10+ interpreter:

```bash
python -m venv .runtime
. .runtime/bin/activate
python -m pip install -c constraints/requirements-v2.txt .
python -m backtrader_mcp --help
```

Register only absolute, trusted roots in the host environment:

```text
BACKTRADER_MCP_STATE_ROOT=/absolute/private/state
BACKTRADER_MCP_SOURCE_ROOTS={"market_data":"/absolute/read-only/csv","functional_corpus":"/absolute/read-only/tests/functional/strategies","package_corpus":"/absolute/read-only/strategies"}
BACKTRADER_MCP_TARGET_ROOTS={"strategies":"/absolute/generated/strategies"}
BACKTRADER_MCP_RUNTIMES={"default":"/absolute/backtrader/source/root"}
```

Root maps are JSON objects. MCP callers receive only root IDs and relative
paths; they cannot submit absolute paths or executable paths. The runtime root
must contain `backtrader/__init__.py`.

Before adding a host, export the same values in the installation shell and run
the read-only diagnostic. Quoting the JSON values prevents the shell from
interpreting them:

```bash
export BACKTRADER_MCP_STATE_ROOT='/absolute/private/state'
export BACKTRADER_MCP_SOURCE_ROOTS='{"market_data":"/absolute/read-only/csv"}'
export BACKTRADER_MCP_TARGET_ROOTS='{"strategies":"/absolute/generated/strategies"}'
export BACKTRADER_MCP_RUNTIMES='{"default":"/absolute/backtrader/source/root"}'
backtrader-mcp doctor | python -m json.tool
```

`doctor.status` must be `passed`. The report is stable JSON and includes the
installed product and dependency versions, configured root checks, supported
adapters/run profiles, and the actual Backtrader `module_file`, version, Git
commit, branch, and runtime capabilities. The CLI diagnostic itself does not
create the state root or write to a source/target root; normal MCP server
startup initializes its private state root before tools are available.

## Catalog modes

The default `snapshot` mode reads only
`backtrader_mcp/catalog_snapshot.jsonl` from this distribution. Every one of
its 1,155 records has `source_available=false`: search and provenance are
available, but `inspect_strategy` does not pretend that the original source
bytes were shipped. `list_strategy_templates` independently returns all 14
current-fork archetype/profile templates.

For an explicit source-attached rebuild, register the functional and package
corpora as two read-only IDs in `BACKTRADER_MCP_SOURCE_ROOTS`, then call:

```json
{
  "tool": "refresh_strategy_catalog",
  "arguments": {
    "source_root_id": "functional_corpus",
    "package_root_id": "package_corpus"
  }
}
```

The server scans metadata and hashes only; it never imports, executes, or
modifies a corpus file. The result reports fresh
`functional_tests`/`strategy_packages`/`mapped` counts, a content hash, and a
diagnostic if they differ from the verified 1,152/1,035/1,032 baseline.
Source-attached records use `source_available=true`; subsequent
`inspect_strategy` detects changed functional or package bytes. Supplying only
`source_root_id` preserves the smaller AST-only refresh for a registered
strategy target root.

## Host setup

Replace every `/ABSOLUTE/PATH` placeholder in the matching file.

### Claude Desktop / Claude Code

Copy `examples/hosts/claude-desktop.json` into the host's MCP configuration,
or replace every placeholder and run this complete Claude Code command:

```bash
claude mcp add-json --scope project backtrader '{
  "type": "stdio",
  "command": "/ABSOLUTE/PATH/backtrader-mcp/.runtime/bin/backtrader-mcp",
  "args": ["serve"],
  "env": {
    "BACKTRADER_MCP_STATE_ROOT": "/ABSOLUTE/PATH/.backtrader-mcp-state",
    "BACKTRADER_MCP_SOURCE_ROOTS": "{\"market_data\":\"/ABSOLUTE/PATH/data\"}",
    "BACKTRADER_MCP_TARGET_ROOTS": "{\"strategies\":\"/ABSOLUTE/PATH/generated-strategies\"}",
    "BACKTRADER_MCP_RUNTIMES": "{\"default\":\"/ABSOLUTE/PATH/backtrader-source\"}"
  }
}'
claude mcp list
```

Restart Claude Desktop after editing its JSON. Claude Code can verify the
project-scoped server with `claude mcp list` and its interactive `/mcp` view.

### Codex

Merge `examples/hosts/codex-config.toml` into `~/.codex/config.toml` or a
trusted project's `.codex/config.toml`, then restart the Codex client. The
Codex app, Codex CLI, and Codex IDE extension share this configuration.
Codex's own `approval_policy` governs the host, but it does not replace either
of this product's trusted local approval records.

The equivalent CLI registration is:

```bash
codex mcp add \
  --env BACKTRADER_MCP_STATE_ROOT=/ABSOLUTE/PATH/.backtrader-mcp-state \
  --env 'BACKTRADER_MCP_SOURCE_ROOTS={"market_data":"/ABSOLUTE/PATH/data"}' \
  --env 'BACKTRADER_MCP_TARGET_ROOTS={"strategies":"/ABSOLUTE/PATH/generated-strategies"}' \
  --env 'BACKTRADER_MCP_RUNTIMES={"default":"/ABSOLUTE/PATH/backtrader-source"}' \
  backtrader -- /ABSOLUTE/PATH/backtrader-mcp/.runtime/bin/backtrader-mcp serve
codex mcp list --json
```

### OpenCode

Merge `examples/hosts/opencode.json` into the global or project OpenCode
configuration. The current configuration places each named local server
directly below `mcp`; the command is an argument vector and `enabled` is true.
Run `opencode mcp list` and require the `backtrader` server to be connected
before starting a strategy request.

### OpenClaw

Edit and run `examples/hosts/openclaw-add.sh`, then keep the successful
`openclaw mcp doctor backtrader --probe` output as setup evidence.

### First host verification

All four adapters start the same stdio server. A successful connection performs
MCP `initialize`; the host then discovers `tools/list`, `resources/list`, and
`prompts/list`. Use the host's MCP view/logs to confirm those discovery calls,
then submit this non-mutating first request:

```text
Use only the backtrader MCP server. Call doctor, then call
get_catalog_snapshot. Return doctor.status, the default runtime's module_file,
version and commit, plus snapshot.extensions.entry_count. Do not create a
draft, write a target, or start a run.
```

Expected evidence is `doctor.status=passed`, a `module_file` below the
registered runtime, the expected Backtrader version/commit, and catalog
`entry_count=1155`. Use these host-specific discovery checks:

| Host | Registration check | Interactive discovery |
| --- | --- | --- |
| Claude Code | `claude mcp list` | `/mcp` shows `backtrader`, then run the first request |
| Codex | `codex mcp list --json` | Start/restart Codex, inspect its MCP tools, then run the first request |
| OpenCode | `opencode mcp list` | Require `backtrader` connected, then run the first request |
| OpenClaw | `openclaw mcp doctor backtrader --probe` | Inspect the workspace MCP tools, then run the first request |

For raw protocol evidence independent of host UI wording, the isolated v2
protocol test performs `initialize`, `tools/list`, `resources/list`,
`prompts/list`, and a typed `get_catalog_snapshot` call.

Host configuration references:
[Claude MCP](https://code.claude.com/docs/en/mcp),
[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp),
[OpenCode MCP](https://opencode.ai/docs/mcp-servers/), and
[OpenClaw MCP](https://docs.openclaw.ai/cli/mcp).

## Upgrade and uninstall

For a compatible `0.1.x` upgrade, stop every connected host, back up the
private state root, activate the dedicated environment, and reinstall:

```bash
. .runtime/bin/activate
python -m pip install --upgrade -c constraints/requirements-v2.txt .
backtrader-mcp doctor | python -m json.tool
```

Restart the host and repeat its registration check and first request. Do not
reuse draft validation tokens, change/run tokens, or approvals across an
incompatible release. This `0.1.0` release does not migrate pre-P0 state.

To uninstall, first remove the `backtrader` MCP registration from each host
(or delete only its matching configuration entry), stop active runs, then:

```bash
. .runtime/bin/activate
python -m pip uninstall backtrader-mcp
```

Uninstalling the wheel intentionally leaves the configured state, datasets,
generated strategies, and source files untouched. Archive or remove those
paths separately only after reviewing their contents. If `.runtime` was
dedicated solely to this product, it can be removed with the platform's file
manager after deactivation.

## Closed-loop workflow

1. `inspect_dataset` reads headers and a bounded sample from a configured
   source root.
2. `register_dataset` requires an explicit canonical column map and writes a
   normalized immutable CSV to the CAS. Registration fails if the source
   changes while read.
3. `preview_dataset` reads a bounded CAS preview.
4. `derive_tabular_dataset` runs only `identity`, `dropna`, `returns`, or
   `sma` with typed parameters and an exact source-manifest hash. It creates a
   new dataset ID; no DataFrame, callable, pickle, or in-memory object crosses
   the protocol.
5. `search_strategy_catalog` selects one of seven archetypes.
6. `create_strategy_draft` renders either `single_test` or `python_bundle`.
   All seven archetypes support both profiles.
7. `update_strategy_draft` requires the current revision and file hash.
8. `validate_strategy_draft` parses and compiles AST without importing the
   candidate in the server. It classifies direct Strategy classes separately
   from cooperative Indicator/LineIterator/Observer/Analyzer objects. A direct
   Strategy does not have a global `super().__init__()` requirement; a custom
   cooperative line object does.
9. `prepare_strategy_changes` requires the validation token, exact target
   preimage hashes, and an idempotency key. It returns a signed change token
   and a complete create/replace/delete review.
10. Review the change, then run the printed command locally:

    ```bash
    backtrader-mcp approve \
      --change-set CHANGE_ID \
      --change-token 'SIGNED_TOKEN' \
      --yes
    ```

    The approval record is created in the private local database. There is no
    MCP tool for approval and no `approved=true` parameter.

11. `apply_strategy_changes` requires that approval ID, the signed change
    token, and a new idempotency key. It rechecks draft and target hashes,
    stages the complete managed directory, and uses a journaled rename
    transaction.
12. `prepare_strategy_run` requires a fresh validation token, immutable
    dataset ID, registered runtime ID, timeout, one of the fixed run profiles
    (`runonce`, `runnext`, `runonce_runnext_compare`, or `fixed_tests`), and an
    idempotency key. It freezes the exact draft, artifact, validation, dataset,
    runtime, profile, and timeout hashes and returns a signed run token.
13. Review those frozen inputs, then create a separate execution approval
    locally:

    ```bash
    backtrader-mcp approve \
      --run-plan RUN_PLAN_ID \
      --run-token 'SIGNED_RUN_TOKEN' \
      --yes
    ```

    Change approvals and run approvals have different subject types and cannot
    be reused for one another.

14. `start_strategy_run` accepts only that run plan ID, signed run token,
    execution approval ID, and a new idempotency key. Poll `get_run_status`;
    optionally call `cancel_strategy_run`; read the normalized JSON and
    Markdown report with `get_run_result`.

Job states are `QUEUED`, `RUNNING`, `CANCEL_REQUESTED`, `CANCELLED`,
`SUCCEEDED`, `FAILED`, `TIMED_OUT`, and `ORPHANED`.

Successful results contain exactly eleven canonical metrics:
`bar_num`, `buy_count`, `sell_count`, `win_count`, `loss_count`, `trade_num`,
`final_value`, `sharpe_ratio`, `annual_return`, `max_drawdown`, and
`return_rate`. `sharpe_ratio` and `annual_return` are nullable. The bundled
`comparison-profile-v1` defines deterministic integer equality and floating
point tolerances for run comparison.

## Typed data adapters and bar operations

`register_local_dataset` accepts six independent typed adapters:
`generic_csv`, `backtrader_csv`, `yahoo_csv`, `mt5_csv`, `pandas`, and
`pandas_custom_lines`. Every source is parsed and normalized into an immutable
canonical CSV object before execution. The controlled worker then constructs
the named Backtrader adapter for each feed; it does not silently route every
format through `GenericCSVData`.

Pandas inputs must use `source_type=materialized_dataframe` and reference a
confined `.csv` file. Pickles, arbitrary Python objects, and caller-supplied
constructors are rejected. `pandas_custom_lines` also requires every custom
line to be declared in both `lines` and `columns`.

Each feed may declare a typed `extensions.bar_operation`:

```json
{"mode": "direct"}
```

or:

```json
{"mode": "resample", "timeframe": "minutes", "compression": 5}
```

`mode` may also be `replay`. Resample and replay are applied with
`Cerebro.resampledata` and `Cerebro.replaydata`, respectively. Successful
fixed-test results include per-mode `feed_runtime` evidence with the requested
format, actual adapter class, bar operation, source row count, and output bar
count.

## Security model

- Stdio writes protocol frames only to stdout. Candidate stdout/stderr are
  redirected to per-job private log files.
- Source, target, draft, CAS, and job paths are confined. Symlinks and parent
  traversal are rejected at caller-controlled boundaries.
- Validation and change tokens use a random 256-bit local secret, random
  nonces, expirations, and HMAC-SHA256 over canonical hash bindings.
- Apply authorization comes only from the trusted local CLI record.
- Target application replaces the entire managed strategy directory. Callers
  must provide the exact hash of every pre-existing file, including files that
  will be deleted.
- Candidate code is never imported by the MCP process. A worker launches it
  with a fixed interpreter, fixed entrypoint, minimal environment, separate
  process group, timeout, captured output, and validated result contract.

Static AST policy and a subprocess are not an OS sandbox. Reviewed candidate
code still runs with the local user's filesystem permissions. P0 is intended
for trusted local strategy development; run it in a container or restricted
OS account for hostile code. SQLite state is single-host, and the journaled
directory swap is crash-recoverable but not a multi-host distributed
transaction. Cancellation is process-based, not an MCP Tasks capability.

## Development and acceptance

Run all commands from this directory:

```bash
python -m pip install -e ".[test]"
PYTHONPATH=src python -m pytest -q
# With the four BACKTRADER_MCP_* root variables from the install section:
PYTHONPATH=src python -m backtrader_mcp doctor
PYTHONPATH=src python -m backtrader_mcp audit-independence
python scripts/run_acceptance.py --matrix all \
  --require-no-skills --require-no-agent
```

Protocol tests install `mcp==2.0.0` only into a temporary target directory.
They must not upgrade or remove the user's base-environment `mcp==1.20.0`.
The fixed acceptance entrypoint consumes a structured 14-cell artifact rather
than inferring success from pytest progress dots. It first builds a temporary
wheel, installs that wheel with `--no-deps` into a clean temporary target, and
runs pytest from a separate directory outside this source checkout. Test and
runtime dependencies must therefore already be available in the active
environment, but `backtrader_mcp` itself is imported only from the installed
wheel target.

The matrix executes all seven archetypes with both output profiles as real
runonce/runnext child-process backtests, covers all six adapters plus
resample/replay, and records inspect/register/preview, draft/validate,
prepare/apply, run, and compare evidence. Its JSON output also records the
wheel SHA-256, installed module origin,
`source_checkout_on_sys_path=false`, sibling-product absence, and the
independence audit. Callers cannot supply an arbitrary pytest target.
The wheel acceptance additionally verifies the exact full-snapshot SHA-256 and
imports/searches it from a clean temporary site directory outside this
repository, with no sibling AI product on `PYTHONPATH`.
