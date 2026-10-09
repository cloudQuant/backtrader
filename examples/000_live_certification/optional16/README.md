# optional16 — optional-component acceptance matrix (Binance USDⓈ-M demo)

`optional16` is the 2 × 2 × 2 × 2 grid of one transport choice
(`direct` or `gateway_zmq`) and the three optional components
(`execution`, `risk`, `monitor`). Core files (sibling gateway/capability
tooling lives alongside them and is documented in its own headers):

| file | purpose |
| --- | --- |
| `spec.py` | `TopologySpec` / `from_config` / `combo_id` / `matrix_specs` (pure validation) |
| `gateway_server.py` | loopback-only server owning one provider session (closed command whitelist) |
| `gateway_client.py` | duck-typed client forwarding every call over the local transport |
| `components.py` | `wrap_client(client, config, topology, env)` mounts the enabled dev-SDK components |
| `run_matrix.py` | the 16-combination acceptance-matrix runner (dry / live) |
| `acceptance-matrix.json` | the last run's record (written by `run_matrix.py`) |

## Combo → flags

`combo_id` is `<transport>-e<0|1>-r<0|1>-m<0|1>`
(`e` = execution, `r` = risk, `m` = monitor), for example
`gateway_zmq-e1-r0-m1`. Every combo becomes one case-runner command:

```text
direct-e0-r0-m0        --transport direct
direct-e1-r0-m1        --transport direct --execution --monitor
gateway_zmq-e0-r0-m1   --transport gateway_zmq --monitor
gateway_zmq-e1-r1-m1   --transport gateway_zmq --execution --risk --monitor
```

The runner passes `--transport` plus one `--<component>` flag per enabled
component; the case config's own `topology:` block is only the default when a
flag is omitted. Nothing else in the case files changes.

## Component mounts (`components.py`)

`wrap_client` keeps the exact case-facing surface (`connect`,
`account_config`, `balances`, `position_risk`, `open_orders`, `query_order`,
`filters`, `mark_price`, `place_order`, `cancel_order`, `describe`, `calls`,
plus `close`/`frozen`/… delegated to the base client) and adds:

* **risk** — the real `bt_api_risk` durable gate: `reserve` →
  `claim_for_dispatch` → provider dispatch → `settle`. The per-run policy
  comes from the case `policy:` block (`max_orders`, `max_notional_usdt`); the
  SQLite gate lives in the run temp dir. A policy rejection raises
  `RuntimeError("risk_rejected:<code>")` **before** any dispatch and the code
  is recorded (`describe()["components"]["risk"]["denials"]`).
* **execution** — the real `bt_api_execution` `ManagedExecutionFacade`
  (`place_order`) and `ManagedCancellationFacade` (`cancel_order`) over a
  per-run `SqliteExecutionStore`; the venue reply round-trips to the caller
  (`orderId`/`status`, `_client_order_id`). With `risk` enabled, both facades
  share the *same* gate through the SDK's `SharedRiskAdmissionAdapter`, so one
  order still runs one reserve/claim/settle chain.
* **monitor** — the real `bt_api_monitor` `DurableOutbox`: one durable
  `append` + `acknowledge` per operation (`connect`, `place_order`,
  `query_order`, `cancel_order`) and a signed `ReadOnlyEventService` readback;
  `client.monitor_counts()` returns `{"appended", "acknowledged"}` plus the
  readback page facts.

A disabled component's package is never imported; `describe()` reports the
`sys.modules` delta under `imports_observed` and every fallback/limit note
under `adapter_notes`. An enabled-but-unimportable package raises
`RuntimeError("component_unavailable:<name>")` (fail closed, no silent skip).

## Dry invocation (no network)

```powershell
C:/anaconda3/python.exe D:/source_code/backtrader/examples/000_live_certification/optional16/run_matrix.py --dry
```

Each case runs its own dry self-check (`cases/<ID>/run.py --transport …`), which
reads the config, resolves credential *names* and prints its plan — the dry
path never constructs a client, so nothing touches the network. Non-zero exits
(`DRY` with missing env names exits 2) and unparsable output are recorded, not
treated as harness failures. `--cases C01,T03` selects the case set and
`--combos …` restricts the grid (useful for a single spot check).

## Live invocation (operator, real demo account)

Writes are only sent when the operator adds the write grants; run the two
cases from their own directories (any CWD works for `run_matrix.py`):

```powershell
# read-only case (C01) through each transport
C:/anaconda3/python.exe examples/000_live_certification/binance_penetration/cases/C01/run.py --live --transport direct
C:/anaconda3/python.exe examples/000_live_certification/binance_penetration/cases/C01/run.py --live --transport gateway_zmq

# cancel case (T03, WRITE risk level) — grants are required
C:/anaconda3/python.exe examples/000_live_certification/binance_penetration/cases/T03/run.py --live --allow-write --transport direct
C:/anaconda3/python.exe examples/000_live_certification/binance_penetration/cases/T03/run.py --live --allow-write --transport gateway_zmq

# with components (execution/risk/monitor are independent flags)
C:/anaconda3/python.exe .../cases/T03/run.py --live --allow-write --transport direct --execution --risk --monitor
C:/anaconda3/python.exe .../cases/T03/run.py --live --allow-write --transport gateway_zmq --execution --risk --monitor

# the whole matrix in one go (operator-run; --allow-write covers the T03 cases)
C:/anaconda3/python.exe examples/000_live_certification/optional16/run_matrix.py --live --allow-write
```

