"""Retired SimNow operator implementation retained for review and tests.

The standalone CLI is disabled under Iteration 41 because the default runtime
registry has no CTP SimNow route. The retained helper APIs document and test
the historical read-only preflight and settlement confirmation flow; invoking
the CLI cannot load credentials or construct a provider.

The standalone operator never prints, logs, or reports a secret. Its retired
CLI fails closed with a stable Iteration 41 error.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

_REPOSITORY_ROOT = str(Path(__file__).resolve().parents[1])
if _REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, _REPOSITORY_ROOT)

from backtrader_runtime.legacy import (  # noqa: E402
    legacy_direct_execution_error as _legacy_direct_execution_error,
)


def main(argv: list[str] | None = None) -> int:
    """Reject the retired standalone SimNow operator before account access."""

    del argv
    error = _legacy_direct_execution_error("examples/ctp_options_simnow_operator.py")
    print(
        json.dumps(
            {
                "status": "BLOCKED",
                "error": error.as_dict(),
                "external_request_counts": {"network": 0, "order_write": 0},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

from backtrader.brokers.btapibroker import BtApiBroker  # noqa: E402 - CLI gate runs first
from backtrader.stores.btapistore import BtApiStore  # noqa: E402 - CLI gate runs first

if __package__:
    from .ctp_options_simnow_common import (
        BundleSelectionError,
        select_three_leg_bundle,
    )
    from .ctp_options_simnow_live_runner import SimNowLiveRunner
else:
    from examples.ctp_options_simnow_common import BundleSelectionError, select_three_leg_bundle
    from examples.ctp_options_simnow_live_runner import SimNowLiveRunner


CTP_EXCHANGE = "CTP___FUTURE"
HERE = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = HERE / ".env"

# The old operator has no Iteration 41 CTP registration. Fake-backed unit
# tests can exercise its assembly contracts with this private opt-in; normal
# calls cannot fall through to a provider or endpoint probe.
_TEST_ONLY_INJECTION_TOKEN = object()

ENVIRONMENTS = frozenset({"first", "second_7x24"})
SDK_PROFILE_FAMILIES = {"first": "set1", "second_7x24": "set2"}
CREDENTIAL_KEYS = (
    "CTP_USER_ID",
    "CTP_PASSWORD",
    "CTP_BROKER_ID",
    "CTP_APP_ID",
    "CTP_AUTH_CODE",
)
QUERY_TIMEOUT_SECONDS = 20.0
SETTLEMENT_VERIFY_TIMEOUT_SECONDS = 30.0


class OperatorBlocked(RuntimeError):
    """A missing or contradictory operator precondition (fail-closed)."""

    def __init__(self, reason: str):
        """Attach the stable machine-readable ``reason`` code."""
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class OperatorConfiguration:
    """Validated operator inputs; secrets stay only in the loaded mapping."""

    environment: str
    product_id: str
    exchange_id: str
    future_instrument_id: str | None = None
    call_instrument_id: str | None = None
    put_instrument_id: str | None = None
    capital: float = 200000.0
    strategy_id: str = "iter23-25-options-smoke"
    purpose: str = "engineering_smoke"
    confirm_settlement: bool = False
    query_timeout: float = QUERY_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if self.environment not in ENVIRONMENTS:
            raise OperatorBlocked(f"ENVIRONMENT_MUST_BE_ONE_OF:{sorted(ENVIRONMENTS)}")
        if self.purpose not in {"engineering_smoke"}:
            raise OperatorBlocked("PURPOSE_NOT_SUPPORTED")
        for name in ("product_id", "exchange_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise OperatorBlocked(f"{name.upper()}_REQUIRED")
        exact = (
            self.future_instrument_id,
            self.call_instrument_id,
            self.put_instrument_id,
        )
        if any(value is not None for value in exact) and not all(
            value is not None for value in exact
        ):
            raise OperatorBlocked("EXACT_BUNDLE_IDS_MUST_BE_COMPLETE")
        if not isinstance(self.capital, (int, float)) or self.capital <= 0:
            raise OperatorBlocked("CAPITAL_MUST_BE_POSITIVE")
        if not isinstance(self.query_timeout, (int, float)) or self.query_timeout <= 0:
            raise OperatorBlocked("QUERY_TIMEOUT_MUST_BE_POSITIVE")


def load_operator_env(path: Path | str = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Load the operator ``.env`` without evaluating shell syntax."""

    env_path = Path(path).expanduser()
    if not env_path.is_file():
        raise OperatorBlocked(f"ENV_FILE_MISSING:{env_path}")
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in values:
            values[key] = value
    return values


