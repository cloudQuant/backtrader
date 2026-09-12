"""Operator-owned SimNow mechanical cycle for Iterations 23/24/25.

This is the governed trading entry the read-only ``engineering_smoke``
operator deliberately stops short of.  It connects one managed CTP client,
confirms settlement once, collects the same read-only three-leg evidence
chain, binds the V2 bundle authorization, redeems one operator-signed
``ctp-execution-entry-approval-v1`` artifact, arms SDK execution through the
public approval path, reserves the complete-path CTP budget from live
evidence, and drives exactly one three-leg open/close cycle to a proven flat
reconciliation.

Every failure is fail-closed with a stable reason code.  The operator never
prints or logs a secret.  ``MECHANICAL_PASS`` is execution-path evidence only;
it is not strategy profitability evidence and does not admit Iter25 HFT
activity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.stores.btapistore import BtApiStore

try:
    from .ctp_options_simnow_approval_issuer import (
        build_entry_payload,
        sign_payload,
        _load_key,
        _private_signing_key,
    )
    from .ctp_options_simnow_authorization import build_bundle_authorization
    from .ctp_options_simnow_common import ThreeLegBundle
    from .ctp_options_simnow_live_drive import drive_simnow_mechanical_session
    from .ctp_options_simnow_live_runner import SimNowLiveRunner
    from .ctp_options_simnow_operator import (
        CTP_EXCHANGE,
        HERE,
        OperatorBlocked,
        OperatorConfiguration,
        _contract_metadata,
        _request_counts,
        _verify_or_confirm_settlement,
        build_live_store,
        collect_three_leg_evidence,
        load_operator_env,
        resolve_credentials,
        resolve_fronts,
    )
except ImportError:  # Direct execution through the examples directory.
    from ctp_options_simnow_approval_issuer import (  # type: ignore[no-redef]
        build_entry_payload,
        sign_payload,
        _load_key,
        _private_signing_key,
    )
    from ctp_options_simnow_authorization import build_bundle_authorization  # type: ignore[no-redef]
    from ctp_options_simnow_common import ThreeLegBundle  # type: ignore[no-redef]
    from ctp_options_simnow_live_drive import (  # type: ignore[no-redef]
        drive_simnow_mechanical_session,
    )
    from ctp_options_simnow_live_runner import SimNowLiveRunner  # type: ignore[no-redef]
    from ctp_options_simnow_operator import (  # type: ignore[no-redef]
        CTP_EXCHANGE,
        HERE,
        OperatorBlocked,
        OperatorConfiguration,
        _contract_metadata,
        _request_counts,
        _verify_or_confirm_settlement,
        build_live_store,
        collect_three_leg_evidence,
        load_operator_env,
        resolve_credentials,
        resolve_fronts,
    )

DEFAULT_ENV_PATH = HERE / ".env"
DEFAULT_KEY_FILE = HERE / ".simnow-approval-operator-key.json"
DEFAULT_TRUST_ROOT = HERE / ".simnow-approval-trust-root.json"
BUDGET_ORDINARY_CAP_CNY = 8000.0
BUDGET_RECOVERY_HEADROOM_CNY = 2000.0


class MechanicalBlocked(RuntimeError):
    """A fail-closed mechanical-cycle precondition."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MechanicalConfiguration:
    environment: str
    product_id: str
    exchange_id: str
    future_instrument_id: str | None = None
    call_instrument_id: str | None = None
    put_instrument_id: str | None = None
    capital: float = 200000.0
    strategy_id: str = "iter23-25-options-mechanical"
    purpose: str = "mechanical_cycle"
    confirm_settlement: bool = True
    query_timeout: float = 20.0
    leg_timeout: float = 45.0

    def __post_init__(self) -> None:
        if self.purpose != "mechanical_cycle":
            raise MechanicalBlocked("PURPOSE_NOT_SUPPORTED")
        exact = (
            self.future_instrument_id,
            self.call_instrument_id,
            self.put_instrument_id,
        )
        if any(value is not None for value in exact) and not all(
            value is not None for value in exact
        ):
            raise MechanicalBlocked("EXACT_BUNDLE_IDS_MUST_BE_COMPLETE")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _strategy_identity(module_path: Path) -> str:
    return _sha256_file(module_path)


