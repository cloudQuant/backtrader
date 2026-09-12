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

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError, _create_ctp_wrapper_class
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
        self.started_at_override = {}
        self.completed_at_override = {}
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
        now = dt.datetime.now(dt.timezone.utc)
        return {
            "request_type": self.request_type_override.get(name, name),
            "request_id": self.request_id_override.get(name, self.request_id),
            "connection_generation": self.generation_override.get(name, 3),
            "account_fingerprint": "acct-sha256",
            "started_at_utc": self.started_at_override.get(name, now.isoformat()),
            "completed_at_utc": (
                self.completed_at_override.get(
                    name, (now + dt.timedelta(microseconds=1)).isoformat()
                )
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

    def query_option_instrument_trade_cost_result(self, instrument_id, timeout=5, **_kwargs):
        return self._result("option_trade_cost")

    def query_option_instrument_commission_rate_result(self, instrument_id, timeout=5, **_kwargs):
        return self._result("option_commission_rate")

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


class LegacyInstrumentSignatureClient(CompleteQueryClient):
    """Direct CTP fixture whose instrument query predates ProductID support."""

    def __init__(self):
        super().__init__()
        self.instrument_filters = []

    def query_instruments_result(self, instrument_id="", exchange_id="", timeout=5):
        self.instrument_filters.append(
            {
                "instrument_id": instrument_id,
                "exchange_id": exchange_id,
                "timeout": timeout,
            }
        )
        return self._result("instruments")


class ManagedBtApiClient(CompleteQueryClient):
    """Only the managed public CTP facade is available to the Store."""

    def __init__(self):
        super().__init__()
        self.exchange_kwargs = {"CTP___FUTURE": {"auto_settlement_confirm": False}}
        self.public_queries = []
        self.public_query_kwargs = []
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
        self.opaque_authorization_proofs = {}
        self.arm_arguments = []

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
        self.public_query_kwargs.append(dict(kwargs))
        methods = {
            "account": self.query_account_result,
            "positions": self.query_positions_result,
            "orders": self.query_orders_result,
            "trades": self.query_trades_result,
            "instruments": self.query_instruments_result,
            "margin_rate": self.query_instrument_margin_rate_result,
            "commission_rate": self.query_instrument_commission_rate_result,
            "option_trade_cost": self.query_option_instrument_trade_cost_result,
            "option_commission_rate": self.query_option_instrument_commission_rate_result,
        }
        return methods[query_type](**kwargs)

    def confirm_ctp_settlement(self, exchange_name="CTP___FUTURE", timeout=5):
        assert exchange_name == "CTP___FUTURE"
        return self.confirm_settlement(timeout=timeout)

    def verify_ctp_settlement(self, exchange_name="CTP___FUTURE", timeout=5):
        assert exchange_name == "CTP___FUTURE"
        return self.verify_settlement_confirmation(timeout=timeout)

    def arm_execution_from_preflight(self, authorization=None, *, proof=None):
        if authorization is not None:
            proof = self.opaque_authorization_proofs[authorization]
        assert proof is not None
        self.arm_arguments.append(authorization if authorization is not None else proof)
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
        summary = {
            **super().get_execution_summary(),
            "armed": self.armed,
            "market_data_only": not self.armed,
            "arm_revoked": False,
            "arm_proof_sha256": self.arm_proof_sha256,
        }
        if self.armed_proofs and "scope_version" in self.armed_proofs[-1]:
            summary.update(
                {
                    "execution_gate_scope_version": self.armed_proofs[-1]["scope_version"],
                    "execution_gate_authorized_instruments": list(
                        self.armed_proofs[-1]["authorized_instruments"]
                    ),
                    "execution_gate_instrument": self.armed_proofs[-1]["instrument"],
                }
            )
        return summary


class BundleQueryClient(ManagedBtApiClient):
    """Managed-facade fixture for raw C/P/F V2 bundle evidence."""

    def __init__(self):
        super().__init__()
        self.reference_requests = []
        self.rows.update(
            {
                "instruments": [
                    {
                        "InstrumentID": "m2701",
                        "ExchangeID": "DCE",
                        "ProductClass": "1",
                        "IsTrading": 1,
                        "ExpireDate": "20261207",
                        "TradingDay": "20260909",
                        "PriceTick": 0.5,
                        "VolumeMultiple": 10,
                        "MinLimitOrderVolume": 1,
                    },
                    {
                        "InstrumentID": "m2701-C-3400",
                        "ExchangeID": "DCE",
                        "ProductClass": "2",
                        "OptionsType": "1",
                        "UnderlyingInstrID": "m2701",
                        "StrikePrice": 3400.0,
                        "IsTrading": 1,
                        "ExpireDate": "20261207",
                        "TradingDay": "20260909",
                        "PriceTick": 0.5,
                        "VolumeMultiple": 10,
                        "MinLimitOrderVolume": 1,
                    },
                    {
                        "InstrumentID": "m2701-P-3400",
                        "ExchangeID": "DCE",
                        "ProductClass": "2",
                        "OptionsType": "2",
                        "UnderlyingInstrID": "m2701",
                        "StrikePrice": 3400.0,
                        "IsTrading": 1,
                        "ExpireDate": "20261207",
                        "TradingDay": "20260909",
                        "PriceTick": 0.5,
                        "VolumeMultiple": 10,
                        "MinLimitOrderVolume": 1,
                    },
                ],
                "margin_rate": [
                    {
                        "InstrumentID": "m2701",
                        "LongMarginRatioByMoney": 0.1,
                        "LongMarginRatioByVolume": 0.0,
                        "ShortMarginRatioByMoney": 0.1,
                        "ShortMarginRatioByVolume": 0.0,
                    },
                    {
                        "InstrumentID": "m2701-C-3400",
                        "LongMarginRatioByMoney": 0.2,
                        "LongMarginRatioByVolume": 0.0,
                        "ShortMarginRatioByMoney": 0.2,
                        "ShortMarginRatioByVolume": 0.0,
                    },
                    {
                        "InstrumentID": "m2701-P-3400",
                        "LongMarginRatioByMoney": 0.2,
                        "LongMarginRatioByVolume": 0.0,
                        "ShortMarginRatioByMoney": 0.2,
                        "ShortMarginRatioByVolume": 0.0,
                    },
                ],
                "commission_rate": [
                    {
                        "InstrumentID": "m2701",
                        "OpenRatioByMoney": 0.0001,
                        "OpenRatioByVolume": 0.0,
                        "CloseRatioByMoney": 0.0001,
                        "CloseRatioByVolume": 0.0,
                        "CloseTodayRatioByMoney": 0.0001,
                        "CloseTodayRatioByVolume": 0.0,
                    },
                    {
                        "InstrumentID": "m2701-C-3400",
                        "OpenRatioByMoney": 0.0002,
                        "OpenRatioByVolume": 0.0,
                        "CloseRatioByMoney": 0.0002,
                        "CloseRatioByVolume": 0.0,
                        "CloseTodayRatioByMoney": 0.0002,
                        "CloseTodayRatioByVolume": 0.0,
                    },
                    {
                        "InstrumentID": "m2701-P-3400",
                        "OpenRatioByMoney": 0.0002,
                        "OpenRatioByVolume": 0.0,
                        "CloseRatioByMoney": 0.0002,
                        "CloseRatioByVolume": 0.0,
                        "CloseTodayRatioByMoney": 0.0002,
                        "CloseTodayRatioByVolume": 0.0,
                    },
                ],
                "option_trade_cost": [
                    {
                        "InstrumentID": "m2701-C-3400",
                        "FixedMargin": 100.0,
                        "MiniMargin": 20.0,
                        "Royalty": 1.0,
                        "ExchFixedMargin": 50.0,
                        "ExchMiniMargin": 10.0,
                    },
                    {
                        "InstrumentID": "m2701-P-3400",
                        "FixedMargin": 100.0,
                        "MiniMargin": 20.0,
                        "Royalty": 1.0,
                        "ExchFixedMargin": 50.0,
                        "ExchMiniMargin": 10.0,
                    },
                ],
                "option_commission_rate": [
                    {
                        "InstrumentID": "m2701-C-3400",
                        "OpenRatioByMoney": 0.0002,
                        "OpenRatioByVolume": 0.0,
                        "CloseRatioByMoney": 0.0002,
                        "CloseRatioByVolume": 0.0,
                        "CloseTodayRatioByMoney": 0.0002,
                        "CloseTodayRatioByVolume": 0.0,
                    },
                    {
                        "InstrumentID": "m2701-P-3400",
                        "OpenRatioByMoney": 0.0002,
                        "OpenRatioByVolume": 0.0,
                        "CloseRatioByMoney": 0.0002,
                        "CloseRatioByVolume": 0.0,
                        "CloseTodayRatioByMoney": 0.0002,
                        "CloseTodayRatioByVolume": 0.0,
                    },
                ],
            }
        )

    def _scoped_reference_result(self, name, instrument_id, exchange_id="", **kwargs):
        self.reference_requests.append(
            {
                "name": name,
                "instrument_id": instrument_id,
                "exchange_id": exchange_id,
                **kwargs,
            }
        )
        result = self._result(name)
        if result["complete"]:
            result["records"] = [
                dict(row)
                for row in result["records"]
                if row.get("InstrumentID") == instrument_id
                and row.get("ExchangeID", exchange_id) == exchange_id
            ]
        return result

    def query_instruments_result(self, instrument_id="", exchange_id="", timeout=5, **kwargs):
        return self._scoped_reference_result(
            "instruments",
            instrument_id,
            exchange_id,
            timeout=timeout,
            **kwargs,
        )

    def query_instrument_margin_rate_result(
        self, instrument_id, exchange_id="", timeout=5, **kwargs
    ):
        return self._scoped_reference_result(
            "margin_rate",
            instrument_id,
            exchange_id,
            timeout=timeout,
            **kwargs,
        )

    def query_instrument_commission_rate_result(
        self, instrument_id, exchange_id="", timeout=5, **kwargs
    ):
        return self._scoped_reference_result(
            "commission_rate",
            instrument_id,
            exchange_id,
            timeout=timeout,
            **kwargs,
        )

    def query_option_instrument_trade_cost_result(
        self,
        instrument_id,
        exchange_id="",
        hedge_flag="1",
        input_price=0.0,
        underlying_price=0.0,
        timeout=5,
        **kwargs,
    ):
        return self._scoped_reference_result(
            "option_trade_cost",
            instrument_id,
            exchange_id,
            hedge_flag=hedge_flag,
            input_price=input_price,
            underlying_price=underlying_price,
            timeout=timeout,
            **kwargs,
        )

    def query_option_instrument_commission_rate_result(
        self, instrument_id, exchange_id="", timeout=5, **kwargs
    ):
        return self._scoped_reference_result(
            "option_commission_rate",
            instrument_id,
            exchange_id,
            timeout=timeout,
            **kwargs,
        )


class PrefixInstrumentBundleClient(BundleQueryClient):
    """Return the full prefix instrument response for every instrument query."""

    def query_instruments_result(self, instrument_id="", exchange_id="", timeout=5, **kwargs):
        self.reference_requests.append(
            {
                "name": "instruments",
                "instrument_id": instrument_id,
                "exchange_id": exchange_id,
                "timeout": timeout,
                **kwargs,
            }
        )
        return self._result("instruments")


class ExecutionReferenceBundleClient(BundleQueryClient):
    """Offline typed depth/cost surface for the public execution reference."""

    def __init__(self):
        super().__init__()
        self.depth_requests = []
        self.rows["depth_market_data"] = [
            {"InstrumentID": "m2701", "ExchangeID": "DCE", "BidPrice1": 3400.0, "AskPrice1": 3400.0, "BidVolume1": 10, "AskVolume1": 10},
            {"InstrumentID": "m2701-C-3400", "ExchangeID": "DCE", "BidPrice1": 100.0, "AskPrice1": 101.0, "BidVolume1": 10, "AskVolume1": 10},
            {"InstrumentID": "m2701-P-3400", "ExchangeID": "DCE", "BidPrice1": 99.0, "AskPrice1": 99.0, "BidVolume1": 10, "AskVolume1": 10},
        ]

    def _result(self, name):
        result = super()._result(name)
        result["schema_version"] = "ctp.query.v1"
        result["trading_day"] = self.trading_day
        return result

    def query_depth_market_data_result(self, instrument_id, exchange_id="", timeout=5, **kwargs):
        self.depth_requests.append({"instrument_id": instrument_id, "exchange_id": exchange_id})
        return self._scoped_reference_result(
            "depth_market_data", instrument_id, exchange_id, timeout=timeout, **kwargs
        )


class OpaqueOnlyBundleClient(BundleQueryClient):
    """Match the real SDK arm signature: one opaque authorization object."""

    def arm_execution_from_preflight(self, authorization):
        return super().arm_execution_from_preflight(authorization)


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


def test_ctp_preflight_normalizes_missing_unmatched_count_only_for_disabled_empty_session():
    client = CompleteQueryClient()
    client.get_execution_summary = lambda: {
        "session_enabled": False,
        "unknown_ids": [],
        "active_orders": None,
    }
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_preflight_snapshot("CZCE.SA609", timeout=0)

    assert snapshot["unmatched_trade_count"] == 0
    assert snapshot["evidence_complete"] is True


def test_ctp_bundle_preflight_keeps_missing_unmatched_count_unknown_outside_safe_state():
    client, store = _dce_bundle_store()
    client.get_execution_summary = lambda: {
        "session_enabled": False,
        "unknown_ids": ["unknown-order"],
        "active_orders": None,
    }

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["unmatched_trade_count"] is None


def _dce_bundle_legs():
    return [
        {"exchange_id": "DCE", "instrument_id": "m2701", "is_primary": True},
        {"exchange_id": "DCE", "instrument_id": "m2701-C-3400"},
        {"exchange_id": "DCE", "instrument_id": "m2701-P-3400"},
    ]


def _dce_bundle_store():
    client = BundleQueryClient()
    return client, make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )


def test_ctp_bundle_preflight_preserves_exact_dce_option_ids_and_uses_only_public_reads():
    client, store = _dce_bundle_store()

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["schema_version"] == "backtrader.ctp.bundle-preflight.v2"
    assert snapshot["evidence_complete"] is True
    assert snapshot["read_only"] is True
    assert snapshot["read_only_safe"] is True
    assert snapshot["execution_eligible"] is False
    assert snapshot["primary_leg"] == {"exchange_id": "DCE", "instrument_id": "m2701"}
    assert [leg["instrument_id"] for leg in snapshot["legs"]] == [
        "m2701",
        "m2701-C-3400",
        "m2701-P-3400",
    ]
    assert [leg["metadata"]["asset_type"] for leg in snapshot["legs"]] == [
        "future",
        "option",
        "option",
    ]
    assert [leg["metadata"]["option_type"] for leg in snapshot["legs"][1:]] == [
        "call",
        "put",
    ]
    assert snapshot["legs"][1]["metadata"]["underlying_instrument_id"] == "m2701"
    assert snapshot["legs"][2]["metadata"]["strike_price"] == 3400.0
    assert snapshot["snapshot_sha256"]
    assert client.public_queries == [
        "account",
        "positions",
        "orders",
        "trades",
        "instruments",
        "instruments",
        "instruments",
        "margin_rate",
        "commission_rate",
        "option_trade_cost",
        "option_commission_rate",
        "option_trade_cost",
        "option_commission_rate",
    ]
    assert client.public_query_kwargs[:4] == [{"timeout": 0.0}] * 4
    assert [request["instrument_id"] for request in client.reference_requests] == [
        "m2701",
        "m2701-C-3400",
        "m2701-P-3400",
        "m2701",
        "m2701",
        "m2701-C-3400",
        "m2701-C-3400",
        "m2701-P-3400",
        "m2701-P-3400",
    ]
    option_cost_requests = [
        request for request in client.reference_requests if request["name"] == "option_trade_cost"
    ]
    assert all(
        request["hedge_flag"] == "1"
        and request["input_price"] == 0.0
        and request["underlying_price"] == 0.0
        for request in option_cost_requests
    )
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )
    assert snapshot["write_request_free"] is True


