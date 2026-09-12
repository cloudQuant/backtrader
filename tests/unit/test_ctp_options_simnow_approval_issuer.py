"""Issuer and mechanical-operator unit contracts."""

from __future__ import annotations

import base64
import json

import pytest

import examples.ctp_options_simnow_approval_issuer as issuer
import examples.ctp_options_simnow_mechanical_operator as mechanical


def _context(**changes):
    context = {
        "candidate_id": "candidate-iter23-25",
        "strategy_id": "iter23-25-options-mechanical",
        "strategy_identity_sha256": "1" * 64,
        "execution_cycle_id": "cycle-1",
        "authorized_instruments": [
            {"exchange_id": "CZCE", "instrument_id": "SA701"},
            {"exchange_id": "CZCE", "instrument_id": "SA701C1080"},
            {"exchange_id": "CZCE", "instrument_id": "SA701P1080"},
        ],
        "primary_instrument": {"exchange_id": "CZCE", "instrument_id": "SA701"},
        "account_fingerprint": "acct_0123456789abcdef",
        "trading_day": "20260911",
        "connection_generation": 7,
        "environment_profile": "simnow_demo",
        "configuration_sha256": "2" * 64,
        "backtrader_sha256": "3" * 64,
        "bt_api_py_sha256": "4" * 64,
        "bt_api_ctp_sha256": "5" * 64,
        "bt_api_base_sha256": "6" * 64,
        "native_sha256": "7" * 64,
        "dependency_hashes_sha256": "8" * 64,
        "preflight_sha256": "9" * 64,
        "evidence_sha256": "a" * 64,
        "budget_policy_id": "iter23-25-three-leg-path-v1",
        "budget_limit": "8000",
        "future_reservation_id": "none",
    }
    context.update(changes)
    return context