The case runner reads credentials by *name* from the checkout-root `.env`;
this task never ran a live session. `--allow-dangerous` is only needed for
DANGEROUS-level cases (none in the default set).

## Acceptance record format (`acceptance-matrix.json`)

```jsonc
{
  "schema": "optional16-acceptance-matrix/1",
  "run_id": "<uuid4 hex>", "mode": "dry" | "live", "dry": true,
  "python": "<interpreter used>", "repo_root": "...", "cert_root": "...", "case_root": "...",
  "cases": ["C01", "T03"], "spec_source": "optional16.spec" | "inline-fallback",
  "grants": {"allow_write": false, "allow_dangerous": false},
  "started_utc": "...", "finished_utc": "...",
  "commands": ["<exact command line per distinct combo>"],
  "combos": [{
    "combo_id": "direct-e0-r0-m0", "transport": "direct",
    "flags": {"execution": false, "risk": false, "monitor": false},
    "started_utc": "...", "finished_utc": "...",
    "cases": {"C01": {
      "case": "C01", "command": "...", "exit_code": 0,
      "status": "DRY|PASS|FAIL|BLOCKED|UNKNOWN|TIMEOUT|ERROR|UNPARSED",
      "reason": "...", "evidence": "<evidence json path or null>",
      "started_utc": "...", "finished_utc": "...",
      "summary": {…case summary/plan…}, "stdout_tail": "…", "stderr_tail": "…"}}]
  }],
  "totals": {"DRY:C01": 16, "DRY:T03": 16}
}
```

`exit_code` is the frozen runner mapping (0 PASS, 1 FAIL, 2 BLOCKED,
3 UNKNOWN); the matrix runner adds `DRY`/`TIMEOUT`/`ERROR`/`UNPARSED` for its
own harness states. Dry mode always exits 0 (statuses are the evidence); live
mode exits 0 only when every case reported `PASS`.

## Known limits

* The `gateway_zmq` transport is a **loopback** server (127.0.0.1, random
  port, random shared token; stdlib TCP+JSON fallback when the ZMQ package is
  unavailable). It is not an OS-isolation boundary and it is not
  latency-equivalent to `direct`; timing-sensitive acceptance must not be
  claimed from it.
* `risk` + `execution` share the real gate, and `claim_for_dispatch` installs
  the gate's durable `dispatch-inflight` latch. No journal authority is
  installed here, so a run admits **one** risk-increasing order; a second
  `place_order` is rejected `risk_rejected:FROZEN` before dispatch. This is
  the current dev-SDK semantics, documented rather than hidden.
* `MARKET` orders have no pre-dispatch notional and fail closed
  (`risk_rejected:NOTIONAL_UNAVAILABLE`) while `risk` is enabled.
* `execution` without `risk` uses the facades' documented
  `allow_unprotected` fixture path (recorded in `adapter_notes`), which issues
  no admission permit.
* `cancel_order` for an order this wrapper did not place is still routed
  through the cancellation facade with a synthetic `unmanaged-<id>` target and
  a note; without any provider identity at all it falls back to the base
  client (also noted).
* Post-dispatch settlement/review failures are recorded
  (`..._failed`/`review_required` facts) but the venue reply is still
  returned, so the caller keeps the order identity it must cancel.
* Gateway-rejected writes whose error shape carries no venue code are
  journalled `UNKNOWN` (conservative); direct-client `code`/`msg` rejections
  are journalled `REJECTED` and re-raised. Writes are never retried.
* The components import the dev SDK from `D:/bt_api_py/bt_api/<pkg>/src`
  (override with `OPTIONAL16_SDK_ROOT`); `bt_api_monitor` additionally needs
  `bt_api_base`. Per-run SQLite files (`risk.sqlite`, `execution.sqlite`,
  `monitor.sqlite`) live in a fresh temp dir (`OPTIONAL16_RUN_DIR` override)
  and are not written inside the repository.
* `run_matrix.py` never imports SDK/provider code, never edits case files and
  only records what the case runner emitted; a recorded `PASS` remains subject
  to the case contract's own evidence rules.
* `run_matrix.py --case-root <suite-dir>` selects the venue suite (default
  `binance_penetration`); `--out` names the acceptance file.  The accepted
  16-combination matrix runs on the binance reference case set; mounting the
  components on the OKX/SimNow clients would need a per-venue order-parameter
  translation layer (sz/px/clOrdId and contract multipliers), which is
  deliberately out of the accepted scope — those suites stay direct-route
  certified.