def test_ctp_bundle_execution_reference_uses_real_quote_inputs_and_no_writes():
    client = ExecutionReferenceBundleClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_bundle_execution_reference_snapshot(
        _dce_bundle_legs(), timeout=0
    )

    assert snapshot["schema_version"] == "backtrader.ctp.bundle-execution-reference.v1"
    assert snapshot["evidence_complete"] is True
    assert snapshot["write_request_free"] is True
    assert snapshot["broker_contract_metadata_complete"] is True
    metadata = snapshot["broker_contract_metadata"]
    assert metadata["schema_version"] == "backtrader.ctp.broker-contract-metadata.v1"
    assert metadata["legs"][0]["symbol_aliases"] == ["DCE.m2701", "m2701"]
    assert metadata["legs"][0]["price_tick"] == 0.5
    assert metadata["legs"][0]["margin"]["short_margin_ratio_by_money"] == 0.1
    assert metadata["legs"][1]["option_premium"] == 101.0
    assert metadata["legs"][1]["option_trade_cost"]["Royalty"] == 1.0
    assert snapshot["prices"] == {"0": 3400.0, "1": 101.0, "2": 99.0}
    assert snapshot["legs"][1]["bid_price"] == 100.0
    assert snapshot["legs"][1]["ask_price"] == 101.0
    assert snapshot["legs"][1]["bid_volume"] == 10.0
    assert snapshot["legs"][1]["entry_buy_price"] == 101.0
    assert snapshot["legs"][1]["exit_sell_price"] == 100.0
    cost_requests = [
        request for request in client.reference_requests if request["name"] == "option_trade_cost"
    ]
    assert len(cost_requests) == 4
    extra_cost_requests = cost_requests[-2:]
    assert {(request["input_price"], request["underlying_price"]) for request in extra_cost_requests} == {
        (101.0, 3400.0),
        (99.0, 3400.0),
    }
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )


