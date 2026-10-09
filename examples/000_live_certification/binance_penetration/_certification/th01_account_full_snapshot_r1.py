"""Source-bound full account snapshot mapper for Binance TH01.

This module does not read credentials or call Binance. Root supplies the
sealed pages collected by one protected owner invocation. A complete
``StateSnapshot`` is returned only after every current and bounded history
route is tied to that same invocation and the account-wide symbol coverage
tree is complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping
from uuid import UUID, uuid4

from . import cases, models, runner


SCHEMA = "iteration41.binance.th01.account-full-snapshot.r1"
SOURCE = "provider:binance_demo_signed_rest_readonly_v1"
SOURCE_INSTANCE = "binance-demo-fixed-rest-root-v1"
SOURCE_CHANNEL = "signed-get-v1"
CURRENT_ROUTES = (
    "account_configuration",
    "account_v2",
    "standard_open_orders",
    "algo_open_orders",
)
ALL_ORDERS_RESOURCE = "all_orders_in_window"
FORCE_ORDERS_RESOURCE = "force_orders_in_window"
INCOME_RESOURCE = "income_in_window"
USER_TRADES_RESOURCE = "user_trades_in_window"
PAGE_LIMIT = 1000
FORCE_ORDER_LIMIT = 100
MAX_REQUESTS = 64
MAX_ROWS = 5000
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_CAPTURE_MS = 120_000
MAX_SNAPSHOT_AGE_MS = 120_000
MIN_HISTORY_CUTOFF_LAG_MS = 2_000
MAX_ACCOUNT_WINDOW_MS = 72 * 60 * 60 * 1000
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
FORCE_ORDERS_EXTENSION_SHA256 = "aaa2e10d2c37ea4cfbb69d18d860db12569b4043b7b45c70a0bbf65f22bd7f6e"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL = re.compile(r"[A-Z0-9_]{1,32}\Z")
_CURRENCY = re.compile(r"[A-Z0-9]{2,24}\Z")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_BASELINE_SEAL = object()
_CAPTURE_SEAL = object()
_ISSUED_ACTIONS: dict[str, tuple[str, str, models.ActionPlan]] = {}


class AccountSnapshotBlocked(ValueError):
    """Fixed public reason without provider, account, or OS values."""

    def __init__(self, code: str):
        if type(code) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "account_snapshot_blocked"
        self.code = code
        super().__init__(code)


def _block(code: str) -> None:
    raise AccountSnapshotBlocked(code)


@dataclass(frozen=True, repr=False)
class BaselineAnchorV1:
    """Private anchor tying later reads to the original Root invocation."""

    invocation_id: str
    evidence_window_id: str
    history_start_ms: int
    t0_ms: int
    snapshot: models.StateSnapshot = field(repr=False)
    _auth: object = field(repr=False, compare=False)
    _owner: object = field(repr=False, compare=False)
    _account_binding_ref: str = field(repr=False)
    _seed_symbols: frozenset[str] = field(repr=False)
    _open_order_keys: frozenset[tuple[str, int]] = field(repr=False)
    _seen_refs: list[str] = field(repr=False, compare=False)
    _last_snapshot: list[models.StateSnapshot] = field(repr=False, compare=False)
    _next_phase: list[str] = field(repr=False, compare=False)
    _last_cutoff_ms: list[int] = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "BaselineAnchorV1(<Root-bound-private-anchor>)"


@dataclass(frozen=True, repr=False)
class SnapshotHistoryEvidenceV1:
    phase: str
    history_start_ms: int
    phase_cutoff_ms: int
    interval: str
    universe_basis: tuple[str, ...]
    page_count: int
    row_count: int
    symbols_queried: tuple[str, ...] = field(repr=False)
    pages: tuple[object, ...] = field(repr=False)

    def __repr__(self) -> str:
        return "SnapshotHistoryEvidenceV1(<protected-window-evidence>)"


@dataclass(frozen=True, repr=False)
class SnapshotCaptureV1:
    snapshot: models.StateSnapshot = field(repr=False)
    baseline: BaselineAnchorV1 = field(repr=False)
    history_evidence: SnapshotHistoryEvidenceV1 | None = field(repr=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "SnapshotCaptureV1(<protected-account-snapshot>)"


def _owner_for_auth(auth: object) -> Any:
    module_name = getattr(type(auth), "__module__", None)
    owner = sys.modules.get(module_name) if type(module_name) is str else None
    if owner is None:
        _block("root_owner_module_unavailable")
    expected_path = Path(__file__).resolve().with_name("th01_root_protected_owner_r1.py")
    try:
        actual_path = Path(owner.__file__).resolve(strict=True)
        source_stat = expected_path.lstat()
        source_bytes = expected_path.read_bytes()
    except Exception:
        _block("root_owner_source_unavailable")
    if (
        actual_path != expected_path.resolve(strict=True)
        or not expected_path.is_file()
        or expected_path.is_symlink()
        or int(getattr(source_stat, "st_file_attributes", 0)) & 0x400
        or hashlib.sha256(source_bytes).hexdigest() != OWNER_SHA256
    ):
        _block("root_owner_source_pin_mismatch")
    page_type = getattr(owner, "_RootTH01AccountWindowPageV1", None)
    auth_type = getattr(owner, "_RootTH01AccountWindowAuthV1", None)
    reader_type = getattr(owner, "FixedAccountWindowGetV1", None)
    if (
        type(auth) is not auth_type
        or getattr(auth, "_seal", None) is not getattr(owner, "_ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL", None)
        or type(getattr(auth, "_reader", None)) is not reader_type
        or getattr(auth._reader, "_seal", None)
        is not getattr(owner, "_ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL", None)
        or page_type is None
    ):
        _block("root_account_window_capability_invalid")
    reader = auth._reader
    if (
        reader.invocation_id != auth.invocation_id
        or reader.evidence_window_id != auth.evidence_window_id
        or reader._account_binding_ref != auth._account_binding_ref
        or type(auth.invocation_id) is not str
        or _HEX32.fullmatch(auth.invocation_id) is None
        or auth.evidence_window_id != "th01-window:" + auth.invocation_id
        or type(auth._account_binding_ref) is not str
        or _HEX64.fullmatch(auth._account_binding_ref) is None
    ):
        _block("root_account_window_binding_invalid")
    return owner


def _verify_force_orders_extension(owner: Any) -> None:
    """Require the exact source-pinned forceOrders extension in this owner."""
    source_path = Path(__file__).resolve().with_name("th01_force_orders_transport_r1.py")
    try:
        source_stat = source_path.lstat()
        if (
            source_path.is_symlink()
            or not source_path.is_file()
            or int(getattr(source_stat, "st_file_attributes", 0)) & 0x400
            or source_stat.st_size > 200_000
        ):
            _block("force_orders_extension_source_shape_invalid")
        source_bytes = source_path.read_bytes()
        after_stat = source_path.lstat()
        verify_owner = getattr(owner, "verify_force_orders_owner_binding", None)
        marker = getattr(owner, "_ROOT_TH01_FORCE_ORDERS_EXTENSION_SHA256", None)
    except AccountSnapshotBlocked:
        raise
    except Exception:
        _block("force_orders_extension_unavailable")
    if (
        source_path.is_symlink()
        or not source_path.is_file()
        or int(getattr(after_stat, "st_file_attributes", 0)) & 0x400
        or after_stat.st_size != len(source_bytes)
        or len(source_bytes) != source_stat.st_size
        or hashlib.sha256(source_bytes).hexdigest() != FORCE_ORDERS_EXTENSION_SHA256
        or marker != FORCE_ORDERS_EXTENSION_SHA256
        or not callable(verify_owner)
    ):
        _block("force_orders_extension_source_pin_mismatch")
    try:
        bound = verify_owner(owner)
    except Exception:
        bound = False
    if bound is not True:
        _block("force_orders_extension_binding_invalid")


def root_th01_read_action(
    auth: object, *, external_ref: str, config_snapshot_id: str
) -> models.Action:
    """Create the one permitted TH01 READ action from Root-owned context.

    ``external_ref`` is the selected TH01 case parameter. The config snapshot
    identifier must come from the verified active TradeLogger configuration.
    These values do not grant account-read authority; that remains the sealed
    auth object produced by the protected Root reader.
    """
    _owner_for_auth(auth)
    if (
        type(external_ref) is not str
        or _IDENTIFIER.fullmatch(external_ref) is None
        or type(config_snapshot_id) is not str
        or _IDENTIFIER.fullmatch(config_snapshot_id) is None
    ):
        _block("th01_action_parameter_invalid")
    case_spec = cases.CASES.get("TH01")
    if (
        case_spec is None
        or case_spec.action != "inspect_submit_threshold"
        or case_spec.risk is not models.Risk.READ
        or case_spec.event != "submit_threshold_observed"
    ):
        _block("th01_case_contract_invalid")
    params = {
        "external_ref": external_ref,
        "evidence_window_id": auth.evidence_window_id,
        "expected_threshold": 5,
        "config_snapshot_id": config_snapshot_id,
    }
    try:
        plan = runner._plan("TH01", params, None, None, "USDT", venue="binance")
    except Exception:
        _block("th01_read_plan_unavailable")
    if (
        type(plan) is not models.ActionPlan
        or plan.order_count != 0
        or plan.total_quantity != 0
        or plan.total_notional != 0
        or plan.notional_currency != "USDT"
        or len(plan.operations) != 1
    ):
        _block("th01_read_plan_invalid")
    operation = plan.operations[0]
    if (
        type(operation) is not models.PlannedOperation
        or operation.phase != "execute"
        or operation.kind != "read"
        or operation.client_order_id is not None
        or operation.target_order_id is not None
        or operation.symbol is not None
        or operation.side is not None
        or operation.quantity != 0
        or operation.price != 0
        or operation.order_type is not None
        or operation.position_id is not None
        or operation.reduce_only is not False
        or operation.instrument_spec_id is not None
        or operation.position_side is not None
        or operation.time_in_force is not None
        or operation.request_digest is not None
    ):
        _block("th01_read_plan_invalid")
    action = models.Action(
        case_id="TH01",
        name="inspect_submit_threshold",
        risk=models.Risk.READ,
        binding=models.Binding("binance", "demo", "sandbox", auth._account_binding_ref),
        params=params,
        correlation_id=auth.invocation_id,
        client_id="th01-" + auth.invocation_id,
        attested_session_id=None,
        evidence_window_id=auth.evidence_window_id,
        plan=plan,
    )
    _ISSUED_ACTIONS[auth.invocation_id] = (external_ref, config_snapshot_id, plan)
    return action


def _validate_action(auth: object, action: object) -> None:
    issued = _ISSUED_ACTIONS.get(auth.invocation_id)
    if (
        issued is None
        or type(action) is not models.Action
        or action.case_id != "TH01"
        or action.name != "inspect_submit_threshold"
        or action.risk is not models.Risk.READ
        or action.binding
        != models.Binding("binance", "demo", "sandbox", auth._account_binding_ref)
        or action.correlation_id != auth.invocation_id
        or action.client_id != "th01-" + auth.invocation_id
        or action.evidence_window_id != auth.evidence_window_id
        or action.attested_session_id is not None
        or type(action.params) is not dict
        or set(action.params)
        != {"external_ref", "evidence_window_id", "expected_threshold", "config_snapshot_id"}
        or action.params.get("evidence_window_id") != auth.evidence_window_id
        or action.params.get("expected_threshold") != 5
        or type(action.params.get("external_ref")) is not str
        or _IDENTIFIER.fullmatch(action.params["external_ref"]) is None
        or type(action.params.get("config_snapshot_id")) is not str
        or _IDENTIFIER.fullmatch(action.params["config_snapshot_id"]) is None
        or action.params.get("external_ref") != issued[0]
        or action.params.get("config_snapshot_id") != issued[1]
        or action.plan != issued[2]
    ):
        _block("th01_action_binding_invalid")


def _uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def _page_rows(owner: Any, auth: object, page: object, resource: str,
               start_ms: int, end_ms: int, *, current: bool = False) -> tuple[dict[str, Any], ...]:
    page_type = owner._RootTH01AccountWindowPageV1
    reader = auth._reader
    if (
        type(page) is not page_type
        or page._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL
        or page.resource != resource
        or page._invocation_id != auth.invocation_id
        or page._evidence_window_id != auth.evidence_window_id
        or page._account_binding_ref != auth._account_binding_ref
        or not _uuid(page.request_ref)
        or not _uuid(page.response_ref)
        or page.request_ref == page.response_ref
        or type(page._private_record_ref) is not str
        or _HEX32.fullmatch(page._private_record_ref) is None
        or page._private_record_ref not in reader._private_record_refs
        or type(page.response_body) is not bytes
        or not page.response_body
        or len(page.response_body) > MAX_PAGE_BYTES
        or page.requested_start_ms != start_ms
        or page.requested_end_ms != end_ms
        or type(page.request_started_at_ms) is not int
        or type(page.response_completed_at_ms) is not int
        or page.request_started_at_ms <= 0
        or page.response_completed_at_ms < page.request_started_at_ms
        or page.http_status != 200
        or page.transport_complete is not True
        or page.truncated is not False
        or type(page.row_count) is not int
        or page.row_count < 0
        or page.row_count != len(page.rows)
        or type(page.row_limit) is not int
        or page.row_count > page.row_limit
    ):
        _block("provider_page_binding_invalid")
    if current:
        if (
            page.request_cursor is not None
            or page.next_cursor is not None
            or page.has_more is not False
            or page.terminal_proof != "single_response"
            or page.page_index != 0
            or page.row_limit != 5000
            or page.row_count >= page.row_limit
        ):
            _block("current_page_completion_invalid")
    try:
        parsed = owner._root_parse_page_rows(page.response_body)
    except Exception:
        _block("provider_page_body_invalid")
    if type(parsed) is not tuple or parsed != page.rows:
        _block("provider_page_body_binding_invalid")
    return page.rows


def _current_pages(owner: Any, auth: object, current_pages: Mapping[str, object]) -> dict[str, object]:
    if type(current_pages) is not dict or set(current_pages) != set(CURRENT_ROUTES):
        _block("current_route_set_invalid")
    verified: dict[str, object] = {}
    refs: list[str] = []
    for resource in CURRENT_ROUTES:
        page = current_pages[resource]
        _page_rows(owner, auth, page, resource, 0, 0, current=True)
        verified[resource] = page
        refs.extend((page.request_ref, page.response_ref, page._private_record_ref))
    if len(refs) != len(set(refs)):
        _block("provider_reference_reused")
    return verified


def _decimal(value: object, *, nonnegative: bool = False, positive: bool = False) -> Decimal:
    if type(value) is not str or len(value) > 96 or _DECIMAL.fullmatch(value) is None:
        _block("provider_decimal_shape_invalid")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        _block("provider_decimal_shape_invalid")
    if not result.is_finite() or (nonnegative and result < 0) or (positive and result <= 0):
        _block("provider_decimal_range_invalid")
    return result


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0 or value >= 2**63:
        _block("provider_integer_shape_invalid")
    return value


def _symbol(value: object) -> str:
    if type(value) is not str or _SYMBOL.fullmatch(value) is None:
        _block("provider_symbol_shape_invalid")
    return value


def _currency(value: object) -> str:
    if type(value) is not str or _CURRENCY.fullmatch(value) is None:
        _block("provider_currency_shape_invalid")
    return value


def _parse_current(owner: Any, auth: object, pages: Mapping[str, object]) -> tuple[
    tuple[models.OrderState, ...], tuple[models.PositionState, ...],
    tuple[models.BalanceState, ...], dict[str, bool], set[str], set[tuple[str, int]],
]:
    config_rows = _page_rows(owner, auth, pages["account_configuration"], "account_configuration", 0, 0, current=True)
    account_rows = _page_rows(owner, auth, pages["account_v2"], "account_v2", 0, 0, current=True)
    standard_rows = _page_rows(owner, auth, pages["standard_open_orders"], "standard_open_orders", 0, 0, current=True)
    algo_rows = _page_rows(owner, auth, pages["algo_open_orders"], "algo_open_orders", 0, 0, current=True)
    if any(len(items) != 1 for items in (config_rows, account_rows)):
        _block("current_account_response_shape_invalid")
    config = config_rows[0]
    for key in ("canTrade", "dualSidePosition", "multiAssetsMargin"):
        if type(config.get(key)) is not bool:
            _block("account_configuration_schema_invalid")
    if config["multiAssetsMargin"]:
        _block("unsupported_account_mode")
    account = account_rows[0]
    assets, native_positions = account.get("assets"), account.get("positions")
    if type(assets) is not list or type(native_positions) is not list:
        _block("account_v2_schema_invalid")
    balances: list[models.BalanceState] = []
    balance_ids: set[str] = set()
    for item in assets:
        if type(item) is not dict:
            _block("balance_row_invalid")
        asset = _currency(item.get("asset"))
        if asset in balance_ids:
            _block("duplicate_balance_row")
        balances.append(models.BalanceState(asset, _decimal(item.get("walletBalance"))))
        balance_ids.add(asset)
    positions: list[models.PositionState] = []
    position_ids: set[tuple[str, str]] = set()
    active_symbols: set[str] = set()
    for item in native_positions:
        if type(item) is not dict:
            _block("position_row_invalid")
        symbol = _symbol(item.get("symbol"))
        side = item.get("positionSide")
        if type(side) is not str or side not in {"BOTH", "LONG", "SHORT"}:
            _block("position_side_invalid")
        quantity = _decimal(item.get("positionAmt"))
        if (side == "LONG" and quantity < 0) or (side == "SHORT" and quantity > 0):
            _block("position_side_quantity_mismatch")
        if (symbol, side) in position_ids:
            _block("duplicate_position_row")
        positions.append(models.PositionState(symbol + ":" + side, symbol, quantity))
        position_ids.add((symbol, side))
        if quantity != 0:
            active_symbols.add(symbol)
    orders: list[models.OrderState] = []
    order_keys: set[tuple[str, int]] = set()
    order_ids: set[str] = set()
    for resource, rows in (("standard_open_orders", standard_rows), ("algo_open_orders", algo_rows)):
        local: set[tuple[str, int]] = set()
        for row in rows:
            if type(row) is not dict:
                _block("open_order_row_invalid")
            symbol = _symbol(row.get("symbol"))
            is_algo = resource == "algo_open_orders"
            raw_id = _positive_int(row.get("algoId" if is_algo else "orderId"))
            if (symbol, raw_id) in local:
                _block("duplicate_open_order_row")
            local.add((symbol, raw_id))
            status_key, id_key = ("algoStatus", "algoId") if is_algo else ("status", "orderId")
            native_status = row.get(status_key)
            if native_status not in {"NEW", "PARTIALLY_FILLED"}:
                _block("open_order_status_invalid")
            side = row.get("side")
            position_side = row.get("positionSide")
            if side not in {"BUY", "SELL"} or position_side not in {"BOTH", "LONG", "SHORT"}:
                _block("open_order_side_invalid")
            if is_algo:
                client = row.get("clientAlgoId")
                kind = row.get("orderType")
                requested_raw = row.get("quantity")
                if row.get("closePosition") is not False:
                    _block("unsupported_algo_shape")
            else:
                client = row.get("clientOrderId")
                kind = row.get("type")
                requested_raw = row.get("origQty")
            if type(client) is not str or not client or type(kind) is not str or not kind:
                _block("open_order_identity_invalid")
            if type(row.get("reduceOnly")) is not bool:
                _block("open_order_reduce_only_invalid")
            tif = row.get("timeInForce")
            if type(tif) is not str or not tif:
                _block("open_order_tif_invalid")
            requested = _decimal(requested_raw, positive=True)
            filled = _decimal(row.get("executedQty"), nonnegative=True)
            if filled >= requested:
                _block("open_order_quantity_invalid")
            with localcontext() as context:
                context.prec = 80
                remaining = requested - filled
            if remaining <= 0:
                _block("open_order_quantity_invalid")
            price = _decimal(row.get("price"), nonnegative=True)
            order_id = str(raw_id)
            if order_id in order_ids:
                _block("duplicate_open_order_id")
            order_ids.add(order_id)
            order_keys.add((symbol, raw_id))
            active_symbols.add(symbol)
            orders.append(
                models.OrderState(
                    order_id=order_id,
                    client_order_id=client,
                    symbol=symbol,
                    side=side.lower(),
                    price=price,
                    order_type=kind.lower(),
                    position_id=None,
                    reduce_only=row["reduceOnly"],
                    instrument_spec_id=None,
                    status="open" if native_status == "NEW" else "partially_filled",
                    requested=requested,
                    filled=filled,
                    remaining=remaining,
                    position_side=position_side,
                    time_in_force=tif,
                )
            )
    return (
        tuple(orders),
        tuple(positions),
        tuple(balances),
        {key: config[key] for key in ("canTrade", "dualSidePosition", "multiAssetsMargin")},
        active_symbols,
        order_keys,
    )


def _source_freshness(auth: object, pages: tuple[object, ...], now_ms: int) -> None:
    reader = auth._reader
    for name, limit in (
        ("_request_count", MAX_REQUESTS),
        ("_row_count", MAX_ROWS),
        ("_response_bytes", MAX_BODY_BYTES),
    ):
        counter = getattr(reader, name, None)
        if type(counter) is not list or len(counter) != 1 or type(counter[0]) is not int:
            _block("root_capture_counter_invalid")
        if counter[0] < 0 or counter[0] > limit:
            _block("root_capture_budget_reached")
    first, last = reader._first_request_ms[0], reader._last_response_ms[0]
    if (
        type(first) is not int
        or type(last) is not int
        or last < first
        or last - first >= MAX_CAPTURE_MS
        or now_ms - last >= MAX_SNAPSHOT_AGE_MS
    ):
        _block("root_capture_stale_or_over_budget")
    for page in pages:
        if page.request_started_at_ms < first or page.response_completed_at_ms > last:
            _block("provider_page_outside_capture")


def _unique_pages(anchor: BaselineAnchorV1 | None, pages: tuple[object, ...]) -> None:
    refs = []
    for page in pages:
        refs.extend((page.request_ref, page.response_ref, page._private_record_ref))
    if len(refs) != len(set(refs)):
        _block("provider_reference_reused")
    if anchor is not None and set(refs) & set(anchor._seen_refs):
        _block("provider_reference_reused")


def _all_orders_tree(
    owner: Any, auth: object, pages: tuple[object, ...], start_ms: int, cutoff_ms: int,
    refs_anchor: BaselineAnchorV1 | None,
) -> tuple[tuple[dict[str, Any], ...], set[tuple[str, int]]]:
    if type(pages) is not tuple or not pages:
        _block("all_orders_coverage_missing")
    nodes: dict[tuple[int, int], object] = {}
    target_end = cutoff_ms - 1
    for page in pages:
        if type(page) is not owner._RootTH01AccountWindowPageV1:
            _block("all_orders_page_type_invalid")
        lo, hi = page.requested_start_ms + 1, page.requested_end_ms - 1
        if (
            page.resource != ALL_ORDERS_RESOURCE
            or lo < start_ms
            or hi > target_end
            or lo > hi
            or (lo, hi) in nodes
        ):
            _block("all_orders_interval_invalid")
        rows = _page_rows(owner, auth, page, ALL_ORDERS_RESOURCE, lo - 1, hi + 1)
        if page.request_cursor is not None or page.page_index != 0 or page.row_limit != PAGE_LIMIT:
            _block("all_orders_page_shape_invalid")
        nodes[(lo, hi)] = page
    _unique_pages(refs_anchor, tuple(pages))
    selected: dict[tuple[str, int], dict[str, Any]] = {}

    def visit(lo: int, hi: int) -> None:
        page = nodes.get((lo, hi))
        if page is None:
            _block("all_orders_bisection_gap")
        if page.row_count < PAGE_LIMIT:
            if page.has_more is not False or page.next_cursor is not None or page.terminal_proof != "short_page":
                _block("all_orders_terminal_page_invalid")
        else:
            if page.row_count != PAGE_LIMIT or page.has_more is not True or page.terminal_proof != "unknown":
                _block("all_orders_saturated_page_invalid")
            if lo == hi:
                _block("all_orders_one_ms_saturated")
            saturated_rows: dict[tuple[str, int], dict[str, Any]] = {}
            for row in page.rows:
                if type(row) is not dict:
                    _block("all_orders_row_invalid")
                symbol = _symbol(row.get("symbol"))
                order_id = _positive_int(row.get("orderId"))
                created = row.get("time")
                if type(created) is not int or not page.requested_start_ms <= created <= page.requested_end_ms:
                    _block("all_orders_row_time_invalid")
                if start_ms <= created < cutoff_ms:
                    key = (symbol, order_id)
                    if key in saturated_rows:
                        _block("all_orders_duplicate_within_page")
                    saturated_rows[key] = row
            mid = (lo + hi) // 2
            visit(lo, mid)
            visit(mid + 1, hi)
            if any(selected.get(key) != row for key, row in saturated_rows.items()):
                _block("all_orders_bisection_changed_observation")
            return
        page_keys: set[tuple[str, int]] = set()
        for row in page.rows:
            if type(row) is not dict:
                _block("all_orders_row_invalid")
            symbol = _symbol(row.get("symbol"))
            order_id = _positive_int(row.get("orderId"))
            created = row.get("time")
            if type(created) is not int or not page.requested_start_ms <= created <= page.requested_end_ms:
                _block("all_orders_row_time_invalid")
            if not start_ms <= created < cutoff_ms:
                continue
            key = (symbol, order_id)
            if key in page_keys:
                _block("all_orders_duplicate_within_page")
            page_keys.add(key)
            previous = selected.get(key)
            if previous is not None and previous != row:
                _block("all_orders_conflicting_overlap")
            selected[key] = row

    visit(start_ms, target_end)
    if len(nodes) != _tree_node_count(start_ms, target_end, nodes):
        _block("all_orders_unreachable_page")
    rows = tuple(selected[key] for key in sorted(selected))
    return rows, set(selected)


def _tree_node_count(lo: int, hi: int, nodes: Mapping[tuple[int, int], object]) -> int:
    page = nodes.get((lo, hi))
    if page is None:
        return 0
    if page.row_count < PAGE_LIMIT:
        return 1
    mid = (lo + hi) // 2
    return 1 + _tree_node_count(lo, mid, nodes) + _tree_node_count(mid + 1, hi, nodes)


def _force_orders_tree(
    owner: Any, extension: Any, auth: object, pages: tuple[object, ...],
    start_ms: int, cutoff_ms: int, anchor: BaselineAnchorV1 | None,
) -> tuple[tuple[dict[str, Any], ...], set[tuple[str, int]]]:
    if type(pages) is not tuple or not pages:
        _block("force_orders_coverage_missing")
    verify_page = getattr(extension, "verify_force_orders_page", None)
    if not callable(verify_page):
        _block("force_orders_extension_unavailable")
    nodes: dict[tuple[int, int], object] = {}
    for page in pages:
        if type(page) is not owner._RootTH01AccountWindowPageV1:
            _block("force_orders_page_type_invalid")
        lo, hi = page.requested_start_ms + 1, page.requested_end_ms - 1
        if (
            page.resource != FORCE_ORDERS_RESOURCE
            or lo < start_ms
            or hi > cutoff_ms - 1
            or lo > hi
            or (lo, hi) in nodes
        ):
            _block("force_orders_interval_invalid")
        try:
            verify_page(auth, page, lo - 1, hi + 1)
        except Exception:
            _block("force_orders_page_binding_invalid")
        _page_rows(owner, auth, page, FORCE_ORDERS_RESOURCE, lo - 1, hi + 1)
        if page.request_cursor is not None or page.page_index != 0 or page.row_limit != FORCE_ORDER_LIMIT:
            _block("force_orders_page_shape_invalid")
        nodes[(lo, hi)] = page
    _unique_pages(anchor, tuple(pages))
    selected: dict[tuple[str, int], dict[str, Any]] = {}

    def visit(lo: int, hi: int) -> None:
        page = nodes.get((lo, hi))
        if page is None:
            _block("force_orders_bisection_gap")
        if page.row_count < FORCE_ORDER_LIMIT:
            if page.has_more is not False or page.next_cursor is not None or page.terminal_proof != "short_page":
                _block("force_orders_terminal_page_invalid")
        else:
            if (
                page.row_count != FORCE_ORDER_LIMIT
                or page.has_more is not False
                or page.next_cursor is not None
                or page.terminal_proof != "interval_saturated"
            ):
                _block("force_orders_saturated_page_invalid")
            if lo == hi:
                _block("force_orders_one_ms_saturated")
            saturated_rows: dict[tuple[str, int], dict[str, Any]] = {}
            for row in page.rows:
                if type(row) is not dict:
                    _block("force_orders_row_invalid")
                symbol = _symbol(row.get("symbol"))
                order_id = _positive_int(row.get("orderId"))
                when = row.get("time")
                if type(when) is not int or not page.requested_start_ms <= when <= page.requested_end_ms:
                    _block("force_orders_row_time_invalid")
                if start_ms <= when < cutoff_ms:
                    key = (symbol, order_id)
                    if key in saturated_rows:
                        _block("force_orders_duplicate_within_page")
                    saturated_rows[key] = row
            mid = (lo + hi) // 2
            visit(lo, mid)
            visit(mid + 1, hi)
            if any(selected.get(key) != row for key, row in saturated_rows.items()):
                _block("force_orders_bisection_changed_observation")
            return
        page_keys: set[tuple[str, int]] = set()
        for row in page.rows:
            if type(row) is not dict:
                _block("force_orders_row_invalid")
            symbol = _symbol(row.get("symbol"))
            order_id = _positive_int(row.get("orderId"))
            when = row.get("time")
            if type(when) is not int or not page.requested_start_ms <= when <= page.requested_end_ms:
                _block("force_orders_row_time_invalid")
            if not start_ms <= when < cutoff_ms:
                continue
            if row.get("status") not in {"FILLED", "PARTIALLY_FILLED", "NEW"}:
                _block("force_orders_status_invalid")
            if row.get("side") not in {"BUY", "SELL"}:
                _block("force_orders_side_invalid")
            _decimal(row.get("origQty"), nonnegative=True)
            _decimal(row.get("executedQty"), nonnegative=True)
            key = (symbol, order_id)
            if key in page_keys:
                _block("force_orders_duplicate_within_page")
            page_keys.add(key)
            previous = selected.get(key)
            if previous is not None and previous != row:
                _block("force_orders_conflicting_overlap")
            selected[key] = row

    visit(start_ms, cutoff_ms - 1)
    if len(nodes) != _tree_node_count_force(start_ms, cutoff_ms - 1, nodes):
        _block("force_orders_unreachable_page")
    rows = tuple(selected[key] for key in sorted(selected))
    return rows, set(selected)


def _tree_node_count_force(lo: int, hi: int, nodes: Mapping[tuple[int, int], object]) -> int:
    page = nodes.get((lo, hi))
    if page is None:
        return 0
    if page.row_count < FORCE_ORDER_LIMIT:
        return 1
    mid = (lo + hi) // 2
    return 1 + _tree_node_count_force(lo, mid, nodes) + _tree_node_count_force(mid + 1, hi, nodes)


def _paginated_pages(
    owner: Any, auth: object, pages: tuple[object, ...], resource: str,
    start_ms: int, end_ms: int, row_limit: int, *, symbol: str | None = None,
) -> tuple[dict[str, Any], ...]:
    if type(pages) is not tuple or not pages:
        _block("history_route_pages_missing")
    rows: list[dict[str, Any]] = []
    expected_cursor: int | None = None
    for index, page in enumerate(pages):
        parsed = _page_rows(owner, auth, page, resource, start_ms, end_ms)
        if page.page_index != index or page.request_cursor != expected_cursor or page.row_limit != row_limit:
            _block("history_page_sequence_invalid")
        if len(parsed) == row_limit:
            if not page.has_more or page.next_cursor is None or page.terminal_proof != "unknown":
                _block("history_full_page_continuation_missing")
            if type(page.next_cursor) is not int or page.next_cursor <= 0:
                _block("history_cursor_invalid")
            expected_cursor = page.next_cursor
        else:
            if page.has_more or page.next_cursor is not None or page.terminal_proof != "short_page":
                _block("history_terminal_page_invalid")
            if index != len(pages) - 1:
                _block("history_page_after_terminal")
            expected_cursor = None
        for row in parsed:
            if type(row) is not dict:
                _block("history_row_invalid")
            rows.append(row)
    return tuple(rows)


def _income_rows(owner: Any, auth: object, pages: tuple[object, ...], start_ms: int,
                 cutoff_ms: int) -> tuple[dict[str, Any], ...]:
    _paginated_pages(
        owner, auth, pages, INCOME_RESOURCE, start_ms - 1, cutoff_ms, PAGE_LIMIT
    )
    selected: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    for page_index, page in enumerate(pages):
        for row in page.rows:
            when = row.get("time")
            kind, tx_id = row.get("incomeType"), row.get("tranId")
            if type(when) is not int or not start_ms - 1 <= when <= cutoff_ms:
                _block("income_row_outside_window")
            if page_index > 0 and (when < start_ms or when >= cutoff_ms):
                _block("income_continuation_crossed_window")
            if not start_ms <= when < cutoff_ms:
                continue
            if type(kind) is not str or not kind:
                _block("income_type_invalid")
            tx_id = _positive_int(tx_id)
            asset = _currency(row.get("asset"))
            _decimal(row.get("income"))
            symbol = row.get("symbol")
            if symbol not in (None, ""):
                _symbol(symbol)
            key = (kind, tx_id, asset, when)
            previous = selected.get(key)
            if previous is not None:
                if previous != row:
                    _block("income_conflicting_duplicate")
                _block("income_duplicate_identity")
            selected[key] = row
    return tuple(selected[key] for key in sorted(selected))


def _trade_pages(
    owner: Any, auth: object, pages: tuple[object, ...], symbol: str,
    start_ms: int, cutoff_ms: int,
) -> tuple[dict[str, Any], ...]:
    rows = _paginated_pages(
        owner, auth, pages, USER_TRADES_RESOURCE, start_ms - 1, cutoff_ms, PAGE_LIMIT,
        symbol=symbol,
    )
    selected: list[dict[str, Any]] = []
    prior_id = 0
    for page_index, page in enumerate(pages):
        for row in page.rows:
            if row.get("symbol") != symbol:
                _block("user_trade_symbol_mismatch")
            trade_id = _positive_int(row.get("id"))
            if trade_id <= prior_id:
                _block("user_trade_id_not_increasing")
            prior_id = trade_id
            when = row.get("time")
            if type(when) is not int:
                _block("user_trade_time_invalid")
            if page_index > 0 and not start_ms <= when < cutoff_ms:
                _block("user_trade_continuation_crossed_window")
            if start_ms <= when < cutoff_ms:
                selected.append(row)
            elif not start_ms - 1 <= when <= cutoff_ms:
                _block("user_trade_row_outside_query")
            if not start_ms <= when < cutoff_ms and page.row_count == PAGE_LIMIT:
                _block("user_trade_full_page_boundary_ambiguous")
            _positive_int(row.get("orderId"))
            if row.get("side") not in {"BUY", "SELL"}:
                _block("user_trade_side_invalid")
            if type(row.get("buyer")) is not bool or type(row.get("maker")) is not bool:
                _block("user_trade_execution_flags_invalid")
            if row["buyer"] is not (row["side"] == "BUY"):
                _block("user_trade_buyer_side_mismatch")
            if row.get("positionSide") not in {"BOTH", "LONG", "SHORT"}:
                _block("user_trade_position_side_invalid")
            _decimal(row.get("qty"), positive=True)
            _decimal(row.get("price"), positive=True)
            _decimal(row.get("quoteQty"), positive=True)
            _decimal(row.get("commission"), nonnegative=True)
            _currency(row.get("commissionAsset"))
            _decimal(row.get("realizedPnl"))
        if page.has_more:
            if page.next_cursor is None or not page.rows:
                _block("user_trade_cursor_missing")
            last_page_id = max(_positive_int(row.get("id")) for row in page.rows)
            if page.next_cursor <= last_page_id:
                _block("user_trade_cursor_not_advancing")
    return tuple(selected)


def _trade_symbols(
    anchor: BaselineAnchorV1,
    current_active_symbols: set[str],
    all_order_rows: tuple[dict[str, Any], ...],
    force_order_rows: tuple[dict[str, Any], ...],
    income_rows: tuple[dict[str, Any], ...],
) -> tuple[str, ...]:
    symbols = set(anchor._seed_symbols) | set(current_active_symbols)
    for row in (*all_order_rows, *force_order_rows):
        symbols.add(_symbol(row.get("symbol")))
    for row in income_rows:
        value = row.get("symbol")
        if value not in (None, ""):
            symbols.add(_symbol(value))
    return tuple(sorted(symbols))


def _validate_later_phase_anchor(
    auth: object, owner: Any, phase: str, baseline: object, prior_snapshot: object
) -> BaselineAnchorV1:
    if (
        type(baseline) is not BaselineAnchorV1
        or baseline._seal is not _BASELINE_SEAL
        or baseline._auth is not auth
        or baseline._owner is not owner
        or baseline.invocation_id != auth.invocation_id
        or baseline.evidence_window_id != auth.evidence_window_id
        or baseline._account_binding_ref != auth._account_binding_ref
        or baseline._next_phase[0] != phase
        or baseline._last_snapshot[0] is not prior_snapshot
        or type(prior_snapshot) is not models.StateSnapshot
    ):
        _block("baseline_anchor_binding_invalid")
    return baseline


def _validate_phase_cutoff(
    auth: object, baseline: BaselineAnchorV1, current_pages: tuple[object, ...],
    phase_cutoff_ms: object, now_ms: int,
) -> int:
    if type(phase_cutoff_ms) is not int:
        _block("phase_cutoff_invalid")
    first_current_request = min(page.request_started_at_ms for page in current_pages)
    latest_current_response = max(page.response_completed_at_ms for page in current_pages)
    if (
        phase_cutoff_ms <= baseline.t0_ms
        or phase_cutoff_ms <= baseline._last_cutoff_ms[0]
        or baseline.t0_ms - 1 < auth.history_start_ms
        or phase_cutoff_ms >= first_current_request
        or first_current_request - phase_cutoff_ms < MIN_HISTORY_CUTOFF_LAG_MS
        or latest_current_response <= phase_cutoff_ms
        or phase_cutoff_ms >= now_ms
        or now_ms - phase_cutoff_ms >= MAX_SNAPSHOT_AGE_MS
        or phase_cutoff_ms - baseline.t0_ms >= MAX_ACCOUNT_WINDOW_MS
    ):
        _block("phase_cutoff_scope_invalid")
    return phase_cutoff_ms


def _prepare_later_phase(
    auth: object,
    action: object,
    phase: str,
    *,
    current_pages: Mapping[str, object],
    all_orders_pages: tuple[object, ...],
    income_pages: tuple[object, ...],
    force_order_pages: tuple[object, ...],
    baseline: object,
    prior_snapshot: object,
    phase_cutoff_ms: object,
    force_extension: object,
) -> tuple[Any, dict[str, object], tuple[Any, ...], BaselineAnchorV1, int,
           tuple[dict[str, Any], ...], set[tuple[str, int]],
           tuple[dict[str, Any], ...], set[tuple[str, int]], tuple[dict[str, Any], ...],
           tuple[str, ...]]:
    owner = _owner_for_auth(auth)
    _validate_action(auth, action)
    if phase not in {"before_cleanup", "after_cleanup"}:
        _block("snapshot_phase_invalid")
    anchor = _validate_later_phase_anchor(auth, owner, phase, baseline, prior_snapshot)
    verified_current = _current_pages(owner, auth, current_pages)
    parsed_current = _parse_current(owner, auth, verified_current)
    current_list = tuple(verified_current[name] for name in CURRENT_ROUTES)
    cutoff_ms = _validate_phase_cutoff(
        auth, anchor, current_list, phase_cutoff_ms, int(time.time() * 1000)
    )
    if force_extension is not owner:
        _block("force_orders_extension_not_owner_bound")
    _verify_force_orders_extension(owner)
    verify_reader = getattr(owner, "verify_force_orders_reader_binding", None)
    capability_type = getattr(owner, "FixedForceOrdersGetV1", None)
    if not callable(verify_reader) or not isinstance(capability_type, type):
        _block("force_orders_extension_unavailable")
    try:
        capability = capability_type(auth)
        verify_reader(auth, capability)
    except Exception:
        _block("force_orders_reader_binding_invalid")
    if type(all_orders_pages) is not tuple or type(force_order_pages) is not tuple:
        _block("history_page_collection_invalid")
    if type(income_pages) is not tuple:
        _block("history_page_collection_invalid")
    all_order_rows, all_order_keys = _all_orders_tree(
        owner, auth, all_orders_pages, anchor.t0_ms, cutoff_ms, anchor
    )
    force_order_rows, force_order_keys = _force_orders_tree(
        owner, owner, auth, force_order_pages, anchor.t0_ms, cutoff_ms, anchor
    )
    income_rows = _income_rows(owner, auth, income_pages, anchor.t0_ms, cutoff_ms)
    queried_symbols = _trade_symbols(
        anchor, set(parsed_current[4]), all_order_rows, force_order_rows, income_rows
    )
    early_history = (*all_orders_pages, *force_order_pages, *income_pages)
    _unique_pages(anchor, (*current_list, *early_history))
    if early_history and min(page.request_started_at_ms for page in early_history) < max(
        page.response_completed_at_ms for page in current_list
    ):
        _block("history_started_before_state_snapshot")
    _source_freshness(auth, (*current_list, *early_history), int(time.time() * 1000))
    return (
        owner, verified_current, (parsed_current,), anchor, cutoff_ms,
        all_order_rows, all_order_keys, force_order_rows, force_order_keys,
        income_rows, queried_symbols,
    )


def _map_fills(
    trade_rows_by_symbol: Mapping[str, tuple[dict[str, Any], ...]],
    start_ms: int, cutoff_ms: int,
) -> tuple[tuple[models.Fill, ...], set[tuple[str, int]]]:
    fills: list[models.Fill] = []
    fill_keys: set[tuple[str, int]] = set()
    for symbol in sorted(trade_rows_by_symbol):
        for row in trade_rows_by_symbol[symbol]:
            when = row.get("time")
            if type(when) is not int or not start_ms <= when < cutoff_ms:
                _block("user_trade_row_outside_window")
            trade_id = _positive_int(row.get("id"))
            order_id = _positive_int(row.get("orderId"))
            key = (symbol, trade_id)
            if key in fill_keys:
                _block("duplicate_account_fill")
            qty = _decimal(row.get("qty"), positive=True)
            price = _decimal(row.get("price"), positive=True)
            quote_qty = _decimal(row.get("quoteQty"), positive=True)
            fee = _decimal(row.get("commission"), nonnegative=True)
            side = row.get("side")
            direction = Decimal(1) if side == "BUY" else Decimal(-1) if side == "SELL" else None
            if direction is None:
                _block("user_trade_side_invalid")
            position_side = row.get("positionSide")
            if position_side not in {"BOTH", "LONG", "SHORT"}:
                _block("user_trade_position_side_invalid")
            realized = _decimal(row.get("realizedPnl"))
            currency = _currency(row.get("commissionAsset"))
            delta = direction * qty
            fills.append(
                models.Fill(
                    fill_id=symbol + ":" + str(trade_id),
                    order_id=str(order_id),
                    symbol=symbol,
                    side=side.lower(),
                    quantity=qty,
                    price=price,
                    base_delta=delta,
                    quote_delta=-direction * quote_qty,
                    settlement_delta=realized,
                    fee_currency=currency,
                    fee=fee,
                    position_id=symbol + ":" + position_side,
                    position_delta=delta,
                )
            )
            fill_keys.add(key)
    return tuple(sorted(fills, key=lambda item: (item.symbol, item.fill_id))), fill_keys


def _map_ledger(
    income_rows: tuple[dict[str, Any], ...], fill_keys: set[tuple[str, int]],
) -> tuple[models.LedgerEntry, ...]:
    ledger: list[models.LedgerEntry] = []
    seen: set[str] = set()
    for row in income_rows:
        kind = row["incomeType"]
        transaction_id = row["tranId"]
        fill_id: str | None = None
        trade_id = row.get("tradeId")
        if trade_id not in (None, "", -1, "-1"):
            if type(trade_id) is int:
                numeric_trade_id = _positive_int(trade_id)
            elif type(trade_id) is str and re.fullmatch(r"[1-9][0-9]{0,18}", trade_id):
                numeric_trade_id = int(trade_id)
            else:
                _block("income_trade_id_invalid")
            symbol = _symbol(row.get("symbol"))
            if (symbol, numeric_trade_id) not in fill_keys:
                _block("income_trade_without_fill")
            fill_id = symbol + ":" + str(numeric_trade_id)
        entry_id = kind + ":" + str(transaction_id)
        if entry_id in seen:
            _block("income_duplicate_identity")
        seen.add(entry_id)
        ledger.append(
            models.LedgerEntry(
                entry_id=entry_id,
                currency=_currency(row.get("asset")),
                delta=_decimal(row.get("income")),
                fill_id=fill_id,
                reason=kind,
            )
        )
    return tuple(sorted(ledger, key=lambda item: item.entry_id))


def _control_digest(config: Mapping[str, bool]) -> str:
    canonical = json.dumps(dict(config), sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(b"TH01-account-control-profile-v1:" + canonical).hexdigest()


def _snapshot(
    auth: object, action: models.Action, phase: str, current_pages: Mapping[str, object],
    parsed: tuple[tuple[models.OrderState, ...], tuple[models.PositionState, ...],
                  tuple[models.BalanceState, ...], dict[str, bool], set[str], set[tuple[str, int]]],
    history_fills: tuple[models.Fill, ...], ledger: tuple[models.LedgerEntry, ...],
) -> models.StateSnapshot:
    orders, positions, balances, config, _active, _order_keys = parsed
    completed = [current_pages[name].response_completed_at_ms for name in CURRENT_ROUTES]
    observed_ms = max(completed)
    now_ms = int(time.time() * 1000)
    if observed_ms > now_ms or now_ms - observed_ms >= MAX_SNAPSHOT_AGE_MS:
        _block("snapshot_freshness_invalid")
    observed_at = datetime.fromtimestamp(observed_ms / 1000, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    return models.StateSnapshot(
        binding=action.binding,
        correlation_id=action.correlation_id,
        snapshot_id=uuid4().hex,
        phase=phase,
        scope="account_full",
        complete=True,
        pagination_complete=True,
        control_state_digest=_control_digest(config),
        orders=orders,
        positions=positions,
        balances=balances,
        fills=history_fills,
        ledger=ledger,
        source=SOURCE,
        source_instance=SOURCE_INSTANCE,
        source_channel=SOURCE_CHANNEL,
        observed_at=observed_at,
    )


def collect_account_snapshot(
    auth: object,
    action: models.Action,
    phase: str,
    *,
    current_pages: Mapping[str, object],
    all_orders_pages: tuple[object, ...] = (),
    income_pages: tuple[object, ...] = (),
    force_order_pages: tuple[object, ...] = (),
    user_trades_by_symbol: Mapping[str, tuple[object, ...]] | None = None,
    baseline: BaselineAnchorV1 | None = None,
    prior_snapshot: models.StateSnapshot | None = None,
    phase_cutoff_ms: int | None = None,
    force_extension: object | None = None,
) -> SnapshotCaptureV1:
    """Build one phase snapshot from pages minted by the same Root auth.

    Root obtains the current routes first. The baseline finishes with an empty
    history set and defines T0 as one millisecond after the latest current
    response. For later phases, Root fixes a cutoff before any GET; it must be
    at least two seconds before the current-page requests. The interval is
    bounded and is never described as lifetime history.
    """
    owner = _owner_for_auth(auth)
    _validate_action(auth, action)
    if phase not in {"baseline", "before_cleanup", "after_cleanup"}:
        _block("snapshot_phase_invalid")
    verified_current = _current_pages(owner, auth, current_pages)
    parsed_current = _parse_current(owner, auth, verified_current)
    current_list = tuple(verified_current[name] for name in CURRENT_ROUTES)
    now_ms = int(time.time() * 1000)
    if phase == "baseline":
        if (
            baseline is not None
            or prior_snapshot is not None
            or phase_cutoff_ms is not None
            or all_orders_pages
            or income_pages
            or force_order_pages
            or user_trades_by_symbol not in (None, {})
        ):
            _block("baseline_history_must_be_empty")
        snapshot = _snapshot(auth, action, phase, verified_current, parsed_current, (), ())
        t0_ms = max(page.response_completed_at_ms for page in current_list) + 1
        if t0_ms <= auth.history_start_ms or t0_ms >= now_ms:
            _block("baseline_history_boundary_invalid")
        seed_symbols = frozenset(parsed_current[4])
        anchor = BaselineAnchorV1(
            invocation_id=auth.invocation_id,
            evidence_window_id=auth.evidence_window_id,
            history_start_ms=t0_ms,
            t0_ms=t0_ms,
            snapshot=snapshot,
            _auth=auth,
            _owner=owner,
            _account_binding_ref=auth._account_binding_ref,
            _seed_symbols=seed_symbols,
            _open_order_keys=frozenset(parsed_current[5]),
            _seen_refs=[
                value
                for page in current_list
                for value in (page.request_ref, page.response_ref, page._private_record_ref)
            ],
            _last_snapshot=[snapshot],
            _next_phase=["before_cleanup"],
            _last_cutoff_ms=[t0_ms],
            _seal=_BASELINE_SEAL,
        )
        _source_freshness(auth, current_list, now_ms)
        return SnapshotCaptureV1(snapshot, anchor, None, _CAPTURE_SEAL)
    if phase_cutoff_ms is None:
        _block("phase_cutoff_missing")
    if type(user_trades_by_symbol) is not dict:
        _block("user_trade_symbol_pages_missing")
    if force_extension is None:
        _block("force_orders_extension_unavailable")
    (
        owner,
        verified_current,
        parsed_holder,
        anchor,
        cutoff_ms,
        all_order_rows,
        all_order_keys,
        force_order_rows,
        force_order_keys,
        income_rows,
        queried_symbols,
    ) = _prepare_later_phase(
        auth,
        action,
        phase,
        current_pages=current_pages,
        all_orders_pages=all_orders_pages,
        income_pages=income_pages,
        force_order_pages=force_order_pages,
        baseline=baseline,
        prior_snapshot=prior_snapshot,
        phase_cutoff_ms=phase_cutoff_ms,
        force_extension=force_extension,
    )
    parsed_current = parsed_holder[0]
    current_list = tuple(verified_current[name] for name in CURRENT_ROUTES)
    if set(user_trades_by_symbol) != set(queried_symbols):
        _block("user_trade_symbol_coverage_mismatch")
    trade_rows: dict[str, tuple[dict[str, Any], ...]] = {}
    for symbol in queried_symbols:
        pages = user_trades_by_symbol.get(symbol)
        if type(pages) is not tuple:
            _block("user_trade_symbol_pages_invalid")
        trade_rows[symbol] = _trade_pages(
            owner, auth, pages, symbol, baseline.t0_ms, cutoff_ms
        )
    fills, fill_keys = _map_fills(trade_rows, baseline.t0_ms, cutoff_ms)
    known_order_keys = (
        set(baseline._open_order_keys)
        | set(parsed_current[5])
        | all_order_keys
        | force_order_keys
    )
    for fill in fills:
        if (fill.symbol, int(fill.order_id)) not in known_order_keys:
            _block("fill_order_source_missing")
    ledger = _map_ledger(income_rows, fill_keys)
    histories = (*all_orders_pages, *force_order_pages, *income_pages)
    for pages in user_trades_by_symbol.values():
        histories += tuple(pages)
    all_pages = (*current_list, *histories)
    _unique_pages(baseline, tuple(all_pages))
    _source_freshness(auth, tuple(all_pages), now_ms)
    if min(page.request_started_at_ms for page in histories) < cutoff_ms:
        _block("history_started_before_state_snapshot")
    snapshot = _snapshot(auth, action, phase, verified_current, parsed_current, fills, ledger)
    if snapshot.observed_at <= prior_snapshot.observed_at:
        _block("snapshot_time_not_after_prior")
    history = SnapshotHistoryEvidenceV1(
        phase=phase,
        history_start_ms=baseline.t0_ms,
        phase_cutoff_ms=cutoff_ms,
        interval="[baseline_t0_ms,phase_cutoff_ms)",
        universe_basis=(
            "account_v2_positions",
            "standard_and_algo_open_orders",
            "all_orders_account_wide_window",
            "force_orders_account_wide_window",
            "income_rows_with_symbol",
        ),
        page_count=len(histories),
        row_count=sum(page.row_count for page in histories),
        symbols_queried=queried_symbols,
        pages=tuple(histories),
    )
    baseline._seen_refs.extend(
        value
        for page in all_pages
        for value in (page.request_ref, page.response_ref, page._private_record_ref)
    )
    baseline._last_snapshot[0] = snapshot
    baseline._next_phase[0] = "after_cleanup" if phase == "before_cleanup" else "done"
    baseline._last_cutoff_ms[0] = cutoff_ms
    return SnapshotCaptureV1(snapshot, baseline, history, _CAPTURE_SEAL)


def required_user_trade_symbols(
    auth: object,
    action: models.Action,
    phase: str,
    *,
    current_pages: Mapping[str, object],
    all_orders_pages: tuple[object, ...],
    income_pages: tuple[object, ...],
    force_order_pages: tuple[object, ...],
    baseline: BaselineAnchorV1,
    prior_snapshot: models.StateSnapshot,
    phase_cutoff_ms: int,
    force_extension: object,
) -> tuple[str, ...]:
    """Derive the only symbols for which a userTrades query is authorized.

    This is a preflight over already collected fixed signed-GET pages. It does
    not consume reference IDs or attest a snapshot. `collect_account_snapshot`
    repeats the same derivation and validates the userTrades pages themselves.
    """
    prepared = _prepare_later_phase(
        auth,
        action,
        phase,
        current_pages=current_pages,
        all_orders_pages=all_orders_pages,
        income_pages=income_pages,
        force_order_pages=force_order_pages,
        baseline=baseline,
        prior_snapshot=prior_snapshot,
        phase_cutoff_ms=phase_cutoff_ms,
        force_extension=force_extension,
    )
    return prepared[-1]


def snapshot_public_document(capture: SnapshotCaptureV1) -> dict[str, Any]:
    """Return a safe status projection; raw account rows remain private."""
    if type(capture) is not SnapshotCaptureV1 or capture._seal is not _CAPTURE_SEAL:
        _block("snapshot_capture_binding_invalid")
    snapshot = capture.snapshot
    history = capture.history_evidence
    return {
        "schema": SCHEMA,
        "phase": snapshot.phase,
        "scope": snapshot.scope,
        "complete": snapshot.complete,
        "pagination_complete": snapshot.pagination_complete,
        "snapshot_ref": snapshot.snapshot_id,
        "observed_at": snapshot.observed_at,
        "account_full_snapshot_issued": True,
        "formal_case_pass": False,
        "history_scope": (
            "bounded_window_complete"
            if history is not None
            else "baseline_no_post_snapshot_history"
        ),
        "history_start_ms": history.history_start_ms if history else capture.baseline.t0_ms,
        "history_cutoff_ms": history.phase_cutoff_ms if history else None,
        "history_page_count": history.page_count if history else 0,
        "history_row_count": history.row_count if history else 0,
        "history_symbol_count": len(history.symbols_queried) if history else 0,
        "universe_basis": list(history.universe_basis) if history else [
            "account_v2_positions", "standard_and_algo_open_orders"
        ],
        "coverage_evidence_kind": "root_sealed_current_state_and_bounded_history_pages",
    }


__all__ = [
    "AccountSnapshotBlocked",
    "BaselineAnchorV1",
    "SnapshotCaptureV1",
    "SnapshotHistoryEvidenceV1",
    "collect_account_snapshot",
    "required_user_trade_symbols",
    "root_th01_read_action",
    "snapshot_public_document",
]