def resolve_credentials(env: Mapping[str, str]) -> dict[str, str]:
    """Validate the CTP credential set; never echo secret values."""

    missing = [
        key
        for key in ("CTP_USER_ID", "CTP_PASSWORD", "CTP_APP_ID", "CTP_AUTH_CODE")
        if not str(env.get(key) or "").strip()
    ]
    if missing:
        raise OperatorBlocked(f"CREDENTIALS_MISSING:{','.join(missing)}")
    return {
        "user_id": str(env["CTP_USER_ID"]).strip(),
        "password": str(env["CTP_PASSWORD"]),
        "broker_id": str(env.get("CTP_BROKER_ID") or "9999").strip() or "9999",
        "app_id": str(env["CTP_APP_ID"]).strip(),
        "auth_code": str(env["CTP_AUTH_CODE"]),
    }


def resolve_fronts(
    env: Mapping[str, str],
    environment: str,
    *,
    selector: Callable[..., Any] | None = None,
    _test_only_injection: object | None = None,
) -> dict[str, str]:
    """Resolve explicit fronts or use a test-injected selector.

    There is no default SDK selector: this historical operator has no sealed
    Iteration 41 CTP runtime registration. Front discovery is available only
    to fake-backed tests that explicitly supply the private injection token.
    """

    if environment not in ENVIRONMENTS:
        raise OperatorBlocked(f"ENVIRONMENT_MUST_BE_ONE_OF:{sorted(ENVIRONMENTS)}")
    td_front = str(env.get("CTP_TD_FRONT") or "").strip()
    md_front = str(env.get("CTP_MD_FRONT") or "").strip()
    if bool(td_front) != bool(md_front):
        raise OperatorBlocked("CTP_TD_FRONT_AND_CTP_MD_FRONT_MUST_BE_SET_TOGETHER")
    if td_front:
        profile = str(env.get("CTP_ENV_PROFILE") or "").strip().lower()
        if not profile:
            raise OperatorBlocked("CTP_ENV_PROFILE_REQUIRED_WITH_EXPLICIT_FRONTS")
        return {
            "profile": environment,
            "sdk_profile": profile,
            "td_front": td_front,
            "md_front": md_front,
        }
    if (
        selector is None
        or _test_only_injection is not _TEST_ONLY_INJECTION_TOKEN
        or getattr(selector, "__backtrader_test_double__", False) is not True
    ):
        raise _legacy_direct_execution_error("examples/ctp_options_simnow_operator.py")

    family = SDK_PROFILE_FAMILIES[environment]
    try:
        selection = selector(env=family)
    except Exception as exc:
        raise OperatorBlocked(f"FRONT_PROBE_FAILED:{type(exc).__name__}") from exc
    profile = str(getattr(selection, "profile", "") or "").strip().lower()
    td_front = str(getattr(selection, "td_front", "") or "").strip()
    md_front = str(getattr(selection, "md_front", "") or "").strip()
    if not profile or not td_front or not md_front:
        raise OperatorBlocked("FRONT_PROBE_INCOMPLETE")
    return {
        "profile": environment,
        "sdk_profile": profile,
        "td_front": td_front,
        "md_front": md_front,
    }