@pytest.mark.parametrize("quote_change", [
    {"LastPrice": 0.0},
    {"LastPrice": float("nan")},
    {"LastPrice": float("inf")},
    {"LastPrice": 1.7976931348623157e308},
    {"BidPrice1": None, "AskPrice1": None},
    {"BidPrice1": 100.0},
    {"BidPrice1": 100.0, "AskPrice1": 101.0, "BidVolume1": 0, "AskVolume1": 10},
])
def test_ctp_bundle_execution_reference_rejects_unsafe_depth_quote(quote_change):
    client = ExecutionReferenceBundleClient()
    client.rows["depth_market_data"][1].clear()
    client.rows["depth_market_data"][1].update(
        {"InstrumentID": "m2701-C-3400", "ExchangeID": "DCE", **quote_change}
    )
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_bundle_execution_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert any("price_required" in error or "volume_positive_required" in error for error in snapshot["evidence_errors"])
    assert snapshot["execution_eligible"] is False


def test_ctp_bundle_execution_reference_rejects_foreign_or_duplicate_depth_identity():
    client = ExecutionReferenceBundleClient()
    client.rows["depth_market_data"][1]["InstrumentID"] = "m2701-P-3400"
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_bundle_execution_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert any("record_not_exactly_one" in error or "instrument_identity_mismatch" in error for error in snapshot["evidence_errors"])


def test_ctp_bundle_execution_reference_rejects_query_identity_generation_shift():
    client = ExecutionReferenceBundleClient()
    client.generation_override["depth_market_data"] = 99
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_bundle_execution_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert any("connection_generation_mismatch" in error for error in snapshot["evidence_errors"])


def test_ctp_bundle_execution_reference_rejects_zero_option_cost_input_path():
    client = ExecutionReferenceBundleClient()
    original = client.query_option_instrument_trade_cost_result
    seen = []

    def capture(*args, **kwargs):
        seen.append((kwargs.get("input_price"), kwargs.get("underlying_price")))
        return original(*args, **kwargs)

    client.query_option_instrument_trade_cost_result = capture
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    snapshot = store.get_ctp_bundle_execution_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True
    assert all(price > 0 and underlying > 0 for price, underlying in seen[-2:])


def test_ctp_bundle_execution_reference_rejects_incomplete_broker_contract_metadata():
    client = ExecutionReferenceBundleClient()
    del client.rows["margin_rate"][0]["ShortMarginRatioByMoney"]
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_bundle_execution_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert snapshot["broker_contract_metadata_complete"] is False
    assert snapshot["broker_contract_metadata"] is None
    assert any("margin_short_by_money" in error for error in snapshot["evidence_errors"])


def _frozen_quote_reference_store():
    client = ExecutionReferenceBundleClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    frozen = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)
    assert frozen["evidence_complete"] is True
    client.reference_requests.clear()
    client.depth_requests.clear()
    return client, store, dict(client.request_counts)


def test_ctp_bundle_quote_reference_requires_frozen_bundle_without_queries():
    client = ExecutionReferenceBundleClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)
    before_counts = dict(client.request_counts)

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["schema_version"] == "backtrader.ctp.bundle-quote-reference.v1"
    assert snapshot["evidence_complete"] is False
    assert snapshot["read_only_safe"] is False
    assert "bundle_quote_preflight_snapshot_missing" in snapshot["evidence_errors"]
    assert client.depth_requests == []
    assert client.reference_requests == []
    assert client.request_counts == before_counts


def test_ctp_bundle_quote_reference_uses_only_depth_against_frozen_scope():
    client, store, before_counts = _frozen_quote_reference_store()

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["schema_version"] == "backtrader.ctp.bundle-quote-reference.v1"
    assert snapshot["evidence_complete"] is True
    assert snapshot["read_only_safe"] is True
    assert snapshot["bundle_preflight"]["schema_version"] == "backtrader.ctp.bundle-preflight.v2"
    assert [request["name"] for request in client.reference_requests] == [
        "depth_market_data",
        "depth_market_data",
        "depth_market_data",
    ]
    assert client.depth_requests == [
        {"instrument_id": "m2701", "exchange_id": "DCE"},
        {"instrument_id": "m2701-C-3400", "exchange_id": "DCE"},
        {"instrument_id": "m2701-P-3400", "exchange_id": "DCE"},
    ]
    assert all(
        client.request_counts[name] == before_counts.get(name, 0)
        for name in ("account", "positions", "orders", "trades")
    )
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )
    assert snapshot["legs"][1]["bid_price"] == 100.0
    assert snapshot["legs"][1]["ask_price"] == 101.0
    assert snapshot["legs"][1]["bid_volume"] == 10.0
    assert snapshot["legs"][1]["ask_volume"] == 10.0
    assert snapshot["legs"][1]["entry_buy_price"] == 101.0
    assert snapshot["legs"][1]["exit_sell_price"] == 100.0
    assert all(leg["request_id"] > 0 for leg in snapshot["legs"])
    assert all(leg["requested_at_utc"] for leg in snapshot["legs"])
    assert all(leg["received_at_utc"] for leg in snapshot["legs"])
    assert all(leg["requested_monotonic"] <= leg["received_monotonic"] for leg in snapshot["legs"])


def test_ctp_bundle_quote_reference_rejects_current_generation_drift_without_depth_query():
    client, store, _before_counts = _frozen_quote_reference_store()
    client.session_generation += 1

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "bundle_quote_current_generation_mismatch" in snapshot["evidence_errors"]
    assert client.depth_requests == []


@pytest.mark.parametrize(
    "field, value, expected_error",
    [
        ("session_fingerprint", "different-account", "bundle_quote_current_account_fingerprint_mismatch"),
        ("trading_day", "20260910", "bundle_quote_current_trading_day_mismatch"),
    ],
)
def test_ctp_bundle_quote_reference_rejects_current_identity_drift_without_depth_query(
    field, value, expected_error
):
    client, store, _before_counts = _frozen_quote_reference_store()
    setattr(client, field, value)

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]
    assert client.depth_requests == []


@pytest.mark.parametrize("field, value", [("evidence_complete", False), ("read_only_safe", False)])
def test_ctp_bundle_quote_reference_rejects_degraded_frozen_preflight_without_query(field, value):
    client, store, _before_counts = _frozen_quote_reference_store()
    store._last_ctp_bundle_preflight_snapshot[field] = value

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "bundle_quote_preflight_snapshot_invalid" in snapshot["evidence_errors"]
    assert client.depth_requests == []


def test_ctp_bundle_quote_reference_rejects_requested_leg_scope_drift_without_query():
    client, store, _before_counts = _frozen_quote_reference_store()
    mismatched_legs = [
        {"exchange_id": "DCE", "instrument_id": "m2701", "is_primary": True},
        {"exchange_id": "DCE", "instrument_id": "m2701-C-3500"},
        {"exchange_id": "DCE", "instrument_id": "m2701-P-3400"},
    ]

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(mismatched_legs, timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "bundle_quote_requested_legs_mismatch" in snapshot["evidence_errors"]
    assert client.depth_requests == []


@pytest.mark.parametrize(
    "change, expected_error",
    [
        ({"InstrumentID": "m2701-P-3400"}, "record_not_exactly_one"),
        ({"AskPrice1": None}, "ask_price_required"),
    ],
)
def test_ctp_bundle_quote_reference_rejects_foreign_or_incomplete_depth_quote(change, expected_error):
    client, store, _before_counts = _frozen_quote_reference_store()
    client.rows["depth_market_data"][1].update(change)

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert any(expected_error in error for error in snapshot["evidence_errors"])
    assert snapshot["legs"][1]["entry_buy_price"] is None
    assert snapshot["legs"][1]["exit_sell_price"] is None


def test_ctp_bundle_quote_reference_rejects_depth_timeout_without_other_queries():
    client, store, before_counts = _frozen_quote_reference_store()
    client.incomplete.add("depth_market_data")

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert any("depth_market_data_query_incomplete" in error for error in snapshot["evidence_errors"])
    assert [request["name"] for request in client.reference_requests] == [
        "depth_market_data",
        "depth_market_data",
        "depth_market_data",
    ]
    assert all(
        client.request_counts[name] == before_counts.get(name, 0)
        for name in ("account", "positions", "orders", "trades")
    )
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )


def test_ctp_bundle_quote_reference_rejects_duplicate_depth_request_ids():
    client, store, _before_counts = _frozen_quote_reference_store()
    client.request_id_override["depth_market_data"] = 700

    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "bundle_quote_request_id_not_unique" in snapshot["evidence_errors"]
    assert len(client.depth_requests) == 3


def test_ctp_bundle_quote_reference_rejects_write_counter_change_during_depth_query():
    client, store, _before_counts = _frozen_quote_reference_store()
    original = client.query_depth_market_data_result

    def depth_with_unexpected_write(*args, **kwargs):
        client.request_counts["order_insert"] += 1
        return original(*args, **kwargs)

    client.query_depth_market_data_result = depth_with_unexpected_write
    snapshot = store.get_ctp_bundle_quote_reference_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert snapshot["write_request_free"] is False
    assert "bundle_quote_write_request_evidence_invalid" in snapshot["evidence_errors"]
    assert len(client.depth_requests) == 3


def test_ctp_bundle_preflight_ignores_unrelated_prefix_rows_but_requires_exact_target():
    client = PrefixInstrumentBundleClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True
    assert all(leg["evidence_complete"] for leg in snapshot["legs"])
    assert not any("identity_mismatch" in error for error in snapshot["evidence_errors"])


