"""Iteration 22 typed CTP query-completion oracles."""

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import sys
import threading
import time

import pytest

from backtrader.stores.btapistore import BtApiStoreError, _create_ctp_wrapper_class
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


class CompleteQueryClient(FakeBtApiClient):
    def __init__(self, *, auto_settlement_confirm=False):
        super().__init__()
        self.auto_settlement_confirm = auto_settlement_confirm
        # Unit fixtures opt out of the production one-query-per-second pace.
        self.ctp_query_min_interval_seconds = 0.0
        self.request_id = 0
        self.request_counts = {
            "settlement_confirm": 0,
            "order_insert": 0,
            "order_action": 0,
        }
        self.settlement_state = "not_requested"
        self.incomplete = set()
        self.generation_override = {}
        self.request_id_override = {}
        self.request_type_override = {}
        self.records_override = {}
        self.session_generation = 3
        self.session_fingerprint = "acct-sha256"
        self.trading_day = "20260909"
        self.session_generation_sequence = []
        self.session_fingerprint_sequence = []
        self.session_trading_day_sequence = []
        self.rows = {
            "account": [{"Balance": 100000.0, "Available": 90000.0}],
            "positions": [],
            "orders": [],
            "trades": [],
            "instruments": [
                {
                    "InstrumentID": "SA609",
                    "ExchangeID": "CZCE",
                    "ProductID": "SA",
                    "IsTrading": 1,
                    "ExpireDate": "20260915",
                    "OpenInterest": 12345.0,
                    "Volume": 6789,
                    "PriceTick": 1.0,
                    "VolumeMultiple": 20,
                    "MinLimitOrderVolume": 1,
                    "LowerLimitPrice": 1200.0,
                    "UpperLimitPrice": 1800.0,
                    "TradingDay": "20260909",
                }
            ],
            "margin_rate": [{"InstrumentID": "SA609", "LongMarginRatioByMoney": 0.1}],
            "commission_rate": [{"InstrumentID": "SA609", "OpenRatioByMoney": 0.0001}],
            "settlement_confirmation": [{"ConfirmDate": "20260909"}],
        }

    def get_session_state(self):
        generation = (
            self.session_generation_sequence.pop(0)
            if self.session_generation_sequence
            else self.session_generation
        )
        account_fingerprint = (
            self.session_fingerprint_sequence.pop(0)
            if self.session_fingerprint_sequence
            else self.session_fingerprint
        )
        trading_day = (
            self.session_trading_day_sequence.pop(0)
            if self.session_trading_day_sequence
            else self.trading_day
        )
        return {
            "connected": True,
            "ready": True,
            "read_only_ready": True,
            "trading_ready": self.settlement_state == "confirmed",
            "auth_state": "authenticated",
            "login_state": "logged_in",
            "settlement_state": self.settlement_state,
            "auto_settlement_confirm": self.auto_settlement_confirm,
            "connection_generation": generation,
            "account_fingerprint": account_fingerprint,
            "trading_day": trading_day,
            "request_counts": dict(self.request_counts),
        }

    def _result(self, name):
        self.request_id += 1
        self.request_counts[name] = self.request_counts.get(name, 0) + 1
        complete = name not in self.incomplete
        return {
            "request_type": self.request_type_override.get(name, name),
            "request_id": self.request_id_override.get(name, self.request_id),
            "connection_generation": self.generation_override.get(name, 3),
            "account_fingerprint": "acct-sha256",
            "started_at_utc": dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc).isoformat(),
            "completed_at_utc": (
                dt.datetime(2026, 9, 9, 0, 0, 1, tzinfo=dt.timezone.utc).isoformat()
                if complete
                else None
            ),
            "is_last_seen": complete,
            "error_code": None,
            "error_message": "" if complete else "timeout",
            "timed_out": not complete,
            "complete": complete,
            "records": (
                self.records_override[name]
                if name in self.records_override
                else list(self.rows[name]) if complete else []
            ),
            "late_callback_count": 0,
            "unsupported": False,
        }

    def query_account_result(self, timeout=5):
        return self._result("account")

    def query_positions_result(self, timeout=5):
        return self._result("positions")

    def query_orders_result(self, timeout=5, **_kwargs):
        return self._result("orders")

    def query_trades_result(self, timeout=5, **_kwargs):
        return self._result("trades")

    def query_instruments_result(self, timeout=5, **_kwargs):
        return self._result("instruments")

    def query_instrument_margin_rate_result(self, instrument_id, timeout=5, **_kwargs):
        return self._result("margin_rate")

    def query_instrument_commission_rate_result(self, instrument_id, timeout=5, **_kwargs):
        return self._result("commission_rate")

    def confirm_settlement(self, timeout=5):
        self.request_counts["settlement_confirm"] = (
            self.request_counts.get("settlement_confirm", 0) + 1
        )
        self.settlement_state = "confirmed"
        return True

    def verify_settlement_confirmation(self, timeout=5):
        self.settlement_state = "confirmed"
        return self._result("settlement_confirmation")

    def get_execution_summary(self):
        return {"unknown_ids": [], "active_orders": 0, "unmatched_trade_count": 0}


