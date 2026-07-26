import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LIVE_CERTIFICATION_ROOT = REPO_ROOT / "examples" / "007_ctp" / "live_certification"
SUITE_NAMES = ("simnow_penetration", "hongyuan_penetration")


def load_suite(suite_name):
    suite_dir = LIVE_CERTIFICATION_ROOT / suite_name
    for module_name in list(sys.modules):
        if module_name == "run_case" or module_name == "common" or module_name.startswith("common."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(suite_dir))
    try:
        run_case = importlib.import_module("run_case")
        certification = importlib.import_module("common.certification")
        result_mod = importlib.import_module("common.result")
    finally:
        sys.path.remove(str(suite_dir))
    return run_case, certification, result_mod


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
    assert payload["required_events_present"] is True
    assert payload["missing_required_events"] == []

    result_mod.save_result(result, tmp_path)

    saved = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    audit_lines = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()

    assert str(tmp_path / "audit.jsonl") in saved["evidence"]
    assert len(audit_lines) == 1
    assert json.loads(audit_lines[0])["scenario_id"] == "AUTH-01"


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_case_result_surfaces_missing_required_events(suite_name):
    _, _, result_mod = load_suite(suite_name)

    with result_mod.CaseTimer("T01", "正常下达开仓指令", "new_7x24") as timer:
        result = timer.pass_result(
            details={"events": ["order_submit_request"]},
        )

    payload = result.to_dict()

    assert payload["scenario_id"] == "TRADE-OPEN-01"
    assert payload["status"] == "FAIL"
    assert payload["required_events_present"] is False
    assert payload["missing_required_events"] == ["order_status_accepted"]
    assert payload["audit_events"][0]["missing_required_events"] == [
        "order_status_accepted"
    ]
    assert "Missing required certification evidence" in payload["failure_reason"]


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


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_reconciliation_revalidates_required_evidence_from_log_files(
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
    assert result.missing_required_events == ["order_status_accepted"]

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "PASS"
    assert result.missing_required_events == []
    assert result.missing_evidence_fields == []
    assert "order_status_accepted" in result.observed_events
    assert result.details["certification_evidence"]["external_order_id"] == "sys-1"
    assert result.details["reconciliation"]["strict_reconciliation_pass"] is True


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_reconciliation_derives_threshold_fields_from_runtime_logs(
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
                "details": {"counter": "submit_count", "value": 2, "threshold": 2},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("TH02", "报单笔数达到阈值预警", "new_7x24") as timer:
        result = timer.pass_result(details={})

    assert result.status == "FAIL"

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "PASS"
    assert result.missing_required_events == []
    assert result.missing_evidence_fields == []
    assert result.details["certification_evidence"]["order_threshold"] == 2
    assert result.details["certification_evidence"]["submitted_order_count"] == 2


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_disconnect_session_stop_revalidates_as_store_disconnected(
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
        + "\n",
        encoding="utf-8",
    )

    with result_mod.CaseTimer("M02", "连接断开显示连接断开", "new_7x24") as timer:
        result = timer.pass_result(
            details={"system_events": ["session_stopped"], "gateway_key": "new_7x24"}
        )

    assert result.status == "FAIL"

    result = evidence.attach_reconciliation(result, tmp_path)

    assert result.status == "PASS"
    assert "store_disconnected" in result.observed_events


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_local_validation_rejects_do_not_count_as_real_order_activity(
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

    assert result.status == "PASS"
    assert result.details["reconciliation"]["checks"]["order_activity"]["passed"] is True
    assert result.details["reconciliation"]["event_counts"]["order_events"] == 0


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
@pytest.mark.parametrize(
    ("case_id", "error_code", "error_msg"),
    [
        ("E01", "31", "CTP:资金不足，约缺少资金[2207099.98]"),
        ("E02", "50", "CTP:平今仓位不足"),
    ],
)
def test_remote_ctp_order_rejection_revalidates_error_cases(
    suite_name, case_id, error_code, error_msg, tmp_path
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

    assert result.status == "PASS"
    assert "order_reject_remote" in result.observed_events
    assert cert["ErrorID"] == error_code
    assert cert["ErrorMsg"] == error_msg
    assert cert["StatusMsg"] == error_msg
    assert reconciliation["checks"]["order_activity"]["expected"] == "required"
    assert reconciliation["checks"]["order_activity"]["passed"] is True
    assert reconciliation["checks"]["trade_activity"]["passed"] is True
    assert reconciliation["checks"]["account_position_unchanged"]["passed"] is True


@pytest.mark.parametrize("suite_name", SUITE_NAMES)
def test_error_log_case_accepts_validation_error_log_event(suite_name):
    _, certification, result_mod = load_suite(suite_name)

    scenario = certification.get_certification_scenario("L04")
    assert scenario.required_events == ("order_validation_rejected",)

    with result_mod.CaseTimer("L04", "错误提示信息记录", "new_7x24") as timer:
        result = timer.pass_result(
            details={
                "events": ["order_validation_rejected"],
                "trace_id": "trace-1",
                "error_code": "invalid_price_tick",
                "error_msg": "invalid tick",
            }
        )

    assert result.status == "PASS"


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
    assert "close_today" in source
    assert "self.cancel(self.order)" not in source
    assert "order is self.open_order" not in source
    assert "order is self.close_order" not in source
    assert "self.open_order_ref == order.ref" in source
    assert "self.close_order_ref == order.ref" in source