def test_ctp_bundle_preflight_rejects_duplicate_exact_prefix_match():
    client = PrefixInstrumentBundleClient()
    duplicate = dict(_bundle_evidence_row(client, "instruments", "m2701-C-3400"))
    client.rows["instruments"].append(duplicate)
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "leg[1].instrument_record_ambiguous" in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_rejects_missing_exact_prefix_target():
    client = PrefixInstrumentBundleClient()
    client.rows["instruments"] = [
        row
        for row in client.rows["instruments"]
        if row["InstrumentID"] != "m2701-C-3400"
    ]
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "leg[1].instrument_record_missing" in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_allows_empty_generic_option_fee_rows():
    client, store = _dce_bundle_store()
    client.rows["margin_rate"] = [
        row for row in client.rows["margin_rate"] if row["InstrumentID"] == "m2701"
    ]
    client.rows["commission_rate"] = [
        row for row in client.rows["commission_rate"] if row["InstrumentID"] == "m2701"
    ]

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True
    assert snapshot["legs"][1]["margin_rate"] is None
    assert snapshot["legs"][1]["commission_rate"] is None
    assert snapshot["legs"][1]["option_trade_cost"] is not None
    assert snapshot["legs"][1]["option_commission_rate"] is not None


def test_ctp_bundle_preflight_requires_future_generic_fee_rows():
    client, store = _dce_bundle_store()
    client.rows["margin_rate"] = []
    client.rows["commission_rate"] = []

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "leg[0].margin_rate_record_missing" in snapshot["evidence_errors"]
    assert "leg[0].commission_rate_record_missing" in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_supports_a_two_leg_future_option_scope():
    client, store = _dce_bundle_store()

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs()[:2], timeout=0)

    assert snapshot["evidence_complete"] is True
    assert len(snapshot["legs"]) == 2
    assert snapshot["primary_leg"] == {"exchange_id": "DCE", "instrument_id": "m2701"}
    assert [leg["metadata"]["asset_type"] for leg in snapshot["legs"]] == [
        "future",
        "option",
    ]


def test_ctp_bundle_preflight_allows_a_future_delivery_expiry_distinct_from_option_expiry():
    client, store = _dce_bundle_store()
    future = _bundle_evidence_row(client, "instruments", "m2701")
    future["ExpireDate"] = "20270307"

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True
    assert snapshot["legs"][0]["metadata"]["expiry_date"] == "20270307"
    assert [leg["metadata"]["expiry_date"] for leg in snapshot["legs"][1:]] == [
        "20261207",
        "20261207",
    ]


def test_ctp_bundle_preflight_requires_call_and_put_option_expiries_to_match():
    client, store = _dce_bundle_store()
    put = _bundle_evidence_row(client, "instruments", "m2701-P-3400")
    put["ExpireDate"] = "20261208"

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "bundle_call_put_expiry_mismatch" in snapshot["evidence_errors"]


@pytest.mark.parametrize(
    "legs,match",
    [
        (
            [
                {"exchange_id": "DCE", "instrument_id": "m2701"},
                {"exchange_id": "DCE", "instrument_id": "m2701-C-3400"},
            ],
            "requires exactly one primary",
        ),
        (
            [
                {"exchange_id": "DCE", "instrument_id": "m2701", "is_primary": True},
                {"exchange_id": "DCE", "instrument_id": "m2701"},
            ],
            "duplicate raw leg",
        ),
        (
            [
                {"exchange_id": "DCE", "instrument_id": "m2701", "is_primary": True},
                {"exchange_id": "CZCE", "instrument_id": "SA701C1080"},
            ],
            "one exact exchange_id",
        ),
        (
            [
                {"exchange_id": " DCE", "instrument_id": "m2701", "is_primary": True},
                {"exchange_id": " DCE", "instrument_id": "m2701-C-3400"},
            ],
            "non-empty exact text",
        ),
        (
            [
                {"exchange_id": "DCE", "instrument_id": "DCE.m2701", "is_primary": True},
                {"exchange_id": "DCE", "instrument_id": "m2701-C-3400"},
            ],
            "raw unqualified",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_invalid_raw_scope_before_any_query(legs, match):
    client, store = _dce_bundle_store()

    with pytest.raises(BtApiStoreError, match=match):
        store.get_ctp_bundle_preflight_snapshot(legs, timeout=0)

    assert client.public_queries == []
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )


def test_ctp_bundle_preflight_accepts_raw_pairs_when_primary_selector_is_exact():
    client, store = _dce_bundle_store()

    snapshot = store.get_ctp_bundle_preflight_snapshot(
        [("DCE", "m2701"), ("DCE", "m2701-C-3400")],
        primary_leg=("DCE", "m2701"),
        timeout=0,
    )

    assert snapshot["evidence_complete"] is True
    assert snapshot["primary_leg"] == {"exchange_id": "DCE", "instrument_id": "m2701"}
    assert [leg["instrument_id"] for leg in snapshot["legs"]] == ["m2701", "m2701-C-3400"]


def test_ctp_bundle_preflight_fails_closed_when_option_metadata_is_missing():
    client, store = _dce_bundle_store()
    call = next(row for row in client.rows["instruments"] if row["InstrumentID"] == "m2701-C-3400")
    del call["UnderlyingInstrID"]

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "leg[1].option_underlying_missing" in snapshot["evidence_errors"]
    assert "bundle_option_underlying_mismatch" in snapshot["evidence_errors"]
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )


def test_ctp_bundle_preflight_fails_closed_on_incomplete_option_reference_query():
    client, store = _dce_bundle_store()
    client.incomplete.add("option_trade_cost")

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "leg[1].option_trade_cost_query_incomplete" in snapshot["evidence_errors"]
    assert "leg[2].option_trade_cost_query_incomplete" in snapshot["evidence_errors"]
    assert snapshot["legs"][1]["option_trade_cost"] is None
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )


def test_ctp_query_result_retains_swig_like_option_reference_fields():
    class SwigLikeOptionRecord:
        InstrumentID = "m2701-C-3400"
        ExchangeID = "DCE"
        ProductClass = "2"
        OptionsType = "1"
        UnderlyingInstrID = "m2701"
        StrikePrice = 3400.0
        FixedMargin = 100.0
        MiniMargin = 20.0
        Royalty = 1.0
        ExchFixedMargin = 50.0
        ExchMiniMargin = 10.0
        OpenRatioByMoney = 0.0002
        CloseRatioByMoney = 0.0002
        CloseTodayRatioByMoney = 0.0002

    result = BtApiStore._normalise_ctp_query_result(
        {
            "request_type": "option_trade_cost",
            "records": [SwigLikeOptionRecord()],
        },
        "option_trade_cost",
    )

    assert result["records"] == [
        {
            "InstrumentID": "m2701-C-3400",
            "ExchangeID": "DCE",
            "ProductClass": "2",
            "OptionsType": "1",
            "UnderlyingInstrID": "m2701",
            "StrikePrice": 3400.0,
            "FixedMargin": 100.0,
            "MiniMargin": 20.0,
            "Royalty": 1.0,
            "ExchFixedMargin": 50.0,
            "ExchMiniMargin": 10.0,
            "OpenRatioByMoney": 0.0002,
            "CloseRatioByMoney": 0.0002,
            "CloseTodayRatioByMoney": 0.0002,
        }
    ]


_BUNDLE_DELETE_FIELD = object()


def _bundle_evidence_row(client, table, instrument_id=None):
    rows = client.rows[table]
    if instrument_id is None:
        assert len(rows) == 1
        return rows[0]
    return next(row for row in rows if row["InstrumentID"] == instrument_id)