class ManagedBtApiClient(CompleteQueryClient):
    """Only the managed public CTP facade is available to the Store."""

    def __init__(self):
        super().__init__()
        self.exchange_kwargs = {"CTP___FUTURE": {"auto_settlement_confirm": False}}
        self.public_queries = []
        self.armed_proofs = []
        self.session_fingerprint = "0123456789abcdef"
        self.execution_config = None
        self.armed = False
        self.arm_proof_sha256 = ""
        self.disarm_reasons = []
        self.authorization_preparations = []
        self.recovery_report = None
        self.recovery_prepares = []
        self.recovery_arms = []
        self.recovery_completions = []

    def configure_execution(self, config):
        self.execution_config = dict(config)

    def get_session_state(self):
        state = super().get_session_state()
        state["environment_profile"] = "simnow_demo"
        return state

    def _result(self, name):
        result = super()._result(name)
        result["account_fingerprint"] = self.session_fingerprint
        return result

    def get_request_api(self, _exchange_name):
        raise AssertionError("managed Store must not escape through get_request_api")

    def get_all_balances(self, normalized=True):
        assert normalized is True
        return {"CTP___FUTURE": {"available": 90000.0, "equity": 100000.0}}

    def get_portfolio_balance(self, venue_balances=None):
        assert "CTP___FUTURE" in (venue_balances or {})
        return {"cash": 90000.0, "value": 100000.0}

    def close(self):
        self.connected = False

    def get_ctp_session_state(self, exchange_name="CTP___FUTURE"):
        assert exchange_name == "CTP___FUTURE"
        return self.get_session_state()

    def query_ctp_result(self, exchange_name, query_type, **kwargs):
        assert exchange_name == "CTP___FUTURE"
        self.public_queries.append(query_type)
        methods = {
            "account": self.query_account_result,
            "positions": self.query_positions_result,
            "orders": self.query_orders_result,
            "trades": self.query_trades_result,
            "instruments": self.query_instruments_result,
            "margin_rate": self.query_instrument_margin_rate_result,
            "commission_rate": self.query_instrument_commission_rate_result,
        }
        return methods[query_type](**kwargs)

    def confirm_ctp_settlement(self, exchange_name="CTP___FUTURE", timeout=5):
        assert exchange_name == "CTP___FUTURE"
        return self.confirm_settlement(timeout=timeout)

    def verify_ctp_settlement(self, exchange_name="CTP___FUTURE", timeout=5):
        assert exchange_name == "CTP___FUTURE"
        return self.verify_settlement_confirmation(timeout=timeout)

    def arm_execution_from_preflight(self, *, proof):
        self.armed_proofs.append(dict(proof))
        proof_sha256 = hashlib.sha256(
            json.dumps(
                dict(proof),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.armed = True
        self.arm_proof_sha256 = proof_sha256
        return {
            "armed": True,
            "market_data_only": False,
            "proof_sha256": proof_sha256,
        }

    def prepare_execution_authorization(self, reason="execution_authorization_reconfigured"):
        self.armed = False
        self.authorization_preparations.append(reason)
        return {
            "armed": False,
            "market_data_only": True,
            "reusable": True,
            "minimum_next_generation": None,
            "reason": reason,
        }

    def disarm_execution(self, reason):
        self.armed = False
        self.disarm_reasons.append(reason)
        return {
            "armed": False,
            "market_data_only": True,
            "reason": reason,
            "revocation_reason": reason,
            "revoked_generation": self.session_generation,
        }

    def prepare_execution_recovery(self, *, proof):
        self.recovery_prepares.append(dict(proof))
        assert self.recovery_report is not None
        return dict(self.recovery_report)

    def arm_execution_recovery(self, *, proof, recovery_token_sha256):
        self.recovery_arms.append((dict(proof), recovery_token_sha256))
        self.armed = True
        return {
            "armed": True,
            "market_data_only": False,
            "recovery_only": True,
            "proof_sha256": hashlib.sha256(
                json.dumps(
                    dict(proof),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest(),
            "recovery_token_sha256": recovery_token_sha256,
            "execution_cycle_id": self.recovery_report["execution_cycle_id"],
        }

    def complete_execution_recovery(self, *, recovery_token_sha256):
        self.recovery_completions.append(recovery_token_sha256)
        self.armed = False
        return {
            "completed": True,
            "armed": False,
            "market_data_only": True,
            "recovery_only": False,
            "requires_new_preflight": True,
            "recovery_token_sha256": recovery_token_sha256,
        }

    def get_execution_summary(self):
        return {
            **super().get_execution_summary(),
            "armed": self.armed,
            "market_data_only": not self.armed,
            "arm_revoked": False,
            "arm_proof_sha256": self.arm_proof_sha256,
        }


def _arming_proof(**changes):
    proof = {
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260909",
        "instrument": "CZCE.SA609",
        "connection_generation": 3,
        "environment_profile": "simnow_demo",
        "receipt_sha256": "1" * 64,
        "native_sha256": "2" * 64,
        "ctp_package_sha256": "3" * 64,
        "source_hashes_sha256": "4" * 64,
        "dependency_hashes_sha256": "5" * 64,
        "preflight_sha256": "6" * 64,
    }
    proof.update(changes)
    return proof


_AUTHORIZATION_KEY_ID = "test-authorization-key"
_AUTHORIZATION_SECRET = "test-authorization-secret-at-least-32-bytes"


def _query_ids(snapshot, names):
    return {name: snapshot["query_results"][name]["request_id"] for name in names}


def _authorized_store(client=None):
    client = client or ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={
            "market_data_only": True,
            "strategy_id": "iter22-sa-v0:engineering_smoke",
            "strategy_identity_sha256": "8" * 64,
        },
        execution_authorization_key_id=_AUTHORIZATION_KEY_ID,
        execution_authorization_secret=_AUTHORIZATION_SECRET,
    )
    stage_a = store.get_ctp_preflight_snapshot(timeout=0)
    stage_b = store.get_ctp_preflight_snapshot("CZCE.SA609", timeout=0)
    now = dt.datetime.now(dt.timezone.utc)
    proof = _arming_proof()
    grant = {
        "schema_version": "backtrader.ctp.execution-authorization.v1",
        "authorization_kind": "hmac_sha256",
        "authorization_key_id": _AUTHORIZATION_KEY_ID,
        "issued_at_utc": (now - dt.timedelta(seconds=1)).isoformat(),
        "expires_at_utc": (now + dt.timedelta(minutes=5)).isoformat(),
        **proof,
        "stage_a_snapshot_sha256": stage_a["snapshot_sha256"],
        "stage_a_query_request_ids": _query_ids(
            stage_a, ("account", "positions", "orders", "trades", "instruments")
        ),
        "stage_b_snapshot_sha256": stage_b["snapshot_sha256"],
        "stage_b_query_request_ids": _query_ids(
            stage_b,
            (
                "account",
                "positions",
                "orders",
                "trades",
                "instruments",
                "margin_rate",
                "commission_rate",
            ),
        ),
        "runtime_executable_sha256": hashlib.sha256(open(sys.executable, "rb").read()).hexdigest(),
        "evidence_hashes_sha256": "7" * 64,
        "gate_statuses": {"G1": "PASS", "G2": "PASS", "G3": "PASS"},
    }
    canonical = json.dumps(
        grant,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    grant["signature_hmac_sha256"] = hmac.new(
        _AUTHORIZATION_SECRET.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    configured = store.configure_ctp_execution_authorization(grant)
    return client, store, proof, grant, configured


def _recovery_report(*, status="RECOVERABLE", cancels=False):
    cycle_id = "sdk-cycle-0001"
    remote = {
        "long_today": "1",
        "long_yesterday": "0",
        "short_today": "0",
        "short_yesterday": "0",
    }
    owned = dict(remote)
    allowed_closes = [
        {
            "execution_cycle_id": cycle_id,
            "symbol": "SA609",
            "exchange_id": "CZCE",
            "position_side": "long",
            "side": "sell",
            "offset": "close",
            "quantity": "1",
            "quantity_unit": "contracts",
        }
    ]
    allowed_cancels = []
    unknown_ids = []
    evidence_errors = []
    recovery_required = True
    can_arm_execution = False
    can_arm_recovery = True
    allowed_actions = ["cancel" if cancels else "close"]
    token = "9" * 64
    if cancels:
        allowed_closes = []
        allowed_cancels = [
            {
                "execution_cycle_id": cycle_id,
                "symbol": "SA609",
                "exchange_id": "CZCE",
                "client_order_id": "client-1",
                "order_id": "SYS-1",
                "order_ref": "17",
                "front_id": 1,
                "session_id": 2,
            }
        ]
    if status == "FLAT":
        remote = dict.fromkeys(remote, "0")
        owned = dict(remote)
        allowed_closes = []
        allowed_cancels = []
        recovery_required = False
        can_arm_execution = True
        can_arm_recovery = False
        cycle_id = None
        allowed_actions = ["complete"]
    elif status == "MANUAL_INTERVENTION":
        owned = dict.fromkeys(remote, "0")
        allowed_closes = []
        allowed_cancels = []
        can_arm_execution = False
        can_arm_recovery = False
        cycle_id = None
        unknown_ids = ["external_position"]
        evidence_errors = ["strategy_ownership_unproven"]
        allowed_actions = []
        token = None
    return {
        "schema_version": "bt_api.execution-recovery.v1",
        "status": status,
        "recovery_required": recovery_required,
        "can_arm_execution": can_arm_execution,
        "can_arm_recovery": can_arm_recovery,
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260909",
        "instrument": "CZCE.SA609",
        "connection_generation": 3,
        "strategy_id": "iter22-sa-v0:engineering_smoke",
        "execution_cycle_id": cycle_id,
        "remote_position": remote,
        "owned_position": owned,
        "allowed_closes": allowed_closes,
        "allowed_cancels": allowed_cancels,
        "allowed_actions": allowed_actions,
        "unknown_ids": unknown_ids,
        "evidence_errors": evidence_errors,
        "journal_sha256": "8" * 64,
        "fencing_epoch": 4,
        "recovery_token_sha256": token,
    }


def test_ctp_preflight_preserves_all_typed_completion_evidence():
    client = CompleteQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_preflight_snapshot("CZCE.SA609")

    assert snapshot["evidence_complete"] is True
    assert snapshot["read_only_safe"] is True
    assert snapshot["instrument_id"] == "SA609"
    assert snapshot["exchange_id"] == "CZCE"
    assert set(snapshot["query_results"]) == {
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    }
    assert all(item["complete"] is True for item in snapshot["query_results"].values())
    assert snapshot["write_request_free"] is True
    assert snapshot["session"]["account_fingerprint"] == "acct-sha256"
    assert snapshot["request_count_delta"].get("settlement_confirm", 0) == 0
    assert snapshot["instruments"][0]["minimum_order_volume"] == 1
    assert snapshot["instruments"][0]["expire_date"] == "20260915"


def test_store_arms_public_sdk_from_same_cached_preflight_and_keeps_openings_frozen():
    client, store, proof, grant, configured = _authorized_store()
    store._command_accept_openings = True

    result = store.arm_sdk_execution(proof)

    assert result == {
        "armed": True,
        "market_data_only": False,
        "proof_sha256": hashlib.sha256(
            json.dumps(
                proof,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    assert client.armed_proofs == [proof]
    assert configured == {
        "configured": True,
        "grant_sha256": hashlib.sha256(
            json.dumps(
                grant,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
        "market_data_only": True,
    }
    assert store._sdk_execution_config["market_data_only"] is False
    assert store._command_accept_openings is False
    assert store._sdk_execution_arming is False


def test_ctp_store_start_enters_read_only_without_irreversible_sdk_disarm():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={"market_data_only": False},
    )

    store.start()

    assert store._sdk_execution_config["market_data_only"] is True
    assert client.armed is False
    assert client.disarm_reasons == []
    store.stop()


def test_authorization_preparation_requires_public_reusable_sdk_transition():
    client = ManagedBtApiClient()
    client.prepare_execution_authorization = None
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={
            "market_data_only": True,
            "strategy_id": "iter22-sa-v0:engineering_smoke",
            "strategy_identity_sha256": "8" * 64,
        },
    )

    with pytest.raises(BtApiStoreError, match="reusable.*preparation is unavailable"):
        store._prepare_sdk_execution_authorization("test_reconfigure")

    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False
    assert client.disarm_reasons == []


def test_recoverable_sdk_plan_arms_and_completes_without_enabling_openings():
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report()

    plan = store.prepare_execution_recovery(proof)
    arm = store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    completed = store.complete_execution_recovery(
        recovery_token_sha256=plan["recovery_token_sha256"]
    )

    assert plan["status"] == "RECOVERABLE"
    assert arm["recovery_only"] is True
    assert completed["completed"] is True
    assert client.recovery_prepares == [proof]
    assert client.recovery_arms == [(proof, "9" * 64)]
    assert client.recovery_completions == ["9" * 64]
    assert client.disarm_reasons == []
    assert store._command_accept_openings is False
    assert store._ctp_execution_recovery_completed is True


def test_flat_sdk_plan_completes_without_recovery_arm():
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")

    plan = store.prepare_execution_recovery(proof)
    with pytest.raises(BtApiStoreError, match="recovery must complete"):
        store.arm_sdk_execution(proof)
    completed = store.complete_execution_recovery(
        recovery_token_sha256=plan["recovery_token_sha256"]
    )

    assert plan["allowed_actions"] == ["complete"]
    assert completed["completed"] is True
    assert client.recovery_arms == []
    assert client.armed_proofs == []
    assert client.recovery_completions == ["9" * 64]
    assert store._ctp_execution_recovery_armed is False
    assert store._ctp_execution_recovery_completed is True
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False
    with pytest.raises(BtApiStoreError, match="not completable"):
        store.complete_execution_recovery(recovery_token_sha256=plan["recovery_token_sha256"])
    assert client.recovery_completions == ["9" * 64]


def test_flat_sdk_completion_failure_remains_read_only(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")

    def fail_completion(*, recovery_token_sha256):
        client.recovery_completions.append(recovery_token_sha256)
        raise RuntimeError("query barrier failed")

    monkeypatch.setattr(client, "complete_execution_recovery", fail_completion)
    plan = store.prepare_execution_recovery(proof)

    with pytest.raises(BtApiStoreError, match="completion failed"):
        store.complete_execution_recovery(recovery_token_sha256=plan["recovery_token_sha256"])

    assert client.recovery_arms == []
    assert client.recovery_completions == ["9" * 64]
    assert client.disarm_reasons == ["execution_recovery_completion_failed"]
    assert store._ctp_execution_recovery_armed is False
    assert store._ctp_execution_recovery_completed is False
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False


def test_cancel_only_recovery_token_cannot_complete_before_refresh():
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(cancels=True)

    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )

    with pytest.raises(BtApiStoreError, match="not completable"):
        store.complete_execution_recovery(recovery_token_sha256=plan["recovery_token_sha256"])

    assert client.recovery_completions == []
    assert store._ctp_execution_recovery_completed is False


def test_recovery_refresh_failure_revokes_the_previous_recovery_arm(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(cancels=True)
    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )

    def fail_refresh(*, proof):
        raise RuntimeError("refresh failed")

    monkeypatch.setattr(client, "prepare_execution_recovery", fail_refresh)
    with pytest.raises(BtApiStoreError, match="preparation failed"):
        store.prepare_execution_recovery(proof)

    assert client.disarm_reasons == ["execution_recovery_prepare_failed"]
    assert store._ctp_execution_recovery_armed is False
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False


def test_recovery_completion_queue_failure_revokes_the_recovery_arm(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report()
    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    monkeypatch.setattr(
        store,
        "_enqueue_sdk_command",
        lambda *_args, **_kwargs: {"queued": False, "status": "rejected"},
    )

    with pytest.raises(BtApiStoreError, match="was not queued"):
        store.enqueue_execution_recovery_completion(
            recovery_token_sha256=plan["recovery_token_sha256"]
        )

    assert client.disarm_reasons == ["execution_recovery_completion_queue_failed"]
    assert store._ctp_execution_recovery_armed is False
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False


@pytest.mark.parametrize("completion_fails", [False, True])
def test_async_recovery_completion_clears_terminal_pending_state(monkeypatch, completion_fails):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")
    plan = store.prepare_execution_recovery(proof)
    receipt_id = "recovery-receipt-terminal"
    store._ctp_execution_recovery_completion_pending = True
    store._ctp_execution_recovery_completion_receipt = {
        "queued": True,
        "status": "submitted",
        "receipt_id": receipt_id,
    }
    if completion_fails:

        def fail_completion(*, recovery_token_sha256):
            client.recovery_completions.append(recovery_token_sha256)
            raise RuntimeError("query barrier failed")

        monkeypatch.setattr(client, "complete_execution_recovery", fail_completion)

    completion = asyncio.run(
        store._execute_sdk_command(
            {
                "operation": "execution_recovery_complete",
                "receipt_id": receipt_id,
                "priority": 1,
                "recovery_token_sha256": plan["recovery_token_sha256"],
                "recovery_generation": store._ctp_execution_recovery_generation,
            }
        )
    )

    assert completion["success"] is (not completion_fails)
    assert store._ctp_execution_recovery_completion_pending is False
    assert store._ctp_execution_recovery_completion_receipt is None
    if completion_fails:
        monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
        monkeypatch.setattr(store, "_start_command_worker", lambda: None)
        monkeypatch.setattr(
            store,
            "_enqueue_sdk_command",
            lambda *_args, **_kwargs: {
                "queued": True,
                "status": "submitted",
                "receipt_id": "recovery-receipt-retry",
            },
        )
        retry = store.enqueue_execution_recovery_completion(
            recovery_token_sha256=plan["recovery_token_sha256"]
        )
        assert retry["receipt_id"] == "recovery-receipt-retry"
    else:
        with pytest.raises(BtApiStoreError, match="not completable"):
            store.enqueue_execution_recovery_completion(
                recovery_token_sha256=plan["recovery_token_sha256"]
            )


def test_async_recovery_completion_cancellation_clears_pending_and_propagates(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")
    plan = store.prepare_execution_recovery(proof)
    receipt_id = "recovery-receipt-cancelled"
    store._ctp_execution_recovery_completion_pending = True
    store._ctp_execution_recovery_completion_receipt = {
        "queued": True,
        "status": "submitted",
        "receipt_id": receipt_id,
    }

    def cancel_completion(*, recovery_token_sha256):
        client.recovery_completions.append(recovery_token_sha256)
        raise asyncio.CancelledError()

    monkeypatch.setattr(client, "complete_execution_recovery", cancel_completion)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            store._execute_sdk_command(
                {
                    "operation": "execution_recovery_complete",
                    "receipt_id": receipt_id,
                    "priority": "reconcile",
                    "recovery_token_sha256": plan["recovery_token_sha256"],
                    "recovery_generation": store._ctp_execution_recovery_generation,
                }
            )
        )

    assert store._ctp_execution_recovery_completion_pending is False
    assert store._ctp_execution_recovery_completion_receipt is None
    assert store._ctp_execution_recovery_completed is False
    assert store._sdk_execution_config["market_data_only"] is True
    assert client.disarm_reasons == ["execution_recovery_completion_cancelled"]


def test_recovery_plan_replacement_waits_for_inflight_completion(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")
    old_plan = store.prepare_execution_recovery(proof)
    completion_entered = threading.Event()
    release_completion = threading.Event()
    prepare_started = threading.Event()
    prepare_finished = threading.Event()
    results = []
    errors = []
    original_complete = client.complete_execution_recovery

    def blocked_completion(*, recovery_token_sha256):
        completion_entered.set()
        assert release_completion.wait(2.0)
        return original_complete(recovery_token_sha256=recovery_token_sha256)

    monkeypatch.setattr(client, "complete_execution_recovery", blocked_completion)

    def complete_old_plan():
        try:
            results.append(
                store.complete_execution_recovery(
                    recovery_token_sha256=old_plan["recovery_token_sha256"]
                )
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def replace_plan():
        prepare_started.set()
        try:
            results.append(store.prepare_execution_recovery(proof))
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            prepare_finished.set()

    completion_thread = threading.Thread(target=complete_old_plan)
    completion_thread.start()
    assert completion_entered.wait(2.0)
    client.recovery_report = _recovery_report(status="RECOVERABLE")
    prepare_thread = threading.Thread(target=replace_plan)
    prepare_thread.start()
    assert prepare_started.wait(2.0)
    assert prepare_finished.wait(0.05) is False

    release_completion.set()
    completion_thread.join(timeout=2.0)
    prepare_thread.join(timeout=2.0)

    assert not errors
    assert not completion_thread.is_alive()
    assert not prepare_thread.is_alive()
    assert results[0]["completed"] is True
    assert results[1]["status"] == "RECOVERABLE"
    assert store.get_execution_recovery_snapshot()["status"] == "RECOVERABLE"
    assert store._ctp_execution_recovery_completed is False


def test_stale_queued_recovery_completion_cannot_complete_replacement_plan(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")
    old_plan = store.prepare_execution_recovery(proof)
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    old_receipt = store.enqueue_execution_recovery_completion(
        recovery_token_sha256=old_plan["recovery_token_sha256"]
    )
    with store._command_condition:
        old_command = dict(store._command_heap[0][2])
        store._command_heap.clear()

    client.recovery_report = _recovery_report(status="RECOVERABLE")
    replacement = store.prepare_execution_recovery(proof)
    completion = asyncio.run(store._execute_sdk_command(old_command))

    assert old_receipt["receipt_id"] == old_command["receipt_id"]
    assert completion["success"] is False
    assert completion["error_code"] == "BtApiStoreError"
    assert client.recovery_completions == []
    assert store.get_execution_recovery_snapshot() == replacement
    assert store._ctp_execution_recovery_completed is False
    assert store._ctp_execution_recovery_completion_pending is False
    assert store._ctp_execution_recovery_completion_receipt is None


def test_discarded_recovery_completion_clears_matching_pending_receipt(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")
    plan = store.prepare_execution_recovery(proof)
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    first = store.enqueue_execution_recovery_completion(
        recovery_token_sha256=plan["recovery_token_sha256"]
    )

    assert store.wait_for_commands(timeout=0, stop_on_timeout=True) is False
    assert store._command_heap == []
    assert store._ctp_execution_recovery_completion_pending is False
    assert store._ctp_execution_recovery_completion_receipt is None

    with store._command_condition:
        store._command_stop_requested = False
    second = store.enqueue_execution_recovery_completion(
        recovery_token_sha256=plan["recovery_token_sha256"]
    )
    assert second["receipt_id"] != first["receipt_id"]


def test_concurrent_recovery_completion_enqueue_uses_one_sdk_command(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report()
    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)

    entered = threading.Event()
    release = threading.Event()
    calls = []

    def enqueue_once(command, *, priority_name):
        calls.append((dict(command), priority_name))
        entered.set()
        assert release.wait(2.0)
        return {
            "queued": True,
            "status": "submitted",
            "receipt_id": "recovery-receipt-1",
        }

    monkeypatch.setattr(store, "_enqueue_sdk_command", enqueue_once)
    start = threading.Barrier(3)
    results = []
    errors = []

    def request_completion():
        try:
            start.wait(timeout=2.0)
            results.append(
                store.enqueue_execution_recovery_completion(
                    recovery_token_sha256=plan["recovery_token_sha256"]
                )
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=request_completion) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=2.0)
    assert entered.wait(2.0)
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert not errors
    assert all(not thread.is_alive() for thread in threads)
    assert len(calls) == 1
    assert calls[0][0]["operation"] == "execution_recovery_complete"
    assert calls[0][1] == "reconcile"
    assert results == [results[0], results[0]]


def test_concurrent_direct_recovery_completion_reaches_sdk_once(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="FLAT")
    plan = store.prepare_execution_recovery(proof)
    entered = threading.Event()
    release = threading.Event()
    calls = []

    original_complete = client.complete_execution_recovery

    def complete_once(*, recovery_token_sha256):
        calls.append(recovery_token_sha256)
        entered.set()
        assert release.wait(2.0)
        return original_complete(recovery_token_sha256=recovery_token_sha256)

    monkeypatch.setattr(client, "complete_execution_recovery", complete_once)
    start = threading.Barrier(3)
    results = []
    errors = []

    def complete_recovery():
        try:
            start.wait(timeout=2.0)
            results.append(
                store.complete_execution_recovery(
                    recovery_token_sha256=plan["recovery_token_sha256"]
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=complete_recovery) for _ in range(2)]
    for thread in threads:
        thread.start()
    start.wait(timeout=2.0)
    assert entered.wait(2.0)
    release.set()
    for thread in threads:
        thread.join(timeout=2.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len(calls) == 1
    assert len(results) == 1
    assert results[0]["completed"] is True
    assert len(errors) == 1
    assert isinstance(errors[0], BtApiStoreError)
    assert "not completable" in str(errors[0])


@pytest.mark.parametrize("dispatch_outcome", ["rejected", "exception"])
def test_recovery_exit_dispatch_failure_strictly_aborts_before_native_write(
    monkeypatch, dispatch_outcome
):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report()
    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    order = type("RecoveryOrder", (), {"info": {"execution_role": "recovery_exit"}})()

    if dispatch_outcome == "exception":

        def fail_enqueue(_order):
            raise RuntimeError("queue unavailable")

        monkeypatch.setattr(store, "_enqueue_order_command", fail_enqueue)
        with pytest.raises(RuntimeError, match="queue unavailable"):
            store.enqueue_order(order)
    else:
        monkeypatch.setattr(
            store,
            "_enqueue_order_command",
            lambda _order: {"queued": False, "status": "rejected"},
        )
        assert store.enqueue_order(order) == {"queued": False, "status": "rejected"}

    assert client.request_counts["order_insert"] == 0
    assert client.submitted_orders == []
    assert client.armed is False
    assert client.disarm_reasons == ["execution_recovery_dispatch_failed"]
    assert store.execution_recovery_armed is False
    assert store._ctp_execution_recovery_proof is None
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False

    cached = store.abort_execution_recovery("later_abort_is_idempotent")
    assert cached["aborted"] is True
    assert client.disarm_reasons == ["execution_recovery_dispatch_failed"]


def test_external_unowned_position_stays_manual_with_zero_recovery_writes():
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(status="MANUAL_INTERVENTION")

    plan = store.prepare_execution_recovery(proof)

    assert plan["status"] == "MANUAL_INTERVENTION"
    with pytest.raises(BtApiStoreError, match="not armable"):
        store.arm_execution_recovery(
            proof,
            recovery_token_sha256="9" * 64,
        )
    with pytest.raises(BtApiStoreError, match="not armed"):
        store.cancel_execution_recovery_orders(recovery_token_sha256="9" * 64)
    assert client.recovery_arms == []
    assert client.recovery_completions == []
    assert client.disarm_reasons == []
    assert store._command_accept_openings is False


def test_recovery_proof_and_token_mismatches_are_rejected_before_sdk_writes():
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report()

    with pytest.raises(BtApiStoreError, match="differs from authorization"):
        store.prepare_execution_recovery({**proof, "preflight_sha256": "0" * 64})
    plan = store.prepare_execution_recovery(proof)
    with pytest.raises(BtApiStoreError, match="token mismatch"):
        store.arm_execution_recovery(
            proof,
            recovery_token_sha256="0" * 64,
        )

    assert plan["status"] == "RECOVERABLE"
    assert client.recovery_prepares == [proof]
    assert client.recovery_arms == []
    assert client.recovery_completions == []


def test_recovery_rejects_czce_close_today_before_any_recovery_write():
    client, store, proof, _grant, _configured = _authorized_store()
    report = _recovery_report()
    report["allowed_closes"][0]["offset"] = "close_today"
    client.recovery_report = report

    with pytest.raises(BtApiStoreError, match="CZCE close offset"):
        store.prepare_execution_recovery(proof)

    assert client.recovery_arms == []
    assert client.recovery_completions == []
    assert client.disarm_reasons == ["execution_recovery_prepare_invalid"]


def test_recovery_rejects_unknown_public_schema_before_any_recovery_write():
    client, store, proof, _grant, _configured = _authorized_store()
    report = _recovery_report()
    report["schema_version"] = "bt_api.execution-recovery.v2"
    client.recovery_report = report

    with pytest.raises(BtApiStoreError, match="schema_version"):
        store.prepare_execution_recovery(proof)

    assert client.recovery_arms == []
    assert client.recovery_completions == []
    assert client.disarm_reasons == ["execution_recovery_prepare_invalid"]


def test_recovery_cancels_sdk_owned_order_without_backtrader_order_object(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(cancels=True)
    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    queued = []
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    monkeypatch.setattr(store, "_sdk_account_id", lambda _venue: "account-1")
    monkeypatch.setattr(
        store,
        "enqueue_cancel",
        lambda reference, dataname=None: queued.append((reference, dataname))
        or {"queued": True, "operation": "cancel"},
    )

    receipts = store.cancel_execution_recovery_orders(
        recovery_token_sha256=plan["recovery_token_sha256"]
    )
    with pytest.raises(BtApiStoreError, match="already requested"):
        store.cancel_execution_recovery_orders(recovery_token_sha256=plan["recovery_token_sha256"])

    assert receipts == [{"queued": True, "operation": "cancel"}]
    assert queued == [("client-1", None)]
    assert store._sdk_local_refs["client-1"]["bt_order_ref"].startswith("recovery:")
    assert store._command_accept_openings is False


def test_recovery_cancel_token_is_claimed_atomically_before_dispatch(monkeypatch):
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report(cancels=True)
    plan = store.prepare_execution_recovery(proof)
    store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )
    dispatch_entered = threading.Event()
    release_dispatch = threading.Event()
    queued = []
    results = []
    errors = []
    monkeypatch.setattr(store, "_require_async_sdk_commands", lambda: None)
    monkeypatch.setattr(store, "_start_command_worker", lambda: None)
    monkeypatch.setattr(store, "_sdk_account_id", lambda _venue: "account-1")

    def enqueue_cancel(reference, dataname=None):
        queued.append((reference, dataname))
        dispatch_entered.set()
        assert release_dispatch.wait(timeout=2.0)
        return {"queued": True, "operation": "cancel"}

    monkeypatch.setattr(store, "enqueue_cancel", enqueue_cancel)

    def invoke():
        try:
            results.append(
                store.cancel_execution_recovery_orders(
                    recovery_token_sha256=plan["recovery_token_sha256"]
                )
            )
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=invoke)
    second = threading.Thread(target=invoke)
    first.start()
    assert dispatch_entered.wait(timeout=2.0)
    second.start()
    second.join(timeout=2.0)
    release_dispatch.set()
    first.join(timeout=2.0)

    assert not first.is_alive() and not second.is_alive()
    assert results == [[{"queued": True, "operation": "cancel"}]]
    assert len(errors) == 1
    assert isinstance(errors[0], BtApiStoreError)
    assert "already requested" in str(errors[0])
    assert queued == [("client-1", None)]


def test_managed_order_request_carries_strategy_cycle_and_recovery_role(monkeypatch):
    class Request:
        def __init__(self, **kwargs):
            vars(self).update(kwargs)

    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={
            "market_data_only": True,
            "strategy_id": "iter22-sa-v0:engineering_smoke",
            "strategy_identity_sha256": "8" * 64,
        },
    )
    store._sdk_command_types = {
        "OrderRequest": Request,
        "OrderType": lambda value: value,
        "Side": lambda value: value,
    }
    monkeypatch.setattr(store, "_sdk_account_id", lambda _venue: "account-1")

    request = store._sdk_order_request(
        "CTP___FUTURE",
        {
            "symbol": "SA609",
            "bt_order_ref": 41,
            "client_order_id": "recovery-client-1",
            "side": "sell",
            "order_type": "limit",
            "size": 1,
            "price": 1500,
            "quantity_unit": "contracts",
            "time_in_force": "GFD",
            "reduce_only": True,
            "position_side": "long",
            "offset": "close",
            "exchange_id": "CZCE",
            "position_mode": "dual_side",
            "execution_cycle_id": "sdk-cycle-1",
            "execution_role": "recovery_exit",
        },
    )

    assert request.strategy_identity_sha256 == "8" * 64
    assert request.execution_cycle_id == "sdk-cycle-1"
    assert request.execution_role == "recovery_exit"
    assert request.quantity_unit == "contracts"
    assert request.offset == "close"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_fingerprint", "acct_fedcba9876543210"),
        ("trading_day", "20260910"),
        ("instrument", "CZCE.SR609"),
        ("connection_generation", 4),
        ("environment_profile", "other_demo"),
    ],
)
def test_store_rejects_proof_not_bound_to_cached_preflight(field, value):
    client, store, proof, _grant, _configured = _authorized_store()
    store._command_accept_openings = True

    with pytest.raises(BtApiStoreError, match=field):
        store.arm_sdk_execution({**proof, field: value})

    assert client.armed_proofs == []
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False
    assert store._sdk_execution_arming is False


def test_store_rejects_stale_cached_preflight_before_public_sdk_call():
    client, store, proof, _grant, _configured = _authorized_store()
    store._ctp_query_max_age_seconds = 30.0
    store._last_ctp_preflight_snapshot["completed_monotonic"] -= 31.0
    store._command_accept_openings = True

    with pytest.raises(BtApiStoreError, match="incomplete or stale"):
        store.arm_sdk_execution(proof)

    assert client.armed_proofs == []
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False
    assert store._sdk_execution_arming is False


@pytest.mark.parametrize(
    "proof",
    [
        {**_arming_proof(), "extra": "forbidden"},
        {key: value for key, value in _arming_proof().items() if key != "receipt_sha256"},
    ],
)
def test_store_rejects_noncanonical_proof_shape_before_public_sdk_call(proof):
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={
            "market_data_only": True,
            "strategy_id": "iter22-sa-v0:engineering_smoke",
            "strategy_identity_sha256": "8" * 64,
        },
    )
    store._command_accept_openings = True

    with pytest.raises(BtApiStoreError, match="invalid shape"):
        store.arm_sdk_execution(proof)

    assert client.armed_proofs == []
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False
    assert store._sdk_execution_arming is False


def test_store_rejects_invalid_sdk_arm_result_and_keeps_openings_frozen():
    client = ManagedBtApiClient()
    client, store, proof, _grant, _configured = _authorized_store(client)
    client.arm_execution_from_preflight = lambda *, proof: {
        "armed": True,
        "market_data_only": False,
        "proof_sha256": "0" * 64,
    }
    store._command_accept_openings = True

    with pytest.raises(BtApiStoreError, match="invalid result"):
        store.arm_sdk_execution(proof)

    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False


def test_empty_incomplete_query_is_not_interpreted_as_zero_records():
    client = CompleteQueryClient()
    client.incomplete.add("positions")
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_preflight_snapshot("SA609")

    assert snapshot["positions"] == []
    assert snapshot["evidence_complete"] is False
    assert "positions_query_incomplete" in snapshot["evidence_errors"]


def test_query_generation_mismatch_fails_closed():
    client = CompleteQueryClient()
    client.generation_override["trades"] = 4
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["evidence_complete"] is False
    assert "query_generation_mismatch" in snapshot["evidence_errors"]


def test_query_generation_must_match_the_current_session():
    client = CompleteQueryClient()
    client.session_generation = 4
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["evidence_complete"] is False
    assert "query_generation_session_mismatch" in snapshot["evidence_errors"]


def test_session_identity_change_during_queries_fails_closed():
    client = CompleteQueryClient()
    client.session_generation_sequence = [3, 4]
    client.session_fingerprint_sequence = ["acct-sha256", "acct-new-sha256"]
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["evidence_complete"] is False
    assert "session_generation_changed" in snapshot["evidence_errors"]
    assert "session_account_fingerprint_changed" in snapshot["evidence_errors"]


def test_trading_day_cannot_change_during_query_group():
    client = CompleteQueryClient()
    client.session_trading_day_sequence = ["20260909", "20260910"]
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot(timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "session_trading_day_changed" in snapshot["evidence_errors"]


def test_session_account_fingerprint_is_mandatory():
    client = CompleteQueryClient()
    client.session_fingerprint = ""
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["evidence_complete"] is False
    assert "session_account_fingerprint_missing" in snapshot["evidence_errors"]


def test_query_request_type_mismatch_fails_closed():
    client = CompleteQueryClient()
    client.request_type_override["positions"] = "orders"
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["evidence_complete"] is False
    assert "positions_request_type_mismatch" in snapshot["evidence_errors"]


def test_malformed_query_records_cannot_be_coerced_to_an_empty_success():
    client = CompleteQueryClient()
    client.records_override["positions"] = None
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot()

    assert snapshot["positions"] == []
    assert snapshot["evidence_complete"] is False
    assert "positions_records_schema_invalid" in snapshot["evidence_errors"]


def test_nested_query_failure_cannot_be_overridden_by_outer_success_fields():
    client = CompleteQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    complete = client._result("positions")
    nested_failure = {
        **complete,
        "complete": False,
        "is_last_seen": False,
        "completed_at_utc": None,
        "timed_out": True,
        "error_code": "timeout",
    }

    result = store._normalise_ctp_query_result(
        {**complete, "query_result": nested_failure}, "positions"
    )

    assert result["complete"] is False
    assert store._ctp_query_result_complete(result) is False


def test_duplicate_query_request_ids_fail_closed_across_reference_queries():
    client = CompleteQueryClient()
    client.request_id_override.update({"margin_rate": 77, "commission_rate": 77})
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_preflight_snapshot("SA609")

    assert snapshot["evidence_complete"] is False
    assert "query_request_id_not_unique" in snapshot["evidence_errors"]


def test_read_only_preflight_requires_auto_settlement_confirm_disabled():
    store = make_store(
        api=CompleteQueryClient(auto_settlement_confirm=True),
        provider="ctp_gateway",
    )

    snapshot = store.get_ctp_preflight_snapshot("SA609")

    assert snapshot["read_only_safe"] is False
    assert snapshot["evidence_complete"] is False
    assert "auto_settlement_confirm_not_disabled" in snapshot["evidence_errors"]


def test_provider_btapi_uses_managed_public_ctp_facade_and_preserves_metadata():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        symbol_routes={"SA609": "CTP___FUTURE"},
    )

    snapshot = store.get_ctp_preflight_snapshot("CZCE.SA609", timeout=0)

    assert snapshot["evidence_complete"] is True
    assert client.public_queries == [
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    ]
    instrument = snapshot["instruments"][0]
    assert instrument["InstrumentID"] == "SA609"
    assert instrument["is_trading"] == 1
    assert instrument["open_interest"] == 12345.0
    assert instrument["minimum_order_volume"] == 1
    assert snapshot["write_request_free"] is True
    assert snapshot["unknown_intent_count"] == 0
    assert snapshot["unmatched_trade_count"] == 0


def test_settlement_prepare_and_verify_expose_request_count_evidence():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    prepared = store.prepare_ctp_settlement(timeout=0)
    verified = store.verify_ctp_settlement(timeout=0)

    assert prepared["evidence_complete"] is True
    assert prepared["settlement_confirm_delta"] == 1
    assert prepared["order_insert_delta"] == 0
    assert prepared["order_action_delta"] == 0
    assert verified["evidence_complete"] is True
    assert verified["read_only_safe"] is True
    assert verified["request_count_delta"].get("settlement_confirm", 0) == 0
    assert verified["request_count_delta"]["settlement_confirmation"] == 1


def test_provider_btapi_uses_only_managed_ctp_query_facade():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        symbol_routes={"CZCE.SA609": "CTP___FUTURE"},
    )

    snapshot = store.get_ctp_preflight_snapshot("CZCE.SA609")

    assert snapshot["evidence_complete"] is True
    assert client.public_queries == [
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "margin_rate",
        "commission_rate",
    ]
    assert snapshot["trading_day"] == "20260909"
    assert snapshot["request_ids"] == {
        "account": 1,
        "positions": 2,
        "orders": 3,
        "trades": 4,
    }


def test_explicit_settlement_preparation_returns_counter_evidence():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    result = store.prepare_ctp_settlement(timeout=0)

    assert result["success"] is True
    assert result["evidence_complete"] is True
    assert result["settlement_confirm_delta"] == 1
    assert result["order_insert_delta"] == 0
    assert result["order_action_delta"] == 0


def test_cached_preflight_is_bound_to_current_session_generation_and_identity():
    client = CompleteQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    assert store.get_ctp_preflight_snapshot("SA609", timeout=0)["evidence_complete"] is True

    client.session_generation = 4
    client.session_fingerprint = "acct-new-sha256"
    health = store.get_ctp_query_health()

    assert health["evidence_complete"] is False
    assert "ctp_query_snapshot_generation_stale" in health["evidence_errors"]
    assert "ctp_query_snapshot_account_stale" in health["evidence_errors"]


def test_cached_preflight_expires_after_the_configured_maximum_age():
    client = CompleteQueryClient()
    store = make_store(
        api=client,
        provider="ctp_gateway",
        auto_settlement_confirm=False,
        ctp_query_max_age_seconds=30.0,
    )
    assert store.get_ctp_preflight_snapshot("SA609", timeout=0)["evidence_complete"] is True
    store._last_ctp_preflight_snapshot["completed_monotonic"] -= 31.0

    health = store.get_ctp_query_health()

    assert health["evidence_complete"] is False
    assert "ctp_query_snapshot_stale" in health["evidence_errors"]


def test_cached_preflight_is_invalidated_at_the_trading_day_boundary():
    client = CompleteQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    assert store.get_ctp_preflight_snapshot("SA609", timeout=0)["evidence_complete"] is True

    client.trading_day = "20260910"
    health = store.get_ctp_query_health()

    assert health["evidence_complete"] is False
    assert "ctp_query_snapshot_trading_day_stale" in health["evidence_errors"]


def test_reconciliation_fingerprint_is_bound_to_the_trading_day():
    client = CompleteQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    first = store.get_ctp_reconciliation_snapshot(timeout=0)
    client.trading_day = "20260910"
    second = store.get_ctp_reconciliation_snapshot(timeout=0)

    assert first["evidence_complete"] is True
    assert second["evidence_complete"] is True
    assert first["reconciliation_fingerprint"] != second["reconciliation_fingerprint"]


def test_legacy_ctp_reconciliation_worker_stops_and_discards_stale_completion():
    client = CompleteQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    receipt = store.enqueue_ctp_reconciliation(timeout=0)
    assert receipt["queued"] is True
    assert store.wait_for_commands(2.0) is True
    worker = store._command_worker_thread
    assert worker is not None and worker.is_alive()

    health = store.stop(timeout=2.0)

    assert not worker.is_alive()
    assert store._command_worker_thread is None
    assert health["shutdown_state"] == "PASS"
    assert store.poll_broker_update() is None


def test_legacy_ctp_stop_does_not_disconnect_under_an_inflight_query():
    entered = threading.Event()
    release = threading.Event()

    class BlockingQueryClient(CompleteQueryClient):
        def query_account_result(self, timeout=5):
            entered.set()
            release.wait(1.0)
            return super().query_account_result(timeout=timeout)

    client = BlockingQueryClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    assert store.enqueue_ctp_reconciliation(timeout=1.0)["queued"] is True
    assert entered.wait(1.0)

    health = store.stop(timeout=0.01)

    assert health["shutdown_state"] == "INCOMPLETE"
    assert client.connected is True
    assert store._connected is True
    with pytest.raises(BtApiStoreError, match="previous CTP query worker"):
        store.start()

    release.set()
    worker = store._command_worker_thread
    assert worker is not None
    worker.join(1.0)
    assert not worker.is_alive()
    store.start()
    store.stop(timeout=1.0)


def test_ctp_query_group_obeys_minimum_start_interval():
    client = CompleteQueryClient()
    client.ctp_query_min_interval_seconds = 0.01
    starts = []
    original = client._result

    def record_start(name):
        starts.append(time.monotonic())
        return original(name)

    client._result = record_start
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_reconciliation_snapshot(timeout=1.0)

    assert snapshot["evidence_complete"] is True
    assert len(starts) == 4
    assert all(right - left >= 0.008 for left, right in zip(starts, starts[1:]))


def test_ctp_query_timeout_is_one_total_deadline_for_the_group():
    client = CompleteQueryClient()
    client.ctp_query_min_interval_seconds = 0.03
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    started = time.monotonic()

    snapshot = store.get_ctp_reconciliation_snapshot(timeout=0.04)
    elapsed = time.monotonic() - started

    assert client.request_id <= 2
    assert elapsed < 0.15
    assert snapshot["evidence_complete"] is False
    assert snapshot["timed_out"] is True
    assert any(
        result["error_code"] == "query_deadline_exceeded"
        for result in snapshot["query_results"].values()
    )


def test_native_ctp_wrapper_rejects_market_before_req_order_insert():
    pytest.importorskip("bt_api_ctp.ctp.client")
    wrapper_cls = _create_ctp_wrapper_class()

    class FakeApi:
        def ReqOrderInsert(self, _field, _request_id):
            raise AssertionError("ReqOrderInsert must not run for a CTP Market order")

    class FakeTraderClient:
        is_ready = True

        def __init__(self):
            self.api = FakeApi()

    client = wrapper_cls(
        md_address="tcp://md",
        td_address="tcp://td",
        broker_id="9999",
        investor_id="demo",
        password="secret",
    )
    client.trader_client = FakeTraderClient()

    with pytest.raises(BtApiStoreError, match="Unsupported CTP order type"):
        client.submit_order(
            {
                "data_name": "CZCE.SA609",
                "side": "buy",
                "size": 1,
                "price": 1500.0,
                "order_type": "market",
                "offset": "close",
            }
        )
