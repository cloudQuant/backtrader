"""Offline tests for the Iter23/24/25 SimNow operator entry.

Every test uses injected fakes; no test ever loads a real credential file,
creates a native client, or connects to SimNow.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from examples.ctp_options_simnow_operator import (
    OperatorBlocked,
    OperatorConfiguration,
    build_live_store,
    collect_three_leg_evidence,
    load_operator_env,
    main,
    resolve_credentials,
    resolve_fronts,
    run_engineering_smoke,
    strategy_identity_sha256,
)

ACCOUNT = "acct-operator-sha256"
TRADING_DAY = "20260911"
GENERATION = 11
FUTURE = "SA701"
CALL = "SA701C1080"
PUT = "SA701P1080"
SYMBOLS = (f"CZCE.{FUTURE}", f"CZCE.{CALL}", f"CZCE.{PUT}")


def _env(**overrides):
    env = {
        "CTP_USER_ID": "simnow-user",
        "CTP_PASSWORD": "simnow-password",
        "CTP_BROKER_ID": "9999",
        "CTP_APP_ID": "simnow_app",
        "CTP_AUTH_CODE": "simnow-auth",
        "CTP_TD_FRONT": "tcp://front:10130",
        "CTP_MD_FRONT": "tcp://front:10131",
        "CTP_ENV_PROFILE": "set2_7x24",
    }
    env.update(overrides)
    return env


def _identity(**changes):
    value = {
        "account_fingerprint": ACCOUNT,
        "trading_day": TRADING_DAY,
        "connection_generation": GENERATION,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "nonzero_positions": [],
        "active_orders": [],
        "request_count_delta": {"order_insert": 0, "order_action": 0},
    }
    value.update(changes)
    return value


def _records():
    def row(instrument_id, product_id, product_class, **extra):
        row_value = {
            "InstrumentID": instrument_id,
            "ExchangeID": "CZCE",
            "ProductID": product_id,
            "ProductClass": product_class,
            "IsTrading": 1,
            "TradingDay": TRADING_DAY,
            "ExpireDate": "20270115",
            "PriceTick": 1.0 if product_class == "1" else 0.5,
            "VolumeMultiple": 20,
        }
        row_value.update(extra)
        return row_value

    return [
        row(FUTURE, "SA", "1"),
        row(CALL, "SAC", "2", OptionsType="1", UnderlyingInstrID=FUTURE, StrikePrice=1080),
        row(PUT, "SAP", "2", OptionsType="2", UnderlyingInstrID=FUTURE, StrikePrice=1080),
    ]


def _legs():
    return [
        {
            "exchange_id": "CZCE",
            "instrument_id": instrument,
            "is_primary": index == 0,
        }
        for index, instrument in enumerate((FUTURE, CALL, PUT))
    ]


def _bundle_preflight():
    return _identity(
        schema_version="backtrader.ctp.bundle-preflight.v2",
        legs=_legs(),
        snapshot_sha256="b" * 64,
    )


def _execution_reference():
    received_monotonic = time.monotonic() - 0.1
    received_at = "2026-09-11T13:00:00+00:00"
    quote_legs = [
        {
            "exchange_id": "CZCE",
            "instrument_id": instrument,
            "bid_price": 1495.0,
            "ask_price": 1500.0,
            "bid_volume": 3,
            "ask_volume": 3,
            "entry_buy_price": 1500.0,
            "exit_sell_price": 1495.0,
            "requested_at_utc": received_at,
            "received_at_utc": received_at,
            "requested_monotonic": received_monotonic - 0.02,
            "received_monotonic": received_monotonic,
        }
        for instrument in (FUTURE, CALL, PUT)
    ]
    return {
        "schema_version": "backtrader.ctp.bundle-execution-reference.v1",
        "read_only": True,
        "write_request_free": True,
        "evidence_complete": True,
        "evidence_errors": [],
        "account_fingerprint": ACCOUNT,
        "trading_day": TRADING_DAY,
        "connection_generation": GENERATION,
        "bundle_preflight": _bundle_preflight(),
        "legs": quote_legs,
        "request_count_delta": {"order_insert": 0, "order_action": 0},
        "snapshot_sha256": "e" * 64,
    }


def _reconciliation():
    return _identity(
        schema_version="backtrader.ctp.reconciliation.v1",
        unmatched_trade_count=0,
        reconciliation_fingerprint="f" * 64,
        query_results={
            "account": {"request_id": 41},
            "positions": {"request_id": 42},
            "orders": {"request_id": 43},
            "trades": {"request_id": 44},
        },
        execution_summary={"unmatched_trade_count": 0},
    )


class FakeStore:
    """Read-only public double; asserts no write method is ever invoked."""

    def __init__(self, *, settlement_confirmed=True):
        self.calls = []
        self.write_attempts = []
        self.settlement_confirmed = settlement_confirmed

    # -- settlement ------------------------------------------------------
    def verify_ctp_settlement(self, *, timeout=30.0):
        self.calls.append(("verify_ctp_settlement", timeout))
        return {
            "schema_version": "backtrader.ctp.settlement-verification.v1",
            "evidence_complete": bool(self.settlement_confirmed),
            "read_only_safe": True,
            "error_code": None
            if self.settlement_confirmed
            else "settlement_verification_evidence_incomplete",
        }

    def prepare_ctp_settlement(self, *, timeout=30.0):
        self.calls.append(("prepare_ctp_settlement", timeout))
        self.settlement_confirmed = True
        return {
            "schema_version": "backtrader.ctp.settlement-preparation.v1",
            "evidence_complete": True,
            "error_code": None,
        }

    # -- preflight / bundle evidence --------------------------------------
    def get_ctp_preflight_snapshot(
        self,
        instrument_id=None,
        *,
        exchange_id="",
        product_id="",
        timeout=15.0,
        read_only=True,
    ):
        self.calls.append(
            (
                "preflight",
                instrument_id,
                exchange_id.upper(),
                product_id.upper(),
            )
        )
        snapshot = _identity(
            schema_version="backtrader.ctp.preflight.v1",
            exchange_id=exchange_id.upper(),
            instrument_id=str(instrument_id or ""),
            product_id=product_id.upper(),
            instruments=_records(),
        )
        snapshot["instruments"] = list(snapshot["instruments"])
        if instrument_id:
            snapshot["instrument_id"] = str(instrument_id).split(".", 1)[-1]
        return snapshot

    def get_ctp_bundle_preflight_snapshot(
        self, legs, *, primary_leg=None, primary_instrument_id=None,
        timeout=15.0, read_only=True,
    ):
        self.calls.append(("bundle_preflight", tuple(map(tuple, (tuple(leg.items()) for leg in legs)))))
        assert read_only is True
        return _bundle_preflight()

    def get_ctp_bundle_execution_reference_snapshot(
        self, legs, *, primary_leg=None, primary_instrument_id=None, timeout=15.0
    ):
        self.calls.append(("execution_reference", len(legs)))
        return _execution_reference()

    def get_ctp_reconciliation_snapshot(self, *, timeout=5.0):
        self.calls.append(("reconciliation", timeout))
        return _reconciliation()

    # -- chain assembly ----------------------------------------------------
    def getdata(self, **kwargs):
        return SimpleNamespace(symbol=kwargs.get("dataname"), store=self)

    # -- forbidden writes ----------------------------------------------------
    def submit_order(self, *args, **kwargs):  # pragma: no cover - guard
        self.write_attempts.append(("submit_order", args, kwargs))
        raise AssertionError("operator smoke must never submit an order")

    def cancel_order(self, *args, **kwargs):  # pragma: no cover - guard
        self.write_attempts.append(("cancel_order", args, kwargs))
        raise AssertionError("operator smoke must never cancel an order")


class FakeBroker:
    def __init__(self, **kwargs):
        self.init_kwargs = kwargs
        self.reconciliation_rounds = 0
        self._state = {
            "complete": False,
            "consecutive_complete_rounds": 0,
            "account_fingerprint": ACCOUNT,
            "connection_generation": GENERATION,
            "unknown_intent_count": 0,
            "unmatched_trade_count": 0,
            "reconciliation_fingerprint": "f" * 64,
        }

    def buy(self, **kwargs):  # pragma: no cover - guard
        raise AssertionError("operator smoke must never buy")

    def sell(self, **kwargs):  # pragma: no cover - guard
        raise AssertionError("operator smoke must never sell")

    def cancel(self, order):  # pragma: no cover - guard
        raise AssertionError("operator smoke must never cancel")

    def record_ctp_reconciliation(self, snapshot):
        self.reconciliation_rounds += 1
        self._state["consecutive_complete_rounds"] += 1
        self._state["complete"] = self._state["consecutive_complete_rounds"] >= 2
        return dict(self._state)

    def get_ctp_reconciliation_state(self):
        return dict(self._state)


def _config(**overrides):
    values = {
        "environment": "second_7x24",
        "product_id": "SA",
        "exchange_id": "CZCE",
    }
    values.update(overrides)
    return OperatorConfiguration(**values)


# ---------------------------------------------------------------------------
# configuration / credentials / fronts
# ---------------------------------------------------------------------------


def test_configuration_rejects_unknown_environment_and_partial_bundle_ids():
    with pytest.raises(OperatorBlocked, match="ENVIRONMENT_MUST_BE_ONE_OF"):
        OperatorConfiguration(environment="production", product_id="SA", exchange_id="CZCE")
    with pytest.raises(OperatorBlocked, match="EXACT_BUNDLE_IDS_MUST_BE_COMPLETE"):
        _config(future_instrument_id=FUTURE)
    with pytest.raises(OperatorBlocked, match="PURPOSE_NOT_SUPPORTED"):
        _config(purpose="mechanical")


def test_load_operator_env_parses_without_shell_evaluation(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "CTP_USER_ID=user\n"
        'CTP_PASSWORD="pass with spaces"\n'
        "EMPTY=\n"
        "CTP_BROKER_ID=9999\n",
        encoding="utf-8",
    )
    values = load_operator_env(env_file)
    assert values == {
        "CTP_USER_ID": "user",
        "CTP_PASSWORD": "pass with spaces",
        "CTP_BROKER_ID": "9999",
    }


def test_load_operator_env_requires_existing_file(tmp_path):
    with pytest.raises(OperatorBlocked, match="ENV_FILE_MISSING"):
        load_operator_env(tmp_path / "missing.env")


def test_resolve_credentials_requires_secret_keys():
    complete = resolve_credentials(_env())
    assert complete["broker_id"] == "9999"
    assert complete["user_id"] == "simnow-user"
    missing = _env(CTP_PASSWORD="")
    with pytest.raises(OperatorBlocked, match="CREDENTIALS_MISSING:CTP_PASSWORD"):
        resolve_credentials(missing)


def test_resolve_fronts_uses_explicit_overrides_and_validates_pairs():
    fronts = resolve_fronts(_env(), "second_7x24")
    assert fronts == {
        "profile": "second_7x24",
        "sdk_profile": "set2_7x24",
        "td_front": "tcp://front:10130",
        "md_front": "tcp://front:10131",
    }
    with pytest.raises(OperatorBlocked, match="MUST_BE_SET_TOGETHER"):
        resolve_fronts(_env(CTP_MD_FRONT=""), "second_7x24")
    with pytest.raises(OperatorBlocked, match="CTP_ENV_PROFILE_REQUIRED"):
        resolve_fronts(_env(CTP_ENV_PROFILE=""), "second_7x24")


def test_resolve_fronts_probes_sdk_when_no_overrides():
    def selector(**kwargs):
        assert kwargs == {"env": "set1"}
        return SimpleNamespace(
            profile="Set1_Group1", td_front="tcp://a:10201", md_front="tcp://a:10211"
        )

    fronts = resolve_fronts(
        _env(CTP_TD_FRONT="", CTP_MD_FRONT=""), "first", selector=selector
    )
    assert fronts["sdk_profile"] == "set1_group1"
    assert fronts["td_front"] == "tcp://a:10201"


def test_build_live_store_builds_read_only_managed_options(tmp_path):
    captured = {}

    class StoreStub:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    config = _config()
    store = build_live_store(
        resolve_credentials(_env()),
        resolve_fronts(_env(), "second_7x24"),
        config,
        state_directory=tmp_path,
        store_cls=StoreStub,
    )
    assert isinstance(store, StoreStub)
    assert captured["provider"] == "btapi"
    sdk_config = captured["config"]
    exchange_kwargs = sdk_config["exchange_kwargs"]["CTP___FUTURE"]
    assert exchange_kwargs["auto_settlement_confirm"] is False
    assert exchange_keys_hidden(exchange_kwargs)
    execution_config = sdk_config["execution_config"]
    assert execution_config["market_data_only"] is True
    assert execution_config["required_environments"] == {"CTP___FUTURE": "demo"}
    assert execution_config["strategy_identity_sha256"] == strategy_identity_sha256(config)
    # No secret ever reaches the non-exchange store options.
    assert "password" not in json.dumps(captured.get("api_kwargs", {}))


def exchange_keys_hidden(exchange_kwargs):
    """Credentials live only inside the SDK-owned exchange kwargs."""
    return exchange_kwargs["user_id"] == "simnow-user"


# ---------------------------------------------------------------------------
# evidence collection
# ---------------------------------------------------------------------------


def test_collect_three_leg_evidence_queries_in_contract_order():
    store = FakeStore()
    evidence = collect_three_leg_evidence(store, _config())

    preflight_calls = [call for call in store.calls if call[0] == "preflight"]
    # 1) exchange-wide scan, 2) product Stage A, 3) exact-future Stage B.
    assert [
        (call[2], call[3], call[1] or "") for call in preflight_calls
    ] == [
        ("CZCE", "", ""),
        ("CZCE", "SA", ""),
        ("CZCE", "", "CZCE.SA701"),
    ]
    assert evidence["trading_day"] == TRADING_DAY
    assert evidence["bundle"].future.instrument_id == FUTURE
    assert evidence["bundle"].call.instrument_id == CALL
    assert evidence["bundle"].put.instrument_id == PUT
    assert len(evidence["reconciliation_rounds"]) == 2
    assert not store.write_attempts


def test_collect_three_leg_evidence_honors_exact_bundle_ids():
    store = FakeStore()
    evidence = collect_three_leg_evidence(
        store,
        _config(
            future_instrument_id=FUTURE,
            call_instrument_id=CALL,
            put_instrument_id=PUT,
        ),
    )
    assert evidence["bundle"].strike == "1080"


def test_collect_three_leg_evidence_fails_closed_on_incomplete_scan():
    store = FakeStore()

    def incomplete_scan(*args, **kwargs):
        return _identity(schema_version="backtrader.ctp.preflight.v1", instruments=[])

    store.get_ctp_preflight_snapshot = incomplete_scan
    with pytest.raises(OperatorBlocked, match="INSTRUMENT_SCAN_EMPTY"):
        collect_three_leg_evidence(store, _config())


def test_collect_three_leg_evidence_rejects_incomplete_stage_a():
    store = FakeStore()
    original = store.get_ctp_preflight_snapshot

    def stage_a_incomplete(instrument_id=None, **kwargs):
        snapshot = original(instrument_id, **kwargs)
        if kwargs.get("product_id"):
            snapshot["evidence_complete"] = False
        return snapshot

    store.get_ctp_preflight_snapshot = stage_a_incomplete
    with pytest.raises(OperatorBlocked, match="STAGE_A_EVIDENCE_INCOMPLETE"):
        collect_three_leg_evidence(store, _config())


# ---------------------------------------------------------------------------
# engineering smoke
# ---------------------------------------------------------------------------


def test_engineering_smoke_passes_end_to_end_with_injected_fakes():
    store = FakeStore()
    report = run_engineering_smoke(
        _config(), _env(), state_directory=Path("."), store=store, broker_cls=FakeBroker
    )

    assert report["status"] == "ENGINEERING_SMOKE_PASS"
    assert report["order_write_allowed"] is False
    assert report["settlement_verified"] is True
    assert report["external_request_counts"] == {"order_write": 0}
    assert report["preflight"]["status"] == "PREFLIGHT_PASS"
    assert report["preflight"]["bundle"]["future"]["instrument_id"] == FUTURE
    assert report["native_execution_status"] == "NOT_CLAIMED_NO_NATIVE_CONFIRMATION"
    assert not store.write_attempts
    # Secrets never leak into the report.
    assert "simnow-password" not in json.dumps(report)
    assert "simnow-auth" not in json.dumps(report)


def test_engineering_smoke_reports_unconfirmed_settlement_without_writes():
    store = FakeStore(settlement_confirmed=False)
    report = run_engineering_smoke(
        _config(), _env(), state_directory=Path("."), store=store, broker_cls=FakeBroker
    )
    assert report["status"] == "ENGINEERING_SMOKE_PASS"
    assert report["settlement_verified"] is False
    assert ("prepare_ctp_settlement", 30.0) not in store.calls


def test_engineering_smoke_confirms_settlement_once_when_requested():
    store = FakeStore(settlement_confirmed=False)
    report = run_engineering_smoke(
        _config(confirm_settlement=True),
        _env(),
        state_directory=Path("."),
        store=store,
        broker_cls=FakeBroker,
    )
    assert report["settlement_verified"] is True
    assert ("prepare_ctp_settlement", 30.0) in store.calls


def test_engineering_smoke_requires_read_only_settlement_evidence():
    store = FakeStore()
    store.verify_ctp_settlement = lambda **kwargs: {
        "evidence_complete": True,
        "read_only_safe": False,
    }
    with pytest.raises(OperatorBlocked, match="SETTLEMENT_VERIFY_NOT_READ_ONLY"):
        run_engineering_smoke(
            _config(), _env(), state_directory=Path("."), store=store, broker_cls=FakeBroker
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_main_reports_blocked_without_env_file(tmp_path, capsys):
    exit_code = main(["--env", str(tmp_path / "missing.env")])
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert report["status"] == "BLOCKED"
    assert report["reason"].startswith("ENV_FILE_MISSING")


def test_main_emits_json_report(tmp_path, capsys, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{key}={value}" for key, value in _env().items()) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.json"

    def fake_smoke(config, env, *, state_directory, **kwargs):
        assert config.environment == "second_7x24"
        assert env["CTP_USER_ID"] == "simnow-user"
        return {"status": "ENGINEERING_SMOKE_PASS", "purpose": config.purpose}

    monkeypatch.setattr(
        "examples.ctp_options_simnow_operator.run_engineering_smoke", fake_smoke
    )
    exit_code = main(
        [
            "--env",
            str(env_file),
            "--environment",
            "second_7x24",
            "--output",
            str(output),
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert report["status"] == "ENGINEERING_SMOKE_PASS"
    assert json.loads(output.read_text(encoding="utf-8")) == report