@pytest.mark.parametrize(
    "table,instrument_id,field,value,expected_error",
    [
        ("account", None, "Balance", float("nan"), "account_balance_missing_or_invalid"),
        (
            "instruments",
            "m2701",
            "PriceTick",
            0.0,
            "leg[0].instrument_price_tick_missing_or_invalid",
        ),
        (
            "instruments",
            "m2701-C-3400",
            "VolumeMultiple",
            True,
            "leg[1].instrument_volume_multiple_missing_or_invalid",
        ),
        (
            "instruments",
            "m2701-P-3400",
            "MinLimitOrderVolume",
            _BUNDLE_DELETE_FIELD,
            "leg[2].instrument_minimum_order_volume_missing_or_invalid",
        ),
        (
            "margin_rate",
            "m2701",
            "ShortMarginRatioByMoney",
            float("inf"),
            "leg[0].margin_rate_margin_short_by_money_missing_or_invalid",
        ),
        (
            "commission_rate",
            "m2701",
            "CloseTodayRatioByMoney",
            None,
            "leg[0].commission_rate_commission_close_today_by_money_missing_or_invalid",
        ),
        (
            "option_trade_cost",
            "m2701-C-3400",
            "Royalty",
            float("nan"),
            "leg[1].option_trade_cost_option_trade_cost_royalty_missing_or_invalid",
        ),
        (
            "option_commission_rate",
            "m2701-C-3400",
            "CloseRatioByMoney",
            True,
            "leg[1].option_commission_rate_commission_close_by_money_missing_or_invalid",
        ),
        (
            "option_trade_cost",
            "m2701-P-3400",
            "MiniMargin",
            _BUNDLE_DELETE_FIELD,
            "leg[2].option_trade_cost_option_trade_cost_minimargin_missing_or_invalid",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_incomplete_or_invalid_numeric_evidence(
    table, instrument_id, field, value, expected_error
):
    client, store = _dce_bundle_store()
    row = _bundle_evidence_row(client, table, instrument_id)
    if value is _BUNDLE_DELETE_FIELD:
        del row[field]
    else:
        row[field] = value

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


@pytest.mark.parametrize(
    "table,instrument_id,field,value,expected_error",
    [
        (
            "instruments",
            "m2701",
            "price_tick",
            0.25,
            "leg[0].instrument_price_tick_alias_mismatch",
        ),
        (
            "instruments",
            "m2701",
            "volume_multiple",
            20,
            "leg[0].instrument_volume_multiple_alias_mismatch",
        ),
        (
            "instruments",
            "m2701",
            "minimum_order_volume",
            2,
            "leg[0].instrument_minimum_order_volume_alias_mismatch",
        ),
        (
            "instruments",
            "m2701-C-3400",
            "strike_price",
            3500.0,
            "leg[1].option_strike_alias_mismatch",
        ),
        (
            "margin_rate",
            "m2701",
            "long_margin_ratio_by_money",
            0.2,
            "leg[0].margin_rate_margin_long_by_money_alias_mismatch",
        ),
        (
            "commission_rate",
            "m2701",
            "open_ratio_by_money",
            0.0002,
            "leg[0].commission_rate_commission_open_by_money_alias_mismatch",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_conflicting_finite_numeric_aliases(
    table, instrument_id, field, value, expected_error
):
    client, store = _dce_bundle_store()
    _bundle_evidence_row(client, table, instrument_id)[field] = value

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


@pytest.mark.parametrize("money,volume", [(0.0, 3.0), (0.0001, 3.0)])
def test_ctp_bundle_preflight_accepts_distinct_money_and_volume_cost_units(money, volume):
    client, store = _dce_bundle_store()
    margin = _bundle_evidence_row(client, "margin_rate", "m2701")
    margin["LongMarginRatioByMoney"] = money
    margin["LongMarginRatioByVolume"] = volume
    commission = _bundle_evidence_row(client, "commission_rate", "m2701")
    commission["OpenRatioByMoney"] = money
    commission["OpenRatioByVolume"] = volume

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True


@pytest.mark.parametrize(
    "table,instrument_id,field,expected_error",
    [
        (
            "margin_rate",
            "m2701",
            "LongMarginRatioByVolume",
            "leg[0].margin_rate_margin_long_by_volume_missing_or_invalid",
        ),
        (
            "commission_rate",
            "m2701",
            "OpenRatioByVolume",
            "leg[0].commission_rate_commission_open_by_volume_missing_or_invalid",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_missing_independent_cost_unit(
    table, instrument_id, field, expected_error
):
    client, store = _dce_bundle_store()
    del _bundle_evidence_row(client, table, instrument_id)[field]

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_accepts_explicit_zero_cost_and_account_values():
    client, store = _dce_bundle_store()
    client.rows["account"] = [{"Balance": 0.0, "Available": 0.0}]
    for row in client.rows["margin_rate"]:
        row["LongMarginRatioByMoney"] = 0.0
        row["ShortMarginRatioByMoney"] = 0.0
    for table in ("commission_rate", "option_commission_rate"):
        for row in client.rows[table]:
            row["OpenRatioByMoney"] = 0.0
            row["CloseRatioByMoney"] = 0.0
            row["CloseTodayRatioByMoney"] = 0.0
    for row in client.rows["option_trade_cost"]:
        for field in ("FixedMargin", "MiniMargin", "Royalty", "ExchFixedMargin", "ExchMiniMargin"):
            row[field] = 0.0

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True


def test_ctp_bundle_preflight_requires_one_usable_account_record():
    client, store = _dce_bundle_store()
    client.rows["account"].append({"Balance": 100000.0, "Available": 90000.0})

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "account_record_not_unique" in snapshot["evidence_errors"]


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        (
            "instrument_id",
            "m2701-C-3400-alias-conflict",
            "leg[1].instrument_response_instrument_alias_mismatch",
        ),
        (
            "exchange_id",
            "CZCE",
            "leg[1].instrument_response_exchange_alias_mismatch",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_conflicting_identity_aliases(field, value, expected_error):
    client, store = _dce_bundle_store()
    call = _bundle_evidence_row(client, "instruments", "m2701-C-3400")
    call[field] = value

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_accepts_semantically_equivalent_contract_aliases():
    client, store = _dce_bundle_store()
    future = _bundle_evidence_row(client, "instruments", "m2701")
    future.update(
        {
            "asset_type": "futures",
            "contract_type": "future",
            "product_class": 1,
        }
    )
    for instrument_id, option_type, short_option_type in (
        ("m2701-C-3400", "call", "c"),
        ("m2701-P-3400", "put", "p"),
    ):
        option = _bundle_evidence_row(client, "instruments", instrument_id)
        option.update(
            {
                "asset_type": "option",
                "contract_type": "options",
                "product_class": 2,
                "option_type": option_type,
                "options_type": short_option_type,
                "underlying_instrument": "m2701",
                "underlying_instr_id": "m2701",
            }
        )

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True
    assert [leg["metadata"]["asset_type"] for leg in snapshot["legs"]] == [
        "future",
        "option",
        "option",
    ]
    assert [leg["metadata"]["option_type"] for leg in snapshot["legs"][1:]] == [
        "call",
        "put",
    ]
    assert all(leg["metadata"]["asset_type_alias_error"] == "" for leg in snapshot["legs"])
    assert all(
        leg["metadata"]["option_type_alias_error"] == ""
        and leg["metadata"]["underlying_alias_error"] == ""
        for leg in snapshot["legs"][1:]
    )


@pytest.mark.parametrize(
    "instrument_id,field,value,expected_error",
    [
        (
            "m2701",
            "asset_type",
            "option",
            "leg[0].instrument_asset_type_alias_mismatch",
        ),
        (
            "m2701",
            "contract_type",
            "option",
            "leg[0].instrument_asset_type_alias_mismatch",
        ),
        (
            "m2701-C-3400",
            "product_class",
            "1",
            "leg[1].instrument_asset_type_alias_mismatch",
        ),
        (
            "m2701-C-3400",
            "asset_type",
            "unknown-contract-kind",
            "leg[1].instrument_asset_type_alias_invalid",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_conflicting_or_invalid_asset_type_aliases(
    instrument_id, field, value, expected_error
):
    client, store = _dce_bundle_store()
    _bundle_evidence_row(client, "instruments", instrument_id)[field] = value

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        ("option_type", "put", "leg[1].option_type_alias_mismatch"),
        ("options_type", "put", "leg[1].option_type_alias_mismatch"),
        ("option_type", "invalid-option-kind", "leg[1].option_type_alias_invalid"),
        (
            "underlying_instrument",
            "m2701-other",
            "leg[1].option_underlying_alias_mismatch",
        ),
        (
            "underlying_instr_id",
            "m2701-other",
            "leg[1].option_underlying_alias_mismatch",
        ),
    ],
)
def test_ctp_bundle_preflight_rejects_conflicting_or_invalid_option_identity_aliases(
    field, value, expected_error
):
    client, store = _dce_bundle_store()
    _bundle_evidence_row(client, "instruments", "m2701-C-3400")[field] = value

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_compares_underlying_as_the_raw_wire_identifier():
    client, store = _dce_bundle_store()
    call = _bundle_evidence_row(client, "instruments", "m2701-C-3400")
    call["UnderlyingInstrID"] = "m2701 "

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["legs"][1]["metadata"]["underlying_instrument_id"] == "m2701 "
    assert snapshot["evidence_complete"] is False
    assert "bundle_option_underlying_mismatch" in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_rejects_a_write_performed_during_lazy_connect():
    class ConnectWritesBundleQueryClient(BundleQueryClient):
        def connect(self):
            super().connect()
            self.request_counts["order_insert"] += 1

    client = ConnectWritesBundleQueryClient()
    store = make_store(api=client, provider="btapi", exchange_kwargs=client.exchange_kwargs)

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert snapshot["write_request_free"] is False
    assert snapshot["connect_request_count_delta"]["order_insert"] == 1
    assert "unexpected_write_request_during_connect" in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_rejects_when_the_preconnect_counter_baseline_is_unavailable():
    class MissingPreconnectCounterBundleQueryClient(BundleQueryClient):
        def __init__(self):
            super().__init__()
            self._ctp_state_reads = 0

        def get_ctp_session_state(self, exchange_name="CTP___FUTURE"):
            state = super().get_ctp_session_state(exchange_name=exchange_name)
            self._ctp_state_reads += 1
            if self._ctp_state_reads == 1:
                state.pop("request_counts")
            return state

    client = MissingPreconnectCounterBundleQueryClient()
    store = make_store(api=client, provider="btapi", exchange_kwargs=client.exchange_kwargs)

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert snapshot["write_request_free"] is False
    assert "preconnect_request_count_evidence_missing" in snapshot["evidence_errors"]
    assert "connect_request_count_evidence_missing" in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_requires_completion_not_earlier_than_the_request():
    client, store = _dce_bundle_store()
    client.completed_at_override["margin_rate"] = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)
    ).isoformat()

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert "leg[0].margin_rate_completed_before_request_sent" in snapshot["evidence_errors"]


@pytest.mark.parametrize(
    "configure,expected_error",
    [
        (
            lambda client: client.generation_override.update({"margin_rate": 4}),
            "query_generation_mismatch",
        ),
        (
            lambda client: client.session_fingerprint_sequence.extend(
                [
                    "0123456789abcdef",
                    "0123456789abcdef",
                    "other-account-fingerprint",
                ]
            ),
            "session_account_fingerprint_changed",
        ),
        (
            lambda client: client.session_trading_day_sequence.extend(
                ["20260909", "20260909", "20260910"]
            ),
            "session_trading_day_changed",
        ),
    ],
)
def test_ctp_bundle_preflight_fails_closed_on_session_or_query_identity_change(
    configure, expected_error
):
    client, store = _dce_bundle_store()
    configure(client)

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]
    assert all(
        client.request_counts[name] == 0
        for name in ("settlement_confirm", "order_insert", "order_action")
    )


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
    assert client.disarm_reasons == []


def test_ctp_store_stop_disarms_after_an_actual_sdk_arm_attempt():
    client, store, proof, _grant, _configured = _authorized_store()

    store.arm_sdk_execution(proof)

    assert store._ctp_sdk_arm_attempted is True
    store.stop()
    assert client.disarm_reasons == ["store_stop"]
    assert store._ctp_sdk_arm_attempted is False


def test_ctp_store_stop_disarms_after_an_actual_recovery_arm_attempt():
    client, store, proof, _grant, _configured = _authorized_store()
    client.recovery_report = _recovery_report()
    plan = store.prepare_execution_recovery(proof)

    store.arm_execution_recovery(proof, recovery_token_sha256=plan["recovery_token_sha256"])

    assert store._ctp_sdk_arm_attempted is True
    store.stop()
    assert client.disarm_reasons == ["store_stop"]
    assert store._ctp_sdk_arm_attempted is False


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
    assert client.disarm_reasons == ["execution_arm_post_commit_failure"]
    assert store._ctp_sdk_arm_attempted is False


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


def test_preflight_product_scan_is_complete_evidence_without_fee_placeholders():
    """A product-scoped Stage A must stay complete evidence.

    The Iter23/24/25 three-leg launcher consumes the product-scoped Stage A
    snapshot through its strict gate, which requires ``evidence_complete``.
    Per-instrument margin/commission queries are Stage B evidence: a product
    scan has no single instrument, so those queries are out of scope rather
    than failed placeholders poisoning the product-scan evidence.
    """
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    snapshot = store.get_ctp_preflight_snapshot(product_id="SA", exchange_id="CZCE", timeout=0)

    assert snapshot["evidence_complete"] is True
    assert snapshot["evidence_errors"] == []
    assert "margin_rate" not in snapshot["query_results"]
    assert "commission_rate" not in snapshot["query_results"]
    assert snapshot["instruments"]
    assert "margin_rate" not in client.public_queries
    assert "commission_rate" not in client.public_queries


def test_preflight_product_filter_is_forwarded_to_the_managed_ctp_facade():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
    )

    snapshot = store.get_ctp_preflight_snapshot(product_id="sa", exchange_id="czce", timeout=0)

    assert snapshot["query_results"]["instruments"]["complete"] is True
    instrument_index = client.public_queries.index("instruments")
    assert client.public_query_kwargs[instrument_index]["product_id"] == "SA"
    assert client.public_query_kwargs[instrument_index]["exchange_id"] == "CZCE"
    trades_index = client.public_queries.index("trades")
    assert client.public_query_kwargs[trades_index]["exchange_id"] == "CZCE"
    assert snapshot["query_results"]["trades"]["requested_scope"] == {
        "instrument_id": "",
        "exchange_id": "CZCE",
        "trading_day": "20260909",
    }


def test_preflight_scopes_stage_b_trades_to_the_frozen_instrument():
    client = ManagedBtApiClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        symbol_routes={"CZCE.SA609": "CTP___FUTURE"},
    )

    snapshot = store.get_ctp_preflight_snapshot("CZCE.SA609", timeout=0)

    trades_index = client.public_queries.index("trades")
    assert client.public_query_kwargs[trades_index]["instrument_id"] == "SA609"
    assert client.public_query_kwargs[trades_index]["exchange_id"] == "CZCE"
    assert snapshot["query_results"]["trades"]["requested_scope"] == {
        "instrument_id": "SA609",
        "exchange_id": "CZCE",
        "trading_day": "20260909",
    }
    assert snapshot["query_results"]["trades"]["scope_valid"] is True


def test_preflight_keeps_legacy_direct_instrument_query_compatible_without_product_filter():
    client = LegacyInstrumentSignatureClient()
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    stage_b = store.get_ctp_preflight_snapshot("CZCE.SA609", timeout=0)

    assert stage_b["evidence_complete"] is True
    assert client.instrument_filters == [
        {"instrument_id": "SA609", "exchange_id": "CZCE", "timeout": 0.0}
    ]

    stage_a = store.get_ctp_preflight_snapshot(
        product_id="SA",
        exchange_id="CZCE",
        timeout=0,
    )

    assert stage_a["evidence_complete"] is False
    assert stage_a["query_results"]["instruments"]["error_code"] == "TypeError"
    assert len(client.instrument_filters) == 1


def test_preflight_rejects_trade_rows_outside_the_requested_scope():
    client = CompleteQueryClient()
    client.rows["trades"] = [
        {"ExchangeID": "SHFE", "InstrumentID": "RB701", "TradingDay": "20260908"}
    ]
    store = make_store(api=client, provider="ctp_gateway", auto_settlement_confirm=False)

    snapshot = store.get_ctp_preflight_snapshot("CZCE.SA609", timeout=0)

    trades = snapshot["query_results"]["trades"]
    assert trades["complete"] is False
    assert trades["scope_valid"] is False
    assert trades["error_code"] == "trade_scope_validation_failed"
    assert set(trades["scope_validation_errors"]) == {
        "trades_response_exchange_scope_mismatch",
        "trades_response_instrument_scope_mismatch",
        "trades_response_trading_day_scope_mismatch",
    }
    assert snapshot["evidence_complete"] is False
    assert "trades_response_exchange_scope_mismatch" in snapshot["evidence_errors"]


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


def test_ctp_quote_v2_sdk_tick_keeps_parent_attestation_evidence_on_native_tick():
    """The Store must not strip evidence consumed by the public cohort gate."""

    symbol = "SA701C1080"
    venue = "CTP___FUTURE"

    class QuoteSdk:
        exchange_kwargs = {venue: {}}

        def __init__(self):
            self.events = [
                {
                    "kind": "tick",
                    "timestamp": 1_789_000_000.0,
                    "local_time": 1_789_000_000.001,
                    "received_wall_time": 1_789_000_000.001,
                    "received_monotonic_ns": 123_456_789,
                    "clock_domain_id": "parent-md-domain",
                    "symbol": symbol,
                    "exchange": "CZCE",
                    "asset_type": "option",
                    "source": "ctp.parent-attested",
                    "price": 42.0,
                    "volume": 1.0,
                    "delta_volume": 1.0,
                    "direction": "buy",
                    "bid_price": 41.0,
                    "ask_price": 42.0,
                    "bid_volume": 2.0,
                    "ask_volume": 3.0,
                    "schema_version": "ctp.quote.v2",
                    "volume_semantics": "delta",
                    "cum_volume": 101.0,
                    "cumulative_volume": 101.0,
                    "volume_complete": True,
                    "volume_quality": "CONTINUOUS",
                    "continuity_status": "continuous",
                    "trading_day": "20260910",
                    "action_day": "20260909",
                    "event_time_utc": "2026-09-10T01:00:00+00:00",
                    "recv_time_utc": "2026-09-10T01:00:00.001+00:00",
                    "recv_monotonic_ns": 123_456_789,
                    "connection_generation": 4,
                    "ingest_seq": 9,
                    "subscription_epoch": 7,
                    "rules_hash": "rules-v2",
                    "event_time_source": "action_day",
                    "source_clock_quality": "verified",
                    "receive_clock_quality": "verified",
                    "source_clock_error_ms": 1.0,
                    "receive_clock_error_ms": 1.0,
                    "freshness_verified": True,
                    "execution_eligible": False,
                    "cohort_now_monotonic_ns": 123_456_999,
                    "cohort_now_epoch": 12,
                    "cohort_now_clock_domain_id": "parent-md-domain",
                    "cohort_now_receive_clock_error_ms": 0.25,
                    "cohort_now_receive_clock_quality": "verified",
                    "cohort_now_freshness_verified": True,
                    # These originate at feed dispatch and must never be
                    # copied from an SDK market event by the Store.
                    "cohort_decision_now_monotonic_ns": 1,
                    "cohort_decision_now_epoch": 1,
                    "cohort_decision_now_clock_domain_id": "forged-domain",
                    "lower_limit_price": 1.0,
                    "upper_limit_price": 100.0,
                }
            ]

        def poll_event(self, _venue):
            return None

        def poll_events(self, _venue, *, max_raw_items, coalesce_market_snapshots):
            del max_raw_items, coalesce_market_snapshots
            events, self.events = self.events, []
            return events

    sdk = QuoteSdk()
    store = make_store(
        api=sdk,
        provider="btapi",
        exchange_kwargs=sdk.exchange_kwargs,
        symbol_routes={symbol: venue},
    )
    store._connected = True
    store._subscribed_datanames.add(symbol)

    tick = store.poll_tick(symbol)

    assert tick is not None
    assert tick.asset_type == "option"
    assert tick.source == "ctp.parent-attested"
    assert tick.subscription_epoch == 7
    assert tick.rules_hash == "rules-v2"
    assert tick.source_clock_quality == "verified"
    assert tick.receive_clock_quality == "verified"
    assert tick.source_clock_error_ms == 1.0
    assert tick.receive_clock_error_ms == 1.0
    assert tick.freshness_verified is True
    assert tick.execution_eligible is False
    assert tick.cohort_now_monotonic_ns == 123_456_999
    assert tick.cohort_now_epoch == 12
    assert tick.cohort_now_clock_domain_id == "parent-md-domain"
    assert tick.cohort_now_receive_clock_error_ms == 0.25
    assert tick.cohort_now_receive_clock_quality == "verified"
    assert tick.cohort_now_freshness_verified is True
    assert not hasattr(tick, "cohort_decision_now_monotonic_ns")
    assert not hasattr(tick, "cohort_decision_now_epoch")
    assert not hasattr(tick, "cohort_decision_now_clock_domain_id")


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


def test_native_ctp_wrapper_defaults_to_read_only_and_rejects_implicit_settlement_write():
    """A direct wrapper cannot connect with the legacy auto-write switch enabled."""

    pytest.importorskip("bt_api_ctp.ctp.client")
    wrapper_cls = _create_ctp_wrapper_class()

    default_client = wrapper_cls()
    assert default_client.auto_settlement_confirm is False

    unsafe_client = wrapper_cls(auto_settlement_confirm=True)
    with pytest.raises(BtApiStoreError, match="not permitted"):
        unsafe_client.connect()


def _bundle_authorized_store(client=None):
    """Build a signed V2 grant from one fresh Stage A/B and bundle snapshot."""
    client = client or BundleQueryClient()
    store = make_store(
        api=client,
        provider="btapi",
        exchange_kwargs=client.exchange_kwargs,
        execution_config={
            "market_data_only": True,
            "strategy_id": "iter23-ctp-bundle:engineering_smoke",
            "strategy_identity_sha256": "8" * 64,
        },
        execution_authorization_key_id=_AUTHORIZATION_KEY_ID,
        execution_authorization_secret=_AUTHORIZATION_SECRET,
    )
    stage_a = store.get_ctp_preflight_snapshot(timeout=0)
    stage_b = store.get_ctp_preflight_snapshot("DCE.m2701", timeout=0)
    bundle = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)
    authorized = sorted(f"{leg['exchange_id']}.{leg['instrument_id']}" for leg in bundle["legs"])
    proof = _arming_proof(
        account_fingerprint="acct_0123456789abcdef",
        trading_day=bundle["trading_day"],
        instrument="DCE.m2701",
        connection_generation=bundle["connection_generation"],
        environment_profile="simnow_demo",
        preflight_sha256=bundle["snapshot_sha256"],
        scope_version="ctp-contract-bundle-v1",
        authorized_instruments=authorized,
    )
    now = dt.datetime.now(dt.timezone.utc)
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
    authorization = object()
    client.opaque_authorization_proofs[authorization] = proof
    return client, store, proof, grant, configured, bundle, authorization


def _bundle_recovery_report(proof, *, status="RECOVERABLE", unknown_leg=None):
    """Fixture report retaining separate remote/owned maps for every leg."""
    zero = {
        "long_today": "0",
        "long_yesterday": "0",
        "short_today": "0",
        "short_yesterday": "0",
    }
    remote = {instrument: dict(zero) for instrument in proof["authorized_instruments"]}
    owned = {instrument: dict(zero) for instrument in proof["authorized_instruments"]}
    remote[proof["instrument"]]["long_today"] = "1"
    owned[proof["instrument"]]["long_today"] = "1"
    if status == "FLAT":
        remote = {instrument: dict(zero) for instrument in remote}
        owned = {instrument: dict(zero) for instrument in owned}
    elif status == "MANUAL_INTERVENTION":
        owned = {instrument: dict(zero) for instrument in remote}
    elif unknown_leg is not None:
        remote[unknown_leg] = dict(zero)
        owned[unknown_leg] = dict(zero)

    cycle_id = None if status != "RECOVERABLE" else "sdk-bundle-cycle-0001"
    allowed_closes = []
    if status == "RECOVERABLE":
        exchange_id, instrument_id = proof["instrument"].split(".", 1)
        allowed_closes = [
            {
                "execution_cycle_id": cycle_id,
                "symbol": instrument_id,
                "exchange_id": exchange_id,
                "position_side": "long",
                "side": "sell",
                "offset": "close",
                "quantity": "1",
                "quantity_unit": "contracts",
            }
        ]
    if status == "FLAT":
        allowed_actions = ["complete"]
        token = "9" * 64
        recovery_required = False
        can_arm_execution = True
        can_arm_recovery = False
    elif status == "MANUAL_INTERVENTION":
        allowed_actions = []
        token = None
        recovery_required = True
        can_arm_execution = False
        can_arm_recovery = False
    else:
        allowed_actions = ["close"]
        token = "9" * 64
        recovery_required = True
        can_arm_execution = False
        can_arm_recovery = True
    return {
        "schema_version": "bt_api.execution-recovery.v1",
        "status": status,
        "recovery_required": recovery_required,
        "can_arm_execution": can_arm_execution,
        "can_arm_recovery": can_arm_recovery,
        "account_fingerprint": proof["account_fingerprint"],
        "trading_day": proof["trading_day"],
        "instrument": proof["instrument"],
        "connection_generation": proof["connection_generation"],
        "strategy_id": "iter23-ctp-bundle:engineering_smoke",
        "execution_cycle_id": cycle_id,
        "remote_position": dict(remote[proof["instrument"]]),
        "owned_position": dict(owned[proof["instrument"]]),
        "allowed_closes": allowed_closes,
        "allowed_cancels": [],
        "allowed_actions": allowed_actions,
        "unknown_ids": [unknown_leg] if unknown_leg is not None else [],
        "evidence_errors": ["unknown_leg"] if unknown_leg is not None else [],
        "journal_sha256": "8" * 64,
        "fencing_epoch": 4,
        "recovery_token_sha256": token,
        "scope_version": proof["scope_version"],
        "authorized_instruments": list(proof["authorized_instruments"]),
        "remote_positions_by_instrument": remote,
        "owned_positions_by_instrument": owned,
    }


def test_ctp_bundle_arm_delegates_exact_scope_to_public_sdk_before_any_opening():
    client, store, proof, _grant, configured, bundle, authorization = _bundle_authorized_store()
    store._command_accept_openings = True

    result = store.arm_sdk_execution(proof, authorization=authorization)

    assert configured["configured"] is True
    assert result["armed"] is True
    assert client.armed_proofs == [proof]
    assert client.arm_arguments == [authorization]
    assert store._sdk_execution_config["market_data_only"] is False
    assert bundle["evidence_complete"] is True


def test_ctp_bundle_arm_matches_opaque_only_sdk_signature():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store(
        OpaqueOnlyBundleClient()
    )

    result = store.arm_sdk_execution(proof, authorization=authorization)

    assert result["armed"] is True
    assert client.arm_arguments == [authorization]


def test_ctp_bundle_arm_accepts_public_session_scope_when_summary_omits_gate_aliases():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    original_state = client.get_session_state

    def state_with_public_gate_scope():
        state = original_state()
        state.update(
            {
                "execution_gate_scope_version": proof["scope_version"],
                "execution_gate_authorized_instruments": list(proof["authorized_instruments"]),
                "execution_gate_instrument": proof["instrument"],
            }
        )
        return state

    client.get_session_state = state_with_public_gate_scope
    client.get_execution_summary = lambda: {
        "unknown_ids": [],
        "active_orders": 0,
        "unmatched_trade_count": 0,
        "armed": True,
        "market_data_only": False,
        "arm_revoked": False,
        "arm_proof_sha256": client.arm_proof_sha256,
    }

    result = store.arm_sdk_execution(proof, authorization=authorization)

    assert result["armed"] is True
    assert client.arm_arguments == [authorization]


def test_ctp_bundle_arm_rejects_conflicting_post_session_scope_even_with_correct_summary():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    original_state = client.get_session_state

    def state_with_extra_unauthorized_leg():
        state = original_state()
        if client.armed:
            state.update(
                {
                    "execution_gate_scope_version": proof["scope_version"],
                    "execution_gate_authorized_instruments": [
                        proof["instrument"],
                        "DCE.m2701-C-3500",
                    ],
                }
            )
        return state

    client.get_session_state = state_with_extra_unauthorized_leg

    with pytest.raises(BtApiStoreError, match="identity mismatch|scope"):
        store.arm_sdk_execution(proof, authorization=authorization)

    assert client.armed is False
    assert client.disarm_reasons == ["execution_arm_post_commit_failure"]
    assert store._sdk_execution_config["market_data_only"] is True
    assert store._command_accept_openings is False


def test_ctp_bundle_arm_rejects_post_arm_environment_drift_and_disarms():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    original_state = client.get_session_state

    def state_with_changed_environment():
        state = original_state()
        if client.armed:
            state["environment_profile"] = "production"
        return state

    client.get_session_state = state_with_changed_environment

    with pytest.raises(BtApiStoreError, match="identity mismatch|environment"):
        store.arm_sdk_execution(proof, authorization=authorization)

    assert client.armed is False
    assert client.disarm_reasons == ["execution_arm_post_commit_failure"]
    assert store._sdk_execution_config["market_data_only"] is True


@pytest.mark.parametrize("stale_target", ["stage_a", "stage_b", "bundle"])
def test_ctp_bundle_arm_rejects_each_independently_stale_preflight_snapshot(stale_target):
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    stale = time.monotonic() - store._ctp_query_max_age_seconds - 1.0
    if stale_target == "stage_a":
        store._ctp_preflight_history[0]["completed_monotonic"] = stale
    elif stale_target == "stage_b":
        store._ctp_preflight_history[1]["completed_monotonic"] = stale
    else:
        store._last_ctp_bundle_preflight_snapshot["completed_monotonic"] = stale

    with pytest.raises(BtApiStoreError, match="clock|stale|fresh"):
        store.arm_sdk_execution(proof, authorization=authorization)

    assert client.armed_proofs == []
    assert client.disarm_reasons == []
    assert store._sdk_execution_config["market_data_only"] is True


@pytest.mark.parametrize(
    "stale_target,field,value",
    [
        ("stage_a", "completed_monotonic", float("nan")),
        ("stage_b", "completed_monotonic", float("inf")),
        ("bundle", "completed_monotonic", None),
        ("bundle", "started_monotonic", float("nan")),
        # Keep parametrization deterministic across xdist workers.  A fixed,
        # impossible local-monotonic future timestamp exercises the same
        # rejection path without baking import-time process state into node IDs.
        ("stage_a", "completed_monotonic", 1_000_000_000_000.0),
    ],
)
def test_ctp_bundle_arm_rejects_untrusted_preflight_clock_values(stale_target, field, value):
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    if stale_target == "stage_a":
        store._ctp_preflight_history[0][field] = value
    elif stale_target == "stage_b":
        store._ctp_preflight_history[1][field] = value
    else:
        store._last_ctp_bundle_preflight_snapshot[field] = value

    with pytest.raises(BtApiStoreError, match="clock|stale|fresh"):
        store.arm_sdk_execution(proof, authorization=authorization)

    assert client.armed_proofs == []


@pytest.mark.parametrize(
    "result_name,expected_error",
    [
        ("account", "account_completed_after_receive_window"),
        ("instruments", "leg[0].instrument_completed_after_receive_window"),
        ("option_trade_cost", "leg[1].option_trade_cost_completed_after_receive_window"),
    ],
)
def test_ctp_bundle_preflight_rejects_query_completion_outside_request_window(
    result_name, expected_error
):
    client, store = _dce_bundle_store()
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    client.completed_at_override[result_name] = future.isoformat()

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


@pytest.mark.parametrize(
    "field,value,expected_error",
    [
        ("started_at_utc", float("nan"), "account_started_at_utc_invalid"),
        ("completed_at_utc", float("inf"), "account_completed_at_utc_invalid"),
        ("started_at_utc", None, "account_started_at_utc_invalid"),
        ("completed_at_utc", None, "account_completed_at_utc_invalid"),
    ],
)
def test_ctp_bundle_preflight_rejects_untrusted_query_clock_values(field, value, expected_error):
    client, store = _dce_bundle_store()
    overrides = {
        "started_at_utc": client.started_at_override,
        "completed_at_utc": client.completed_at_override,
    }
    overrides[field]["account"] = value

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is False
    assert expected_error in snapshot["evidence_errors"]


def test_ctp_bundle_preflight_accepts_query_timestamps_from_same_request_window():
    client, store = _dce_bundle_store()

    snapshot = store.get_ctp_bundle_preflight_snapshot(_dce_bundle_legs(), timeout=0)

    assert snapshot["evidence_complete"] is True
    account_query = snapshot["query_results"]["account"]
    assert (
        account_query["requested_at_utc"]
        <= account_query["started_at_utc"]
        <= account_query["completed_at_utc"]
        <= account_query["received_at_utc"]
    )
    assert account_query["requested_monotonic"] <= account_query["received_monotonic"]


def test_ctp_bundle_query_time_rejects_monotonic_receive_rollback():
    base = dt.datetime(2026, 9, 11, tzinfo=dt.timezone.utc)

    errors = BtApiStore._ctp_bundle_query_time_errors(
        {
            "started_at_utc": base,
            "completed_at_utc": base + dt.timedelta(microseconds=1),
            "requested_monotonic": 20.0,
            "received_monotonic": 19.0,
        },
        label="account",
        requested_at_utc=base,
        received_at_utc=base + dt.timedelta(seconds=1),
    )

    assert "account_received_monotonic_before_request" in errors


def test_ctp_bundle_arm_requires_opaque_public_sdk_authorization():
    client, store, proof, _grant, _configured, _bundle, _authorization = _bundle_authorized_store()

    with pytest.raises(BtApiStoreError, match="caller-provided public authorization"):
        store.arm_sdk_execution(proof)

    assert client.armed_proofs == []


def test_ctp_bundle_arm_rejects_extra_member_before_sdk_write():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    forged = dict(proof)
    forged["authorized_instruments"] = list(proof["authorized_instruments"]) + ["DCE.m2701-C-3500"]

    with pytest.raises(BtApiStoreError):
        store.arm_sdk_execution(forged, authorization=authorization)

    assert client.armed_proofs == []


def test_ctp_bundle_arm_rejects_generation_change_before_sdk_write():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    client.session_generation = proof["connection_generation"] + 1

    with pytest.raises(BtApiStoreError, match="generation|preflight"):
        store.arm_sdk_execution(proof, authorization=authorization)

    assert client.armed_proofs == []


def test_ctp_bundle_arm_rejects_incomplete_preflight_before_sdk_write():
    client, store, proof, _grant, _configured, _bundle, authorization = _bundle_authorized_store()
    store._last_ctp_bundle_preflight_snapshot["evidence_complete"] = False
    store._last_ctp_bundle_preflight_snapshot["evidence_errors"] = ["late_callback"]

    with pytest.raises(BtApiStoreError, match="incomplete|stale"):
        store.arm_sdk_execution(proof, authorization=authorization)

    assert client.armed_proofs == []


def test_ctp_bundle_recovery_preserves_per_leg_position_maps_and_arms_only_recovery():
    client, store, proof, _grant, _configured, _bundle, _authorization = _bundle_authorized_store()
    client.recovery_report = _bundle_recovery_report(proof)

    plan = store.prepare_execution_recovery(proof)
    arm = store.arm_execution_recovery(
        proof,
        recovery_token_sha256=plan["recovery_token_sha256"],
    )

    assert plan["scope_version"] == "ctp-contract-bundle-v1"
    assert set(plan["remote_positions_by_instrument"]) == set(proof["authorized_instruments"])
    assert plan["remote_positions_by_instrument"][proof["instrument"]]["long_today"] == "1"
    assert arm["recovery_only"] is True
    assert store._command_accept_openings is False


def test_ctp_bundle_recovery_rejects_unknown_leg_before_sdk_recovery_arm():
    client, store, proof, _grant, _configured, _bundle, _authorization = _bundle_authorized_store()
    client.recovery_report = _bundle_recovery_report(
        proof,
        status="MANUAL_INTERVENTION",
        unknown_leg="DCE.m2701-C-3500",
    )

    plan = store.prepare_execution_recovery(proof)

    assert client.recovery_prepares == [proof]
    assert client.recovery_arms == []
    assert plan["status"] == "MANUAL_INTERVENTION"
    assert plan["can_arm_recovery"] is False


def test_ctp_bundle_recovery_rejects_same_total_when_close_quantity_is_on_wrong_leg():
    client, store, proof, _grant, _configured, _bundle, _authorization = _bundle_authorized_store()
    report = _bundle_recovery_report(proof)
    option = proof["authorized_instruments"][1]
    report["remote_positions_by_instrument"][option]["long_today"] = "1"
    report["owned_positions_by_instrument"][option]["long_today"] = "1"
    report["allowed_closes"][0]["quantity"] = "2"
    client.recovery_report = report

    with pytest.raises(BtApiStoreError, match="close exceeds|each leg"):
        store.prepare_execution_recovery(proof)

    assert client.recovery_arms == []


def test_ctp_bundle_recovery_rejects_per_leg_close_overage_from_distinct_actions():
    client, store, proof, _grant, _configured, _bundle, _authorization = _bundle_authorized_store()
    report = _bundle_recovery_report(proof)
    option = proof["authorized_instruments"][1]
    report["remote_positions_by_instrument"][option]["long_today"] = "1"
    report["owned_positions_by_instrument"][option]["long_today"] = "1"
    option_symbol = option.split(".", 1)[1]
    report["allowed_closes"].append(
        {
            "execution_cycle_id": report["execution_cycle_id"],
            "symbol": option_symbol,
            "exchange_id": "DCE",
            "position_side": "long",
            "side": "sell",
            "offset": "close",
            "quantity": "2",
            "quantity_unit": "contracts",
        }
    )
    client.recovery_report = report

    with pytest.raises(BtApiStoreError, match="close exceeds|each leg"):
        store.prepare_execution_recovery(proof)

    assert client.recovery_arms == []