def _key_material(tmp_path):
    cryptography = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )
    private = cryptography.Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    return {
        "algorithm": "Ed25519",
        "key_id": "operator-test",
        "created_at_utc": "2026-09-11T00:00:00.000000Z",
        "private_key": base64.urlsafe_b64encode(private.private_bytes_raw())
        .decode("ascii")
        .rstrip("="),
        "public_key": base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("="),
    }, private


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_keygen_trust_root_and_sign_roundtrip(tmp_path, capsys):
    key_file = tmp_path / "operator-key.json"
    assert issuer.main(["keygen", "--key-file", str(key_file)]) == 0
    capsys.readouterr()
    material = json.loads(key_file.read_text())
    assert set(material) == {
        "algorithm",
        "key_id",
        "created_at_utc",
        "private_key",
        "public_key",
    }
    assert key_file.stat().st_mode & 0o777 == 0o600

    trust_file = tmp_path / "trust-root.json"
    assert (
        issuer.main(
            [
                "trust-root",
                "--key-file",
                str(key_file),
                "--output",
                str(trust_file),
            ]
        )
        == 0
    )
    capsys.readouterr()
    root = json.loads(trust_file.read_text())
    assert root["schema_version"] == "ctp-execution-trust-root-v1"
    assert root["keys"][material["key_id"]]["public_key"] == material["public_key"]

    context_file = tmp_path / "context.json"
    context_file.write_text(json.dumps(_context()), encoding="utf-8")
    artifact_file = tmp_path / "artifact.json"
    assert (
        issuer.main(
            [
                "sign",
                "--key-file",
                str(key_file),
                "--context",
                str(context_file),
                "--receipt-sha256",
                "b" * 64,
                "--source-hashes-sha256",
                "c" * 64,
                "--ctp-package-sha256",
                "d" * 64,
                "--output",
                str(artifact_file),
            ]
        )
        == 0
    )
    capsys.readouterr()
    artifact = json.loads(artifact_file.read_text())
    assert artifact["schema_version"] == "ctp-execution-entry-approval-v1"
    assert artifact["payload"]["schema_version"] == artifact["schema_version"]
    assert artifact["payload"]["purpose"] == "ctp_execution_approval"
    assert artifact["payload"]["receipt_sha256"] == "b" * 64

    cryptography = pytest.importorskip(
        "cryptography.hazmat.primitives.asymmetric.ed25519"
    )
    public = cryptography.Ed25519PublicKey.from_public_bytes(
        _b64decode(material["public_key"])
    )
    payload_bytes = json.dumps(
        artifact["payload"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    public.verify(_b64decode(artifact["signature"]), payload_bytes)


def test_keygen_refuses_overwrite(tmp_path, capsys):
    key_file = tmp_path / "key.json"
    assert issuer.main(["keygen", "--key-file", str(key_file)]) == 0
    capsys.readouterr()
    assert issuer.main(["keygen", "--key-file", str(key_file)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED"
    assert report["reason"].startswith("KEY_FILE_EXISTS")


def test_build_entry_payload_rejects_unsorted_or_cross_exchange_scope():
    with pytest.raises(issuer.IssuerError, match="NOT_SORTED_UNIQUE"):
        issuer.build_entry_payload(
            _context(
                authorized_instruments=[
                    {"exchange_id": "CZCE", "instrument_id": "SA701C1080"},
                    {"exchange_id": "CZCE", "instrument_id": "SA701"},
                    {"exchange_id": "CZCE", "instrument_id": "SA701P1080"},
                ]
            ),
            key_id="k",
            issuer_role="r",
            receipt_sha256="1" * 64,
            source_hashes_sha256="2" * 64,
            ctp_package_sha256="3" * 64,
        )
    with pytest.raises(issuer.IssuerError, match="CROSS_EXCHANGE"):
        issuer.build_entry_payload(
            _context(
                authorized_instruments=[
                    {"exchange_id": "CZCE", "instrument_id": "SA701"},
                    {"exchange_id": "DCE", "instrument_id": "m2701"},
                ],
                primary_instrument={"exchange_id": "CZCE", "instrument_id": "SA701"},
            ),
            key_id="k",
            issuer_role="r",
            receipt_sha256="1" * 64,
            source_hashes_sha256="2" * 64,
            ctp_package_sha256="3" * 64,
        )


def test_build_entry_payload_rejects_missing_context_fields():
    context = _context()
    del context["native_sha256"]
    with pytest.raises(issuer.IssuerError, match="CONTEXT_MISSING:native_sha256"):
        issuer.build_entry_payload(
            context,
            key_id="k",
            issuer_role="r",
            receipt_sha256="1" * 64,
            source_hashes_sha256="2" * 64,
            ctp_package_sha256="3" * 64,
        )


def _bundle():
    from examples.ctp_options_simnow_common import LegIdentity, ThreeLegBundle

    future = LegIdentity(
        instrument_id="SA709",
        exchange_id="CZCE",
        product_id="SA",
        asset_type="future",
        active=True,
        trading_day="20260911",
        expiry="20260930",
        tick_size="1.0",
        multiplier="20",
    )
    call = LegIdentity(
        instrument_id="SA709C1500",
        exchange_id="CZCE",
        product_id="SA",
        asset_type="option",
        active=True,
        trading_day="20260911",
        expiry="20260827",
        tick_size="0.5",
        multiplier="20",
        underlying_instrument_id="SA709",
        option_type="C",
        strike="1500.0",
    )
    put = LegIdentity(
        instrument_id="SA709P1500",
        exchange_id="CZCE",
        product_id="SA",
        asset_type="option",
        active=True,
        trading_day="20260911",
        expiry="20260827",
        tick_size="0.5",
        multiplier="20",
        underlying_instrument_id="SA709",
        option_type="P",
        strike="1500.0",
    )
    return ThreeLegBundle(
        exchange_id="CZCE",
        product_id="SA",
        trading_day="20260911",
        future=future,
        call=call,
        put=put,
        option_expiry="20260827",
        strike="1500.0",
    )


def _stage_b():
    def margin_record(instrument, **fields):
        base = {
            "InstrumentID": instrument,
            "LongMarginRatio": "0.09",
            "ShortMarginRatio": "0.10",
        }
        base.update(fields)
        return base

    def fee_record(instrument, **fields):
        base = {
            "InstrumentID": instrument,
            "OpenRatioByVolume": "10.0",
            "CloseRatioByVolume": "10.0",
        }
        base.update(fields)
        return base

    return {
        "query_results": {
            "margin_rate": {
                "complete": True,
                "records": [
                    margin_record("SA709"),
                    margin_record("SA709C1500"),
                    margin_record("SA709P1500"),
                ],
            },
            "commission_rate": {
                "complete": True,
                "records": [
                    fee_record("SA709"),
                    fee_record("SA709C1500"),
                    fee_record("SA709P1500"),
                ],
            },
        }
    }


def _reference():
    return {
        "legs": [
            {
                "exchange_id": "CZCE",
                "instrument_id": "SA709",
                "ask_price": 1500.0,
                "bid_price": 1499.0,
                "entry_buy_price": 1500.0,
                "exit_sell_price": 1499.0,
            },
            {
                "exchange_id": "CZCE",
                "instrument_id": "SA709C1500",
                "ask_price": 40.0,
                "bid_price": 39.5,
                "entry_buy_price": 40.0,
                "exit_sell_price": 39.5,
            },
            {
                "exchange_id": "CZCE",
                "instrument_id": "SA709P1500",
                "ask_price": 20.0,
                "bid_price": 19.5,
                "entry_buy_price": 20.0,
                "exit_sell_price": 19.5,
            },
        ]
    }


def test_build_budget_evidence_produces_complete_path_states():
    evidence = mechanical.build_budget_evidence(
        bundle=_bundle(),
        stage_b=_stage_b(),
        reference=_reference(),
        context=_context(),
        account_available_cny=200000.0,
        expires_at_utc="2026-09-11T12:00:00.000000Z",
        source_version="test-v1",
    )
    states = evidence["reachable_states"]
    kinds = {state["state_kind"] for state in states}
    assert kinds == {"prefix", "partial", "unknown", "cancel", "late_fill", "recovery"}
    cost_fields = {
        "future_gross_margin",
        "seller_option_gross_margin",
        "paid_long_premium",
        "fees_financing",
        "stress_cash_loss",
        "unresolved_reserve",
    }
    for state in states:
        assert set(state["costs"]) == cost_fields
        total = sum(state["costs"].values())
        assert total <= mechanical.BUDGET_ORDINARY_CAP_CNY
    # future margin = 1500 * 20 * 0.09 = 2700; short call = 40*20*0.10 = 80
    assert states[0]["costs"]["future_gross_margin"] == 2700.0
    assert states[0]["costs"]["seller_option_gross_margin"] == 80.0
    assert states[0]["costs"]["paid_long_premium"] == 400.0
    assert evidence["source"] == "sdk_runtime"
    assert evidence["money_unit"] == "CNY"


def test_build_budget_evidence_blocks_when_margin_evidence_missing():
    stage_b = _stage_b()
    stage_b["query_results"]["margin_rate"]["records"] = [
        record
        for record in stage_b["query_results"]["margin_rate"]["records"]
        if record["InstrumentID"] != "SA709C1500"
    ]
    with pytest.raises(mechanical.MechanicalBlocked, match="MARGIN_RATIO_MISSING"):
        mechanical.build_budget_evidence(
            bundle=_bundle(),
            stage_b=stage_b,
            reference=_reference(),
            context=_context(),
            account_available_cny=200000.0,
            expires_at_utc="2026-09-11T12:00:00.000000Z",
            source_version="test-v1",
        )


def test_build_budget_evidence_blocks_when_cap_exceeded():
    stage_b = _stage_b()
    for query in ("margin_rate", "commission_rate"):
        for record in stage_b["query_results"][query]["records"]:
            record["LongMarginRatio"] = "0.30"
            record["ShortMarginRatio"] = "0.30"
    with pytest.raises(mechanical.MechanicalBlocked, match="BUDGET_ORDINARY_CAP_EXCEEDED"):
        mechanical.build_budget_evidence(
            bundle=_bundle(),
            stage_b=stage_b,
            reference=_reference(),
            context=_context(),
            account_available_cny=200000.0,
            expires_at_utc="2026-09-11T12:00:00.000000Z",
            source_version="test-v1",
        )


def test_build_budget_evidence_blocks_insufficient_available():
    with pytest.raises(mechanical.MechanicalBlocked, match="ACCOUNT_AVAILABLE"):
        mechanical.build_budget_evidence(
            bundle=_bundle(),
            stage_b=_stage_b(),
            reference=_reference(),
            context=_context(),
            account_available_cny=1000.0,
            expires_at_utc="2026-09-11T12:00:00.000000Z",
            source_version="test-v1",
        )


def test_entry_prices_use_executable_reference_quotes():
    prices = mechanical._entry_prices(_bundle(), _reference())
    assert prices == {
        "CZCE.SA709": 1500.0,
        "CZCE.SA709C1500": 40.0,
        "CZCE.SA709P1500": 20.0,
    }
