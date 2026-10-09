"""Root-bound USD-M perpetual account snapshot producer, revision 2.

R2 keeps the frozen R1 parser and reconciliation rules, but binds the result
to a two-route Demo instrument catalog and to the R9 forceOrders callback and
attempt-ticket contract.  It never infers a product from a symbol's spelling.

The module is deliberately unregistered.  Its production entry requires a
RootSnapshotBackendHookV1 from the pinned Root wrapper, its already-held auth
and protected writer, and the exact installed R9 extension.  Tests replace
only HTTPS leaves and use synthetic Root objects.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import http.client
import json
from pathlib import Path
import re
import ssl
import sys
import time
from types import FunctionType, MappingProxyType, ModuleType
from typing import Any, Mapping
from uuid import uuid4
import weakref

from . import th01_account_full_snapshot_r1 as _r1


SCHEMA = "iteration41.binance.th01.account-full-snapshot.r2"
PHASES = ("baseline", "before_cleanup", "after_cleanup")
CATALOG_SCHEMA = "iteration41.binance.th01.instrument-catalog.private.r2"
CLASSIFICATION_SCHEMA = "iteration41.binance.th01.instrument-classification.private.r2"
ROOT_WRAPPER_SHA256 = "ba0360ecc5ed99b37196e3d077e25a78cd771facec8e224ab1371635cf9be021"
OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
R1_ADAPTER_SHA256 = "049ef44814d2131b53a5b32dfdd5519b5c4607cb3db9922d330c1282c01d93c5"
R9_EXTENSION_SHA256 = "c937a07671a6df7991fb29e131d895c0eca21644d28140542fab7c8b0db1b944"
CATALOG_ROUTES = (
    ("USD_M", "demo-fapi.binance.com", "/fapi/v1/exchangeInfo"),
    ("COIN_M", "demo-dapi.binance.com", "/dapi/v1/exchangeInfo"),
)
MAX_CATALOG_REQUESTS = 2
MAX_CATALOG_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CATALOG_TOTAL_BYTES = 8 * 1024 * 1024
MAX_CATALOG_ROWS = 10_000
MAX_CATALOG_CAPTURE_MS = 20_000
MAX_ROOT_CAPTURE_MS = 120_000
CATALOG_TIMEOUT_SECONDS = 8.0
CATALOG_HEADERS = MappingProxyType(
    {
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "iteration41-th01-instrument-catalog-r2",
    }
)
CONTRACT_TYPES = frozenset(
    {
        "PERPETUAL",
        "CURRENT_MONTH",
        "NEXT_MONTH",
        "CURRENT_QUARTER",
        "NEXT_QUARTER",
        "PERPETUAL_DELIVERING",
    }
)
CONTRACT_STATUSES = frozenset(
    {
        "PENDING_TRADING",
        "TRADING",
        "PRE_DELIVERING",
        "DELIVERING",
        "DELIVERED",
        "PRE_SETTLE",
        "SETTLING",
        "CLOSE",
        "TRADING_HALT",
        "TRADING_CANCEL_ONLY",
    }
)
_DELIVERY_TYPES = frozenset(
    {"CURRENT_MONTH", "NEXT_MONTH", "CURRENT_QUARTER", "NEXT_QUARTER", "PERPETUAL_DELIVERING"}
)
_DELIVERY_STATUSES = frozenset(
    {"PRE_DELIVERING", "DELIVERING", "DELIVERED", "PRE_SETTLE", "SETTLING"}
)
_SYMBOL = re.compile(r"[A-Z0-9_]{1,32}\Z")
_ASSET = re.compile(r"[A-Z0-9]{2,24}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ACCOUNT_ROUTES = frozenset(_r1.CURRENT_ROUTES)
_HISTORY_ROUTES = frozenset(
    {
        _r1.ALL_ORDERS_RESOURCE,
        _r1.FORCE_ORDERS_RESOURCE,
        _r1.INCOME_RESOURCE,
        _r1.USER_TRADES_RESOURCE,
    }
)
_CATALOG_SEAL = object()
_LEDGER_SEAL = object()
_RESULT_SEAL = object()
_USED_CATALOG_HOOKS: weakref.WeakKeyDictionary[Any, object] = weakref.WeakKeyDictionary()
_ACTIVE_ROOT_PRODUCERS: weakref.WeakKeyDictionary[Any, Any] = weakref.WeakKeyDictionary()
R9_MODULE_NAME = (
    "examples.000_live_certification.binance_penetration._certification."
    "th01_force_orders_transport_r9"
)


class AccountSnapshotR2Blocked(ValueError):
    """Fixed safe failure code; never contains account/provider text."""

    def __init__(self, code: str):
        if type(code) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "account_snapshot_r2_blocked"
        self.code = code
        super().__init__(code)


def _block(code: str) -> None:
    raise AccountSnapshotR2Blocked(code)


@dataclass(frozen=True, repr=False)
class _InstrumentV2:
    symbol: str = field(repr=False)
    family: str
    contract_type: str
    contract_status: str
    base_asset: str = field(repr=False)
    quote_asset: str = field(repr=False)
    margin_asset: str = field(repr=False)
    decision: str

    def __repr__(self) -> str:
        return "_InstrumentV2(<private-instrument-metadata>)"


@dataclass(frozen=True, repr=False)
class InstrumentCatalogReceiptV2:
    """Opaque result of the fixed two-origin Root metadata capture."""

    invocation_id: str
    evidence_window_id: str
    captured_at_ms: int
    completed_at_ms: int
    route_count: int
    row_counts: tuple[tuple[str, int], ...]
    category_counts: tuple[tuple[str, int], ...]
    blocker_codes: tuple[str, ...]
    catalog_references: tuple[str, ...] = field(repr=False)
    _by_family_symbol: Mapping[tuple[str, str], _InstrumentV2] = field(repr=False)
    _server_times: tuple[tuple[str, int], ...] = field(repr=False)
    _body_digests: tuple[tuple[str, str], ...] = field(repr=False)
    _auth: object = field(repr=False, compare=False)
    _writer: object = field(repr=False, compare=False)
    _root_hook: object = field(repr=False, compare=False)
    _api_snapshot: object = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "InstrumentCatalogReceiptV2(<Root-private-source-bound-catalog>)"

    @property
    def usable(self) -> bool:
        return not self.blocker_codes and len(self.catalog_references) == MAX_CATALOG_REQUESTS


@dataclass(frozen=True, repr=False)
class ClassificationRecordV2:
    source: str
    source_index: int
    family: str
    contract_type: str
    decision: str
    symbol: str = field(repr=False)

    def __repr__(self) -> str:
        return "ClassificationRecordV2(<private-row-classification>)"


@dataclass(frozen=True, repr=False)
class ClassificationLedgerV2:
    invocation_id: str
    evidence_window_id: str
    catalog_references: tuple[str, ...] = field(repr=False)
    counts: tuple[tuple[str, int], ...]
    blockers: tuple[str, ...]
    record_count: int
    protected_record_ref: str = field(repr=False)
    _records: tuple[ClassificationRecordV2, ...] = field(repr=False)
    _catalog: InstrumentCatalogReceiptV2 = field(repr=False, compare=False)
    _root_hook: object = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "ClassificationLedgerV2(<protected-classification-ledger>)"


@dataclass(frozen=True, repr=False)
class AccountSnapshotCandidateV2:
    status: str
    phase: str
    snapshot_ref: str | None
    ledger: ClassificationLedgerV2
    blocker_codes: tuple[str, ...]
    capture: object | None = field(repr=False, compare=False)
    _catalog: InstrumentCatalogReceiptV2 = field(repr=False, compare=False)
    _root_hook: object = field(repr=False, compare=False)
    _seal: object = field(repr=False, compare=False)

    def __repr__(self) -> str:
        return "AccountSnapshotCandidateV2(<safe-candidate>)"


def _sha(path: Path) -> tuple[str, int]:
    try:
        info = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or int(getattr(info, "st_file_attributes", 0)) & 0x400
            or info.st_size < 1
            or info.st_size > 2_000_000
        ):
            _block("source_binding_shape_invalid")
        raw = path.read_bytes()
        after = path.lstat()
    except Exception:
        _block("source_binding_unavailable")
    if (
        path.is_symlink()
        or not path.is_file()
        or int(getattr(info, "st_file_attributes", 0)) & 0x400
        or int(getattr(after, "st_file_attributes", 0)) & 0x400
        or info.st_size != len(raw)
        or after.st_size != len(raw)
    ):
        _block("source_binding_shape_invalid")
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _verify_fixed_source(path: Path, expected_sha256: str, expected_size: int, code: str) -> None:
    digest, size = _sha(path)
    if digest != expected_sha256 or size != expected_size:
        _block(code)


def _verify_r1_source() -> None:
    path = Path(__file__).resolve().with_name("th01_account_full_snapshot_r1.py")
    _verify_fixed_source(path, R1_ADAPTER_SHA256, 60_349, "r1_adapter_source_pin_mismatch")
    if Path(getattr(_r1, "__file__", "")).resolve() != path:
        _block("r1_adapter_module_origin_invalid")


def _owner_for_auth_v2(auth: object) -> Any:
    owner_name = getattr(type(auth), "__module__", None)
    owner = sys.modules.get(owner_name) if type(owner_name) is str else None
    extension = sys.modules.get(R9_MODULE_NAME)
    owner_path = Path(__file__).resolve().with_name("th01_root_protected_owner_r1.py")
    extension_path = owner_path.with_name("th01_force_orders_transport_r9.py")
    _verify_fixed_source(owner_path, OWNER_SHA256, 92_566, "owner_source_pin_mismatch")
    _verify_fixed_source(
        extension_path, R9_EXTENSION_SHA256, 73_002, "r9_extension_source_pin_mismatch"
    )
    if (
        type(owner) is not ModuleType
        or owner is not sys.modules.get("__main__")
        or type(extension) is not ModuleType
        or Path(getattr(extension, "__file__", "")).resolve() != extension_path
        or sys.modules.get(extension.__name__) is not extension
        or getattr(owner, "__th01_verified_owner_source_path__", None) != str(owner_path)
        or getattr(owner, "__th01_verified_owner_source_sha256__", None) != OWNER_SHA256
    ):
        _block("root_owner_source_binding_invalid")
    try:
        owner_bound = owner.verify_force_orders_owner_binding(owner)
        auth_valid = (
            type(auth) is owner._RootTH01AccountWindowAuthV1
            and auth._seal is owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
            and type(auth._reader) is owner.FixedAccountWindowGetV1
            and auth._reader._seal is owner._ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
            and auth._reader.invocation_id == auth.invocation_id
            and auth._reader.evidence_window_id == auth.evidence_window_id
            and auth._reader._account_binding_ref == auth._account_binding_ref
            and auth._reader.history_start_ms == auth.history_start_ms
            and any(item is auth for item in owner._ACTIVE_ROOT_ACCOUNT_AUTH)
        )
    except Exception:
        _block("root_account_window_capability_invalid")
    if owner_bound is not True or auth_valid is not True:
        _block("root_account_window_capability_invalid")
    return owner


def root_th01_read_action(auth: object, *, external_ref: str, config_snapshot_id: str) -> Any:
    """Create the existing TH01 read action under the R9 canonical owner."""
    _owner_for_auth_v2(auth)
    if (
        type(external_ref) is not str
        or _r1._IDENTIFIER.fullmatch(external_ref) is None
        or type(config_snapshot_id) is not str
        or _r1._IDENTIFIER.fullmatch(config_snapshot_id) is None
    ):
        _block("th01_action_parameter_invalid")
    case_spec = _r1.cases.CASES.get("TH01")
    if (
        case_spec is None
        or case_spec.action != "inspect_submit_threshold"
        or case_spec.risk is not _r1.models.Risk.READ
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
        plan = _r1.runner._plan("TH01", params, None, None, "USDT", venue="binance")
    except Exception:
        _block("th01_read_plan_unavailable")
    if (
        type(plan) is not _r1.models.ActionPlan
        or plan.order_count != 0
        or plan.total_quantity != 0
        or plan.total_notional != 0
        or plan.notional_currency != "USDT"
        or len(plan.operations) != 1
    ):
        _block("th01_read_plan_invalid")
    operation = plan.operations[0]
    if (
        type(operation) is not _r1.models.PlannedOperation
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
    action = _r1.models.Action(
        case_id="TH01",
        name="inspect_submit_threshold",
        risk=_r1.models.Risk.READ,
        binding=_r1.models.Binding("binance", "demo", "sandbox", auth._account_binding_ref),
        params=params,
        correlation_id=auth.invocation_id,
        client_id="th01-" + auth.invocation_id,
        attested_session_id=None,
        evidence_window_id=auth.evidence_window_id,
        plan=plan,
    )
    _r1._ISSUED_ACTIONS[auth.invocation_id] = (external_ref, config_snapshot_id, plan)
    return action


def _validate_action(auth: object, action: object) -> None:
    _owner_for_auth_v2(auth)
    try:
        _r1._validate_action(auth, action)
    except Exception:
        _block("th01_action_binding_invalid")


def _strict_json(body: bytes) -> Any:
    if type(body) is not bytes or not body or len(body) > MAX_CATALOG_RESPONSE_BYTES:
        _block("catalog_body_limit_or_empty")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _block("catalog_duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(_value: str) -> Any:
        _block("catalog_nonfinite_json")

    try:
        return json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=pairs,
            parse_constant=nonfinite,
        )
    except AccountSnapshotR2Blocked:
        raise
    except Exception:
        _block("catalog_json_invalid")


def _parse_catalog_body(
    family: str, body: bytes
) -> tuple[tuple[_InstrumentV2, ...], int, dict[str, int], tuple[str, ...]]:
    document = _strict_json(body)
    if type(document) is not dict:
        _block("catalog_response_shape_invalid")
    server_time = document.get("serverTime")
    rows = document.get("symbols")
    if type(server_time) is not int or server_time <= 0 or type(rows) is not list:
        _block("catalog_response_shape_invalid")
    if not rows or len(rows) > MAX_CATALOG_ROWS:
        _block("catalog_row_count_invalid")
    counts = {
        "catalog_symbol_rows": len(rows),
        "catalog_invalid_rows": 0,
        "catalog_unknown_contract_type": 0,
        "catalog_unknown_contract_status": 0,
        "catalog_inconsistent_metadata": 0,
    }
    blockers: set[str] = set()
    instruments: list[_InstrumentV2] = []
    seen: set[str] = set()
    for row in rows:
        if type(row) is not dict:
            counts["catalog_invalid_rows"] += 1
            blockers.add("catalog_row_invalid")
            continue
        symbol = row.get("symbol")
        contract_type = row.get("contractType")
        status = row.get("contractStatus", row.get("status"))
        base_asset, quote_asset, margin_asset = (
            row.get("baseAsset"),
            row.get("quoteAsset"),
            row.get("marginAsset"),
        )
        if (
            type(symbol) is not str
            or _SYMBOL.fullmatch(symbol) is None
            or type(base_asset) is not str
            or _ASSET.fullmatch(base_asset) is None
            or type(quote_asset) is not str
            or _ASSET.fullmatch(quote_asset) is None
            or type(margin_asset) is not str
            or _ASSET.fullmatch(margin_asset) is None
        ):
            counts["catalog_invalid_rows"] += 1
            blockers.add("catalog_instrument_fields_invalid")
            continue
        if symbol in seen:
            counts["catalog_invalid_rows"] += 1
            blockers.add("catalog_duplicate_symbol")
            continue
        seen.add(symbol)
        if type(contract_type) is not str or contract_type not in CONTRACT_TYPES:
            counts["catalog_unknown_contract_type"] += 1
            blockers.add("catalog_contract_type_unknown")
            contract_type = "UNKNOWN"
        if type(status) is not str or status not in CONTRACT_STATUSES:
            counts["catalog_unknown_contract_status"] += 1
            blockers.add("catalog_contract_status_unknown")
            status = "UNKNOWN"
        if contract_type == "PERPETUAL_DELIVERING" and status not in _DELIVERY_STATUSES:
            counts["catalog_inconsistent_metadata"] += 1
            blockers.add("catalog_contract_metadata_inconsistent")
        if contract_type == "PERPETUAL" and status in _DELIVERY_STATUSES:
            counts["catalog_inconsistent_metadata"] += 1
            blockers.add("catalog_contract_metadata_inconsistent")
        decision = "in_scope" if contract_type == "PERPETUAL" else "out_of_scope"
        instruments.append(
            _InstrumentV2(
                symbol=symbol,
                family=family,
                contract_type=contract_type,
                contract_status=status,
                base_asset=base_asset,
                quote_asset=quote_asset,
                margin_asset=margin_asset,
                decision=decision,
            )
        )
    return tuple(instruments), server_time, counts, tuple(sorted(blockers))


def _function_shape(function: object) -> tuple[Any, ...]:
    if type(function) is not FunctionType:
        _block("r2_producer_api_invalid")
    return (
        function,
        function.__code__,
        function.__defaults__,
        function.__kwdefaults__,
        function.__globals__,
        function.__module__,
        function.__qualname__,
    )


def _binding_shape(value: Any, seen: frozenset[int] = frozenset()) -> Any:
    value_type = type(value)
    if value is None or value_type in (bool, int, float, str, bytes):
        return (value_type.__name__, value)
    identity = id(value)
    if identity in seen:
        return ("cycle", identity)
    next_seen = seen | {identity}
    if value_type in (tuple, list):
        return (value_type.__name__, tuple(_binding_shape(item, next_seen) for item in value))
    if value_type in (set, frozenset):
        parts = tuple(_binding_shape(item, next_seen) for item in value)
        return (value_type.__name__, tuple(sorted(parts, key=repr)))
    if value_type in (dict, type(MappingProxyType({}))):
        rows = tuple(
            (_binding_shape(key, next_seen), _binding_shape(item, next_seen))
            for key, item in value.items()
        )
        return ("mapping", tuple(sorted(rows, key=repr)))
    if value_type is FunctionType:
        closure = []
        for cell in value.__closure__ or ():
            try:
                content = cell.cell_contents
            except ValueError:
                content = None
            closure.append((id(cell), _binding_shape(content, next_seen)))
        return (
            "function",
            identity,
            id(value.__code__),
            id(value.__globals__),
            id(value.__closure__),
            tuple(closure),
            _binding_shape(value.__defaults__, next_seen),
            _binding_shape(value.__kwdefaults__, next_seen),
            _binding_shape(value.__annotations__, next_seen),
            value.__module__,
            value.__qualname__,
        )
    if value_type is property:
        return (
            "property",
            identity,
            _binding_shape(value.fget, next_seen),
            _binding_shape(value.fset, next_seen),
            _binding_shape(value.fdel, next_seen),
            value.__doc__,
        )
    if value_type in (staticmethod, classmethod):
        return (
            value_type.__name__,
            identity,
            _binding_shape(value.__func__, next_seen),
        )
    if value_type is type:
        members = tuple(
            sorted(
                (
                    name,
                    _binding_shape(member, next_seen),
                )
                for name, member in vars(value).items()
                if name not in {"__dict__", "__weakref__"}
            )
        )
        return ("type", identity, value.__module__, value.__qualname__, members)
    if value_type is ModuleType:
        return ("module", identity, value.__name__, getattr(value, "__file__", None))
    return ("identity", value_type.__module__, value_type.__qualname__, identity)


def _module_binding_snapshot() -> tuple[Any, ...]:
    module = sys.modules.get(__name__)
    if type(module) is not ModuleType or module.__dict__ is not globals():
        _block("r2_module_origin_invalid")
    mutable_globals = {"_USED_CATALOG_HOOKS", "_ACTIVE_ROOT_PRODUCERS"}
    rows = []
    for name, value in module.__dict__.items():
        if name.startswith("__"):
            continue
        shape = (
            ("mutable_registry_identity", id(value))
            if name in mutable_globals
            else _binding_shape(value)
        )
        rows.append((name, shape))
    return id(module), id(module.__dict__), tuple(sorted(rows, key=lambda row: row[0]))


def _api_binding_snapshot() -> tuple[tuple[Any, ...], ...]:
    return (
        _module_binding_snapshot(),
        tuple(
            _function_shape(function)
            for function in (
                root_th01_read_action,
                _validate_action,
                create_root_snapshot_producer_v2,
                required_user_trade_symbols,
                collect_account_snapshot,
                account_snapshot_candidate_for_hook_v2,
                capture_instrument_catalog_v2,
                required_user_trade_symbols_v2,
                collect_account_snapshot_v2,
                snapshot_public_document_v2,
            )
        ),
    )


def _verify_api_binding(snapshot: tuple[tuple[Any, ...], ...]) -> None:
    try:
        if snapshot != _api_binding_snapshot():
            _block("r2_producer_api_binding_invalid")
    except AccountSnapshotR2Blocked:
        raise
    except Exception:
        _block("r2_producer_api_binding_invalid")


def _root_context(
    root_hook: object, *, require_idle: bool = False
) -> tuple[Any, Any, Any, Any, Any]:
    _verify_r1_source()
    if type(root_hook).__name__ != "RootSnapshotBackendHookV1":
        _block("root_snapshot_hook_invalid")
    wrapper = sys.modules.get(getattr(type(root_hook), "__module__", ""))
    if (
        type(wrapper) is not ModuleType
        or getattr(wrapper, "RootSnapshotBackendHookV1", None) is not type(root_hook)
        or Path(getattr(wrapper, "__file__", "")).resolve()
        != Path(__file__).resolve().parents[4]
        / "scripts"
        / "iteration41_binance_th01_root_account_window_call_r1.py"
    ):
        _block("root_snapshot_hook_origin_invalid")
    wrapper_path = Path(wrapper.__file__).resolve()
    wrapper_digest, wrapper_size = _sha(wrapper_path)
    if (
        wrapper_digest != ROOT_WRAPPER_SHA256
        or wrapper_size != 132_886
        or getattr(wrapper, "__th01_held_source_sha256__", None) != wrapper_digest
    ):
        _block("root_snapshot_wrapper_source_pin_mismatch")
    owner = getattr(root_hook, "owner", None)
    auth = getattr(root_hook, "auth", None)
    writer = getattr(root_hook, "writer", None)
    force_module = getattr(root_hook, "force_module", None)
    force_reader = getattr(root_hook, "force_reader", None)
    if type(owner) is not ModuleType or type(force_module) is not ModuleType:
        _block("root_snapshot_hook_binding_invalid")
    owner_path = Path(__file__).resolve().with_name("th01_root_protected_owner_r1.py")
    try:
        # R9 intentionally executes the held owner under the candidate driver's
        # canonical __main__ path. R1's older helper insists on the owner's
        # physical source path in __file__, so use R9's stronger installed
        # owner verifier here and separately bind the held owner source path.
        source_digest, source_size = _sha(owner_path)
        writer = owner._require_writer(writer)
        owner_verifier = owner.verify_force_orders_owner_binding
        reader_verifier = owner.verify_force_orders_reader_binding
        extension_verifier = force_module.verify_force_orders_callback_bindings
        owner_bound = owner_verifier(owner)
        reader_bound = reader_verifier(owner, auth, force_reader)
        callbacks_bound = extension_verifier(owner, root_hook._force_callback_bindings)
        auth_type = owner._RootTH01AccountWindowAuthV1
        reader_type = owner.FixedAccountWindowGetV1
        auth_valid = (
            type(auth) is auth_type
            and auth._seal is owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
            and type(auth._reader) is reader_type
            and auth._reader._seal is owner._ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
            and auth._reader.invocation_id == auth.invocation_id
            and auth._reader.evidence_window_id == auth.evidence_window_id
            and auth._reader._account_binding_ref == auth._account_binding_ref
            and auth._reader.history_start_ms == auth.history_start_ms
            and any(item is auth for item in owner._ACTIVE_ROOT_ACCOUNT_AUTH)
        )
    except Exception:
        _block("root_snapshot_auth_or_writer_invalid")
    if (
        owner is not root_hook.owner
        or owner is not sys.modules.get("__main__")
        or getattr(owner, "__name__", None) not in {"__main__", "__mp_main__"}
        or Path(getattr(owner, "__file__", "")).resolve()
        != Path(force_module.R2_DRIVER_PATH).resolve()
        or getattr(owner, "__th01_verified_owner_source_path__", None) != str(owner_path)
        or getattr(owner, "__th01_verified_owner_source_sha256__", None) != OWNER_SHA256
        or source_digest != OWNER_SHA256
        or source_size != 92_566
        or owner_bound is not True
        or reader_bound is not True
        or callbacks_bound is not True
        or auth_valid is not True
        or auth._reader.writer is not writer
        or writer.invocation_id != auth.invocation_id
        or type(getattr(root_hook, "_force_callback_bindings", None)) is not tuple
        or type(getattr(root_hook, "_force_callback_api_snapshot", None)) is not tuple
        or not callable(getattr(root_hook, "_verify_force_extension_state", None))
        or getattr(root_hook._verify_force_extension_state, "__func__", None)
        is not getattr(type(root_hook), "_verify_force_extension_state", None)
    ):
        _block("root_snapshot_hook_binding_invalid")
    extension_path = Path(__file__).resolve().with_name("th01_force_orders_transport_r9.py")
    _verify_fixed_source(
        extension_path, R9_EXTENSION_SHA256, 73_002, "r9_extension_source_pin_mismatch"
    )
    if Path(getattr(force_module, "__file__", "")).resolve() != extension_path:
        _block("r9_extension_module_origin_invalid")
    if sys.modules.get(force_module.__name__) is not force_module:
        _block("r9_extension_module_not_loaded")
    owner_verifier = getattr(owner, "verify_force_orders_owner_binding", None)
    reader_verifier = getattr(owner, "verify_force_orders_reader_binding", None)
    callback_verifier = getattr(force_module, "verify_force_orders_callback_bindings", None)
    try:
        if (
            not callable(owner_verifier)
            or owner_verifier(owner) is not True
            or getattr(owner, "_ROOT_TH01_FORCE_ORDERS_EXTENSION_R9_SHA256", None)
            != R9_EXTENSION_SHA256
            or not callable(reader_verifier)
            or reader_verifier(owner, auth, force_reader) is not True
            or not callable(callback_verifier)
            or callback_verifier(owner, root_hook._force_callback_bindings) is not True
        ):
            _block("r9_extension_binding_invalid")
        root_hook._verify_force_extension_state()
    except AccountSnapshotR2Blocked:
        raise
    except Exception:
        _block("r9_extension_binding_invalid")
    if require_idle:
        if (
            getattr(root_hook, "_phase_index", None) != 0
            or getattr(root_hook, "_captures", None)
            or getattr(root_hook, "_snapshots", None)
            or auth._reader._request_count != [0]
            or auth._reader._response_bytes != [0]
            or getattr(owner, "_ACTIVE_ROOT_FIXED_WORKERS", None)
        ):
            _block("catalog_capture_not_before_account_reads")
    return owner, auth, writer, force_module, wrapper


def _read_catalog_route(
    owner: Any,
    auth: object,
    root_hook: object,
    family: str,
    host: str,
    path: str,
    *,
    started_monotonic: float,
) -> tuple[bytes, int, int, str, str]:
    context = ssl.create_default_context()
    if (
        getattr(context, "check_hostname", None) is not True
        or getattr(context, "verify_mode", None) != ssl.CERT_REQUIRED
    ):
        _block("catalog_tls_verification_unavailable")
    connection = None
    close_failed = False
    request_ref, response_ref = uuid4().hex, uuid4().hex
    request_started_ms = int(time.time() * 1000)
    body = b""
    completed_ms = 0
    try:
        _root_context(root_hook)
        connection = http.client.HTTPSConnection(
            host, timeout=CATALOG_TIMEOUT_SECONDS, context=context
        )
        connection.request("GET", path, headers=dict(CATALOG_HEADERS))
        response = connection.getresponse()
        if type(getattr(response, "status", None)) is not int or response.status != 200:
            _block("catalog_http_status_unaccepted")
        encoding = response.getheader("Content-Encoding")
        if encoding not in (None, "identity"):
            _block("catalog_content_encoding_unaccepted")
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            if (
                type(content_length) is not str
                or re.fullmatch(r"[0-9]{1,9}", content_length) is None
            ):
                _block("catalog_content_length_invalid")
            if int(content_length) > MAX_CATALOG_RESPONSE_BYTES:
                _block("catalog_body_limit_reached")
        body = response.read(MAX_CATALOG_RESPONSE_BYTES + 1)
        if type(body) is not bytes or not body or len(body) > MAX_CATALOG_RESPONSE_BYTES:
            _block("catalog_body_limit_reached")
        completed_ms = int(time.time() * 1000)
        if (
            time.monotonic() - started_monotonic > MAX_CATALOG_CAPTURE_MS / 1000.0
            or completed_ms < request_started_ms
        ):
            _block("catalog_capture_deadline_reached")
    except AccountSnapshotR2Blocked:
        raise
    except Exception:
        _block("catalog_transport_unproven")
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                close_failed = True
    if close_failed:
        _block("catalog_transport_cleanup_uncertain")
    _root_context(root_hook)
    if type(body) is not bytes or completed_ms <= 0:
        _block("catalog_response_unproven")
    return body, request_started_ms, completed_ms, request_ref, response_ref


def capture_instrument_catalog_v2(root_hook: object) -> InstrumentCatalogReceiptV2:
    """Fetch both fixed Demo exchangeInfo catalogs through one Root session.

    This uses unauthenticated HTTPS GETs with no query or write route. The raw
    responses are kept in the same protected writer as the account evidence.
    A catalog does not itself prove account coverage or TH01 PASS.
    """
    api_snapshot = _api_binding_snapshot()
    owner, auth, writer, force_module, _wrapper = _root_context(root_hook, require_idle=True)
    try:
        if root_hook in _USED_CATALOG_HOOKS:
            _block("catalog_capture_replayed")
        _USED_CATALOG_HOOKS[root_hook] = object()
    except TypeError:
        _block("root_snapshot_hook_not_weakrefable")
    capture_started_ms = int(time.time() * 1000)
    start_monotonic = time.monotonic()
    total_bytes = 0
    all_instruments: list[_InstrumentV2] = []
    row_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    blockers: set[str] = set()
    catalog_refs: list[str] = []
    server_times: list[tuple[str, int]] = []
    digests: list[tuple[str, str]] = []
    for family, host, path in CATALOG_ROUTES:
        if len(catalog_refs) >= MAX_CATALOG_REQUESTS:
            _block("catalog_request_budget_reached")
        _root_context(root_hook)
        body, request_started_ms, completed_ms, request_ref, response_ref = _read_catalog_route(
            owner,
            auth,
            root_hook,
            family,
            host,
            path,
            started_monotonic=start_monotonic,
        )
        total_bytes += len(body)
        if total_bytes > MAX_CATALOG_TOTAL_BYTES:
            _block("catalog_total_body_budget_reached")
        instruments, server_time, counts, route_blockers = _parse_catalog_body(family, body)
        for key, value in counts.items():
            category_counts[key] = category_counts.get(key, 0) + value
        row_counts[family] = len(instruments)
        blockers.update(route_blockers)
        record_ref = writer.write_private_record(
            "instrument_catalog",
            {
                "schema": CATALOG_SCHEMA,
                "invocation_ref": auth.invocation_id,
                "evidence_window_ref": auth.evidence_window_id,
                "catalog_ref": request_ref,
                "request_ref": request_ref,
                "response_ref": response_ref,
                "family": family,
                "origin": "https://" + host,
                "path": path,
                "method": "GET",
                "query": {},
                "request_started_at_ms": request_started_ms,
                "response_completed_at_ms": completed_ms,
                "http_status": 200,
                "transport_complete": True,
                "body_bytes": len(body),
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "body_base64": base64.b64encode(body).decode("ascii"),
            },
        )
        if type(record_ref) is not str or re.fullmatch(r"[0-9a-f]{32}", record_ref) is None:
            _block("catalog_protected_record_ref_invalid")
        catalog_refs.append(record_ref)
        server_times.append((family, server_time))
        digests.append((family, hashlib.sha256(body).hexdigest()))
        all_instruments.extend(instruments)
    _root_context(root_hook)
    _verify_api_binding(api_snapshot)
    if time.monotonic() - start_monotonic > MAX_CATALOG_CAPTURE_MS / 1000.0:
        _block("catalog_capture_deadline_reached")
    by_family_symbol: dict[tuple[str, str], _InstrumentV2] = {}
    duplicate_keys: set[tuple[str, str]] = set()
    for instrument in all_instruments:
        key = (instrument.family, instrument.symbol)
        if key in by_family_symbol:
            duplicate_keys.add(key)
        else:
            by_family_symbol[key] = instrument
    if duplicate_keys:
        blockers.add("catalog_duplicate_family_symbol")
        category_counts["catalog_duplicate_family_symbol"] = len(duplicate_keys)
    symbols_by_family: dict[str, set[str]] = {}
    for family, symbol in by_family_symbol:
        symbols_by_family.setdefault(symbol, set()).add(family)
    cross_family_symbols = {
        symbol for symbol, families in symbols_by_family.items() if len(families) > 1
    }
    if cross_family_symbols:
        blockers.add("catalog_cross_family_symbol_collision")
        category_counts["catalog_cross_family_symbol_collision"] = len(cross_family_symbols)
    if len(catalog_refs) != MAX_CATALOG_REQUESTS or set(row_counts) != {"USD_M", "COIN_M"}:
        blockers.add("catalog_route_set_incomplete")
    if sum(row_counts.values()) > MAX_CATALOG_ROWS * MAX_CATALOG_REQUESTS:
        blockers.add("catalog_total_row_budget_reached")
    completed_at_ms = int(time.time() * 1000)
    if completed_at_ms < capture_started_ms:
        blockers.add("catalog_clock_invalid")
    return InstrumentCatalogReceiptV2(
        invocation_id=auth.invocation_id,
        evidence_window_id=auth.evidence_window_id,
        captured_at_ms=capture_started_ms,
        completed_at_ms=completed_at_ms,
        route_count=len(catalog_refs),
        row_counts=tuple(sorted(row_counts.items())),
        category_counts=tuple(sorted(category_counts.items())),
        blocker_codes=tuple(sorted(blockers)),
        catalog_references=tuple(catalog_refs),
        _by_family_symbol=MappingProxyType(by_family_symbol),
        _server_times=tuple(server_times),
        _body_digests=tuple(digests),
        _auth=auth,
        _writer=writer,
        _root_hook=root_hook,
        _api_snapshot=api_snapshot,
        _seal=_CATALOG_SEAL,
    )


def _verify_catalog(catalog: object, root_hook: object) -> InstrumentCatalogReceiptV2:
    if (
        type(catalog) is not InstrumentCatalogReceiptV2
        or catalog._seal is not _CATALOG_SEAL
        or catalog._root_hook is not root_hook
        or catalog._auth is not root_hook.auth
        or catalog._writer is not root_hook.writer
        or catalog.invocation_id != root_hook.auth.invocation_id
        or catalog.evidence_window_id != root_hook.auth.evidence_window_id
        or type(catalog._by_family_symbol) is not type(MappingProxyType({}))
    ):
        _block("instrument_catalog_binding_invalid")
    _verify_api_binding(catalog._api_snapshot)
    if not catalog.usable:
        _block("instrument_catalog_metadata_unusable")
    return catalog


def _route_family(owner: Any, resource: str) -> str:
    routes = getattr(owner, "FIXED_RESOURCE_PATHS", None)
    path = routes.get(resource) if type(routes) is dict else None
    if type(path) is not str or not path.startswith("/fapi/"):
        _block("account_row_product_route_unbound")
    return "USD_M"


def _instrument_for_row(
    catalog: InstrumentCatalogReceiptV2,
    symbol: object,
    row_family: str,
) -> tuple[str, str, str]:
    if type(symbol) is not str or _SYMBOL.fullmatch(symbol) is None:
        return "UNKNOWN", "UNKNOWN", "unknown_symbol_shape"
    matched_families = tuple(
        family for family in ("USD_M", "COIN_M") if (family, symbol) in catalog._by_family_symbol
    )
    if len(matched_families) > 1:
        return "UNKNOWN", "UNKNOWN", "product_family_ambiguous"
    instrument = catalog._by_family_symbol.get((row_family, symbol))
    if instrument is None:
        if ("COIN_M", symbol) in catalog._by_family_symbol:
            coin = catalog._by_family_symbol[("COIN_M", symbol)]
            return coin.family, coin.contract_type, "product_family_conflict"
        return "UNKNOWN", "UNKNOWN", "instrument_metadata_missing"
    if (
        instrument.contract_type not in CONTRACT_TYPES
        or instrument.contract_status not in CONTRACT_STATUSES
    ):
        return instrument.family, instrument.contract_type, "instrument_metadata_unknown"
    if instrument.contract_type == "PERPETUAL":
        return instrument.family, instrument.contract_type, "in_scope_usd_m_perpetual"
    return instrument.family, instrument.contract_type, "out_of_scope_contract_type"


def _classification_counts(
    records: tuple[ClassificationRecordV2, ...]
) -> tuple[tuple[str, int], ...]:
    counts = {
        "symbol_rows": len(records),
        "usd_m_perpetual_rows": 0,
        "coin_m_rows": 0,
        "delivery_or_monthly_rows": 0,
        "unknown_rows": 0,
        "product_family_conflict_rows": 0,
        "per_source_rows": 0,
        "per_derived_rows": 0,
    }
    for record in records:
        if record.family == "USD_M" and record.decision == "in_scope_usd_m_perpetual":
            counts["usd_m_perpetual_rows"] += 1
        elif record.family == "COIN_M":
            counts["coin_m_rows"] += 1
        if record.decision == "out_of_scope_contract_type":
            counts["delivery_or_monthly_rows"] += 1
        if record.family == "UNKNOWN" or record.decision in {
            "instrument_metadata_missing",
            "instrument_metadata_unknown",
            "unknown_symbol_shape",
        }:
            counts["unknown_rows"] += 1
        if record.decision == "product_family_conflict":
            counts["product_family_conflict_rows"] += 1
        if record.source.startswith("provider:"):
            counts["per_source_rows"] += 1
        else:
            counts["per_derived_rows"] += 1
    return tuple(sorted(counts.items()))


def _add_row(
    records: list[ClassificationRecordV2],
    blockers: set[str],
    catalog: InstrumentCatalogReceiptV2,
    owner: Any,
    *,
    source: str,
    index: int,
    resource: str,
    symbol: object,
) -> None:
    family = _route_family(owner, resource)
    classified_family, contract_type, decision = _instrument_for_row(catalog, symbol, family)
    if decision != "in_scope_usd_m_perpetual":
        if decision == "out_of_scope_contract_type":
            blockers.add("out_of_scope_delivery_or_monthly_row")
        elif decision == "product_family_conflict":
            blockers.add("account_row_product_family_conflict")
        elif decision == "product_family_ambiguous":
            blockers.add("account_row_product_family_ambiguous")
        else:
            blockers.add("account_row_instrument_metadata_unresolved")
    records.append(
        ClassificationRecordV2(
            source=source,
            source_index=index,
            family=classified_family,
            contract_type=contract_type,
            decision=decision,
            symbol=symbol if type(symbol) is str else "",
        )
    )


def _classify_pages_and_snapshot(
    owner: Any,
    auth: object,
    catalog: InstrumentCatalogReceiptV2,
    phase: str,
    current_pages: Mapping[str, object],
    snapshot: Any,
    history_pages: tuple[object, ...],
) -> tuple[tuple[ClassificationRecordV2, ...], tuple[str, ...]]:
    records: list[ClassificationRecordV2] = []
    blockers: set[str] = set(catalog.blocker_codes)
    verified_current = _r1._current_pages(owner, auth, current_pages)
    for resource in _r1.CURRENT_ROUTES:
        page = verified_current[resource]
        rows = page.rows
        if resource == "account_v2":
            account = rows[0]
            position_rows = account.get("positions")
            if type(position_rows) is not list:
                _block("account_v2_schema_invalid")
            for index, row in enumerate(position_rows):
                _add_row(
                    records,
                    blockers,
                    catalog,
                    owner,
                    source="provider:account_v2.positions",
                    index=index,
                    resource=resource,
                    symbol=row.get("symbol") if type(row) is dict else None,
                )
        elif resource in {"standard_open_orders", "algo_open_orders"}:
            for index, row in enumerate(rows):
                _add_row(
                    records,
                    blockers,
                    catalog,
                    owner,
                    source="provider:" + resource,
                    index=index,
                    resource=resource,
                    symbol=row.get("symbol") if type(row) is dict else None,
                )
    for page_index, page in enumerate(history_pages):
        resource = getattr(page, "resource", None)
        if resource not in _HISTORY_ROUTES:
            _block("account_history_resource_invalid")
        for row_index, row in enumerate(getattr(page, "rows", ())):
            if type(row) is not dict:
                _block("account_history_row_invalid")
            symbol = row.get("symbol")
            if symbol in (None, "") and resource == _r1.INCOME_RESOURCE:
                continue
            _add_row(
                records,
                blockers,
                catalog,
                owner,
                source="provider:" + resource,
                index=page_index * 1_000_000 + row_index,
                resource=resource,
                symbol=symbol,
            )
    for index, row in enumerate(snapshot.orders):
        _add_row(
            records,
            blockers,
            catalog,
            owner,
            source="derived:snapshot.orders",
            index=index,
            resource="standard_open_orders",
            symbol=row.symbol,
        )
    for index, row in enumerate(snapshot.positions):
        _add_row(
            records,
            blockers,
            catalog,
            owner,
            source="derived:snapshot.positions",
            index=index,
            resource="account_v2",
            symbol=row.symbol,
        )
    for index, row in enumerate(snapshot.fills):
        _add_row(
            records,
            blockers,
            catalog,
            owner,
            source="derived:snapshot.fills",
            index=index,
            resource=_r1.USER_TRADES_RESOURCE,
            symbol=row.symbol,
        )
    return tuple(records), tuple(sorted(blockers))


def _write_ledger(
    root_hook: object,
    catalog: InstrumentCatalogReceiptV2,
    records: tuple[ClassificationRecordV2, ...],
    blockers: tuple[str, ...],
) -> ClassificationLedgerV2:
    owner, auth, writer, _force_module, _wrapper = _root_context(root_hook)
    counts = _classification_counts(records)
    private_rows = [
        {
            "source": record.source,
            "source_index": record.source_index,
            "symbol": record.symbol,
            "product_family": record.family,
            "contract_type": record.contract_type,
            "decision": record.decision,
        }
        for record in records
    ]
    ref = writer.write_private_record(
        "account_scope_classification",
        {
            "schema": CLASSIFICATION_SCHEMA,
            "invocation_ref": auth.invocation_id,
            "evidence_window_ref": auth.evidence_window_id,
            "catalog_refs": list(catalog.catalog_references),
            "phase": getattr(root_hook, "_phase_index", -1),
            "blocker_codes": list(blockers),
            "classification_counts": dict(counts),
            "records": private_rows,
        },
    )
    if type(ref) is not str or re.fullmatch(r"[0-9a-f]{32}", ref) is None:
        _block("classification_private_record_ref_invalid")
    return ClassificationLedgerV2(
        invocation_id=auth.invocation_id,
        evidence_window_id=auth.evidence_window_id,
        catalog_references=catalog.catalog_references,
        counts=counts,
        blockers=blockers,
        record_count=len(records),
        protected_record_ref=ref,
        _records=records,
        _catalog=catalog,
        _root_hook=root_hook,
        _seal=_LEDGER_SEAL,
    )


def _candidate(
    phase: str,
    capture: object,
    ledger: ClassificationLedgerV2,
    catalog: InstrumentCatalogReceiptV2,
    root_hook: object,
) -> AccountSnapshotCandidateV2:
    blockers = tuple(sorted(set(ledger.blockers) | set(catalog.blocker_codes)))
    valid_capture = (
        type(capture) is _r1.SnapshotCaptureV1
        and capture._seal is _r1._CAPTURE_SEAL
        and capture.snapshot.scope == "account_full"
        and capture.snapshot.complete is True
        and capture.snapshot.pagination_complete is True
    )
    if not valid_capture:
        blockers = tuple(sorted(set(blockers) | {"r1_snapshot_invariants_unproven"}))
    snapshot = capture.snapshot if valid_capture else None
    if blockers:
        return AccountSnapshotCandidateV2(
            status="BLOCKED_ACCOUNT_SNAPSHOT",
            phase=phase,
            snapshot_ref=None,
            ledger=ledger,
            blocker_codes=blockers,
            capture=None,
            _catalog=catalog,
            _root_hook=root_hook,
            _seal=_RESULT_SEAL,
        )
    return AccountSnapshotCandidateV2(
        status="READY_SCOPED_CANDIDATE",
        phase=phase,
        snapshot_ref=snapshot.snapshot_id,
        ledger=ledger,
        blocker_codes=(),
        capture=capture,
        _catalog=catalog,
        _root_hook=root_hook,
        _seal=_RESULT_SEAL,
    )


def _observe_only_state_signature(snapshot: Any) -> tuple[Any, ...]:
    return (
        snapshot.control_state_digest,
        snapshot.orders,
        snapshot.positions,
        snapshot.balances,
    )


def _observe_only_history_signature(snapshot: Any) -> tuple[Any, ...]:
    return snapshot.fills, snapshot.ledger


class RootAccountSnapshotProducerV2:
    """Sequential R2 adapter around the validated R1 account mappers.

    The same instance must be retained for baseline, before_cleanup, and
    after_cleanup. It binds the R9 ticket/callback state and metadata catalog
    to the original Root hook and keeps every phase fail-closed.
    """

    def __init__(self, root_hook: object, catalog: InstrumentCatalogReceiptV2):
        owner, auth, writer, _force_module, _wrapper = _root_context(root_hook)
        self.root_hook = root_hook
        self.owner = owner
        self.auth = auth
        self.writer = writer
        self.catalog = _verify_catalog(catalog, root_hook)
        self._api_snapshot = self.catalog._api_snapshot
        self._records: list[ClassificationRecordV2] = []
        self._phase_candidates: list[AccountSnapshotCandidateV2] = []
        self._baseline = None
        self._prior_snapshot = None
        self._phase_index = 0
        self._catalog_started_ms = catalog.captured_at_ms
        self._started_monotonic = time.monotonic()

    def __repr__(self) -> str:
        return "RootAccountSnapshotProducerV2(<Root-bound-sequential-producer>)"

    def _verify_live(self) -> None:
        owner, auth, writer, force_module, _wrapper = _root_context(self.root_hook)
        if (
            owner is not self.owner
            or auth is not self.auth
            or writer is not self.writer
            or force_module is not self.root_hook.force_module
            or self.catalog._root_hook is not self.root_hook
        ):
            _block("root_snapshot_producer_binding_invalid")
        _verify_catalog(self.catalog, self.root_hook)
        _verify_api_binding(self._api_snapshot)
        if (
            int(time.time() * 1000) - self._catalog_started_ms >= MAX_ROOT_CAPTURE_MS
            or time.monotonic() - self._started_monotonic >= MAX_ROOT_CAPTURE_MS / 1000.0
        ):
            _block("root_catalog_to_snapshot_window_expired")

    def _verify_phase(self, phase: str, action: object) -> None:
        self._verify_live()
        if (
            phase not in {"baseline", "before_cleanup", "after_cleanup"}
            or self._phase_index >= len(PHASES)
            or phase != PHASES[self._phase_index]
            or getattr(self.root_hook, "_phase_index", None) != self._phase_index
            or action is not self.root_hook.action
        ):
            _block("snapshot_phase_order_invalid")
        try:
            self.root_hook._check_action(action, phase)
        except Exception:
            _block("snapshot_action_binding_invalid")

    def _classify_and_record(
        self,
        phase: str,
        capture: object,
        current_pages: Mapping[str, object],
        history_pages: tuple[object, ...],
    ) -> ClassificationLedgerV2:
        records, blockers = _classify_pages_and_snapshot(
            self.owner,
            self.auth,
            self.catalog,
            phase,
            current_pages,
            capture.snapshot,
            history_pages,
        )
        self._records.extend(records)
        all_records = tuple(self._records)
        # The private row ledger is written every phase, bound to the same
        # protected directory and invocation as the source account pages.
        return _write_ledger(
            self.root_hook,
            self.catalog,
            all_records,
            blockers,
        )

    def collect_baseline(
        self, action: object, *, current_pages: Mapping[str, object]
    ) -> AccountSnapshotCandidateV2:
        self._verify_phase("baseline", action)
        try:
            _r1._validate_action(self.auth, action)
            verified_current = _r1._current_pages(self.owner, self.auth, current_pages)
            parsed_current = _r1._parse_current(self.owner, self.auth, verified_current)
            current_list = tuple(verified_current[name] for name in _r1.CURRENT_ROUTES)
            now_ms = int(time.time() * 1000)
            snapshot = _r1._snapshot(
                self.auth, action, "baseline", verified_current, parsed_current, (), ()
            )
            t0_ms = max(page.response_completed_at_ms for page in current_list) + 1
            if t0_ms <= self.auth.history_start_ms or t0_ms >= now_ms:
                _r1._block("baseline_history_boundary_invalid")
            anchor = _r1.BaselineAnchorV1(
                invocation_id=self.auth.invocation_id,
                evidence_window_id=self.auth.evidence_window_id,
                history_start_ms=t0_ms,
                t0_ms=t0_ms,
                snapshot=snapshot,
                _auth=self.auth,
                _owner=self.owner,
                _account_binding_ref=self.auth._account_binding_ref,
                _seed_symbols=frozenset(parsed_current[4]),
                _open_order_keys=frozenset(parsed_current[5]),
                _seen_refs=[
                    value
                    for page in current_list
                    for value in (
                        page.request_ref,
                        page.response_ref,
                        page._private_record_ref,
                    )
                ],
                _last_snapshot=[snapshot],
                _next_phase=["before_cleanup"],
                _last_cutoff_ms=[t0_ms],
                _seal=_r1._BASELINE_SEAL,
            )
            _r1._source_freshness(self.auth, current_list, now_ms)
            capture = _r1.SnapshotCaptureV1(snapshot, anchor, None, _r1._CAPTURE_SEAL)
        except Exception as exc:
            if type(exc) is _r1.AccountSnapshotBlocked:
                raise
            _block("r1_baseline_validation_failed")
        ledger = self._classify_and_record("baseline", capture, current_pages, ())
        candidate = _candidate("baseline", capture, ledger, self.catalog, self.root_hook)
        self._phase_candidates.append(candidate)
        if candidate.status != "READY_SCOPED_CANDIDATE":
            return candidate
        self._baseline = capture.baseline
        self._prior_snapshot = capture.snapshot
        self._phase_index = 1
        return candidate

    def _verify_force_pages(
        self,
        pages: tuple[object, ...],
        tickets: tuple[tuple[object, object], ...],
        start_ms: int,
        cutoff_ms: int,
    ) -> dict[int, object]:
        self._verify_live()
        if type(pages) is not tuple or type(tickets) is not tuple or len(pages) != len(tickets):
            _block("force_orders_ticket_coverage_missing")
        ticket_by_page_id: dict[int, object] = {}
        for page, ticket in tickets:
            if id(page) in ticket_by_page_id:
                _block("force_orders_ticket_reused")
            ticket_by_page_id[id(page)] = ticket
        if set(ticket_by_page_id) != {id(page) for page in pages}:
            _block("force_orders_ticket_coverage_mismatch")
        verify_page = getattr(self.owner, "verify_force_orders_page", None)
        if not callable(verify_page):
            _block("force_orders_page_verifier_unavailable")
        output: dict[int, object] = {}
        for page in pages:
            if type(page) is not self.owner._RootTH01AccountWindowPageV1:
                _block("force_orders_page_type_invalid")
            lo, hi = page.requested_start_ms + 1, page.requested_end_ms - 1
            if (
                page.resource != _r1.FORCE_ORDERS_RESOURCE
                or lo < start_ms
                or hi > cutoff_ms - 1
                or lo > hi
                or page.row_limit != _r1.FORCE_ORDER_LIMIT
                or page.request_cursor is not None
                or page.next_cursor is not None
                or page.page_index != 0
            ):
                _block("force_orders_page_scope_invalid")
            ticket = ticket_by_page_id[id(page)]
            try:
                valid = verify_page(
                    self.auth,
                    page,
                    lo - 1,
                    hi + 1,
                    root_attempt=ticket,
                )
            except Exception:
                valid = False
            if valid is not True:
                _block("force_orders_page_ticket_invalid")
            output[id(page)] = ticket
        self._verify_live()
        return output

    def _prepare_later(
        self,
        action: object,
        phase: str,
        *,
        current_pages: Mapping[str, object],
        all_orders_pages: tuple[object, ...],
        income_pages: tuple[object, ...],
        force_order_pages: tuple[object, ...],
        force_page_tickets: tuple[tuple[object, object], ...],
        phase_cutoff_ms: int,
    ) -> tuple[Any, ...]:
        self._verify_phase(phase, action)
        if phase not in {"before_cleanup", "after_cleanup"} or self._baseline is None:
            _block("baseline_anchor_missing")
        try:
            _r1._validate_action(self.auth, action)
            anchor = _r1._validate_later_phase_anchor(
                self.auth, self.owner, phase, self._baseline, self._prior_snapshot
            )
            verified_current = _r1._current_pages(self.owner, self.auth, current_pages)
            parsed_current = _r1._parse_current(self.owner, self.auth, verified_current)
            current_list = tuple(verified_current[name] for name in _r1.CURRENT_ROUTES)
            cutoff_ms = _r1._validate_phase_cutoff(
                self.auth, anchor, current_list, phase_cutoff_ms, int(time.time() * 1000)
            )
        except Exception as exc:
            if type(exc) is _r1.AccountSnapshotBlocked:
                raise
            _block("r1_phase_contract_invalid")
        if (
            self.root_hook._phase_index != self._phase_index
            or type(all_orders_pages) is not tuple
            or type(income_pages) is not tuple
            or type(force_order_pages) is not tuple
        ):
            _block("snapshot_phase_input_invalid")
        self._verify_force_pages(
            force_order_pages,
            force_page_tickets,
            anchor.t0_ms,
            cutoff_ms,
        )
        try:
            all_order_rows, all_order_keys = _r1._all_orders_tree(
                self.owner, self.auth, all_orders_pages, anchor.t0_ms, cutoff_ms, anchor
            )
            force_order_rows, force_order_keys = self._force_orders_tree_r2(
                force_order_pages, force_page_tickets, anchor.t0_ms, cutoff_ms, anchor
            )
            income_rows = _r1._income_rows(
                self.owner, self.auth, income_pages, anchor.t0_ms, cutoff_ms
            )
        except Exception as exc:
            if type(exc) is _r1.AccountSnapshotBlocked:
                raise
            _block("history_validation_failed")
        queried_symbols = _r1._trade_symbols(
            anchor, set(parsed_current[4]), all_order_rows, force_order_rows, income_rows
        )
        early_history = (*all_orders_pages, *force_order_pages, *income_pages)
        _r1._unique_pages(anchor, (*current_list, *early_history))
        if early_history and min(page.request_started_at_ms for page in early_history) < max(
            page.response_completed_at_ms for page in current_list
        ):
            _r1._block("history_started_before_state_snapshot")
        _r1._source_freshness(self.auth, (*current_list, *early_history), int(time.time() * 1000))
        return (
            anchor,
            verified_current,
            parsed_current,
            current_list,
            cutoff_ms,
            all_order_rows,
            all_order_keys,
            force_order_rows,
            force_order_keys,
            income_rows,
            queried_symbols,
        )

    def _force_orders_tree_r2(
        self,
        pages: tuple[object, ...],
        tickets: tuple[tuple[object, object], ...],
        start_ms: int,
        cutoff_ms: int,
        anchor: object,
    ) -> tuple[tuple[dict[str, Any], ...], set[tuple[str, int]]]:
        self._verify_force_pages(pages, tickets, start_ms, cutoff_ms)
        ticket_map = {id(page): ticket for page, ticket in tickets}
        nodes: dict[tuple[int, int], object] = {}
        for page in pages:
            lo, hi = page.requested_start_ms + 1, page.requested_end_ms - 1
            if (lo, hi) in nodes:
                _block("force_orders_interval_duplicate")
            _r1._page_rows(
                self.owner,
                self.auth,
                page,
                _r1.FORCE_ORDERS_RESOURCE,
                lo - 1,
                hi + 1,
            )
            nodes[(lo, hi)] = page
        _r1._unique_pages(anchor, tuple(pages))
        selected: dict[tuple[str, int], dict[str, Any]] = {}

        def visit(lo: int, hi: int) -> None:
            page = nodes.get((lo, hi))
            if page is None:
                _block("force_orders_bisection_gap")
            ticket = ticket_map.get(id(page))
            try:
                valid = self.owner.verify_force_orders_page(
                    self.auth,
                    page,
                    lo - 1,
                    hi + 1,
                    root_attempt=ticket,
                )
            except Exception:
                valid = False
            if valid is not True:
                _block("force_orders_page_ticket_invalid")
            if page.row_count < _r1.FORCE_ORDER_LIMIT:
                if (
                    page.has_more is not False
                    or page.next_cursor is not None
                    or page.terminal_proof != "short_page"
                ):
                    _block("force_orders_terminal_page_invalid")
            else:
                if (
                    page.row_count != _r1.FORCE_ORDER_LIMIT
                    or page.has_more is not False
                    or page.next_cursor is not None
                    or page.terminal_proof != "interval_saturated"
                ):
                    _block("force_orders_saturated_page_invalid")
                if lo == hi:
                    _block("force_orders_one_ms_saturated")
                saturated: dict[tuple[str, int], dict[str, Any]] = {}
                for row in page.rows:
                    if type(row) is not dict:
                        _block("force_orders_row_invalid")
                    symbol = _r1._symbol(row.get("symbol"))
                    order_id = _r1._positive_int(row.get("orderId"))
                    when = row.get("time")
                    if (
                        type(when) is not int
                        or not page.requested_start_ms <= when <= page.requested_end_ms
                    ):
                        _block("force_orders_row_time_invalid")
                    if start_ms <= when < cutoff_ms:
                        key = (symbol, order_id)
                        if key in saturated:
                            _block("force_orders_duplicate_within_page")
                        saturated[key] = row
                mid = (lo + hi) // 2
                visit(lo, mid)
                visit(mid + 1, hi)
                if any(selected.get(key) != row for key, row in saturated.items()):
                    _block("force_orders_bisection_changed_observation")
                return
            local: set[tuple[str, int]] = set()
            for row in page.rows:
                if type(row) is not dict:
                    _block("force_orders_row_invalid")
                symbol = _r1._symbol(row.get("symbol"))
                order_id = _r1._positive_int(row.get("orderId"))
                when = row.get("time")
                if (
                    type(when) is not int
                    or not page.requested_start_ms <= when <= page.requested_end_ms
                ):
                    _block("force_orders_row_time_invalid")
                if not start_ms <= when < cutoff_ms:
                    continue
                if row.get("status") not in {"FILLED", "PARTIALLY_FILLED", "NEW"}:
                    _block("force_orders_status_invalid")
                if row.get("side") not in {"BUY", "SELL"}:
                    _block("force_orders_side_invalid")
                _r1._decimal(row.get("origQty"), nonnegative=True)
                _r1._decimal(row.get("executedQty"), nonnegative=True)
                key = (symbol, order_id)
                if key in local:
                    _block("force_orders_duplicate_within_page")
                local.add(key)
                previous = selected.get(key)
                if previous is not None and previous != row:
                    _block("force_orders_conflicting_overlap")
                selected[key] = row

        visit(start_ms, cutoff_ms - 1)
        if len(nodes) != _r1._tree_node_count_force(start_ms, cutoff_ms - 1, nodes):
            _block("force_orders_unreachable_page")
        return tuple(selected[key] for key in sorted(selected)), set(selected)

    def required_user_trade_symbols(
        self,
        action: object,
        phase: str,
        *,
        current_pages: Mapping[str, object],
        all_orders_pages: tuple[object, ...],
        income_pages: tuple[object, ...],
        force_order_pages: tuple[object, ...],
        force_page_tickets: tuple[tuple[object, object], ...],
        phase_cutoff_ms: int,
    ) -> tuple[str, ...]:
        prepared = self._prepare_later(
            action,
            phase,
            current_pages=current_pages,
            all_orders_pages=all_orders_pages,
            income_pages=income_pages,
            force_order_pages=force_order_pages,
            force_page_tickets=force_page_tickets,
            phase_cutoff_ms=phase_cutoff_ms,
        )
        symbols = prepared[-1]
        # Fail before any userTrades request when the symbol cannot be proven
        # to be a USD-M perpetual by the captured Demo catalog.
        owner = self.owner
        records: list[ClassificationRecordV2] = []
        blockers: set[str] = set()
        for symbol_index, symbol in enumerate(symbols):
            _add_row(
                records,
                blockers,
                self.catalog,
                owner,
                source="provider:derived_user_trade_universe",
                index=symbol_index,
                resource="account_v2",
                symbol=symbol,
            )
        for resource, pages in (
            (_r1.ALL_ORDERS_RESOURCE, all_orders_pages),
            (_r1.FORCE_ORDERS_RESOURCE, force_order_pages),
            (_r1.INCOME_RESOURCE, income_pages),
        ):
            for page_index, page in enumerate(pages):
                for row_index, row in enumerate(page.rows):
                    if row.get("symbol") in (None, "") and resource == _r1.INCOME_RESOURCE:
                        continue
                    _add_row(
                        records,
                        blockers,
                        self.catalog,
                        owner,
                        source="provider:" + resource,
                        index=page_index * 1_000_000 + row_index,
                        resource=resource,
                        symbol=row.get("symbol"),
                    )
        if blockers:
            self._write_preflight_blocker("trade_universe", tuple(sorted(blockers)), tuple(records))
            _block("trade_universe_not_usd_m_perpetual")
        self._verify_live()
        return tuple(symbols)

    def _write_preflight_blocker(
        self,
        stage: str,
        blockers: tuple[str, ...],
        records: tuple[ClassificationRecordV2, ...],
    ) -> None:
        rows = [
            {
                "source": record.source,
                "source_index": record.source_index,
                "symbol": record.symbol,
                "product_family": record.family,
                "contract_type": record.contract_type,
                "decision": record.decision,
            }
            for record in records
        ]
        self.writer.write_private_record(
            "account_scope_classification",
            {
                "schema": CLASSIFICATION_SCHEMA,
                "invocation_ref": self.auth.invocation_id,
                "evidence_window_ref": self.auth.evidence_window_id,
                "catalog_refs": list(self.catalog.catalog_references),
                "stage": stage,
                "blocker_codes": list(blockers),
                "classification_counts": dict(_classification_counts(records)),
                "records": rows,
            },
        )

    def collect_snapshot(
        self,
        action: object,
        phase: str,
        *,
        current_pages: Mapping[str, object],
        all_orders_pages: tuple[object, ...] = (),
        income_pages: tuple[object, ...] = (),
        force_order_pages: tuple[object, ...] = (),
        force_page_tickets: tuple[tuple[object, object], ...] = (),
        user_trades_by_symbol: Mapping[str, tuple[object, ...]] | None = None,
        phase_cutoff_ms: int | None = None,
    ) -> AccountSnapshotCandidateV2:
        self._verify_phase(phase, action)
        if phase == "baseline":
            return self.collect_baseline(action, current_pages=current_pages)
        if phase_cutoff_ms is None or type(user_trades_by_symbol) is not dict:
            _block("snapshot_history_input_missing")
        prepared = self._prepare_later(
            action,
            phase,
            current_pages=current_pages,
            all_orders_pages=all_orders_pages,
            income_pages=income_pages,
            force_order_pages=force_order_pages,
            force_page_tickets=force_page_tickets,
            phase_cutoff_ms=phase_cutoff_ms,
        )
        (
            anchor,
            verified_current,
            parsed_current,
            current_list,
            cutoff_ms,
            all_order_rows,
            all_order_keys,
            force_order_rows,
            force_order_keys,
            income_rows,
            queried_symbols,
        ) = prepared
        if set(user_trades_by_symbol) != set(queried_symbols):
            _block("user_trade_symbol_coverage_mismatch")
        trade_rows: dict[str, tuple[dict[str, Any], ...]] = {}
        for symbol in queried_symbols:
            pages = user_trades_by_symbol.get(symbol)
            if type(pages) is not tuple:
                _block("user_trade_symbol_pages_invalid")
            trade_rows[symbol] = _r1._trade_pages(
                self.owner, self.auth, pages, symbol, anchor.t0_ms, cutoff_ms
            )
        fills, fill_keys = _r1._map_fills(trade_rows, anchor.t0_ms, cutoff_ms)
        known_order_keys = (
            set(anchor._open_order_keys)
            | set(parsed_current[5])
            | all_order_keys
            | force_order_keys
        )
        for fill in fills:
            if (fill.symbol, int(fill.order_id)) not in known_order_keys:
                _block("fill_order_source_missing")
        ledger_rows = _r1._map_ledger(income_rows, fill_keys)
        histories = (*all_orders_pages, *force_order_pages, *income_pages)
        for pages in user_trades_by_symbol.values():
            histories += tuple(pages)
        _r1._unique_pages(anchor, (*current_list, *histories))
        _r1._source_freshness(self.auth, (*current_list, *histories), int(time.time() * 1000))
        if min(page.request_started_at_ms for page in histories) < cutoff_ms:
            _r1._block("history_started_before_state_snapshot")
        capture_snapshot = _r1._snapshot(
            self.auth, action, phase, verified_current, parsed_current, fills, ledger_rows
        )
        if capture_snapshot.observed_at <= self._prior_snapshot.observed_at:
            _r1._block("snapshot_time_not_after_prior")
        history = _r1.SnapshotHistoryEvidenceV1(
            phase=phase,
            history_start_ms=anchor.t0_ms,
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
        capture = _r1.SnapshotCaptureV1(
            capture_snapshot,
            anchor,
            history,
            _r1._CAPTURE_SEAL,
        )
        records, blockers = _classify_pages_and_snapshot(
            self.owner,
            self.auth,
            self.catalog,
            phase,
            current_pages,
            capture_snapshot,
            tuple(histories),
        )
        self._records.extend(records)
        combined_blockers = tuple(sorted(set(blockers) | set(self.catalog.blocker_codes)))
        phase_reader_pages = (*current_list, *histories)
        if (
            max(page.response_completed_at_ms for page in phase_reader_pages)
            - self.catalog.captured_at_ms
            >= MAX_ROOT_CAPTURE_MS
        ):
            combined_blockers = tuple(
                sorted(set(combined_blockers) | {"root_catalog_to_snapshot_window_expired"})
            )
        if phase == "after_cleanup":
            if self._baseline is None or self._prior_snapshot is None:
                combined_blockers = tuple(
                    sorted(set(combined_blockers) | {"observe_only_reconciliation_anchor_missing"})
                )
            elif not (
                _observe_only_state_signature(self._baseline.snapshot)
                == _observe_only_state_signature(self._prior_snapshot)
                == _observe_only_state_signature(capture_snapshot)
                and _observe_only_history_signature(self._prior_snapshot)
                == _observe_only_history_signature(capture_snapshot)
            ):
                combined_blockers = tuple(
                    sorted(set(combined_blockers) | {"observe_only_account_state_changed"})
                )
        classification = _write_ledger(
            self.root_hook,
            self.catalog,
            tuple(self._records),
            combined_blockers,
        )
        candidate = _candidate(phase, capture, classification, self.catalog, self.root_hook)
        self._phase_candidates.append(candidate)
        if candidate.status != "READY_SCOPED_CANDIDATE":
            return candidate
        anchor._seen_refs.extend(
            value
            for page in (*phase_reader_pages,)
            for value in (page.request_ref, page.response_ref, page._private_record_ref)
        )
        anchor._last_snapshot[0] = capture_snapshot
        anchor._next_phase[0] = "after_cleanup" if phase == "before_cleanup" else "done"
        anchor._last_cutoff_ms[0] = cutoff_ms
        self._prior_snapshot = capture_snapshot
        self._phase_index += 1
        self._verify_live()
        return candidate


SnapshotCaptureV1 = _r1.SnapshotCaptureV1
BaselineAnchorV1 = _r1.BaselineAnchorV1


def create_root_snapshot_producer_v2(
    root_hook: object, catalog: InstrumentCatalogReceiptV2
) -> RootAccountSnapshotProducerV2:
    _root_context(root_hook)
    if root_hook in _ACTIVE_ROOT_PRODUCERS:
        _block("snapshot_producer_replayed")
    producer = RootAccountSnapshotProducerV2(root_hook, catalog)
    try:
        _ACTIVE_ROOT_PRODUCERS[root_hook] = producer
    except TypeError:
        _block("root_snapshot_hook_not_weakrefable")
    return producer


def _producer_for_auth(auth: object) -> RootAccountSnapshotProducerV2:
    matches = [
        producer
        for hook, producer in tuple(_ACTIVE_ROOT_PRODUCERS.items())
        if getattr(hook, "auth", None) is auth
    ]
    if len(matches) != 1:
        _block("snapshot_producer_binding_missing")
    producer = matches[0]
    producer._verify_live()
    return producer


def _ticket_pairs_for_pages(
    root_hook: object, pages: tuple[object, ...]
) -> tuple[tuple[object, object], ...]:
    if type(pages) is not tuple:
        _block("force_orders_page_set_invalid")
    current_ids = {id(page) for page in pages}
    raw = getattr(root_hook, "_force_page_ticket_bindings", None)
    if type(raw) is not list:
        _block("force_orders_ticket_state_invalid")
    selected: list[tuple[object, object]] = []
    for pair in raw:
        if type(pair) is not tuple or len(pair) != 2:
            _block("force_orders_ticket_state_invalid")
        if id(pair[0]) in current_ids:
            selected.append(pair)
    return tuple(selected)


def _verify_callback_phase_refs(
    producer: RootAccountSnapshotProducerV2,
    phase: str,
    baseline: object,
    prior_snapshot: object,
) -> None:
    if phase == "baseline":
        if baseline is not None or prior_snapshot is not None:
            _block("baseline_anchor_must_be_empty")
    elif (
        phase not in {"before_cleanup", "after_cleanup"}
        or baseline is not producer._baseline
        or prior_snapshot is not producer._prior_snapshot
    ):
        _block("snapshot_phase_anchor_binding_invalid")


def required_user_trade_symbols(
    auth: object,
    action: object,
    phase: str,
    *,
    force_extension: object,
    **kwargs: Any,
) -> tuple[str, ...]:
    producer = _producer_for_auth(auth)
    if force_extension is not producer.owner:
        _block("force_orders_owner_binding_invalid")
    baseline = kwargs.pop("baseline", None)
    prior_snapshot = kwargs.pop("prior_snapshot", None)
    _verify_callback_phase_refs(producer, phase, baseline, prior_snapshot)
    force_pages = kwargs.get("force_order_pages")
    tickets = _ticket_pairs_for_pages(producer.root_hook, force_pages)
    return producer.required_user_trade_symbols(
        action,
        phase,
        force_page_tickets=tickets,
        **kwargs,
    )


def collect_account_snapshot(
    auth: object,
    action: object,
    phase: str,
    *,
    force_extension: object,
    **kwargs: Any,
) -> SnapshotCaptureV1:
    producer = _producer_for_auth(auth)
    if force_extension is not producer.owner:
        _block("force_orders_owner_binding_invalid")
    baseline = kwargs.pop("baseline", None)
    prior_snapshot = kwargs.pop("prior_snapshot", None)
    _verify_callback_phase_refs(producer, phase, baseline, prior_snapshot)
    force_pages = kwargs.get("force_order_pages", ())
    tickets = _ticket_pairs_for_pages(producer.root_hook, force_pages)
    candidate = producer.collect_snapshot(
        action,
        phase,
        force_page_tickets=tickets,
        **kwargs,
    )
    if candidate.capture is None:
        code = candidate.blocker_codes[0] if candidate.blocker_codes else "account_scope_not_ready"
        _block(code)
    return candidate.capture


def account_snapshot_candidate_for_hook_v2(
    root_hook: object,
) -> AccountSnapshotCandidateV2:
    producer = _ACTIVE_ROOT_PRODUCERS.get(root_hook)
    if type(producer) is not RootAccountSnapshotProducerV2:
        _block("snapshot_producer_binding_missing")
    producer._verify_live()
    if len(producer._phase_candidates) != 3:
        _block("three_phase_snapshot_incomplete")
    return producer._phase_candidates[-1]


def required_user_trade_symbols_v2(
    producer: RootAccountSnapshotProducerV2,
    action: object,
    phase: str,
    **kwargs: Any,
) -> tuple[str, ...]:
    if type(producer) is not RootAccountSnapshotProducerV2:
        _block("snapshot_producer_invalid")
    return producer.required_user_trade_symbols(action, phase, **kwargs)


def collect_account_snapshot_v2(
    producer: RootAccountSnapshotProducerV2,
    action: object,
    phase: str,
    **kwargs: Any,
) -> AccountSnapshotCandidateV2:
    if type(producer) is not RootAccountSnapshotProducerV2:
        _block("snapshot_producer_invalid")
    return producer.collect_snapshot(action, phase, **kwargs)


def snapshot_public_document_v2(candidate: AccountSnapshotCandidateV2) -> dict[str, Any]:
    if type(candidate) is not AccountSnapshotCandidateV2 or candidate._seal is not _RESULT_SEAL:
        _block("snapshot_candidate_binding_invalid")
    if candidate.ledger._seal is not _LEDGER_SEAL or candidate._catalog._seal is not _CATALOG_SEAL:
        _block("snapshot_candidate_binding_invalid")
    counts = dict(candidate.ledger.counts)
    catalog_rows = dict(candidate._catalog.row_counts)
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "status": candidate.status,
        "phase": candidate.phase,
        "scope": "binance_demo_usd_m_perpetual",
        "scope_family": "USD_M",
        "scope_contract_type": "PERPETUAL",
        "snapshot_issued": candidate.capture is not None,
        "account_full_snapshot_issued": candidate.capture is not None,
        "formal_case_pass": False,
        "catalog_route_count": candidate._catalog.route_count,
        "catalog_usd_m_instrument_count": catalog_rows.get("USD_M", 0),
        "catalog_coin_m_excluded_instrument_count": catalog_rows.get("COIN_M", 0),
        "classified_symbol_row_count": candidate.ledger.record_count,
        "usd_m_perpetual_row_count": counts.get("usd_m_perpetual_rows", 0),
        "coin_m_row_count": counts.get("coin_m_rows", 0),
        "delivery_or_monthly_row_count": counts.get("delivery_or_monthly_rows", 0),
        "unknown_row_count": counts.get("unknown_rows", 0),
        "product_family_conflict_row_count": counts.get("product_family_conflict_rows", 0),
        "provider_row_count": counts.get("per_source_rows", 0),
        "derived_row_count": counts.get("per_derived_rows", 0),
        "blockers": list(candidate.blocker_codes),
    }
    if candidate.capture is not None:
        document["snapshot_ref"] = candidate.snapshot_ref
        document["complete"] = candidate.capture.snapshot.complete
        document["pagination_complete"] = candidate.capture.snapshot.pagination_complete
        document["observed_at"] = candidate.capture.snapshot.observed_at
    else:
        document["complete"] = False
        document["pagination_complete"] = False
    return document


__all__ = [
    "AccountSnapshotCandidateV2",
    "AccountSnapshotR2Blocked",
    "ClassificationLedgerV2",
    "InstrumentCatalogReceiptV2",
    "RootAccountSnapshotProducerV2",
    "SnapshotCaptureV1",
    "account_snapshot_candidate_for_hook_v2",
    "capture_instrument_catalog_v2",
    "collect_account_snapshot",
    "collect_account_snapshot_v2",
    "create_root_snapshot_producer_v2",
    "required_user_trade_symbols",
    "required_user_trade_symbols_v2",
    "root_th01_read_action",
    "snapshot_public_document_v2",
]