def strategy_identity_sha256(config: OperatorConfiguration) -> str:
    """Bind the SDK journal to this operator entry's stable source provenance."""

    material = {
        "schema_version": "iter23-25.options-operator.v1",
        "strategy_id": config.strategy_id,
        "purpose": config.purpose,
        "product_id": config.product_id.upper(),
        "exchange_id": config.exchange_id.upper(),
        "operator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_live_store(
    credentials: Mapping[str, str],
    fronts: Mapping[str, str],
    config: OperatorConfiguration,
    *,
    state_directory: Path,
    api_cls: Any = None,
    store_cls: Any = None,
    _test_only_injection: object | None = None,
    execution_authorization_key_id: str | None = None,
    execution_authorization_secret: str | None = None,
    strategy_identity_sha256: str | None = None,
) -> BtApiStore:
    """Build a fake-backed Store for tests; real Store construction is closed.

    This module has no sealed Iteration 41 CTP runtime registration, so it
    cannot construct the default ``BtApiStore``. Tests must explicitly inject
    a Store class and the private test-only token. SDK API-class injection is
    not supported here.
    """

    if (
        _test_only_injection is not _TEST_ONLY_INJECTION_TOKEN
        or store_cls is None
        or store_cls is BtApiStore
        or (isinstance(store_cls, type) and issubclass(store_cls, BtApiStore))
        or getattr(store_cls, "__backtrader_test_double__", False) is not True
        or api_cls is not None
    ):
        raise _legacy_direct_execution_error("examples/ctp_options_simnow_operator.py")

    account_hash = hashlib.sha256(
        f"{credentials['broker_id']}:{credentials['user_id']}".encode("utf-8")
    ).hexdigest()
    sdk_state = state_directory / account_hash / "sdk"
    exchange_kwargs = {
        CTP_EXCHANGE: {
            "broker_id": credentials["broker_id"],
            "user_id": credentials["user_id"],
            "password": credentials["password"],
            "app_id": credentials["app_id"],
            "auth_code": credentials["auth_code"],
            "td_front": fronts["td_front"],
            "md_front": fronts["md_front"],
            "ctp_env_profile": fronts["sdk_profile"],
            "require_ctp_profile": fronts["sdk_profile"],
            "auto_settlement_confirm": False,
        }
    }
    execution_config = {
        "market_data_only": True,
        "order_journal": str(sdk_state / "orders.jsonl"),
        "account_risk_state": str(sdk_state / "account-risk.json"),
        "require_order_journal": True,
        "account_currency": "CNY",
        "required_environments": {CTP_EXCHANGE: "demo"},
        "strategy_id": config.strategy_id,
        "strategy_identity_sha256": strategy_identity_sha256 or strategy_identity_sha256_of(config),
    }
    store_options: dict[str, Any] = {
        "provider": "btapi",
        "backend": "direct",
        "config": {
            "exchange_kwargs": exchange_kwargs,
            "symbol_routes": {},
            "execution_config": execution_config,
            "require_account_risk": False,
            "book_queue_size": 1,
        },
    }
    if execution_authorization_key_id and execution_authorization_secret:
        store_options["config"]["execution_authorization_key_id"] = execution_authorization_key_id
        store_options["config"]["execution_authorization_secret"] = execution_authorization_secret
    return store_cls(**store_options)


def strategy_identity_sha256_of(config: OperatorConfiguration) -> str:
    """Default strategy identity bound to the operator entry's provenance."""

    return strategy_identity_sha256(config)


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatorBlocked(f"{name}_SCHEMA_INVALID")
    return value


def _require_complete_read_only(snapshot: Mapping[str, Any], label: str) -> None:
    if snapshot.get("evidence_complete") is not True:
        raise OperatorBlocked(f"{label}_EVIDENCE_INCOMPLETE")
    if snapshot.get("read_only_safe") is not True:
        raise OperatorBlocked(f"{label}_NOT_READ_ONLY")
    if snapshot.get("write_request_free") is not True:
        raise OperatorBlocked(f"{label}_WRITE_REQUEST_OBSERVED")


def _verify_or_confirm_settlement(store: BtApiStore, config: OperatorConfiguration) -> bool:
    """Prove the settlement state read-only; optionally confirm it once.

    ``verify_ctp_settlement`` is read-only: its ``evidence_complete`` folds the
    server-side settlement confirmation together with write-free evidence.
    Only an explicit ``confirm_settlement`` operator action performs the one
    sanctioned settlement confirmation write through ``prepare_ctp_settlement``
    (settlement-only scope; it never grants an order right).
    """

    def verify() -> Mapping[str, Any]:
        result = _require_mapping(
            store.verify_ctp_settlement(timeout=SETTLEMENT_VERIFY_TIMEOUT_SECONDS),
            "SETTLEMENT_VERIFY",
        )
        if result.get("read_only_safe") is not True:
            raise OperatorBlocked("SETTLEMENT_VERIFY_NOT_READ_ONLY")
        return result

    verified = verify().get("evidence_complete") is True
    if verified or not config.confirm_settlement:
        return verified
    preparation = _require_mapping(
        store.prepare_ctp_settlement(timeout=SETTLEMENT_VERIFY_TIMEOUT_SECONDS),
        "SETTLEMENT_PREPARE",
    )
    if preparation.get("evidence_complete") is not True:
        raise OperatorBlocked(
            "SETTLEMENT_CONFIRMATION_INCOMPLETE:" + str(preparation.get("error_code") or "unknown")
        )
    confirmed = verify().get("evidence_complete") is True
    if not confirmed:
        raise OperatorBlocked("SETTLEMENT_CONFIRMATION_NOT_PROVEN")
    return True