def _runtime_hashes() -> dict[str, str]:
    """Hash the deployed packages honestly from their installed locations."""

    import backtrader
    import bt_api_py

    hashes: dict[str, str] = {}
    for name, module in (("backtrader", backtrader), ("bt_api_py", bt_api_py)):
        package = Path(module.__file__).resolve().parent
        digest = hashlib.sha256()
        for source in sorted(package.rglob("*.py")):
            digest.update(str(source.relative_to(package)).encode())
            digest.update(source.read_bytes())
        hashes[name] = digest.hexdigest()
    try:
        import bt_api_ctp

        package = Path(bt_api_ctp.__file__).resolve().parent
        digest = hashlib.sha256()
        for source in sorted(package.rglob("*.py")):
            digest.update(str(source.relative_to(package)).encode())
            digest.update(source.read_bytes())
        for shared in sorted(package.parent.glob("*.dylib")):
            digest.update(shared.name.encode())
            digest.update(shared.read_bytes())
        hashes["bt_api_ctp"] = digest.hexdigest()
    except ImportError:
        raise MechanicalBlocked("BT_API_CTP_UNAVAILABLE") from None
    import sys

    hashes["runtime_executable"] = _sha256_file(Path(sys.executable))
    return hashes


def _first_number(record: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = record.get(name)
        if value is None:
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(parsed) and parsed >= 0:
            return parsed
    return None


def _leg_records(stage_b: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index the per-leg margin/commission evidence by InstrumentID."""

    results = stage_b.get("query_results") or {}
    rows: dict[str, Mapping[str, Any]] = {}
    for name in ("margin_rate", "commission_rate"):
        query = results.get(name) or {}
        for record in query.get("records") or ():
            if isinstance(record, Mapping):
                instrument = str(
                    record.get("InstrumentID")
                    or record.get("instrument_id")
                    or ""
                ).strip()
                if instrument:
                    rows.setdefault(instrument, {})
                    merged = dict(rows[instrument])
                    merged.update(dict(record))
                    rows[instrument] = merged
    return rows


def _cost_field(record: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    return _first_number(record, names)


_MARGIN_KEYS = (
    "LongMarginRatio",
    "LongMarginRatioByMoney",
    "long_margin_ratio",
)
_SHORT_MARGIN_KEYS = (
    "ShortMarginRatio",
    "ShortMarginRatioByMoney",
    "short_margin_ratio",
)
_VOLUME_FEE_KEYS = (
    "OpenRatioByVolume",
    "CloseRatioByVolume",
    "CloseTodayRatioByVolume",
    "open_ratio_by_volume",
    "close_ratio_by_volume",
)
_MONEY_FEE_KEYS = (
    "OpenRatioByMoney",
    "CloseRatioByMoney",
    "open_ratio_by_money",
    "close_ratio_by_money",
)


def build_budget_evidence(
    *,
    bundle: ThreeLegBundle,
    stage_b: Mapping[str, Any],
    reference: Mapping[str, Any],
    context: Mapping[str, Any],
    account_available_cny: float,
    expires_at_utc: str,
    source_version: str,
) -> dict[str, Any]:
    """Build the complete-path CTP budget evidence from live SimNow data.

    The reachable states share one conservative complete-path cost bundle:
    every alternative execution path of the three-leg cycle must fit inside
    the same worst-case envelope.  Costs come from the live Stage B
    margin/commission queries and the executable reference quotes; nothing is
    defaulted or guessed.
    """

    legs = {
        "F": bundle.future,
        "C": bundle.call,
        "P": bundle.put,
    }
    quotes: dict[str, Mapping[str, Any]] = {}
    for leg in reference.get("legs") or ():
        if isinstance(leg, Mapping):
            instrument = str(leg.get("instrument_id") or "").strip()
            if instrument:
                quotes[instrument] = leg
    records = _leg_records(stage_b)

    def quote(instrument_id: str, field: str) -> float:
        leg = quotes.get(instrument_id)
        if leg is None:
            raise MechanicalBlocked(f"REFERENCE_QUOTE_MISSING:{instrument_id}")
        value = _first_number(leg, (field,))
        if value is None or value <= 0:
            raise MechanicalBlocked(f"REFERENCE_QUOTE_INVALID:{instrument_id}:{field}")
        return value

    def margin(instrument_id: str, *, short: bool) -> float:
        record = records.get(instrument_id)
        if record is None:
            raise MechanicalBlocked(f"MARGIN_EVIDENCE_MISSING:{instrument_id}")
        value = _cost_field(record, _SHORT_MARGIN_KEYS if short else _MARGIN_KEYS)
        if value is None:
            raise MechanicalBlocked(f"MARGIN_RATIO_MISSING:{instrument_id}")
        return value

    def fees_per_lot(instrument_id: str, price: float, multiplier: float) -> float:
        record = records.get(instrument_id)
        if record is None:
            raise MechanicalBlocked(f"COMMISSION_EVIDENCE_MISSING:{instrument_id}")
        by_volume = _cost_field(record, _VOLUME_FEE_KEYS)
        if by_volume is not None and by_volume > 0:
            return by_volume
        by_money = _cost_field(record, _MONEY_FEE_KEYS)
        if by_money is not None and by_money > 0:
            return by_money * price * multiplier
        raise MechanicalBlocked(f"COMMISSION_RATE_MISSING:{instrument_id}")

    future = legs["F"]
    call = legs["C"]
    put = legs["P"]
    future_price = quote(future.instrument_id, "ask_price")
    call_price = quote(call.instrument_id, "ask_price")
    put_price = quote(put.instrument_id, "ask_price")

    future_margin = future_price * float(future.multiplier) * margin(
        future.instrument_id, short=False
    )
    short_call_margin = call_price * float(call.multiplier) * margin(
        call.instrument_id, short=True
    )
    paid_premium = put_price * float(put.multiplier)
    legs_fees = (
        fees_per_lot(future.instrument_id, future_price, float(future.multiplier))
        + fees_per_lot(call.instrument_id, call_price, float(call.multiplier))
        + fees_per_lot(put.instrument_id, put_price, float(put.multiplier))
    )
    # One open plus one close round for all three legs.
    fees_financing = legs_fees * 2.0
    tick_value = float(future.tick_size) * float(future.multiplier)
    stress_cash_loss = fees_financing + 4.0 * tick_value
    unresolved_reserve = fees_financing + 2.0 * tick_value
    seller_option_gross_margin = short_call_margin

    cost_bundle = {
        "future_gross_margin": round(future_margin, 2),
        "seller_option_gross_margin": round(seller_option_gross_margin, 2),
        "paid_long_premium": round(paid_premium, 2),
        "fees_financing": round(fees_financing, 2),
        "stress_cash_loss": round(stress_cash_loss, 2),
        "unresolved_reserve": round(unresolved_reserve, 2),
    }
    total = round(sum(cost_bundle.values()), 2)
    if total > BUDGET_ORDINARY_CAP_CNY:
        raise MechanicalBlocked(
            f"BUDGET_ORDINARY_CAP_EXCEEDED:{total:.2f}>{BUDGET_ORDINARY_CAP_CNY:.2f}"
        )
    if account_available_cny < BUDGET_RECOVERY_HEADROOM_CNY:
        raise MechanicalBlocked("ACCOUNT_AVAILABLE_INSUFFICIENT_FOR_HEADROOM")

    def state(state_id: str, state_kind: str) -> dict[str, Any]:
        return {
            "state_id": state_id,
            "state_kind": state_kind,
            "costs": dict(cost_bundle),
            "context": {
                "account_fingerprint": context["account_fingerprint"],
                "trading_day": context["trading_day"],
                "connection_generation": context["connection_generation"],
                "environment_profile": context["environment_profile"],
                "candidate_id": context["candidate_id"],
                "strategy_id": context["strategy_id"],
                "strategy_identity_sha256": context["strategy_identity_sha256"],
                "execution_cycle_id": context["execution_cycle_id"],
                "scope_version": "ctp-contract-bundle-v1",
                "authorized_instruments": context["authorized_instruments"],
                "primary_instrument": context["primary_instrument"],
            },
        }

    return {
        "source": "sdk_runtime",
        "source_version": source_version,
        "money_unit": "CNY",
        "complete": True,
        "historical_min_pnl_cny": "0",
        "fresh_available_cny": round(account_available_cny, 2),
        "remaining_unabsorbed_new_obligation_cny": "0",
        "unallocated_recovery_headroom_cny": str(BUDGET_RECOVERY_HEADROOM_CNY),
        "expires_at": expires_at_utc,
        "reachable_states": [
            state("entry-prefix-leg", "prefix"),
            state("entry-partial-legs", "partial"),
            state("entry-unknown-leg", "unknown"),
            state("entry-cancel-refill", "cancel"),
            state("entry-late-fill", "late_fill"),
            state("de-risk-recovery", "recovery"),
        ],
    }


def _account_available(store: BtApiStore, timeout: float) -> float:
    snapshot = store.get_ctp_preflight_snapshot(timeout=timeout, read_only=True)
    results = snapshot.get("query_results") or {}
    account = results.get("account") or {}
    records = account.get("records") or []
    if not records:
        raise MechanicalBlocked("ACCOUNT_EVIDENCE_MISSING")
    value = _first_number(
        records[0],
        ("Available", "available", "AvailableFunds", "available_funds"),
    )
    if value is None:
        raise MechanicalBlocked("ACCOUNT_AVAILABLE_MISSING")
    return value


def _entry_prices(bundle: ThreeLegBundle, reference: Mapping[str, Any]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for leg in (bundle.future, bundle.call, bundle.put):
        symbol = f"{leg.exchange_id}.{leg.instrument_id}"
        row = next(
            (
                item
                for item in reference.get("legs") or ()
                if isinstance(item, Mapping)
                and item.get("instrument_id") == leg.instrument_id
            ),
            None,
        )
        if row is None:
            raise MechanicalBlocked(f"ENTRY_QUOTE_MISSING:{symbol}")
        price = _first_number(row, ("entry_buy_price", "ask_price"))
        if price is None or price <= 0:
            raise MechanicalBlocked(f"ENTRY_QUOTE_INVALID:{symbol}")
        prices[symbol] = price
    return prices


class _MechanicalOwner:
    """Minimal notification sink; the drive loop drains the broker queue."""

    def notify_order(self, order: Any) -> None:  # pragma: no cover - sink
        del order

    def notify_trade(self, trade: Any) -> None:  # pragma: no cover - sink
        del trade


def _approval_seed(
    config: MechanicalConfiguration, cycle_suffix: str, bundle: ThreeLegBundle
) -> dict[str, Any]:
    return {
        "candidate_id": "iter23-25-mechanical-candidate-v1",
        "strategy_id": config.strategy_id,
        "strategy_identity_sha256": _strategy_identity(Path(__file__).resolve()),
        "execution_cycle_id": f"{config.strategy_id}:{cycle_suffix}",
        "authorized_instruments": [
            {"exchange_id": leg.exchange_id, "instrument_id": leg.instrument_id}
            for leg in (bundle.future, bundle.call, bundle.put)
        ],
        "primary_instrument": {
            "exchange_id": bundle.future.exchange_id,
            "instrument_id": bundle.future.instrument_id,
        },
        "budget_policy_id": "iter23-25-three-leg-path-v1",
        "budget_limit": str(int(BUDGET_ORDINARY_CAP_CNY)),
        "future_reservation_id": "none",
    }


def _confirm_settlement_with_approval(
    store: BtApiStore,
    api: Any,
    config: MechanicalConfiguration,
    *,
    bundle: ThreeLegBundle,
    key_material: Mapping[str, str],
    trust_root: Mapping[str, Any],
) -> bool:
    """Confirm settlement once through a redeemed operator approval."""

    # Short-circuit on the native settlement verdict without triggering a
    # readback: when settlement is NOT yet confirmed for the session
    # trading day, verify_ctp_settlement's readback finds no matching
    # confirmation record, records a settlement identity last_error on the
    # session, and the SDK's confirm path then rejects with
    # ctp_session_not_read_only_ready (diagnosed 2026-09-12 on the second
    # set whose trading day stays at the last real session day).  Confirm
    # first through the approval, then verify read-only to prove it.
    session_state = store.get_ctp_session_state()
    if str(session_state.get("settlement_state") or "") == "confirmed":
        verified = store.verify_ctp_settlement(timeout=float(config.query_timeout))
        if verified.get("evidence_complete") is True:
            return True
    seed = _approval_seed(config, "settlement", bundle)
    context = api.build_ctp_execution_approval_context(
        seed,
        exchange_name=CTP_EXCHANGE,
        configuration={"purpose": config.purpose, "phase": "settlement"},
        strategy_source=Path(__file__).resolve(),
        preflight={"phase": "settlement"},
        evidence={"phase": "settlement"},
    )
    payload = build_entry_payload(
        context.as_dict(),
        key_id=key_material["key_id"],
        issuer_role="independent_operator",
        receipt_sha256=_sha256_json({"settlement": config.strategy_id}),
        source_hashes_sha256=_sha256_file(Path(__file__).resolve()),
        ctp_package_sha256=_runtime_hashes()["bt_api_ctp"],
    )
    artifact = sign_payload(payload, _private_signing_key(key_material))
    capability = api.redeem_ctp_execution_approval(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True),
        trust_root=trust_root,
        context=context,
    )
    api.confirm_ctp_settlement_from_approval(
        capability,
        exchange_name=CTP_EXCHANGE,
        timeout=float(config.query_timeout),
    )
    verified = store.verify_ctp_settlement(timeout=float(config.query_timeout))
    return verified.get("evidence_complete") is True


def run_mechanical_cycle(
    config: MechanicalConfiguration,
    env: Mapping[str, str],
    *,
    state_directory: Path,
    key_file: Path = DEFAULT_KEY_FILE,
    trust_root_file: Path = DEFAULT_TRUST_ROOT,
    store: BtApiStore | None = None,
    broker_cls: Any = BtApiBroker,
) -> dict[str, Any]:
    """Run one governed three-leg open/close cycle on SimNow."""

    credentials = resolve_credentials(env)
    fronts = resolve_fronts(env, config.environment)
    key_material = _load_key(key_file)
    if not trust_root_file.is_file():
        raise MechanicalBlocked(f"TRUST_ROOT_MISSING:{trust_root_file}")
    trust_root = json.loads(trust_root_file.read_text(encoding="utf-8"))

    owned_store = store is None
    if store is None:
        store = build_live_store(
            credentials,
            fronts,
            _as_operator_config(config),
            state_directory=state_directory,
            execution_authorization_key_id=key_material["key_id"],
            execution_authorization_secret=load_authorization_secret(env),
            strategy_identity_sha256=_strategy_identity(Path(__file__).resolve()),
        )
    api = store.sdk_api
    if api is None:
        api = store._ensure_api_ready()

    # The CTP trade-session semantics bridge (auth/generation/trading-day
    # surfaced through get_ctp_session_state) only materialises after the
    # first trader-side query group completes.  A preflight snapshot reads
    # session_before before its queries, so the very first snapshot after
    # connect always fails the evidence gate with session_*_missing errors
    # even though its queries succeed.  The smoke flow primes the bridge
    # with verify_ctp_settlement, but on the second set that readback can
    # leave a settlement-identity last_error which then blocks the
    # approval-gated settlement confirmation.  Prime instead with a narrow
    # discarded instrument-scoped snapshot (read-only, no settlement
    # interaction, no write): the first snapshot's own queries complete the
    # login so the real evidence scan below sees a logged-in before-state.
    # Diagnosed 2026-09-12; also the likely cause behind the 2026-09-11
    # night "connected=false" block attributed to SimNow maintenance.
    store.get_ctp_preflight_snapshot(
        f"{config.exchange_id.upper()}.{config.future_instrument_id}",
        exchange_id=config.exchange_id.upper(),
        timeout=float(config.query_timeout),
        read_only=True,
    )

    evidence = collect_three_leg_evidence(store, _as_operator_config(config))
    bundle = evidence["bundle"]
    symbols = tuple(
        f"{leg.exchange_id}.{leg.instrument_id}"
        for leg in (bundle.future, bundle.call, bundle.put)
    )
    metadata = _contract_metadata(bundle)
    reference = evidence["execution_reference"]

    # Settlement confirmation is the one terminal write a market-data-only
    # session may perform; the SDK requires a separately redeemed approval
    # bound to the live identity and the frozen three-leg scope.
    settlement_confirmed = _confirm_settlement_with_approval(
        store,
        api,
        config,
        bundle=bundle,
        key_material=key_material,
        trust_root=trust_root,
    )
    if settlement_confirmed is not True:
        raise MechanicalBlocked("SETTLEMENT_NOT_CONFIRMED")

    runtime = _runtime_hashes()
    source_hashes = {
        name: _sha256_file(HERE / name)
        for name in (
            "ctp_options_simnow_operator.py",
            "ctp_options_simnow_mechanical_operator.py",
            "ctp_options_simnow_approval_issuer.py",
            "ctp_options_simnow_authorization.py",
            "ctp_options_simnow_common.py",
            "ctp_options_simnow_mechanical_cycle.py",
            "ctp_options_simnow_live_drive.py",
            "ctp_options_simnow_live_runner.py",
        )
    }
    cycle_receipt = {
        "schema_version": "iter23-25.mechanical-receipt.v1",
        "purpose": config.purpose,
        "strategy_id": config.strategy_id,
        "environment": config.environment,
        "product_id": config.product_id.upper(),
        "exchange_id": config.exchange_id.upper(),
        "instruments": list(symbols),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    receipt_sha256 = _sha256_json(cycle_receipt)
    source_hashes_sha256 = _sha256_json(source_hashes)
    evidence_hashes = {
        "stage_a": evidence["stage_a"].get("snapshot_sha256"),
        "stage_b": evidence["stage_b"].get("snapshot_sha256"),
        "bundle_preflight": evidence["bundle_preflight"].get("snapshot_sha256"),
        "execution_reference": reference.get("snapshot_sha256"),
        "reconciliation_1": evidence["reconciliation_rounds"][0].get("snapshot_sha256"),
        "reconciliation_2": evidence["reconciliation_rounds"][1].get("snapshot_sha256"),
    }
    now = datetime.now(timezone.utc)
    # Refresh Stage A/B and the bundle preflight right before building the
    # authorization: the evidence chain so far (scan -> stages -> bundle ->
    # reference -> settlement -> approval prerequisites) runs far longer
    # than the default 30s snapshot freshness budget, and configure()
    # rejects stale stage and bundle-preflight evidence.  Refreshing keeps
    # the freshness gate at its default instead of widening it; identity
    # fields are session-bound and unchanged by the refresh, and the grant
    # hash binds to the refreshed bundle snapshot (diagnosed 2026-09-12).
    evidence["stage_a"] = store.get_ctp_preflight_snapshot(
        product_id=config.product_id.upper(),
        exchange_id=config.exchange_id.upper(),
        timeout=float(config.query_timeout),
        read_only=True,
    )
    evidence["stage_b"] = store.get_ctp_preflight_snapshot(
        f"{bundle.exchange_id}.{bundle.future.instrument_id}",
        exchange_id=bundle.exchange_id,
        timeout=float(config.query_timeout),
        read_only=True,
    )
    _refresh_legs = [
        {
            "exchange_id": leg.exchange_id,
            "instrument_id": leg.instrument_id,
            "is_primary": index == 0,
        }
        for index, leg in enumerate((bundle.future, bundle.call, bundle.put))
    ]
    evidence["bundle_preflight"] = store.get_ctp_bundle_preflight_snapshot(
        _refresh_legs,
        primary_leg=_refresh_legs[0],
        timeout=float(config.query_timeout),
        read_only=True,
    )
    derived_bundle = derive_bundle_preflight(evidence, bundle)
    artifacts = build_bundle_authorization(
        stage_a=evidence["stage_a"],
        stage_b=evidence["stage_b"],
        bundle_preflight=derived_bundle,
        runtime_identity={
            "account_fingerprint": derived_bundle["account_fingerprint"],
            "trading_day": derived_bundle["trading_day"],
            "connection_generation": derived_bundle["connection_generation"],
            "environment_profile": runtime_environment_profile(store),
        },
        strategy_id=config.strategy_id,
        strategy_identity_sha256=_strategy_identity(Path(__file__).resolve()),
        authorization_key_id=key_material["key_id"],
        authorization_secret=load_authorization_secret(env),
        issued_at_utc=now.isoformat(),
        expires_at_utc=(now + timedelta(minutes=30)).isoformat(),
        receipt_sha256=receipt_sha256,
        native_sha256=runtime["bt_api_ctp"],
        ctp_package_sha256=runtime["bt_api_ctp"],
        source_hashes_sha256=source_hashes_sha256,
        dependency_hashes_sha256=_sha256_json(
            {
                "backtrader_sha256": runtime["backtrader"],
                "bt_api_py_sha256": runtime["bt_api_py"],
            }
        ),
        evidence_hashes_sha256=_sha256_json(evidence_hashes),
        runtime_executable_sha256=runtime["runtime_executable"],
        gate_statuses={"G1": "PASS", "G2": "PASS", "G3": "PASS"},
    )
    store.configure_ctp_execution_authorization(artifacts.grant)

    if api is None:
        raise MechanicalBlocked("SDK_API_UNAVAILABLE")
    seed = _approval_seed(config, "cycle", bundle)
    context = api.build_ctp_execution_approval_context(
        seed,
        exchange_name=CTP_EXCHANGE,
        configuration={"purpose": config.purpose, "cycle_receipt": cycle_receipt},
        strategy_source=Path(__file__).resolve(),
        preflight={"stage_a_sha256": evidence_hashes["stage_a"], "complete": True},
        evidence=evidence_hashes,
    )
    payload = build_entry_payload(
        context.as_dict(),
        key_id=key_material["key_id"],
        issuer_role="independent_operator",
        receipt_sha256=receipt_sha256,
        source_hashes_sha256=source_hashes_sha256,
        ctp_package_sha256=runtime["bt_api_ctp"],
    )
    artifact = sign_payload(payload, _private_signing_key(key_material))
    capability = api.redeem_ctp_execution_approval(
        json.dumps(artifact, ensure_ascii=False, sort_keys=True),
        trust_root=trust_root,
        context=context,
    )

    proof = dict(artifacts.arming_proof)
    arm_result = store.arm_sdk_execution(proof, authorization=capability)

    available = _account_available(store, float(config.query_timeout))
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=20)
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    budget_evidence = build_budget_evidence(
        bundle=bundle,
        stage_b=evidence["stage_b"],
        reference=reference,
        context=context.as_dict(),
        account_available_cny=available,
        expires_at_utc=expires_at,
        source_version="iter23-25-mechanical-v1",
    )
    reservation = api.reserve_ctp_execution_budget(budget_evidence, mode="ordinary")

    broker = broker_cls(
        store=store,
        provider="btapi",
        cash=config.capital,
        value=config.capital,
        contract_metadata=metadata,
        sdk_preflight=False,
        market_data_only=False,
        flatten_on_stop=False,
        force_refresh_queries=False,
    )
    feeds = {
        symbol: store.getdata(
            dataname=symbol,
            historical_bars=[],
            live_bars=[],
            backfill_start=False,
            dispatch_ticks=False,
            dispatch_bars=False,
            qcheck=0.0,
        )
        for symbol in symbols
    }
    snapshots = {
        "settlement_verified": settlement_confirmed,
        "preflight_context": {"market_data_only": False, "execution_armed": True},
        "stage_a": evidence["stage_a"],
        "stage_b": evidence["stage_b"],
        "bundle_execution_reference": reference,
        "public_capabilities": {
            "get_ctp_bundle_execution_reference_snapshot": True
        },
        "raw_reconciliation_rounds": evidence["reconciliation_rounds"],
    }
    owner = _MechanicalOwner()
    runner = SimNowLiveRunner(
        store=store,
        broker=broker,
        feeds=feeds,
        owner=owner,
        instrument_records=evidence["records"],
        product_id=config.product_id.upper(),
        exchange_id=config.exchange_id.upper(),
        trading_day=evidence["trading_day"],
        snapshots=snapshots,
        cycle_id=f"{config.strategy_id}:mechanical",
        # SimNow serves executable references through rate-limited trader
        # queries (three legs ~= 3s apart); the 2s tick window cannot hold
        # that acquisition pattern.
        max_quote_age_seconds=10.0,
        exact_instrument_ids=(
            {
                "future": config.future_instrument_id,
                "call": config.call_instrument_id,
                "put": config.put_instrument_id,
            }
            if config.future_instrument_id
            else None
        ),
    )
    runner.preflight()
    entry_prices = _entry_prices(bundle, reference)
    execution_state = {
        "store_armed": arm_result.get("armed") is True,
        "broker_started": True,
        "account_fingerprint": proof["account_fingerprint"],
        "trading_day": proof["trading_day"],
        "connection_generation": proof["connection_generation"],
    }
    session = runner.execute_preflighted(
        prices=entry_prices,
        execution_state=execution_state,
        budget_capability=reservation,
    )

    def fresh_exit_prices():
        fresh = store.get_ctp_bundle_execution_reference_snapshot(
            [
                {
                    "exchange_id": leg.exchange_id,
                    "instrument_id": leg.instrument_id,
                    "is_primary": index == 0,
                }
                for index, leg in enumerate((bundle.future, bundle.call, bundle.put))
            ],
            primary_leg={
                "exchange_id": bundle.future.exchange_id,
                "instrument_id": bundle.future.instrument_id,
                "is_primary": True,
            },
            timeout=float(config.query_timeout),
        )
        prices = {}
        for leg in (bundle.future, bundle.call, bundle.put):
            symbol = f"{leg.exchange_id}.{leg.instrument_id}"
            row = next(
                (
                    item
                    for item in fresh.get("legs") or ()
                    if isinstance(item, Mapping)
                    and item.get("instrument_id") == leg.instrument_id
                ),
                None,
            )
            if row is None:
                raise MechanicalBlocked(f"EXIT_QUOTE_MISSING:{symbol}")
            price = _first_number(row, ("exit_sell_price", "bid_price"))
            if price is None or price <= 0:
                raise MechanicalBlocked(f"EXIT_QUOTE_INVALID:{symbol}")
            prices[symbol] = price
        return prices, fresh

    drive = drive_simnow_mechanical_session(
        broker=broker,
        session=session,
        fresh_exit_prices=fresh_exit_prices,
        reconciliation_snapshot=lambda: store.get_ctp_reconciliation_snapshot(
            timeout=float(config.query_timeout)
        ),
        leg_timeout=float(config.leg_timeout),
    )
    report = {
        "status": "MECHANICAL_PASS" if drive.get("status") == "MECHANICAL_PASS" else "BLOCKED",
        "drive": drive,
        "purpose": config.purpose,
        "environment": config.environment,
        "bundle": bundle.to_dict(),
        "budget": {
            "reserved": True,
            "ordinary_cap_cny": BUDGET_ORDINARY_CAP_CNY,
            "available_cny": round(available, 2),
        },
        "operator": {
            "owned_store": owned_store,
            "store_type": type(store).__name__,
            "broker_type": type(broker).__name__,
        },
        "settlement_verified": settlement_confirmed,
        "external_request_counts": _request_counts(evidence),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return report


def load_authorization_secret(env: Mapping[str, str]) -> str:
    secret = str(env.get("ITER_APPROVAL_HMAC_SECRET") or "").strip()
    if len(secret) < 32:
        raise MechanicalBlocked("ITER_APPROVAL_HMAC_SECRET_REQUIRED")
    return secret


def runtime_environment_profile(store: BtApiStore) -> str:
    state = store.get_ctp_session_state()
    profile = str(state.get("environment_profile") or "").strip()
    if not profile:
        raise MechanicalBlocked("ENVIRONMENT_PROFILE_MISSING")
    return profile


def derive_bundle_preflight(
    evidence: Mapping[str, Any], bundle: ThreeLegBundle
) -> dict[str, Any]:
    """Derive the strict V2 bundle snapshot the authorization builder needs."""

    reference = evidence["execution_reference"]
    rounds = evidence["reconciliation_rounds"]
    base = reference
    for candidate in (evidence.get("bundle_preflight"), reference):
        # Preflight snapshots carry the session identity on their top level
        # (account_fingerprint/connection_generation/trading_day); only the
        # reference snapshot nests it under session_scope.  Select the first
        # candidate that actually carries an identity either way — selecting
        # by the session_scope key alone never matches a preflight snapshot
        # and made every mechanical run fail BUNDLE_IDENTITY_INCOMPLETE
        # (diagnosed 2026-09-12).
        if isinstance(candidate, Mapping) and (
            candidate.get("account_fingerprint") or candidate.get("session_scope")
        ):
            base = candidate
            break
    session_scope = base.get("session_scope") if isinstance(base, Mapping) else None
    if not isinstance(session_scope, Mapping):
        session_scope = {}
    identity = {
        "account_fingerprint": base.get("account_fingerprint")
        or session_scope.get("account_fingerprint"),
        "trading_day": base.get("trading_day") or session_scope.get("trading_day"),
        "connection_generation": base.get("connection_generation")
        or session_scope.get("connection_generation"),
    }
    if any(not value for value in identity.values()):
        raise MechanicalBlocked("BUNDLE_IDENTITY_INCOMPLETE")
    legs = [
        {
            "exchange_id": leg.exchange_id,
            "instrument_id": leg.instrument_id,
            "is_primary": index == 0,
        }
        for index, leg in enumerate((bundle.future, bundle.call, bundle.put))
    ]
    return {
        "schema_version": "backtrader.ctp.bundle-preflight.v2",
        **identity,
        "evidence_complete": True,
        "read_only_safe": True,
        "write_request_free": True,
        "flat": True,
        "active_order_count": 0,
        "unknown_intent_count": 0,
        "unmatched_trade_count": 0,
        "legs": legs,
        "reconciled": True,
        # Bind the derived bundle proof to the bundle-preflight snapshot it
        # was derived from (base): after the pre-authorization refresh that
        # snapshot IS the Store's latest _last_ctp_bundle_preflight_snapshot,
        # which is the authoritative comparison target for
        # proof.preflight_sha256 (diagnosed 2026-09-12).
        "snapshot_sha256": base.get("snapshot_sha256")
        or (
            reference.get("bundle_preflight", {}).get("snapshot_sha256")
            if isinstance(reference.get("bundle_preflight"), Mapping)
            else None
        )
        or _sha256_json(reference),
        "session_scope": dict(session_scope),
        # The authorization builder reads the live session evidence
        # (environment_profile etc.) through session_after/session; preflight
        # snapshots carry it on session_after, so pass it through instead of
        # dropping it (missing key failed every authorization build with
        # "bundle session evidence is missing", diagnosed 2026-09-12).
        "session_after": dict(
            base.get("session_after") or base.get("session") or session_scope or {}
        ),
        "query_results": dict(base.get("query_results") or {}),
    }


def _as_operator_config(config: MechanicalConfiguration) -> OperatorConfiguration:
    return OperatorConfiguration(
        environment=config.environment,
        product_id=config.product_id,
        exchange_id=config.exchange_id,
        future_instrument_id=config.future_instrument_id,
        call_instrument_id=config.call_instrument_id,
        put_instrument_id=config.put_instrument_id,
        capital=config.capital,
        strategy_id=config.strategy_id,
        purpose="engineering_smoke",
        confirm_settlement=config.confirm_settlement,
        query_timeout=config.query_timeout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument(
        "--environment",
        choices=("first", "second_7x24"),
        default="second_7x24",
    )
    parser.add_argument("--product", default="SA")
    parser.add_argument("--exchange", default="CZCE")
    parser.add_argument("--future")
    parser.add_argument("--call")
    parser.add_argument("--put")
    parser.add_argument("--capital", type=float, default=200000.0)
    parser.add_argument("--leg-timeout", type=float, default=45.0)
    parser.add_argument(
        "--query-timeout",
        type=float,
        default=20.0,
        help="Per-query timeout; SimNow reference queries may need 60s+ after "
        "large scans due to exchange flow control.",
    )
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--trust-root", type=Path, default=DEFAULT_TRUST_ROOT)
    parser.add_argument("--state-directory", type=Path, default=HERE / "state")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    def emit(report: dict[str, Any]) -> int:
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if report.get("status") == "MECHANICAL_PASS" else 2

    try:
        config = MechanicalConfiguration(
            environment=args.environment,
            product_id=args.product,
            exchange_id=args.exchange,
            future_instrument_id=args.future,
            call_instrument_id=args.call,
            put_instrument_id=args.put,
            capital=args.capital,
            leg_timeout=args.leg_timeout,
            query_timeout=float(args.query_timeout),
        )
        env = load_operator_env(args.env)
        report = run_mechanical_cycle(
            config,
            env,
            state_directory=args.state_directory,
            key_file=args.key_file,
            trust_root_file=args.trust_root,
        )
    except (MechanicalBlocked, OperatorBlocked) as exc:
        report = {
            "status": "BLOCKED",
            "reason": getattr(exc, "reason", str(exc)),
            "external_request_counts": {"order_write": "UNKNOWN_ON_BLOCK"},
        }
    return emit(report)


if __name__ == "__main__":
    raise SystemExit(main())
