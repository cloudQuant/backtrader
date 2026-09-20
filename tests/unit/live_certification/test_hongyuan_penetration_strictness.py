"""Strictness regressions for the Hongyuan penetration certification suite.

Iteration 31 changed the Hongyuan suite in three ways that the shared
``test_simnow_penetration_certification.py`` contract must not regress:

1. every order call declares an explicit ``position_side`` (dual-side account);
2. evidence must be traceable — a case can no longer promote an arbitrary
   ``details["events"]`` literal into observed evidence;
3. "position unchanged" reconciliation ignores tick-driven mark-to-market
   fields, so threshold cases no longer flip between PASS and FAIL.

The SimNow copy intentionally keeps the previous semantics; its own tests stay
in the shared module.
"""
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SUITE_DIR = REPO_ROOT / "examples" / "007_ctp" / "live_certification" / "hongyuan_penetration"
CASES_DIR = SUITE_DIR / "cases"


def load_suite_module(name):
    """Import ``common.<name>`` from the Hongyuan suite without cross-talk."""
    for module_name in list(sys.modules):
        if module_name == "common" or module_name.startswith("common."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SUITE_DIR))
    try:
        return importlib.import_module(f"common.{name}")
    finally:
        sys.path.remove(str(SUITE_DIR))


def write_snapshots(tmp_path, before, after):
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps([before, after], ensure_ascii=False), encoding="utf-8"
    )