def collect_three_leg_evidence(
    store: BtApiStore,
    config: OperatorConfiguration,
) -> dict[str, Any]:
    """Collect the full read-only three-leg evidence chain through public APIs.

    Order matters: the exchange-wide instrument scan runs first so the
    Store's Stage A/B preflight history (a length-2 deque) holds exactly the
    product-scoped Stage A and the exact-future Stage B snapshots that the
    governed authorization contract expects.
    """

    timeout = float(config.query_timeout)
    exchange_id = config.exchange_id.upper()
    product_id = config.product_id.upper()

    scan = _require_mapping(
        store.get_ctp_preflight_snapshot(exchange_id=exchange_id, timeout=timeout, read_only=True),
        "INSTRUMENT_SCAN",
    )
    _require_complete_read_only(scan, "INSTRUMENT_SCAN")
    records = list(scan.get("instruments") or [])
    if not records:
        raise OperatorBlocked("INSTRUMENT_SCAN_EMPTY")
    trading_day = str(scan.get("trading_day") or "").strip()
    if not trading_day:
        raise OperatorBlocked("TRADING_DAY_MISSING")

    try:
        bundle = select_three_leg_bundle(
            records,
            product_id=product_id,
            exchange_id=exchange_id,
            trading_day=trading_day,
            future_instrument_id=config.future_instrument_id,
            call_instrument_id=config.call_instrument_id,
            put_instrument_id=config.put_instrument_id,
        )
    except BundleSelectionError as exc:
        raise OperatorBlocked(f"BUNDLE_SELECTION_FAILED:{exc.reason}") from exc

    stage_a = _require_mapping(
        store.get_ctp_preflight_snapshot(
            product_id=product_id, exchange_id=exchange_id, timeout=timeout, read_only=True
        ),
        "STAGE_A",
    )
    _require_complete_read_only(stage_a, "STAGE_A")
    stage_b = _require_mapping(
        store.get_ctp_preflight_snapshot(
            f"{bundle.exchange_id}.{bundle.future.instrument_id}",
            exchange_id=bundle.exchange_id,
            timeout=timeout,
            read_only=True,
        ),
        "STAGE_B",
    )
    _require_complete_read_only(stage_b, "STAGE_B")

    legs = [
        {
            "exchange_id": leg.exchange_id,
            "instrument_id": leg.instrument_id,
            "is_primary": index == 0,
        }
        for index, leg in enumerate((bundle.future, bundle.call, bundle.put))
    ]
    bundle_preflight = _require_mapping(
        store.get_ctp_bundle_preflight_snapshot(
            legs, primary_leg=legs[0], timeout=timeout, read_only=True
        ),
        "BUNDLE_PREFLIGHT",
    )
    _require_complete_read_only(bundle_preflight, "BUNDLE_PREFLIGHT")

    reconciliation_rounds = []
    for round_index in (1, 2):
        snapshot = _require_mapping(
            store.get_ctp_reconciliation_snapshot(timeout=timeout),
            f"RECONCILIATION_{round_index}",
        )
        if snapshot.get("evidence_complete") is not True:
            raise OperatorBlocked(f"RECONCILIATION_{round_index}_EVIDENCE_INCOMPLETE")
        reconciliation_rounds.append(snapshot)

    # The execution reference carries the freshest leg quotes; collect it
    # last so the governed runner's quote-age window still holds after the
    # rate-limited reconciliation rounds.
    execution_reference = _require_mapping(
        store.get_ctp_bundle_execution_reference_snapshot(
            legs, primary_leg=legs[0], timeout=timeout
        ),
        "EXECUTION_REFERENCE",
    )
    if execution_reference.get("evidence_complete") is not True:
        raise OperatorBlocked(
            f"EXECUTION_REFERENCE_INCOMPLETE:{','.join(execution_reference.get('evidence_errors') or [])}"
        )

    return {
        "records": records,
        "trading_day": trading_day,
        "bundle": bundle,
        "legs": legs,
        "stage_a": stage_a,
        "stage_b": stage_b,
        "bundle_preflight": bundle_preflight,
        "execution_reference": execution_reference,
        "reconciliation_rounds": reconciliation_rounds,
    }


