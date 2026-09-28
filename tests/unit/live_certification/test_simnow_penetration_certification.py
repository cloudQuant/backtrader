import contextlib
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_CERTIFICATION_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification"
SUITE_NAMES = ("simnow_penetration", "hongyuan_penetration")


def _is_suite_module(module_name):
    return (
        module_name == "run_case"
        or module_name == "common"
        or module_name.startswith("common.")
    )


def _clear_suite_modules():
    for module_name in list(sys.modules):
        if _is_suite_module(module_name):
            sys.modules.pop(module_name, None)


@contextlib.contextmanager
def _preserve_suite_import_state():
    previous_modules = {
        name: module for name, module in sys.modules.items() if _is_suite_module(name)
    }
    previous_path = sys.path[:]
    try:
        yield
    finally:
        _clear_suite_modules()
        sys.modules.update(previous_modules)
        sys.path[:] = previous_path


def _no_op_load_dotenv(*args, **kwargs):
    return None


@pytest.fixture(autouse=True)
def restore_suite_import_state(monkeypatch):
    try:
        dotenv = importlib.import_module("dotenv")
    except ImportError:
        pass
    else:
        monkeypatch.setattr(dotenv, "load_dotenv", _no_op_load_dotenv)

    with _preserve_suite_import_state():
        yield


def load_suite(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    _clear_suite_modules()
    sys.path.insert(0, str(suite_dir))
    try:
        run_case = importlib.import_module("run_case")
        certification = importlib.import_module("common.certification")
        result_mod = importlib.import_module("common.result")
    finally:
        sys.path.remove(str(suite_dir))
    return run_case, certification, result_mod


def test_simnow_admission_rejects_missing_typed_interfaces():
    load_suite("simnow_penetration")
    runtime = importlib.import_module("common.runtime")

    class MissingPreflight:
        def __getattr__(self, name):
            if name == "get_ctp_preflight_snapshot":
                raise AttributeError(name)
            raise AssertionError(f"unexpected store access: {name}")

    denied = runtime.ensure_ctp_trading_admission(MissingPreflight(), "SA701")
    assert denied.ok is False
    assert "preflight interface unavailable" in denied.reason

    class MissingArm:
        def get_ctp_preflight_snapshot(self, symbol, *, timeout):
            assert (symbol, timeout) == ("SA701", 15.0)
            return {"snapshot_sha256": "a" * 64}

        def get_ctp_query_health(self):
            return {"evidence_complete": True}

        def __getattr__(self, name):
            if name == "arm_registered_sim_execution":
                raise AttributeError(name)
            raise AssertionError(f"unexpected store access: {name}")

    denied = runtime.ensure_ctp_trading_admission(MissingArm(), "SA701")
    assert denied.ok is False
    assert "execution admission interface unavailable" in denied.reason


def test_loading_each_suite_restores_preexisting_module_objects(monkeypatch):
    previous_common = types.ModuleType("common")
    previous_common.__path__ = []
    previous_modules = {
        "run_case": types.ModuleType("run_case"),
        "common": previous_common,
        "common.evidence": types.ModuleType("common.evidence"),
        "common.runtime": types.ModuleType("common.runtime"),
    }
    for module_name, module in previous_modules.items():
        monkeypatch.setitem(sys.modules, module_name, module)

    with _preserve_suite_import_state():
        for suite_name in SUITE_NAMES:
            suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
            run_case, _, _ = load_suite(suite_name)
            evidence = importlib.import_module("common.evidence")
            runtime = importlib.import_module("common.runtime")

            assert Path(run_case.__file__).resolve().parent == suite_dir.resolve()
            assert Path(evidence.__file__).resolve().parent == (
                suite_dir / "common"
            ).resolve()
            assert Path(runtime.__file__).resolve().parent == (
                suite_dir / "common"
            ).resolve()

    for module_name, module in previous_modules.items():
        assert sys.modules[module_name] is module


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_suite_maps_all_33_cases_to_canonical_scenarios(suite_name):
    run_case, certification, _ = load_suite(suite_name)

    assert len(run_case.CASE_ORDER) == 33
    assert set(run_case.CASE_ORDER) == set(run_case.CASE_REGISTRY)

    scenarios = [
        certification.get_certification_scenario(case_id)
        for case_id in run_case.CASE_ORDER
    ]
    scenario_ids = [item.scenario_id for item in scenarios]

    assert len(scenario_ids) == 33
    assert len(set(scenario_ids)) == 33
    assert scenario_ids[0] == "AUTH-01"
    assert scenario_ids[-1] == "LOG-ERROR-01"
    assert scenarios[0].required_events == (
        "store_auth_success",
        "store_login_success",
    )


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_case_result_contains_canonical_trace_and_audit_event(suite_name, tmp_path):
    _, _, result_mod = load_suite(suite_name)

    with result_mod.CaseTimer("C01", "旧编号名称", "new_7x24") as timer:
        result = timer.pass_result(
            evidence=["system.log"],
            details={
                "events": ["store_auth_success", "store_login_success"],
                "front_id": 1,
                "session_id": 2,
                "trading_day": "20260618",
            },
        )

    payload = result.to_dict()

    assert payload["scenario_id"] == "AUTH-01"
    assert payload["scenario_name"] == "认证登录"
    assert payload["trace_id"].startswith("ctp-cert-")
    assert payload["required_events"] == [
        "store_auth_success",
        "store_login_success",
    ]
    assert payload["evidence_fields"] == [
        "front_id",
        "session_id",
        "trading_day",
    ]
    assert payload["audit_events"][0]["scenario_id"] == "AUTH-01"
    assert payload["audit_events"][0]["trace_id"] == payload["trace_id"]
    if suite_name == "simnow_penetration":
        assert payload["status"] == "FAIL"
        assert payload["required_events_present"] is False
        assert payload["observed_events"] == []
        assert payload["missing_required_events"] == payload["required_events"]
        assert payload["evidence_fields_present"] is False
        assert payload["missing_evidence_fields"] == payload["evidence_fields"]
        assert result_mod.PASS_UNAVAILABLE_REASON in payload["failure_reason"]
    else:
        assert payload["required_events_present"] is True
        assert payload["missing_required_events"] == []

    result_mod.save_result(result, tmp_path)

    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()

    assert str(tmp_path / "audit.jsonl") in saved["evidence"]
    assert len(audit_lines) == 1
    saved_audit = json.loads(audit_lines[0])
    assert saved_audit["scenario_id"] == "AUTH-01"
    if suite_name == "simnow_penetration":
        assert saved["status"] == "FAIL"
        assert saved_audit["status"] == "FAIL"


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_case_result_surfaces_missing_required_events(suite_name):
    _, _, result_mod = load_suite(suite_name)

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "new_7x24") as timer:
        result = timer.pass_result(
            details={"events": ["order_submit_request"]},
        )

    payload = result.to_dict()

    assert payload["scenario_id"] == "TRADE-OPEN-01"
    if suite_name == "simnow_penetration":
        assert payload["status"] == "FAIL"
        assert payload["required_events_present"] is False
        assert payload["missing_required_events"] == [
            "order_submit_request",
            "order_status_accepted",
        ]
        assert payload["audit_events"][0]["missing_required_events"] == [
            "order_submit_request",
            "order_status_accepted",
        ]
        assert result_mod.PASS_UNAVAILABLE_REASON in payload["failure_reason"]
    else:
        assert payload["status"] == "FAIL"
        assert payload["required_events_present"] is False
        assert payload["missing_required_events"] == ["order_status_accepted"]
        assert payload["audit_events"][0]["missing_required_events"] == [
            "order_status_accepted"
        ]
        assert "Missing required certification evidence" in payload["failure_reason"]