def write_threshold_log(tmp_path, threshold=10):
    """Minimal framework log that satisfies TH01's threshold evidence."""
    logs = tmp_path / "logs"
    logs.mkdir(exist_ok=True)
    (logs / "monitor.log").write_text(
        json.dumps(
            {
                "event_type": "risk_threshold_configured",
                "details": {"thresholds": {"submit_count": threshold}},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def blank_snapshot(label, positions):
    return {
        "label": label,
        "balance": {"cash": 1000.0, "value": 1000.0},
        "positions": positions,
        "open_orders": [],
    }


# ---------------------------------------------------------------------------
# 1. dual-side order contract
# ---------------------------------------------------------------------------


def test_every_order_call_declares_position_side():
    offenders = []
    for path in sorted(CASES_DIR.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"self\.(buy|sell)\(", line):
                continue
            window = "\n".join(lines[index : index + 6])
            if "position_side" not in window:
                offenders.append(f"{path.name}:{index + 1}")
    assert offenders == [], f"order calls missing position_side: {offenders}"


def test_every_order_call_is_preceded_by_ctp_admission():
    """BtApiBroker blocks exposure without fresh typed-query evidence."""
    offenders = []
    for path in sorted(CASES_DIR.glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not re.search(r"self\.(buy|sell)\(", line):
                continue
            if not any(
                "ensure_ctp_trading_admission" in lines[look]
                for look in range(max(0, index - 2), index + 1)
            ):
                offenders.append(f"{path.name}:{index + 1}")
    assert offenders == [], f"order calls without admission check: {offenders}"


def test_order_cases_start_from_a_deterministic_seed_bar():
    """Sparse exchange ticks must not decide whether a case can start.

    The simulation front pushes ~0.2 tick/s, so a case that waits for a live
    5-second bar flakes between runs.  Order-capable cases must seed one
    historical bar (``next()`` then fires deterministically), and
    ``store.set_history()`` must not be used because it never feeds the
    strategy.
    """
    offenders = []
    for path in sorted(CASES_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "set_history(" in source:
            offenders.append(f"{path.name}:set_history")
        if re.search(r"self\.(buy|sell)\(", source) and "historical_bars" not in source:
            offenders.append(f"{path.name}:no_seed")
    assert offenders == [], f"non-deterministic case startup: {offenders}"


def test_make_seed_bar_shape():
    runtime = load_suite_module("runtime")

    bar = runtime.make_seed_bar(price=4260.0)

    assert set(bar) == {
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "openinterest",
    }
    assert bar["close"] == 4260.0
    assert bar["volume"] == 1.0


def test_admission_helper_short_circuits_on_fresh_evidence():
    runtime = load_suite_module("runtime")

    class FreshStore:
        queries = 0

        def get_ctp_query_health(self):
            return {"evidence_complete": True}

        def get_ctp_preflight_snapshot(self, *_args, **_kwargs):
            self.queries += 1
            return {}

    store = FreshStore()
    runtime.ensure_ctp_trading_admission(store, "rb2701")
    assert store.queries == 0


def test_admission_helper_queries_and_raises_when_incomplete():
    runtime = load_suite_module("runtime")

    class StaleStore:
        queries = 0

        def get_ctp_query_health(self):
            if self.queries == 0:
                return {
                    "evidence_complete": False,
                    "evidence_errors": ["ctp_query_snapshot_missing"],
                }
            return {"evidence_complete": False, "evidence_errors": ["still_incomplete"]}

        def get_ctp_preflight_snapshot(self, *_args, **_kwargs):
            self.queries += 1
            return {"evidence_complete": False}

    store = StaleStore()
    with pytest.raises(RuntimeError, match="CTP admission preflight incomplete"):
        runtime.ensure_ctp_trading_admission(store, "rb2701")
    # A persistently incomplete sample must not fail the order immediately:
    # the helper retries a bounded number of times before raising.
    assert 1 < store.queries <= 4


def test_symbol_resolution_follows_the_store_alias_table():
    """CTP naming is case-sensitive per exchange; resolve via the store.

    SHFE/DCE use the lowercase native id (``rb2701``); CZCE uses the uppercase
    alias (``SA2701``).  Blindly upper/lower-casing breaks the other exchange,
    so the store's own alias table decides.
    """
    runtime = load_suite_module("runtime")

    class Store:
        def __init__(self, table):
            self.table = table

        def get_symbol_info(self, symbol):
            return self.table.get(symbol, {})

    czce = Store({"SA2701": {"instrument": "SA701"}, "sa2701": {}, "SA701": {"instrument": "SA701"}})
    assert runtime.resolve_ctp_symbol(czce, "sa2701") == "SA2701"
    assert runtime.resolve_ctp_symbol(czce, "SA2701") == "SA2701"

    shfe = Store({"rb2701": {"instrument": "rb2701"}, "RB2701": {}})
    assert runtime.resolve_ctp_symbol(shfe, "rb2701") == "rb2701"
    assert runtime.resolve_ctp_symbol(shfe, "RB2701") == "rb2701"

    unknown = Store({})
    assert runtime.resolve_ctp_symbol(unknown, "zz9999") == "zz9999"


def test_live_seed_bar_falls_back_to_the_cached_tick_price():
    """No fresh tick must not mean an out-of-limit synthetic seed price."""
    runtime = load_suite_module("runtime")

    class NoPollStore:
        def subscribe(self, _symbol):
            pass

        def poll_tick(self, _symbol):
            return None

        def get_latest_tick_snapshot(self, _symbol):
            return type("CachedTick", (), {"price": 1010.0})()

    bar = runtime.live_seed_bar(NoPollStore(), "SA2701", timeout=0.0)

    assert bar["close"] == 1010.0


def test_admission_arms_with_preflight_resolved_instrument():
    """The gate canonicalises EXCHANGE.INSTRUMENT; arm with the resolved pair.

    A bare CZCE certification symbol such as ``sa2701`` cannot be canonicalised
    on its own (its native id is ``SA701``/``CZCE``), and the SDK rejects it as
    ``ctp_execution_gate_invalid_proof``.
    """
    runtime = load_suite_module("runtime")

    class RecordingStore:
        armed = None

        def get_ctp_query_health(self):
            return {"evidence_complete": True}

        def get_ctp_preflight_snapshot(self, *_args, **_kwargs):
            return {
                "snapshot_sha256": "a" * 64,
                "instrument_id": "SA701",
                "exchange_id": "CZCE",
                "evidence_complete": True,
            }

        def arm_registered_sim_execution(self, instrument_id, exchange_id="", **kwargs):
            type(self).armed = (instrument_id, exchange_id, kwargs)

    store = RecordingStore()
    runtime.ensure_ctp_trading_admission(store, "sa2701")

    assert RecordingStore.armed is not None
    instrument_id, exchange_id, kwargs = RecordingStore.armed
    assert instrument_id == "SA701"
    assert exchange_id == "CZCE"
    assert kwargs["preflight_sha256"] == "a" * 64


def test_store_start_retries_transient_login_readiness():
    """The simulation front occasionally misses the fixed 20s login window."""
    runtime = load_suite_module("runtime")

    class FlakyStore:
        def __init__(self):
            self.starts = 0
            self.stops = 0

        def start(self):
            self.starts += 1
            if self.starts == 1:
                raise RuntimeError("CTP market data login did not become ready within 20s")

        def stop(self):
            self.stops += 1

    store = FlakyStore()
    runtime.start_store_with_retry(store, attempts=3, delay=0.0)

    assert store.starts == 2
    assert store.stops == 1


def test_store_start_fails_fast_on_non_readiness_errors():
    """Credential/auth failures must surface immediately, never be retried."""
    runtime = load_suite_module("runtime")

    class BrokenStore:
        def __init__(self):
            self.starts = 0

        def start(self):
            self.starts += 1
            raise RuntimeError("CTP authentication failed: bad password")

        def stop(self):
            raise AssertionError("stop must not be called for a non-readiness error")

    store = BrokenStore()
    with pytest.raises(RuntimeError, match="authentication failed"):
        runtime.start_store_with_retry(store, attempts=3, delay=0.0)
    assert store.starts == 1


def test_close_offset_is_exchange_aware():
    """CZCE (three-digit month) takes ``close``; SHFE/DCE take ``close_today``."""
    runtime = load_suite_module("runtime")

    assert runtime.close_offset_for("SA701") == "close"
    assert runtime.close_offset_for("CZCE.SA701") == "close"
    assert runtime.close_offset_for("rb2701") == "close_today"
    assert runtime.close_offset_for("SHFE.rb2701") == "close_today"


def test_open_case_waits_for_counter_acceptance():
    """T01 must stop on the counter's acceptance, not the broker's bookkeeping."""
    source = (CASES_DIR / "T01_open_order.py").read_text(encoding="utf-8")

    assert "counter_accepted" in source
    assert "order_status_accepted" in source
    assert "notify_store" in source


def test_cancel_case_requires_counter_cancel_confirmation():
    """T03 must not certify a cancel from the broker-local ``Canceled`` status."""
    source = (CASES_DIR / "T03_cancel_order.py").read_text(encoding="utf-8")

    assert "counter_canceled" in source
    assert "order_status_canceled" in source


def test_run_case_resolves_report_root_before_spawning_cases():
    """A relative --report-root must not be resolved against the case's cwd."""
    source = (SUITE_DIR / "run_case.py").read_text(encoding="utf-8")

    assert "Path(args.report_root).resolve()" in source


def test_suite_runs_the_broker_in_dual_side_mode():
    config = load_suite_module("config")

    assert config.DEFAULT_POSITION_MODE == "dual_side"
    assert config.get_position_mode() == "dual_side"

    runtime_source = (SUITE_DIR / "common" / "runtime.py").read_text(encoding="utf-8")
    assert 'broker_kwargs.setdefault("position_mode"' in runtime_source


def test_default_contract_is_the_active_rebar_contract():
    config = load_suite_module("config")

    assert config.DEFAULT_ORDER_SYMBOL == "rb2701"
    assert config.DEFAULT_TICK_SYMBOL == "rb2701"


def test_create_config_carries_position_mode(monkeypatch):
    config = load_suite_module("config")
    monkeypatch.setenv("HONGYUAN_USER_ID", "tester")
    monkeypatch.setenv("HONGYUAN_PASSWORD", "secret")
    monkeypatch.delenv("HONGYUAN_POSITION_MODE", raising=False)

    payload = config.create_config("telecom")

    assert payload["position_mode"] == "dual_side"
    monkeypatch.setenv("HONGYUAN_POSITION_MODE", "net")
    assert config.create_config("telecom")["position_mode"] == "net"


# ---------------------------------------------------------------------------
# 2. evidence provenance
# ---------------------------------------------------------------------------


def test_case_declared_events_do_not_self_certify(tmp_path):
    """``details["events"]`` must not satisfy required_events on its own."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(tmp_path, blank_snapshot("before_action", []), blank_snapshot("after_action_before_stop", []))

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "telecom") as timer:
        result = timer.pass_result(
            details={"events": ["order_submit_request", "order_status_accepted"]}
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    assert "order_submit_request" in result.missing_required_events
    assert "order_status_accepted" in result.missing_required_events
    assert "order_submit_request" not in result.observed_events


def _write_lines(dir_path, name, rows):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / name).write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_store_request_acceptance_does_not_impersonate_counter_acceptance(tmp_path):
    """``order_submit_accepted`` only proves the store enqueued the request.

    The 2026-09-18 morning run certified T01 on out-of-limit orders that the
    counter actually rejected, because the store's submit response was aliased
    to ``order_status_accepted``.  Only a counter status may certify.
    """
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(tmp_path, blank_snapshot("before_action", []), blank_snapshot("after_action_before_stop", []))
    _write_lines(
        tmp_path / "logs",
        "monitor.log",
        [
            {"event_type": "order_submit_request", "order_ref": 1},
            {"event_type": "order_submit_accepted", "order_ref": 1, "status": "accepted"},
        ],
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "telecom") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert "order_status_accepted" not in result.observed_events
    assert "order_status_accepted" in result.missing_required_events
    assert result.status == "FAIL"


def test_broker_local_order_log_acceptance_does_not_impersonate_counter_acceptance(tmp_path):
    """An order.log ``Accepted`` row is broker-local, not counter-confirmed."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(tmp_path, blank_snapshot("before_action", []), blank_snapshot("after_action_before_stop", []))
    _write_lines(tmp_path / "logs", "monitor.log", [{"event_type": "order_submit_request", "order_ref": 1}])
    _write_lines(
        tmp_path / "logs",
        "order.log",
        [{"ref": 1, "order_type": "Buy", "status": "Accepted", "external_order_id": None}],
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "telecom") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert "order_status_accepted" not in result.observed_events
    assert result.status == "FAIL"


def test_counter_status_event_certifies_acceptance(tmp_path):
    """A counter status event (with its OrderSysID) still certifies T01."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(tmp_path, blank_snapshot("before_action", []), blank_snapshot("after_action_before_stop", []))
    _write_lines(tmp_path / "logs", "monitor.log", [{"event_type": "order_submit_request", "order_ref": 1}])
    _write_lines(
        tmp_path / "logs",
        "error.log",
        [
            {
                "event_type": "order_status_accepted",
                "order_ref": "1341935",
                "external_order_id": "1341935",
                "status": "accepted",
            }
        ],
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "telecom") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert "order_status_accepted" in result.observed_events
    assert result.status == "PASS"


def test_counter_qualified_order_log_row_still_certifies(tmp_path):
    """A counter-qualified log row remains the authoritative evidence source."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(tmp_path, blank_snapshot("before_action", []), blank_snapshot("after_action_before_stop", []))
    _write_lines(tmp_path / "logs", "monitor.log", [{"event_type": "order_submit_request", "order_ref": "1"}])
    _write_lines(
        tmp_path / "logs",
        "order.log",
        [{"ref": 1, "order_type": "Buy", "status": "Accepted", "external_order_id": "sys-1"}],
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "telecom") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert "order_status_accepted" in result.observed_events
    assert result.status == "PASS"
    assert result.missing_required_events == []


def test_store_notification_channel_is_provenance_guarded(tmp_path):
    """The notification channel only counts when it carries the right key."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(tmp_path, blank_snapshot("before_action", []), blank_snapshot("after_action_before_stop", []))

    with result_mod.CaseTimer("M03", "断线后显示重连成功", "telecom") as timer:
        result = timer.pass_result(
            details={
                "store_notification_events": ["store_reconnect_success"],
                "gateway_key": "telecom",
                "timestamp": "2026-09-17T10:00:00+08:00",
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "PASS"
    assert "store_reconnect_success" in result.observed_events
    assert result.details["certification_evidence"]["timestamp"] == "2026-09-17T10:00:00+08:00"


def test_notification_channel_requires_get_notifications_in_source():
    """Any case claiming in-process store events must actually read them."""
    offenders = []
    for path in sorted(CASES_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "store_notification_events" in source and "get_notifications()" not in source:
            offenders.append(path.name)
    assert offenders == [], f"unproven notification evidence: {offenders}"


def test_snapshot_keys_are_not_universal_evidence_fields(tmp_path):
    """A snapshot's own ``timestamp`` key must not satisfy a required field."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(
        tmp_path,
        {**blank_snapshot("before_action", []), "timestamp": "2026-09-17T10:00:00"},
        {**blank_snapshot("after_action_before_stop", []), "timestamp": "2026-09-17T10:01:00"},
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "system.log").write_text(
        json.dumps({"event_type": "session_stopped"}) + "\n", encoding="utf-8"
    )

    with result_mod.CaseTimer("M02", "连接断开显示连接断开", "telecom") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert "store_disconnected" in result.observed_events
    assert "timestamp" in result.missing_evidence_fields


# ---------------------------------------------------------------------------
# 3. reconciliation ignores mark-to-market noise
# ---------------------------------------------------------------------------


def test_position_unchanged_ignores_mark_to_market_moves(tmp_path):
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    before = blank_snapshot(
        "before_action",
        [{"instrument": "rb2701", "direction": "long", "volume": 6, "current_price": 4785.0, "profit": 5760.0}],
    )
    after = blank_snapshot(
        "after_action_before_stop",
        [{"instrument": "rb2701", "direction": "long", "volume": 6, "current_price": 4873.0, "profit": 11040.0}],
    )
    write_snapshots(tmp_path, before, after)
    write_threshold_log(tmp_path)

    with result_mod.CaseTimer("TH01", "报单笔数阈值设置", "telecom") as timer:
        result = timer.pass_result(details={"order_threshold": 10})

    result = evidence.attach_reconciliation(result, tmp_path)
    checks = result.details["reconciliation"]["checks"]

    assert checks["account_position_unchanged"]["positions_changed"] is False
    assert checks["account_position_unchanged"]["passed"] is True
    assert result.status == "PASS"


def test_external_position_drift_does_not_fail_position_unchanged(tmp_path):
    """A shared live account can change underneath a case that traded nothing.

    C01 (login only) observed SA701 long 2 -> 3 because a *previous* case's
    working order filled inside its snapshot window.  Without any trade event
    of its own the case cannot have caused that move, so the drift must be
    recorded as evidence rather than failing the case.
    """
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(
        tmp_path,
        blank_snapshot("before_action", [{"instrument": "rb2701", "direction": "long", "volume": 6}]),
        blank_snapshot("after_action_before_stop", [{"instrument": "rb2701", "direction": "long", "volume": 8}]),
    )
    write_threshold_log(tmp_path)

    with result_mod.CaseTimer("TH01", "报单笔数阈值设置", "telecom") as timer:
        result = timer.pass_result(details={"order_threshold": 10})

    result = evidence.attach_reconciliation(result, tmp_path)
    check = result.details["reconciliation"]["checks"]["account_position_unchanged"]

    assert check["positions_changed"] is True
    assert check["case_trade_events"] == 0
    assert check["passed"] is True
    assert result.status == "PASS"


def test_case_attributable_position_change_fails_position_unchanged(tmp_path):
    """A fill that belongs to this case must still fail a no-change case."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    write_snapshots(
        tmp_path,
        blank_snapshot("before_action", [{"instrument": "rb2701", "direction": "long", "volume": 6}]),
        blank_snapshot("after_action_before_stop", [{"instrument": "rb2701", "direction": "long", "volume": 8}]),
    )
    write_threshold_log(tmp_path)
    with open(tmp_path / "logs" / "monitor.log", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_type": "trade_execution", "trade_id": "t-1"}) + "\n")

    with result_mod.CaseTimer("TH01", "报单笔数阈值设置", "telecom") as timer:
        result = timer.pass_result(details={"order_threshold": 10})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.details["reconciliation"]["checks"]["account_position_unchanged"]["passed"] is False
    assert result.status == "FAIL"


def test_cash_drift_alone_does_not_fail_position_unchanged(tmp_path):
    """Commission/fee drift must not be reported as a position change."""
    result_mod = load_suite_module("result")
    evidence = load_suite_module("evidence")

    before = blank_snapshot("before_action", [{"instrument": "rb2701", "direction": "long", "volume": 1}])
    after = blank_snapshot("after_action_before_stop", [{"instrument": "rb2701", "direction": "long", "volume": 1}])
    after["balance"] = {"cash": 990.0, "value": 1000.0}
    write_snapshots(tmp_path, before, after)
    write_threshold_log(tmp_path)

    with result_mod.CaseTimer("TH01", "报单笔数阈值设置", "telecom") as timer:
        result = timer.pass_result(details={"order_threshold": 10})

    result = evidence.attach_reconciliation(result, tmp_path)
    check = result.details["reconciliation"]["checks"]["account_position_unchanged"]

    assert check["balance_changed"] is True
    assert check["positions_changed"] is False
    assert check["passed"] is True
    assert result.status == "PASS"


# ---------------------------------------------------------------------------
# 4. coverage must not read as a pass rate
# ---------------------------------------------------------------------------


def test_coverage_separates_attempted_from_evidenced_pass():
    certification = load_suite_module("certification")

    results = []
    for case_id in ("C01", "M01", "M02", "T01", "T02"):
        scenario = certification.get_certification_scenario(case_id)
        results.append(
            {
                "case_id": case_id,
                "scenario_id": scenario.scenario_id,
                "status": "PASS" if case_id in ("C01", "M01") else "FAIL",
            }
        )

    coverage = certification.build_certification_coverage(
        case_order=["C01", "M01", "M02", "T01", "T02"],
        case_registry={case_id: Path("x") for case_id in ("C01", "M01", "M02", "T01", "T02")},
        results=results,
    )

    assert coverage["covered_scenarios"] == 5
    assert coverage["evidenced_pass_scenarios"] == 2
    assert coverage["evidenced_pass_ids"] == [
        certification.get_certification_scenario("C01").scenario_id,
        certification.get_certification_scenario("M01").scenario_id,
    ]
    assert coverage["required_scenarios"] == 5
    assert coverage["evidenced_required_pass_scenarios"] == 2