class _SmokeOwner:
    """Minimal notification sink; the mechanical session drains the broker queue."""

    def notify_order(self, order: Any) -> None:  # pragma: no cover - trivial sink
        """Discard the notification; the session loop drains the broker queue."""
        del order

    def notify_trade(self, trade: Any) -> None:  # pragma: no cover - trivial sink
        """Discard the notification; the session loop drains the broker queue."""
        del trade


def _contract_metadata(bundle: Any) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for leg in (bundle.future, bundle.call, bundle.put):
        symbol = f"{leg.exchange_id}.{leg.instrument_id}"
        metadata[symbol] = {
            "tick_size": float(leg.tick_size),
            "contract_multiplier": float(leg.multiplier),
            "min_size": 1,
            "lot_size": 1,
            "quantity_step": 1,
            "currency": "CNY",
        }
    return metadata


def run_engineering_smoke(
    config: OperatorConfiguration,
    env: Mapping[str, str],
    *,
    state_directory: Path,
    store: BtApiStore | None = None,
    broker_cls: Any = BtApiBroker,
) -> dict[str, Any]:
    """Drive the read-only preflight only through an explicitly injected Store."""

    if store is None:
        raise _legacy_direct_execution_error("examples/ctp_options_simnow_operator.py")
    del env, state_directory  # No credentials or Store construction in this injected path.

    settlement_confirmed = _verify_or_confirm_settlement(store, config)

    evidence = collect_three_leg_evidence(store, config)
    bundle = evidence["bundle"]
    symbols = tuple(
        f"{leg.exchange_id}.{leg.instrument_id}" for leg in (bundle.future, bundle.call, bundle.put)
    )
    metadata = _contract_metadata(bundle)
    broker = broker_cls(
        store=store,
        provider="btapi",
        cash=config.capital,
        value=config.capital,
        contract_metadata=metadata,
        sdk_preflight=False,
        market_data_only=True,
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
        "preflight_context": {"market_data_only": True, "execution_armed": False},
        "stage_a": evidence["stage_a"],
        "stage_b": evidence["stage_b"],
        "bundle_execution_reference": evidence["execution_reference"],
        "public_capabilities": {"get_ctp_bundle_execution_reference_snapshot": True},
        "raw_reconciliation_rounds": evidence["reconciliation_rounds"],
    }
    runner = SimNowLiveRunner(
        store=store,
        broker=broker,
        feeds=feeds,
        owner=_SmokeOwner(),
        instrument_records=evidence["records"],
        product_id=config.product_id.upper(),
        exchange_id=config.exchange_id.upper(),
        trading_day=evidence["trading_day"],
        snapshots=snapshots,
        cycle_id=f"{config.strategy_id}:smoke",
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
    preflight_report = runner.preflight()
    report = {
        "status": "ENGINEERING_SMOKE_PASS",
        "mode": "simnow",
        "purpose": "engineering_smoke",
        "environment": config.environment,
        "operator": {
            "owned_store": False,
            "store_type": type(store).__name__,
            "broker_type": type(broker).__name__,
        },
        "settlement_verified": settlement_confirmed,
        "preflight": preflight_report,
        "bundle_count": 1,
        "external_request_counts": _request_counts(evidence),
        "native_execution_status": "NOT_CLAIMED_NO_NATIVE_CONFIRMATION",
        "order_write_allowed": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return report


def _request_counts(evidence: Mapping[str, Any]) -> dict[str, int]:
    """Aggregate observed write-request deltas across the evidence chain."""

    order_write = 0
    observed = False
    for snapshot in (
        evidence["stage_a"],
        evidence["stage_b"],
        evidence["bundle_preflight"],
        evidence["execution_reference"],
        *evidence["reconciliation_rounds"],
    ):
        delta = snapshot.get("request_count_delta")
        if isinstance(delta, Mapping):
            observed = True
            order_write += sum(
                int(delta.get(key, 0) or 0) for key in ("order_insert", "order_action")
            )
    return {"order_write": order_write if observed else "NOT_OBSERVED"}