def test_simnow_bare_pass_result_and_save_are_fail_closed(tmp_path):
    _, certification, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    scenario = certification.get_certification_scenario("C01")
    details = {
        "events": list(scenario.required_events),
        **dict.fromkeys(scenario.evidence_fields, "caller-claimed"),
        "certification_evidence": {"claimed": True},
    }
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "events.log").write_text(
        "\n".join(
            json.dumps(
                {
                    "event_type": event,
                    "source": "runtime_provider_validator_receipt",
                    "event_id": f"claimed-{index}",
                    "evidence_sha256": "a" * 64,
                    "trace_id": "claimed-trace",
                }
            )
            for index, event in enumerate(scenario.required_events)
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("C01", scenario.name, "new_7x24") as timer:
        result = timer.pass_result(details=details)

    assert result.status == "FAIL"
    assert result.failure_reason == result_mod.PASS_UNAVAILABLE_REASON
    assert result.observed_events == []
    assert result.missing_required_events == list(scenario.required_events)
    assert result.missing_evidence_fields == list(scenario.evidence_fields)
    assert "certification_evidence" not in result.details

    result = evidence.attach_reconciliation(result, tmp_path)
    assert result.status == "FAIL"
    assert result.observed_events == []
    assert result.missing_required_events == list(scenario.required_events)
    assert result.missing_evidence_fields == list(scenario.evidence_fields)
    assert result.details["certification_evidence"] == {}

    def forge_pass_result():
        result.status = "PASS"
        result.observed_events = list(scenario.required_events)
        result.required_events_present = True
        result.missing_required_events = []
        result.missing_evidence_fields = []
        result.evidence_fields_present = True
        result.details["certification_evidence"] = {"claimed": True}
        result.audit_events[0]["status"] = "PASS"

    # Public result accessors must fail-close even before persistence.
    forge_pass_result()
    assert result.exit_code() == result_mod.EXIT_FAIL
    assert result.status == "FAIL"
    assert result.failure_reason == result_mod.PASS_UNAVAILABLE_REASON
    assert result.observed_events == []
    assert result.required_events_present is False

    forge_pass_result()
    payload = result.to_dict()
    assert payload["status"] == "FAIL"
    assert payload["failure_reason"] == result_mod.PASS_UNAVAILABLE_REASON
    assert payload["observed_events"] == []
    assert payload["required_events_present"] is False
    assert "certification_evidence" not in payload["details"]
    assert payload["audit_events"][0]["status"] == "FAIL"

    # The persistence guard is independent of the public accessors.
    forge_pass_result()
    result_mod.save_result(result, tmp_path)

    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    saved_audit = json.loads(
        (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert saved["status"] == "FAIL"
    assert saved["failure_reason"] == result_mod.PASS_UNAVAILABLE_REASON
    assert saved["observed_events"] == []
    assert saved["missing_required_events"] == list(scenario.required_events)
    assert saved["missing_evidence_fields"] == list(scenario.evidence_fields)
    assert "certification_evidence" not in saved["details"]
    assert saved_audit["status"] == "FAIL"
    assert saved_audit["observed_events"] == []
    assert saved_audit["required_events_present"] is False


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_reconciliation_compares_account_positions_orders_and_trades(
    suite_name, tmp_path
):
    _, _, result_mod = load_suite(suite_name)
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [{"instrument": "rb2610", "direction": "long", "volume": 1}],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 980.0, "value": 1005.0},
            "positions": [{"instrument": "rb2610", "direction": "long", "volume": 2}],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "order.log").write_text(
        json.dumps({"event_type": "order_submit_request"}) + "\n"
        + json.dumps({"event_type": "trade_execution"}) + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": [
                    "order_submit_request",
                    "order_status_accepted",
                    "trade_execution",
                ],
                "order_ref": "ref-1",
                "external_order_id": "sys-1",
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)
    reconciliation = result.details["reconciliation"]

    assert reconciliation["event_counts"]["order_events"] >= 1
    assert reconciliation["event_counts"]["trade_events"] >= 1
    assert reconciliation["account_delta"]["balance_changed"] is True
    assert reconciliation["account_delta"]["positions_changed"] is True
    assert reconciliation["checks"]["order_activity"]["passed"] is True
    assert reconciliation["checks"]["post_action_open_orders"]["passed"] is True
    assert str(tmp_path / "reconciliation.json") in result.evidence


def test_untrusted_jsonl_does_not_revalidate_required_order_evidence(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "monitor.log").write_text(
        json.dumps({"event_type": "order_submit_request", "order_ref": "bt-1"})
        + "\n"
        + json.dumps({"event_type": "order_submit_accepted", "order_ref": "bt-1"})
        + "\n",
        encoding="utf-8",
    )
    (logs / "order.log").write_text(
        json.dumps(
            {
                "ref": "bt-1",
                "status": "Accepted",
                "external_order_id": "sys-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "new_7x24") as timer:
        result = timer.pass_result(details={"events": ["order_submit_request"]})

    assert result.status == "FAIL"
    assert result.missing_required_events == [
        "order_submit_request",
        "order_status_accepted",
    ]

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    assert result.missing_required_events == ["order_submit_request", "order_status_accepted"]
    assert "order_status_accepted" not in result.observed_events
    assert result.details["certification_evidence"] == {}
    assert result.details["reconciliation"]["strict_reconciliation_pass"] is False


def test_source_less_threshold_log_does_not_revalidate_threshold_case(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "monitor.log").write_text(
        json.dumps(
            {
                "event_type": "order_submit_request",
                "details": {"bt_order_ref": "bt-1"},
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_type": "risk_threshold_triggered",
                "source": "runtime_monitor_receipt",
                "event_id": "claimed-threshold-event",
                "evidence_sha256": "a" * 64,
                "monitor_digest": "b" * 64,
                "timestamp": "2026-09-28T00:00:01Z",
                "trace_id": "claimed-trace",
                "details": {"counter": "submit_count", "value": 2, "threshold": 2},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("TH02", "报单笔数达到阈值预警", "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": ["risk_threshold_triggered"],
                "order_threshold": 2,
                "submitted_order_count": 2,
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    cert = result.details["certification_evidence"]
    assert result.status == "FAIL"
    assert "risk_threshold_triggered" in result.missing_required_events
    assert "risk_threshold_triggered" not in result.observed_events
    assert "order_threshold" not in cert
    assert cert == {}


@pytest.mark.parametrize(
    ("case_id", "event_type", "activity_types", "untrusted_field", "details"),
    [
        (
            "TH01",
            "risk_threshold_configured",
            (),
            "order_threshold",
            {"thresholds": {"submit_count": 5}},
        ),
        (
            "TH03",
            "risk_threshold_configured",
            (),
            "cancel_threshold",
            {"thresholds": {"submit_cancel_total": 10}},
        ),
        (
            "TH04",
            "risk_threshold_triggered",
            ("order_submit_request", "order_cancel_request"),
            "cancel_threshold",
            {"counter": "submit_cancel_total", "threshold": 10, "value": 10},
        ),
        (
            "TH05",
            "risk_threshold_configured",
            (),
            "repeat_threshold",
            {"thresholds": {"duplicate_order": 3}, "repeat_window_sec": 60},
        ),
        (
            "TH06",
            "risk_threshold_triggered",
            ("order_submit_request",),
            "repeat_threshold",
            {"counter": "duplicate_order", "threshold": 3, "value": 3},
        ),
        (
            "L03",
            "risk_monitor_event",
            (),
            "metric",
            {"metric": "order_rejection_rate"},
        ),
    ],
)
def test_legacy_monitor_receipt_claims_do_not_satisfy_th_or_l03(
    case_id, event_type, activity_types, untrusted_field, details, tmp_path
):
    _, certification, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    scenario = certification.get_certification_scenario(case_id)

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    rows = [
        {"event_type": activity_type, "order_ref": f"local-{index}"}
        for index, activity_type in enumerate(activity_types, start=1)
    ]
    rows.append(
        {
            "event_type": event_type,
            "source": "runtime_monitor_receipt",
            "event_id": f"claimed-{case_id}",
            "evidence_sha256": "a" * 64,
            "monitor_digest": "b" * 64,
            "timestamp": "2026-09-28T00:00:01Z",
            "trace_id": "claimed-trace",
            "details": details,
        }
    )
    (logs / "monitor.log").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )

    with result_mod.CaseTimer(case_id, scenario.name, "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": [event_type],
                **dict.fromkeys(scenario.evidence_fields, "caller-claimed"),
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    cert = result.details["certification_evidence"]
    assert result.status == "FAIL"
    assert scenario.required_events[0] in result.missing_required_events
    assert scenario.required_events[0] not in result.observed_events
    assert untrusted_field not in cert


def test_legacy_monitoring_summary_cannot_override_request_derived_counts():
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    result = result_mod.CaseTimer("M04", "正常统计报单笔数").blocked_result(
        "offline monitor receipt negative probe",
        details={"submitted_order_count": 99},
    )

    derived = evidence._derive_runtime_evidence(
        result,
        [
            {"event_type": "order_submit_request", "order_ref": "actual-request-1"},
            {
                "event_type": "monitoring_summary",
                "source": "runtime_monitor_receipt",
                "event_id": "claimed-summary",
                "evidence_sha256": "a" * 64,
                "monitor_digest": "b" * 64,
                "timestamp": "2026-09-28T00:00:01Z",
                "details": {
                    "submit_count": 99,
                    "submit_threshold": 5,
                    "thresholds": {"submit_count": 5},
                },
            },
        ],
        [],
    )

    assert derived == {"observed_events": [], "field_names": set(), "values": {}}


def test_local_session_stop_does_not_revalidate_as_provider_disconnect(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "system.log").write_text(
        json.dumps(
            {
                "event_type": "session_stopped",
                "event_time": "2026-06-18T12:00:00",
            }
        )
        + "\n"
        + json.dumps(
            {
                "event_type": "store_disconnected",
                "status": "disconnected",
                "timestamp": "2026-06-18T12:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("M02", "连接断开显示连接断开", "new_7x24") as timer:
        result = timer.pass_result(
            details={"system_events": ["session_stopped"], "gateway_key": "new_7x24"}
        )

    assert result.status == "FAIL"

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    assert "store_disconnected" in result.missing_required_events


def test_result_details_cannot_claim_provider_reconnect_without_log_evidence(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "env": "gateway",
            "balance": {"cash": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "system.log").write_text(
        json.dumps(
            {
                "event_type": "store_reconnect_success",
                "timestamp": "2026-09-28T00:00:00Z",
                "gateway_key": "gateway",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("M03", "断线后显示重连成功", "gateway") as timer:
        result = timer.pass_result(
            details={
                "events": ["store_reconnect_success"],
                "gateway_key": "gateway",
                "timestamp": "2026-09-28T00:00:00Z",
                "previous_session_id": "session-a",
                "new_session_id": "session-b",
            }
        )

    assert result.status == "FAIL"
    assert result.failure_reason == result_mod.PASS_UNAVAILABLE_REASON
    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    assert "store_reconnect_success" in result.missing_required_events
    assert set(result.missing_evidence_fields) == {"gateway_key", "timestamp"}


def test_no_open_order_expectation_requires_a_post_action_snapshot(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "order.log").write_text(
        json.dumps({"event_type": "order_submit_request", "order_ref": "bt-1"})
        + "\n"
        + json.dumps(
            {
                "event_type": "order_submit_accepted",
                "order_ref": "bt-1",
                "external_order_id": "provider-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "gateway") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    check = result.details["reconciliation"]["checks"]["post_action_open_orders"]
    assert check["passed"] is False


def test_account_change_without_trade_fails_allowed_if_trade_reconciliation(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 900.0, "value": 900.0},
            "positions": [{"instrument": "rb2610", "direction": "long", "volume": 1}],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "order.log").write_text(
        json.dumps(
            {"event_type": "order_submit_request", "order_ref": "bt-1"}
        )
        + "\n"
        + json.dumps(
            {
                "event_type": "order_submit_accepted",
                "order_ref": "bt-1",
                "external_order_id": "provider-1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "gateway") as timer:
        result = timer.pass_result(details={})

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    check = result.details["reconciliation"]["checks"]["account_position_change"]
    assert check["trade_events"] == 0
    assert check["passed"] is False


def test_local_validation_rejects_do_not_count_as_real_order_activity(tmp_path):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "error.log").write_text(
        json.dumps(
            {
                "event_type": "order_validation_rejected",
                "error_code": "invalid_contract",
                "error_msg": "Contract rb2610 is not valid for trading",
                "details": {"data_name": "rb2610"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (logs / "system.log").write_text(
        json.dumps(
            {
                "event_type": "open_orders_sync_completed",
                "status": "completed",
                "details": {"open_order_count": 0, "orders": []},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("V01", "合约代码错误检查并拒绝报单", "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": ["order_validation_rejected"],
                "instrument": "rb2610",
                "error_msg": "Contract rb2610 is not valid for trading",
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    assert "order_validation_rejected" in result.missing_required_events
    assert "order_validation_rejected" not in result.observed_events
    assert result.details["reconciliation"]["checks"]["order_activity"]["passed"] is True
    assert result.details["reconciliation"]["event_counts"]["order_events"] == 0


@pytest.mark.parametrize(
    ("case_id", "error_code", "error_msg"),
    [
        ("E01", "31", "CTP:资金不足，约缺少资金[2207099.98]"),
        ("E02", "50", "CTP:平今仓位不足"),
    ],
)
def test_source_less_remote_ctp_order_rejection_does_not_revalidate_error_cases(
    case_id, error_code, error_msg, tmp_path
):
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "order.log").write_text(
        json.dumps({"event_type": "order_submit_request", "order_ref": "1"})
        + "\n"
        + json.dumps({"event_type": "order_submit_accepted", "order_ref": "1"})
        + "\n",
        encoding="utf-8",
    )
    (logs / "error.log").write_text(
        json.dumps(
            {
                "event_type": "order_rejected",
                "provider": "ctp",
                "data_name": "rb2610",
                "order_ref": "1",
                "error_code": error_code,
                "error_msg": error_msg,
                "status": "Rejected",
                "details": {"order_type": "Sell"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer(case_id, "柜台错误展示", "new_7x24") as timer:
        result = timer.pass_result(details={})

    assert result.status == "FAIL"

    result = evidence.attach_reconciliation(result, tmp_path)
    cert = result.details["certification_evidence"]
    reconciliation = result.details["reconciliation"]

    assert result.status == "FAIL"
    assert "order_reject_remote" in result.missing_required_events
    assert "order_reject_remote" not in result.observed_events
    assert "ErrorID" not in cert
    assert "ErrorMsg" not in cert
    assert "StatusMsg" not in cert
    assert reconciliation["checks"]["order_activity"]["expected"] == "required"
    assert reconciliation["checks"]["order_activity"]["passed"] is True
    assert reconciliation["checks"]["trade_activity"]["passed"] is True
    assert reconciliation["checks"]["account_position_unchanged"]["passed"] is True


@pytest.mark.parametrize(
    ("case_id", "event_type", "activity_type"),
    [
        ("E01", "order_rejected", "order_submit_request"),
        ("E02", "order_rejected", "order_submit_request"),
        ("E03", "order_rejected", "order_submit_request"),
        ("EM01", "account_trading_disabled", "order_submit_request"),
        ("EM02", "strategy_trading_paused", "strategy_run"),
        ("EM03", "gateway_force_logout_requested", "gateway_stop"),
        ("O01", "risk_repeat_order_detected", "order_submit_request"),
        ("O02", "risk_repeat_order_detected", "order_submit_request"),
        ("O03", "risk_repeat_cancel_detected", "order_cancel_request"),
    ],
)
def test_legacy_high_risk_receipt_claims_are_not_trusted_from_jsonl(
    case_id, event_type, activity_type, tmp_path
):
    _, certification, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    scenario = certification.get_certification_scenario(case_id)

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    activity = {"event_type": activity_type, "order_ref": "local-order-1"}
    if activity_type == "order_cancel_request":
        activity["cancel_ref"] = "local-cancel-1"
    receipt_source = "ctp_provider_callback"
    callback_name = "OnRspOrderInsert"
    if event_type.startswith("risk_repeat_"):
        receipt_source = "runtime_monitor_receipt"
        callback_name = ""
    elif event_type in {
        "account_trading_disabled",
        "strategy_trading_paused",
        "gateway_force_logout_requested",
    }:
        receipt_source = "control_plane_receipt"
        if event_type == "gateway_force_logout_requested":
            callback_name = "OnFrontDisconnected"
    receipt_claim = {
        "event_type": event_type,
        "source": receipt_source,
        "event_id": f"claimed-{case_id}",
        "evidence_sha256": "a" * 64,
        "timestamp": "2026-09-28T00:00:01Z",
        "provider": "ctp",
        "callback_name": callback_name,
        "session_id": "claimed-session",
        "trading_day": "20260928",
        "sequence": 1,
        "order_ref": "local-order-1",
        "ErrorID": 31,
        "ErrorMsg": "CTP: claimed remote rejection",
        "StatusMsg": "claimed status",
        "verified_rejection_class": {
            "E01": "insufficient_funds",
            "E02": "insufficient_position",
            "E03": "market_state",
        }.get(case_id, "account_permission_denied"),
        "error_mapping_evidence_ref": "claimed-mapping",
        "market_state_evidence_ref": "claimed-market-state",
        "market_state_source_event_id": "claimed-market-event",
        "account_id_masked": "masked-account",
        "reason": "claimed reason",
        "authorization_ref": "claimed-authorization",
        "independent_account_permission_evidence_ref": "claimed-permission",
        "blocked_order_ref": "local-order-1",
        "permission_restored_ref": "claimed-restoration",
        "strategy_id": "local-strategy",
        "gateway_key": "local-gateway",
        "operator_termination_evidence_ref": "claimed-termination",
        "post_disconnect_write_guard_evidence_ref": "claimed-write-guard",
        "gateway_released": True,
        "actor_id_hash": "claimed-actor",
        "signature_sha256": "b" * 64,
        "monitor_digest": "c" * 64,
        "trace_id": "claimed-trace",
        "repeat_key": "claimed-repeat-key",
        "repeat_count": 2,
    }
    (logs / "events.log").write_text(
        json.dumps(activity)
        + "\n"
        + json.dumps(receipt_claim)
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer(case_id, scenario.name, "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": [event_type],
                **dict.fromkeys(scenario.evidence_fields, "caller-claimed"),
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    cert = result.details["certification_evidence"]
    assert result.status == "FAIL"
    assert scenario.required_events[0] in result.missing_required_events
    assert scenario.required_events[0] not in result.observed_events
    assert not set(scenario.evidence_fields).intersection(cert)


def test_untrusted_validation_log_does_not_pass_l04(tmp_path):
    _, certification, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    scenario = certification.get_certification_scenario("L04")
    assert scenario.required_events == ("order_validation_rejected",)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "error.log").write_text(
        json.dumps(
            {
                "event_type": "order_validation_rejected",
                "source": "local_validator_receipt",
                "validator_digest": "a" * 64,
                "reference_data_digest": "b" * 64,
                "dispatch_absent": True,
                "trace_id": "claimed-trace",
                "error_code": "invalid_price_tick",
                "error_msg": "invalid tick",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("L04", "错误提示信息记录", "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": ["order_validation_rejected"],
                "trace_id": "trace-1",
                "error_code": "invalid_price_tick",
                "error_msg": "invalid tick",
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "FAIL"
    assert result.missing_required_events == ["order_validation_rejected"]
    assert set(scenario.evidence_fields).issubset(result.missing_evidence_fields)
    assert result.details["certification_evidence"] == {}


def test_all_33_source_less_legacy_certification_scenarios_fail_closed(tmp_path):
    _, certification, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    scenarios = certification.all_certification_scenarios()
    assert len(scenarios) == 33

    required_event_types = sorted(
        {event for scenario in scenarios for event in scenario.required_events}
    )
    required_fields = sorted(
        {field for scenario in scenarios for field in scenario.evidence_fields}
    )
    source_by_event = {
        "store_auth_success": "ctp_provider_callback",
        "store_login_success": "ctp_provider_callback",
        "store_connected": "ctp_provider_callback",
        "store_disconnected": "ctp_provider_callback",
        "store_reconnect_success": "ctp_provider_callback",
        "order_submit_request": "managed_runtime_receipt",
        "order_cancel_request": "managed_runtime_receipt",
        "order_status_accepted": "ctp_provider_callback",
        "order_status_canceled": "ctp_provider_callback",
        "trade_execution": "ctp_provider_callback",
        "risk_repeat_order_detected": "runtime_monitor_receipt",
        "risk_repeat_cancel_detected": "runtime_monitor_receipt",
        "risk_threshold_configured": "runtime_monitor_receipt",
        "risk_threshold_triggered": "runtime_monitor_receipt",
        "risk_monitor_event": "runtime_monitor_receipt",
        "order_validation_rejected": "local_validator_receipt",
        "order_reject_remote": "ctp_provider_callback",
        "account_trading_disabled": "control_plane_receipt",
        "strategy_trading_paused": "control_plane_receipt",
        "gateway_force_logout_requested": "control_plane_receipt",
        "batch_cancel_requested": "managed_runtime_receipt",
        "store_ready": "ctp_provider_callback",
    }
    claimed_fields = dict.fromkeys(required_fields, "claimed-value")
    event_rows = []
    for sequence, event_type in enumerate(required_event_types, start=1):
        event_rows.append(
            {
                "event_type": event_type,
                "source": source_by_event[event_type],
                "event_id": f"claimed-{sequence}",
                "evidence_sha256": "a" * 64,
                "monitor_digest": "b" * 64,
                "signature_sha256": "c" * 64,
                "actor_id_hash": "claimed-actor",
                "callback_names": [
                    "OnRspOrderInsert",
                    "OnErrRtnOrderInsert",
                    "OnRtnOrder",
                    "OnRtnTrade",
                    "OnFrontConnected",
                    "OnFrontDisconnected",
                    "OnRspUserLogin",
                ],
                "callback_name": "OnRspOrderInsert",
                "provider": "ctp",
                "session_id": "claimed-session",
                "provider_session_id": "claimed-session",
                "trading_day": "20260928",
                "sequence": sequence,
                "source_sequence": sequence,
                "timestamp": "2026-09-28T00:00:01Z",
                "observed_at_utc": "2026-09-28T00:00:01Z",
                "order_ref": "claimed-order-ref",
                "external_order_id": "claimed-provider-order",
                "trade_id": "claimed-trade-id",
                "ErrorID": 31,
                "ErrorMsg": "claimed error",
                "StatusMsg": "claimed status",
                "verified_rejection_class": "insufficient_funds",
                "error_mapping_evidence_ref": "claimed-error-map",
                "authorization_ref": "claimed-authorization",
                "independent_account_permission_evidence_ref": "claimed-permission",
                "permission_restored_ref": "claimed-restoration",
                "operator_termination_evidence_ref": "claimed-termination",
                "post_disconnect_write_guard_evidence_ref": "claimed-write-guard",
                "gateway_released": True,
                "dispatch_absent": True,
                "validator_digest": "d" * 64,
                "reference_data_digest": "e" * 64,
                "trace_id": "claimed-trace",
                "metric": "claimed-metric",
                "repeat_key": "claimed-repeat-key",
                "repeat_count": 2,
                "details": claimed_fields,
                **claimed_fields,
            }
        )
    # These source-less rows produce the old accepted/canceled/trade aliases.
    event_rows.extend(
        [
            {"event_type": "order_submit_accepted", "status": "Accepted"},
            {"event_type": "order_status_probe", "status": "Accepted"},
            {"event_type": "order_cancel_probe", "status": "Canceled"},
            {"event_type": "order_partial_probe", "status": "Partial"},
            {"event_type": "", "trade_id": "claimed-trade", "status": "Completed"},
        ]
    )

    for scenario in scenarios:
        report_dir = tmp_path / scenario.case_id
        logs = report_dir / "logs"
        logs.mkdir(parents=True)
        (report_dir / "state_snapshots.json").write_text(
            json.dumps(
                [
                    {
                        "label": "before_action",
                        "balance": {"cash": 1000.0},
                        "positions": [],
                        "open_orders": [],
                    },
                    {
                        "label": "after_action_before_stop",
                        "balance": {"cash": 1000.0},
                        "positions": [],
                        "open_orders": [],
                    },
                ]
            ),
            encoding="utf-8",
        )
        (logs / "all-events.log").write_text(
            "\n".join(json.dumps(row) for row in event_rows) + "\n",
            encoding="utf-8",
        )

        with result_mod.CaseTimer(
            scenario.case_id, scenario.name, "new_7x24"
        ) as timer:
            result = timer.pass_result(
                details={
                    "events": list(scenario.required_events),
                    **dict.fromkeys(scenario.evidence_fields, "caller-claimed"),
                }
            )
        result = evidence.attach_reconciliation(result, report_dir)

        assert result.status == "FAIL", scenario.case_id
        assert result.missing_required_events == list(scenario.required_events)
        assert not set(scenario.required_events).intersection(result.observed_events)
        assert set(scenario.evidence_fields).issubset(result.missing_evidence_fields)
        assert result.details["certification_evidence"] == {}


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_pause_strategy_reconciliation_fails_if_trade_occurs_after_control(
    suite_name, tmp_path
):
    _, _, result_mod = load_suite(suite_name)
    evidence = importlib.import_module("common.evidence")

    snapshots = [
        {
            "label": "before_action",
            "balance": {"cash": 1000.0, "value": 1000.0},
            "positions": [],
            "open_orders": [],
        },
        {
            "label": "after_action_before_stop",
            "balance": {"cash": 990.0, "value": 1000.0},
            "positions": [{"instrument": "rb2610", "direction": "long", "volume": 1}],
            "open_orders": [],
        },
    ]
    (tmp_path / "state_snapshots.json").write_text(
        json.dumps(snapshots, ensure_ascii=False), encoding="utf-8"
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "monitor.log").write_text(
        json.dumps({"event_type": "strategy_trading_paused"}) + "\n"
        + json.dumps({"event_type": "trade_execution"}) + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("EM02", "暂停策略执行", "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": ["strategy_trading_paused", "trade_execution"],
                "strategy_id": "s1",
                "reason": "test",
            }
        )

    result = evidence.attach_reconciliation(result, tmp_path)
    reconciliation = result.details["reconciliation"]

    assert reconciliation["checks"]["trade_activity"]["passed"] is False
    assert reconciliation["checks"]["account_position_unchanged"]["passed"] is False


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_create_cerebro_keeps_store_lifecycle_in_runtime_context(suite_name):
    load_suite(suite_name)
    runtime = importlib.import_module("common.runtime")

    class FakeStore:
        is_connected = True

        def start(self, data=None, broker=None):
            return None

        def register(self, feed):
            return None

        def subscribe(self, dataname):
            return None

    store = FakeStore()

    cerebro = runtime.create_cerebro(store, symbol="rb2610")

    assert store in cerebro.stores
    assert store._cerebro_managed_lifecycle is False


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_summary_reports_canonical_coverage(suite_name, tmp_path):
    run_case, certification, result_mod = load_suite(suite_name)

    results = []
    for case_id in run_case.CASE_ORDER:
        scenario = certification.get_certification_scenario(case_id)
        with result_mod.CaseTimer(case_id, scenario.name, "new_7x24") as timer:
            results.append(timer.blocked_result("static coverage only").to_dict())

    run_case.print_summary(results, tmp_path)

    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    coverage = summary["certification"]

    assert coverage["total_scenarios"] == 33
    assert coverage["covered_scenarios"] == 33
    assert coverage["unmapped_cases"] == []
    assert coverage["missing_cases"] == []
    assert coverage["scenario_ids"][0] == "AUTH-01"
    assert coverage["scenario_ids"][-1] == "LOG-ERROR-01"


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_case_main_exception_result_keeps_canonical_audit(
    suite_name, tmp_path, monkeypatch
):
    load_suite(suite_name)
    runtime = importlib.import_module("common.runtime")

    class ExitCalled(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.code = code

    def raise_exit(code):
        raise ExitCalled(code)

    def boom(_report_dir):
        raise RuntimeError("boom")

    monkeypatch.setattr(sys, "argv", ["case.py", "--report-dir", str(tmp_path)])
    monkeypatch.setattr(runtime.os, "_exit", raise_exit)

    with pytest.raises(ExitCalled) as exc:
        runtime.case_main(
            boom,
            {
                "case_id": "C01",
                "case_name": "验证登录测试账号通过柜台认证并完成账号登录",
            },
        )

    assert exc.value.code == 1

    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()

    assert saved["status"] == "FAIL"
    assert saved["scenario_id"] == "AUTH-01"
    assert saved["trace_id"].startswith("ctp-cert-")
    assert len(audit_lines) == 1
    assert json.loads(audit_lines[0])["status"] == "FAIL"


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_emergency_cases_use_standard_broker_control_events(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    em02_source = (suite_dir / "cases" / "EM02_pause_strategy.py").read_text(
        encoding="utf-8"
    )
    em03_source = (suite_dir / "cases" / "EM03_force_logout.py").read_text(
        encoding="utf-8"
    )

    assert ".pause_strategy(" in em02_source
    assert ".force_logout(" in em03_source
    assert 'reason = "EM03_test"' in em03_source
    assert '"reason": reason' in em03_source


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_repeat_cancel_case_requires_repeat_cancel_evidence(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    source = (suite_dir / "cases" / "O03_repeat_cancel_order.py").read_text(
        encoding="utf-8"
    )

    assert "risk_repeat_cancel_detected" in source


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_repeat_threshold_case_requires_canonical_threshold_event(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    source = (suite_dir / "cases" / "TH06_repeat_threshold_alert.py").read_text(
        encoding="utf-8"
    )

    assert "risk_threshold_triggered" in source
    assert "duplicate_order_threshold_reached" in source


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_local_rejection_cases_use_common_cerebro_lifecycle(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    case_files = [
        "V01_invalid_instrument.py",
        "V02_invalid_price_tick.py",
        "V03_exceed_max_volume.py",
        "E01_insufficient_funds.py",
        "L04_error_info_log.py",
    ]

    for filename in case_files:
        source = (suite_dir / "cases" / filename).read_text(encoding="utf-8")

        assert "create_cerebro(" in source, filename
        assert "bt.Cerebro()" not in source, filename


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_market_state_error_case_does_not_fake_local_contract_rejection(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    source = (suite_dir / "cases" / "E03_market_state_error.py").read_text(
        encoding="utf-8"
    )

    assert "contract_metadata" not in source
    assert "tradable" not in source
    assert "blocked_result" in source
    assert "order_reject_remote" in source


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_error_cases_do_not_use_local_guards_for_remote_counter_errors(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name

    e01_source = (suite_dir / "cases" / "E01_insufficient_funds.py").read_text(
        encoding="utf-8"
    )
    e02_source = (suite_dir / "cases" / "E02_insufficient_position.py").read_text(
        encoding="utf-8"
    )

    assert "max_order_size" not in e01_source
    assert "disable_trading" not in e02_source
    for source in (e01_source, e02_source):
        assert "order_reject_remote" in source
        assert "ErrorID" in source
        assert "ErrorMsg" in source
        assert "StatusMsg" in source
        assert "_remote_counter_errors_from_log" in source


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_batch_cancel_cases_use_standard_batch_cancel_api(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name

    for filename in ("B01_batch_cancel_partial.py", "B02_batch_cancel_pending.py"):
        source = (suite_dir / "cases" / filename).read_text(encoding="utf-8")

        assert ".batch_cancel(" in source, filename


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_reconnect_case_reuses_same_store_instance(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    source = (suite_dir / "cases" / "M03_reconnect_success.py").read_text(
        encoding="utf-8"
    )

    assert "with started_store(" in source
    assert "store2" not in source
    assert "BtApiStore(" not in source


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_trade_log_case_waits_for_real_trade_before_passing(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    source = (suite_dir / "cases" / "L01_trade_info_log.py").read_text(
        encoding="utf-8"
    )

    assert "trade_execution" in source
    # A same-day close must exist; CZCE uses the generic ``close`` offset
    # (via close_offset_for) while SHFE/DCE use ``close_today``.
    assert "close_today" in source or "close_offset_for" in source
    assert "self.cancel(self.order)" not in source
    assert "order is self.open_order" not in source
    assert "order is self.close_order" not in source
    assert "self.open_order_ref == order.ref" in source
    assert "self.close_order_ref == order.ref" in source


def test_b01_partial_count_ignores_local_partial_labels():
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    local_partial_events = [
        {
            "event_type": "order_status_partial",
            "provider": "ctp",
            "status": "partial",
            "order_ref": "local-1",
            "filled": 1,
            "remaining": 1,
        },
        {
            "event_type": "order_status_partial",
            "provider": "ctp",
            "status": "partial",
            "order_ref": "local-2",
            "filled": 1,
            "remaining": 1,
        },
    ]
    result = result_mod.CaseTimer("B01", "batch partial cancel").blocked_result(
        "offline negative probe",
        details={
            "events": ["order_status_partial", "order_status_partial"],
            "partial_count": 2,
        },
    )

    derived = evidence._derive_runtime_evidence(result, local_partial_events, [])

    assert "partial_count" not in derived["values"]
    assert "partial_count" not in derived["field_names"]


def test_b01_partial_count_does_not_trust_callback_shaped_jsonl():
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")

    def callback(order_ref, sequence):
        return {
            "event_type": "order_status_partial",
            "provider": "ctp",
            "source": "ctp_provider_callback",
            "callback_name": "OnRtnOrder",
            "event_id": f"callback-{sequence}",
            "session_id": "offline-contract-session",
            "trading_day": "20260928",
            "sequence": sequence,
            "observed_at_utc": f"2026-09-28T00:00:{sequence:02d}Z",
            "evidence_sha256": "a" * 64,
            "status": "partial",
            "order_ref": order_ref,
            "traded_quantity": 1,
            "remaining_quantity": 1,
        }

    result = result_mod.CaseTimer("B01", "batch partial cancel").blocked_result(
        "offline contract probe", details={"partial_count": 99}
    )
    derived = evidence._derive_runtime_evidence(
        result,
        [callback("provider-1", 1), callback("provider-1", 2), callback("provider-2", 3)],
        [],
    )

    assert derived == {"observed_events": [], "field_names": set(), "values": {}}


def test_b01_partial_count_does_not_trust_raw_callback_shaped_jsonl():
    _, _, result_mod = load_suite("simnow_penetration")
    evidence = importlib.import_module("common.evidence")
    result = result_mod.CaseTimer("B01", "batch partial cancel").blocked_result(
        "offline raw callback contract probe"
    )
    event = {
        "source": "ctp_provider_callback",
        "callback_name": "OnRtnOrder",
        "event_id": "raw-callback-1",
        "session_id": "offline-contract-session",
        "trading_day": "20260928",
        "sequence": 1,
        "observed_at_utc": "2026-09-28T00:00:01Z",
        "evidence_sha256": "b" * 64,
        "order_ref": "provider-raw-1",
        "details": {"OrderStatus": "1", "VolumeTraded": 1, "VolumeTotal": 1},
    }

    derived = evidence._derive_runtime_evidence(result, [event], [])

    assert derived == {"observed_events": [], "field_names": set(), "values": {}}
