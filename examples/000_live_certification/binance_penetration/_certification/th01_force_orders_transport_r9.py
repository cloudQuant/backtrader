"""Source-bound read-only forceOrders extension for the TH01 R1 owner.

The installer accepts only the already verified R1 owner namespace in
``__main__``. It preserves that namespace's auth, reader, worker and page
types, and adds one fixed GET route without adding any independent budget or
transport implementation.

This is a candidate source component. Importing this module performs no
credential read, provider request, process creation, or filesystem write.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256 as _sha256
from pathlib import Path
import re
import stat
import sys
from types import CodeType, FunctionType, ModuleType
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[4]
VENUE_ROOT = ROOT / "examples" / "000_live_certification" / "binance_penetration"
EXTENSION_PATH = VENUE_ROOT / "_certification" / "th01_force_orders_transport_r9.py"
EXTENSION_MODULE_NAME = (
    "examples.000_live_certification.binance_penetration._certification."
    "th01_force_orders_transport_r9"
)
OWNER_PACKAGE_NAME = "examples.000_live_certification.binance_penetration._certification"
BASE_OWNER_PATH = VENUE_ROOT / "_certification" / "th01_root_protected_owner_r1.py"
R2_DRIVER_PATH = ROOT / "scripts" / "iteration41_binance_th01_account_window_candidate_r2.py"
ROOT_WRAPPER_RELATIVE = "scripts/iteration41_binance_th01_root_account_window_call_r1.py"
ROOT_WRAPPER_PATH = ROOT / ROOT_WRAPPER_RELATIVE
ACCOUNT_WINDOW_CANDIDATE_PATH = (
    VENUE_ROOT / "_certification" / "th01_account_window_candidate_r2.py"
)
BASE_OWNER_SHA256 = "290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f"
ACCOUNT_WINDOW_CANDIDATE_SHA256 = "4dfe7ea41c2666b87ef63984780ae5be7e3ae7c3c2777fb69dd79f764e89ac63"

FORCE_ORDERS_RESOURCE = "force_orders_in_window"
FORCE_ORDERS_PATH = "/fapi/v1/forceOrders"
FORCE_ORDERS_PAGE_LIMIT = 100
FORCE_ORDERS_MAX_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000
_FORCE_ORDERS_SEAL = object()
_INSTALL_STATE_ATTR = "__th01_force_orders_extension_r9_state__"
_INSTALL_MARKER_ATTR = "__th01_force_orders_extension_r9_sha256__"
_PUBLIC_SOURCE_PIN_ATTR = "_ROOT_TH01_FORCE_ORDERS_EXTENSION_R9_SHA256"
_INSTALL_FAILED_ATTR = "__th01_force_orders_extension_r9_failed__"
_EXTENSION_SELF_PIN = "baa9a92fe71258528291a4748af0b811cdc0cece40f3ac80859c6a54d1801f63"
_EXTENSION_IMPORTED_GLOBAL_NAMES = (
    "replace",
    "_sha256",
    "Path",
    "re",
    "stat",
    "sys",
    "CodeType",
    "FunctionType",
    "ModuleType",
    "Any",
    "Mapping",
)
_CALLBACK_FUNCTION_NAMES = (
    "_fixed_request_path",
    "_run_root_fixed_signed_get",
    "verify_force_orders_page",
    "verify_force_orders_reader_binding",
    "verify_force_orders_owner_binding",
    "capture_force_orders_callback_bindings",
    "verify_force_orders_callback_bindings",
)
_CAPABILITY_METHOD_NAMES = ("__init__", "__repr__", "_require", "force_orders")
_ROOT_ATTEMPT_LEDGER_METHOD_NAMES = (
    "__init__",
    "__repr__",
    "_row",
    "_valid_event",
    "_matches_snapshot",
    "reserve",
    "snapshot",
    "verify_snapshot",
    "_latest_state",
    "verify",
    "consume",
    "finish",
    "verify_transition",
    "set_phase",
)
_ROOT_ATTEMPT_TICKET_METHOD_NAMES = ("__init__", "__eq__", "__setattr__", "__repr__")
_ROOT_ATTEMPT_TICKET_FIELD_NAMES = (
    "ledger",
    "auth",
    "sequence",
    "start_ms",
    "end_ms",
    "nonce",
)
_ROOT_ATTEMPT_TICKET_GENERATED_METHOD_NAMES = frozenset({"__init__", "__eq__", "__setattr__"})
_ROOT_ATTEMPT_LEDGER_SLOTS = ("_auth", "_events", "_next_sequence", "_phase", "_phase_index")
_ROOT_ATTEMPT_EVENT_FIELD_NAMES = (
    "ticket",
    "auth",
    "sequence",
    "start_ms",
    "end_ms",
    "nonce",
    "phase",
    "state",
    "outcome_code",
)
_ROOT_ATTEMPT_EVENT_GENERATED_METHOD_NAMES = frozenset({"__init__", "__eq__", "__setattr__"})

_BASE_FUNCTION_NAMES = (
    "_fixed_request_path",
    "_reader_progress",
    "_root_fixed_signed_get_worker",
    "_run_root_fixed_signed_get",
    "_require_writer",
    "_make_root_account_window_auth",
    "_root_parse_page_rows",
    "_preflight_response_budget",
)
_BASE_METHOD_NAMES = (
    ("FixedAccountWindowGetV1", "_require"),
    ("FixedAccountWindowGetV1", "_get"),
    ("FixedAccountWindowGetV1", "all_orders"),
    ("FixedAccountWindowGetV1", "user_trades"),
    ("FixedAccountWindowGetV1", "income"),
    ("RootTH01ProtectedWriterV1", "write_private_record"),
)
_BASE_CONSTANT_NAMES = (
    "FIXED_ENDPOINT",
    "FIXED_HOST",
    "FIXED_REQUEST_TIMEOUT_SECONDS",
    "FIXED_RECV_WINDOW_MS",
    "FIXED_PAGE_LIMIT",
    "MAX_ACCOUNT_WINDOW_MS",
    "MAX_FIXED_REQUESTS",
    "MAX_FIXED_ROWS",
    "MAX_FIXED_BODY_BYTES",
    "MAX_FIXED_CAPTURE_MS",
    "MAX_FIXED_PAGE_BYTES",
)


class ForceOrdersExtensionBlocked(ValueError):
    """Fixed public failure code; never includes account or OS text."""

    def __init__(self, code: str):
        if type(code) is not str or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "force_orders_extension_blocked"
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ForceOrdersExtensionBlocked(code)


def _route_mapping_matches(mapping: Any, expected_items: Any) -> bool:
    """Compare a fixed route dictionary with immutable string pairs."""
    if type(mapping) is not dict or type(expected_items) is not tuple:
        return False
    if len(mapping) != len(expected_items):
        return False
    for item in expected_items:
        if (
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not str
            or type(mapping.get(item[0])) is not str
            or mapping.get(item[0]) != item[1]
        ):
            return False
    return True


def _function_binding_matches(actual: Any, expected: Any) -> bool:
    if (
        type(actual) is not tuple
        or type(expected) is not tuple
        or len(actual) != 7
        or len(expected) != 7
        or any(actual[index] is not expected[index] for index in range(6))
        or type(actual[6]) is not tuple
        or type(expected[6]) is not tuple
        or len(actual[6]) != len(expected[6])
        or any(left is not right for left, right in zip(actual[6], expected[6]))
    ):
        return False
    return True


def _root_attempt_contract(root_wrapper_module: Any) -> tuple[Any, ...] | None:
    """Capture the Root-owned ticket and ledger source surface at installation."""
    try:
        if (
            type(root_wrapper_module) is not ModuleType
            or type(getattr(root_wrapper_module, "__name__", None)) is not str
            or not root_wrapper_module.__name__
            or sys.modules.get(root_wrapper_module.__name__) is not root_wrapper_module
            or getattr(root_wrapper_module, "__package__", None) != ""
            or type(getattr(root_wrapper_module, "__file__", None)) is not str
            or Path(root_wrapper_module.__file__).resolve() != ROOT_WRAPPER_PATH.resolve()
        ):
            return None
        spec = getattr(root_wrapper_module, "__spec__", None)
        if (
            spec is None
            or getattr(spec, "name", None) != root_wrapper_module.__name__
            or Path(getattr(spec, "origin", "")).resolve() != ROOT_WRAPPER_PATH.resolve()
            or getattr(root_wrapper_module, "__loader__", None) is not spec.loader
        ):
            return None
        info = ROOT_WRAPPER_PATH.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > 300_000
        ):
            return None
        raw = ROOT_WRAPPER_PATH.read_bytes()
        source_digest = _sha256(raw).hexdigest()
        if getattr(root_wrapper_module, "__th01_held_source_sha256__", None) != source_digest:
            return None
        after = ROOT_WRAPPER_PATH.lstat()
        if (
            stat.S_ISLNK(after.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or getattr(after, "st_file_attributes", 0) & 0x400
            or after.st_size != len(raw)
        ):
            return None
        ledger_type = root_wrapper_module.__dict__.get("RootForceOrdersAttemptLedgerV1")
        ticket_type = root_wrapper_module.__dict__.get("RootForceOrdersAttemptTicketV1")
        event_type = root_wrapper_module.__dict__.get("_RootForceOrdersAttemptEventV1")
        ticket_fields = getattr(ticket_type, "__dataclass_fields__", None)
        ticket_params = getattr(ticket_type, "__dataclass_params__", None)
        event_fields = getattr(event_type, "__dataclass_fields__", None)
        event_params = getattr(event_type, "__dataclass_params__", None)
        if (
            type(ledger_type) is not type
            or type(ticket_type) is not type
            or type(event_type) is not type
            or ledger_type.__module__ != root_wrapper_module.__name__
            or ticket_type.__module__ != root_wrapper_module.__name__
            or event_type.__module__ != root_wrapper_module.__name__
            or tuple(ticket_fields or ()) != _ROOT_ATTEMPT_TICKET_FIELD_NAMES
            or tuple(event_fields or ()) != _ROOT_ATTEMPT_EVENT_FIELD_NAMES
            or ticket_params is None
            or event_params is None
            or getattr(ticket_params, "frozen", False) is not True
            or getattr(ticket_params, "repr", True) is not False
            or getattr(ticket_params, "eq", False) is not True
            or getattr(event_params, "frozen", False) is not True
            or getattr(event_params, "repr", True) is not False
            or getattr(event_params, "eq", False) is not True
            or tuple(getattr(ticket_type, "__slots__", ())) != _ROOT_ATTEMPT_TICKET_FIELD_NAMES
            or tuple(getattr(event_type, "__slots__", ())) != _ROOT_ATTEMPT_EVENT_FIELD_NAMES
            or tuple(getattr(ledger_type, "__slots__", ())) != _ROOT_ATTEMPT_LEDGER_SLOTS
            or ledger_type.__dict__.get("_OUTCOMES")
            != frozenset({"page_received", "blocked", "transport_error", "interrupted"})
            or ledger_type.__dict__.get("_STATES")
            != frozenset({"reserved", "dispatching", "terminal"})
            or getattr(ticket_type, "__dictoffset__", -1) != 0
            or getattr(event_type, "__dictoffset__", -1) != 0
            or getattr(ledger_type, "__dictoffset__", -1) != 0
            or getattr(ticket_fields["ledger"], "repr", True) is not False
            or getattr(ticket_fields["ledger"], "compare", True) is not False
            or getattr(ticket_fields["auth"], "repr", True) is not False
            or getattr(ticket_fields["auth"], "compare", True) is not False
            or getattr(event_fields["ticket"], "repr", True) is not False
            or getattr(event_fields["ticket"], "compare", True) is not False
            or getattr(event_fields["auth"], "repr", True) is not False
            or getattr(event_fields["auth"], "compare", True) is not False
        ):
            return None

        methods = []
        for label, owner_type, names in (
            ("ledger", ledger_type, _ROOT_ATTEMPT_LEDGER_METHOD_NAMES),
            ("ticket", ticket_type, _ROOT_ATTEMPT_TICKET_METHOD_NAMES),
            (
                "event",
                event_type,
                tuple(sorted(_ROOT_ATTEMPT_EVENT_GENERATED_METHOD_NAMES)),
            ),
        ):
            class_methods = []
            for method_name in names:
                function = owner_type.__dict__.get(method_name)
                binding = _function_binding(function)
                generated = (
                    label == "ticket" and method_name in _ROOT_ATTEMPT_TICKET_GENERATED_METHOD_NAMES
                ) or (
                    label == "event" and method_name in _ROOT_ATTEMPT_EVENT_GENERATED_METHOD_NAMES
                )
                if (
                    binding is None
                    or (
                        generated
                        and (
                            function.__module__ not in (None, root_wrapper_module.__name__)
                            or function.__code__.co_filename != "<string>"
                        )
                    )
                    or (
                        not generated
                        and (
                            function.__globals__ is not root_wrapper_module.__dict__
                            or function.__module__ != root_wrapper_module.__name__
                            or Path(function.__code__.co_filename).resolve()
                            != ROOT_WRAPPER_PATH.resolve()
                        )
                    )
                ):
                    return None
                class_methods.append((method_name, binding))
            methods.append((label, owner_type, tuple(class_methods)))
        globals_bindings = []
        for name in ("PHASES", "uuid4", "_block"):
            value = root_wrapper_module.__dict__.get(name)
            if value is None:
                return None
            binding = _function_binding(value) if name in {"uuid4", "_block"} else None
            if name == "PHASES" and (
                type(value) is not tuple or value != ("baseline", "before_cleanup", "after_cleanup")
            ):
                return None
            if name in {"uuid4", "_block"} and binding is None:
                return None
            globals_bindings.append((name, value, binding))
        return (
            root_wrapper_module,
            root_wrapper_module.__name__,
            root_wrapper_module.__dict__,
            root_wrapper_module.__file__,
            root_wrapper_module.__package__,
            spec,
            source_digest,
            ledger_type,
            ticket_type,
            event_type,
            tuple(methods),
            tuple(globals_bindings),
        )
    except Exception:
        return None


def _same_root_attempt_contract(
    root_wrapper_module: Any,
    expected: Any,
) -> bool:
    current = _root_attempt_contract(root_wrapper_module)
    if (
        type(expected) is not tuple
        or len(expected) != 12
        or type(current) is not tuple
        or len(current) != 12
        or any(current[index] is not expected[index] for index in (0, 1, 2, 3, 4, 5, 7, 8, 9))
        or current[6] != expected[6]
        or type(current[10]) is not tuple
        or type(expected[10]) is not tuple
        or len(current[10]) != len(expected[10])
        or type(current[11]) is not tuple
        or type(expected[11]) is not tuple
        or len(current[11]) != len(expected[11])
    ):
        return False
    for actual_group, expected_group in zip(current[10], expected[10]):
        if (
            type(actual_group) is not tuple
            or type(expected_group) is not tuple
            or len(actual_group) != 3
            or len(expected_group) != 3
            or actual_group[0] != expected_group[0]
            or actual_group[1] is not expected_group[1]
            or type(actual_group[2]) is not tuple
            or type(expected_group[2]) is not tuple
            or len(actual_group[2]) != len(expected_group[2])
        ):
            return False
        for actual_method, expected_method in zip(actual_group[2], expected_group[2]):
            if (
                type(actual_method) is not tuple
                or type(expected_method) is not tuple
                or len(actual_method) != 2
                or len(expected_method) != 2
                or actual_method[0] != expected_method[0]
                or not _function_binding_matches(actual_method[1], expected_method[1])
            ):
                return False
    for actual_global, expected_global in zip(current[11], expected[11]):
        if (
            type(actual_global) is not tuple
            or type(expected_global) is not tuple
            or len(actual_global) != 3
            or len(expected_global) != 3
            or actual_global[0] != expected_global[0]
            or actual_global[1] is not expected_global[1]
            or (actual_global[2] is None and expected_global[2] is not None)
            or (
                actual_global[2] is not None
                and not _function_binding_matches(actual_global[2], expected_global[2])
            )
        ):
            return False
    return True


def _function_binding(function: Any) -> tuple[Any, ...] | None:
    if type(function) is not FunctionType:
        return None
    closure = function.__closure__
    try:
        cells = tuple(cell.cell_contents for cell in closure or ())
    except Exception:
        return None
    return (
        function,
        function.__code__,
        function.__globals__,
        closure,
        function.__defaults__,
        function.__kwdefaults__,
        cells,
    )


def _function_closure_graph(function: Any) -> tuple[tuple[Any, ...], ...] | None:
    """Capture callback functions and every function reachable from a closure."""
    if type(function) is not FunctionType:
        return None
    records = []
    pending = [function]
    seen = set()
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        binding = _function_binding(current)
        if binding is None:
            return None
        records.append(binding)
        try:
            nested = tuple(
                cell.cell_contents
                for cell in (current.__closure__ or ())
                if type(cell.cell_contents) is FunctionType
            )
        except Exception:
            return None
        pending.extend(reversed(nested))
    return tuple(records)


def _same_function_closure_graph(actual: Any, expected: Any) -> bool:
    if type(actual) is not tuple or type(expected) is not tuple or len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected):
        if (
            type(left) is not tuple
            or type(right) is not tuple
            or len(left) != 7
            or len(right) != 7
            or any(left[index] is not right[index] for index in range(6))
            or type(left[6]) is not tuple
            or type(right[6]) is not tuple
            or len(left[6]) != len(right[6])
            or any(a is not b for a, b in zip(left[6], right[6]))
        ):
            return False
    return True


def _extension_function_bindings(
    namespace: Mapping[str, Any]
) -> tuple[tuple[Any, ...], ...] | None:
    """Capture every module-level function and Python class method binding."""
    if not isinstance(namespace, Mapping):
        return None
    records = []
    for name, value in namespace.items():
        if type(value) is FunctionType:
            graph = _function_closure_graph(value)
            if graph is None:
                return None
            records.append((name, namespace, graph))
        elif type(value) is type:
            for method_name, method in value.__dict__.items():
                if type(method) is not FunctionType:
                    continue
                graph = _function_closure_graph(method)
                if graph is None:
                    return None
                records.append((f"{name}.{method_name}", value, graph))
    return tuple(records)


def _same_extension_function_bindings(actual: Any, expected: Any) -> bool:
    if type(actual) is not tuple or type(expected) is not tuple or len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected):
        if (
            type(left) is not tuple
            or type(right) is not tuple
            or len(left) != 3
            or len(right) != 3
            or left[0] != right[0]
            or left[1] is not right[1]
            or not _same_function_closure_graph(left[2], right[2])
        ):
            return False
    return True


def _callback_binding_records(bindings: Mapping[str, Any]) -> tuple[tuple[Any, ...], ...] | None:
    records = []
    owner = bindings.get("owner")
    for name in _CALLBACK_FUNCTION_NAMES:
        binding = _function_binding(bindings.get(name))
        graph = _function_closure_graph(bindings.get(name))
        if binding is None or graph is None:
            return None
        records.append((name, owner, *binding, graph))
    capability = bindings.get("FixedForceOrdersGetV1")
    if type(capability) is not type:
        return None
    for name in _CAPABILITY_METHOD_NAMES:
        binding = _function_binding(capability.__dict__.get(name))
        graph = _function_closure_graph(capability.__dict__.get(name))
        if binding is None or graph is None:
            return None
        records.append((f"FixedForceOrdersGetV1.{name}", capability, *binding, graph))
    return tuple(records)


def _same_callback_binding_records(
    actual: Any,
    expected: Any,
) -> bool:
    if type(actual) is not tuple or type(expected) is not tuple or len(actual) != len(expected):
        return False
    for actual_record, expected_record in zip(actual, expected):
        if (
            type(actual_record) is not tuple
            or type(expected_record) is not tuple
            or len(actual_record) != 10
            or len(expected_record) != 10
            or actual_record[0] != expected_record[0]
            or any(actual_record[index] is not expected_record[index] for index in range(1, 8))
        ):
            return False
        actual_cells = actual_record[8]
        expected_cells = expected_record[8]
        if (
            type(actual_cells) is not tuple
            or type(expected_cells) is not tuple
            or len(actual_cells) != len(expected_cells)
            or any(left is not right for left, right in zip(actual_cells, expected_cells))
            or not _same_function_closure_graph(actual_record[9], expected_record[9])
        ):
            return False
    return True


def _extension_globals_match(namespace: Any, expected_items: Any, expected_functions: Any) -> bool:
    if (
        type(namespace) is not dict
        or namespace is not globals()
        or type(expected_items) is not tuple
    ):
        return False
    if len(namespace) != len(expected_items):
        return False
    for item in expected_items:
        if (
            type(item) is not tuple
            or len(item) != 2
            or item[0] not in namespace
            or namespace[item[0]] is not item[1]
        ):
            return False
    return _same_extension_function_bindings(
        _extension_function_bindings(namespace), expected_functions
    )


def _publish_module_bindings(
    target: dict[str, Any],
    bindings: Mapping[str, Any],
    failed_attr: str,
    failed_value: str,
    state: dict[str, Any],
) -> None:
    """Publish owner callbacks as one rollback-capable transaction."""
    if not isinstance(target, dict) or not isinstance(bindings, Mapping):
        _fail("force_orders_install_target_invalid")
    original = dict(target)
    if failed_attr in original or failed_attr in bindings:
        _fail("force_orders_install_target_invalid")
    try:
        dict.__setitem__(target, failed_attr, failed_value)
        for name, value in bindings.items():
            target[name] = value
        dict.__delitem__(target, failed_attr)
        state["installation_phase"] = "installed"
    except BaseException:
        state["installation_phase"] = "failed"
        for name in bindings:
            if name in original:
                dict.__setitem__(target, name, original[name])
            elif name in target:
                dict.__delitem__(target, name)
        if failed_attr not in target:
            dict.__setitem__(target, failed_attr, failed_value)
        raise


def capture_force_orders_callback_bindings(owner: object) -> tuple[Any, ...]:
    """Return the frozen installed callback and extension-global bindings.

    The cold caller must retain this tuple and compare it before invoking any
    callback verifier. That outer comparison detects in-place ``__code__``
    replacement, which a verifier implemented by that same function cannot
    detect by itself.
    """
    if type(owner) is not ModuleType:
        _fail("force_orders_owner_binding_invalid")
    state = owner.__dict__.get(_INSTALL_STATE_ATTR)
    if type(state) is not dict or state.get("installation_phase") != "installed":
        _fail("force_orders_extension_not_installed")
    expected_callbacks = state.get("callback_bindings")
    expected_globals = state.get("extension_global_bindings")
    extension_globals = state.get("extension_globals")
    expected_functions = state.get("extension_function_bindings")
    current = _callback_binding_records(
        {
            "owner": owner,
            **{name: owner.__dict__.get(name) for name in _CALLBACK_FUNCTION_NAMES},
            "FixedForceOrdersGetV1": owner.__dict__.get("FixedForceOrdersGetV1"),
        }
    )
    if not _extension_globals_match(
        extension_globals, expected_globals, expected_functions
    ) or not _same_callback_binding_records(current, expected_callbacks):
        _fail("force_orders_callback_binding_invalid")
    try:
        source_matches = _read_extension_source() == (
            state.get("extension_module"),
            state.get("extension_sha256"),
        )
        owner_matches = owner.verify_force_orders_owner_binding(owner) is True
    except Exception:
        _fail("force_orders_callback_binding_invalid")
    if not source_matches or not owner_matches:
        _fail("force_orders_callback_binding_invalid")
    return (
        owner,
        expected_callbacks,
        extension_globals,
        expected_globals,
        expected_functions,
    )


def verify_force_orders_callback_bindings(owner: object, expected: object) -> bool:
    """Check callback and full extension-global bindings against a held tuple."""
    try:
        if type(owner) is not ModuleType or type(expected) is not tuple or len(expected) != 5:
            return False
        (
            held_owner,
            held_callbacks,
            held_globals,
            held_global_bindings,
            held_global_functions,
        ) = expected
        state = owner.__dict__.get(_INSTALL_STATE_ATTR)
        if type(state) is not dict or state.get("installation_phase") != "installed":
            return False
        if (
            held_owner is not owner
            or held_callbacks is not state.get("callback_bindings")
            or held_globals is not state.get("extension_globals")
            or held_global_bindings is not state.get("extension_global_bindings")
            or held_global_functions is not state.get("extension_function_bindings")
            or not _extension_globals_match(
                held_globals, held_global_bindings, held_global_functions
            )
        ):
            return False
        current = _callback_binding_records(
            {
                "owner": owner,
                **{name: owner.__dict__.get(name) for name in _CALLBACK_FUNCTION_NAMES},
                "FixedForceOrdersGetV1": owner.__dict__.get("FixedForceOrdersGetV1"),
            }
        )
        if not _same_callback_binding_records(current, held_callbacks):
            return False
        if (
            _read_extension_source()
            != (state.get("extension_module"), state.get("extension_sha256"))
            or owner.verify_force_orders_owner_binding(owner) is not True
        ):
            return False
        return True
    except Exception:
        return False


def _read_base_owner() -> bytes:
    try:
        lexical = BASE_OWNER_PATH
        if lexical.resolve() != BASE_OWNER_PATH.resolve():
            _fail("force_orders_owner_origin_invalid")
        info = lexical.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > 200_000
        ):
            _fail("force_orders_owner_shape_invalid")
        raw = lexical.read_bytes()
        after = lexical.lstat()
        if (
            stat.S_ISLNK(after.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or getattr(after, "st_file_attributes", 0) & 0x400
            or after.st_size != len(raw)
            or _sha256(raw).hexdigest() != BASE_OWNER_SHA256
        ):
            _fail("force_orders_owner_pin_mismatch")
        return raw
    except ForceOrdersExtensionBlocked:
        raise
    except Exception:
        _fail("force_orders_owner_unavailable")


def _read_extension_source() -> tuple[ModuleType, str]:
    module = sys.modules.get(__name__)
    try:
        if (
            not isinstance(module, ModuleType)
            or __name__ != EXTENSION_MODULE_NAME
            or type(getattr(module, "__file__", None)) is not str
            or Path(module.__file__).resolve() != EXTENSION_PATH.resolve()
            or Path(install_force_orders_extension.__code__.co_filename).resolve()
            != EXTENSION_PATH.resolve()
        ):
            _fail("force_orders_extension_origin_invalid")
        info = EXTENSION_PATH.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & 0x400
            or info.st_size > 200_000
        ):
            _fail("force_orders_extension_shape_invalid")
        raw = EXTENSION_PATH.read_bytes()
        after = EXTENSION_PATH.lstat()
        if (
            stat.S_ISLNK(after.st_mode)
            or not stat.S_ISREG(after.st_mode)
            or getattr(after, "st_file_attributes", 0) & 0x400
            or after.st_size != len(raw)
        ):
            _fail("force_orders_extension_source_changed")
        canonical = re.sub(
            rb'(?m)^_EXTENSION_SELF_PIN = "[0-9a-f]{64}"$',
            b'_EXTENSION_SELF_PIN = "' + (b"0" * 64) + b'"',
            raw,
        )
        if _sha256(canonical).hexdigest() != _EXTENSION_SELF_PIN:
            _fail("force_orders_extension_self_pin_mismatch")
        compiled_namespace: dict[str, Any] = {
            "__name__": __name__,
            "__file__": str(EXTENSION_PATH),
        }
        exec(compile(raw, str(EXTENSION_PATH), "exec", dont_inherit=True), compiled_namespace)
        for name in (
            "_fail",
            "_route_mapping_matches",
            "_function_binding_matches",
            "_root_attempt_contract",
            "_same_root_attempt_contract",
            "_read_base_owner",
            "_expected_base_namespace",
            "_function_code",
            "_same_base_code",
            "_verify_candidate_binding",
            "_code_fingerprint",
            "_verify_base_owner",
            "_owner_fail",
            "install_force_orders_extension",
            "_force_orders_spawn_worker",
            "_read_extension_source",
            "_function_binding",
            "_function_closure_graph",
            "_same_function_closure_graph",
            "_extension_function_bindings",
            "_same_extension_function_bindings",
            "_callback_binding_records",
            "_same_callback_binding_records",
            "_extension_globals_match",
            "_publish_module_bindings",
            "capture_force_orders_callback_bindings",
            "verify_force_orders_callback_bindings",
        ):
            actual = globals().get(name)
            expected = compiled_namespace.get(name)
            if not _same_base_code(actual, expected):
                _fail("force_orders_extension_code_pin_mismatch")
        if not _same_base_code(
            ForceOrdersExtensionBlocked.__init__,
            compiled_namespace["ForceOrdersExtensionBlocked"].__init__,
        ):
            _fail("force_orders_extension_code_pin_mismatch")
        for name in _EXTENSION_IMPORTED_GLOBAL_NAMES:
            if globals().get(name) is not compiled_namespace.get(name):
                _fail("force_orders_extension_import_binding_invalid")
        for name in (
            "ROOT",
            "VENUE_ROOT",
            "EXTENSION_PATH",
            "EXTENSION_MODULE_NAME",
            "OWNER_PACKAGE_NAME",
            "BASE_OWNER_PATH",
            "R2_DRIVER_PATH",
            "ROOT_WRAPPER_RELATIVE",
            "ROOT_WRAPPER_PATH",
            "ACCOUNT_WINDOW_CANDIDATE_PATH",
            "BASE_OWNER_SHA256",
            "ACCOUNT_WINDOW_CANDIDATE_SHA256",
            "FORCE_ORDERS_RESOURCE",
            "FORCE_ORDERS_PATH",
            "FORCE_ORDERS_PAGE_LIMIT",
            "FORCE_ORDERS_MAX_INTERVAL_MS",
            "_INSTALL_STATE_ATTR",
            "_INSTALL_MARKER_ATTR",
            "_PUBLIC_SOURCE_PIN_ATTR",
            "_INSTALL_FAILED_ATTR",
            "_EXTENSION_IMPORTED_GLOBAL_NAMES",
            "_CALLBACK_FUNCTION_NAMES",
            "_CAPABILITY_METHOD_NAMES",
            "_ROOT_ATTEMPT_LEDGER_METHOD_NAMES",
            "_ROOT_ATTEMPT_TICKET_METHOD_NAMES",
            "_ROOT_ATTEMPT_TICKET_FIELD_NAMES",
            "_ROOT_ATTEMPT_TICKET_GENERATED_METHOD_NAMES",
            "_ROOT_ATTEMPT_LEDGER_SLOTS",
            "_ROOT_ATTEMPT_EVENT_FIELD_NAMES",
            "_ROOT_ATTEMPT_EVENT_GENERATED_METHOD_NAMES",
            "_EXTENSION_SELF_PIN",
        ):
            if globals().get(name) != compiled_namespace.get(name):
                _fail("force_orders_extension_global_pin_mismatch")
        return module, _sha256(raw).hexdigest()
    except ForceOrdersExtensionBlocked:
        raise
    except Exception:
        _fail("force_orders_extension_unavailable")


def _expected_base_namespace(raw: bytes) -> dict[str, Any]:
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(BASE_OWNER_PATH),
    }
    try:
        code = compile(raw, str(BASE_OWNER_PATH), "exec", dont_inherit=True)
        exec(code, namespace)
    except Exception:
        _fail("force_orders_owner_compile_failed")
    return namespace


def _function_code(value: Any) -> Any:
    if isinstance(value, (classmethod, staticmethod)):
        value = value.__func__
    return getattr(value, "__code__", None)


def _same_base_code(actual: Any, expected: Any) -> bool:
    actual_code = _function_code(actual)
    expected_code = _function_code(expected)
    if actual_code is None or expected_code is None:
        return False
    try:
        return _code_fingerprint(actual_code) == _code_fingerprint(expected_code)
    except Exception:
        return False


def _verify_candidate_binding(owner: ModuleType) -> None:
    candidate = getattr(owner, "_CANDIDATE_MODULE", None)
    candidate_name = getattr(candidate, "__name__", None)
    verify = getattr(candidate, "_verify_candidate_source_binding", None)
    if (
        not isinstance(candidate, ModuleType)
        or type(candidate_name) is not str
        or re.fullmatch(
            r"_iteration41_th01_account_window_candidate_r2_[0-9a-f]{32}", candidate_name
        )
        is None
        or sys.modules.get(candidate_name) is not candidate
        or type(getattr(candidate, "__file__", None)) is not str
        or Path(candidate.__file__).resolve() != ACCOUNT_WINDOW_CANDIDATE_PATH.resolve()
        or getattr(candidate, "ROOT", None) != ROOT
        or getattr(candidate, "DRIVER_PATH", None) != R2_DRIVER_PATH
        or getattr(candidate, "CAPTURE_CANDIDATE_PATH", None) != ACCOUNT_WINDOW_CANDIDATE_PATH
        or getattr(candidate, "OWNER_PATH", None) != BASE_OWNER_PATH
        or getattr(candidate, "OWNER_SHA256", None) != BASE_OWNER_SHA256
        or getattr(candidate, "__th01_verified_candidate_source_sha256__", None)
        != ACCOUNT_WINDOW_CANDIDATE_SHA256
        or not callable(verify)
        or Path(getattr(getattr(verify, "__code__", None), "co_filename", "")).resolve()
        != ACCOUNT_WINDOW_CANDIDATE_PATH.resolve()
    ):
        _fail("force_orders_candidate_binding_invalid")
    try:
        if verify() != ACCOUNT_WINDOW_CANDIDATE_SHA256:
            _fail("force_orders_candidate_pin_mismatch")
    except ForceOrdersExtensionBlocked:
        raise
    except Exception:
        _fail("force_orders_candidate_unavailable")


def _code_fingerprint(code: Any) -> tuple[Any, ...]:
    def constant(value: Any) -> Any:
        if type(value) is CodeType:
            return _code_fingerprint(value)
        if type(value) is tuple:
            return tuple(constant(item) for item in value)
        if type(value) is frozenset:
            return frozenset(constant(item) for item in value)
        return type(value), value

    return (
        code.co_argcount,
        getattr(code, "co_posonlyargcount", 0),
        code.co_kwonlyargcount,
        code.co_nlocals,
        code.co_stacksize,
        code.co_flags,
        code.co_code,
        tuple(constant(item) for item in code.co_consts),
        code.co_names,
        code.co_varnames,
        code.co_filename,
        code.co_name,
        getattr(code, "co_qualname", code.co_name),
        code.co_firstlineno,
        code.co_linetable,
        getattr(code, "co_exceptiontable", b""),
        code.co_freevars,
        code.co_cellvars,
    )


def _verify_base_owner(owner: object) -> tuple[ModuleType, dict[str, Any]]:
    if (
        type(owner) is not ModuleType
        or owner is not sys.modules.get("__main__")
        or getattr(owner, "__name__", None) not in {"__main__", "__mp_main__"}
        or getattr(owner, "__package__", None) != OWNER_PACKAGE_NAME
        or type(getattr(owner, "__file__", None)) is not str
        or Path(owner.__file__).resolve() != R2_DRIVER_PATH.resolve()
        or getattr(owner, "ROOT", None) != ROOT
        or getattr(owner, "OWNER_PATH", None) != BASE_OWNER_PATH
        or getattr(owner, "OWNER_SHA256", None) != BASE_OWNER_SHA256
        or getattr(owner, "__th01_verified_owner_source_sha256__", None) != BASE_OWNER_SHA256
        or getattr(owner, "__th01_verified_owner_source_path__", None) != str(BASE_OWNER_PATH)
    ):
        _fail("force_orders_owner_binding_invalid")
    _verify_candidate_binding(owner)
    raw = _read_base_owner()
    expected = _expected_base_namespace(raw)
    for name in _BASE_FUNCTION_NAMES:
        if not _same_base_code(getattr(owner, name, None), expected.get(name)):
            _fail("force_orders_owner_code_binding_invalid")
    for class_name, method_name in _BASE_METHOD_NAMES:
        actual_class = getattr(owner, class_name, None)
        expected_class = expected.get(class_name)
        if (
            actual_class is None
            or expected_class is None
            or not _same_base_code(
                getattr(actual_class, method_name, None),
                getattr(expected_class, method_name, None),
            )
        ):
            _fail("force_orders_owner_code_binding_invalid")
    for name in _BASE_CONSTANT_NAMES:
        if getattr(owner, name, object()) != expected.get(name, object()):
            _fail("force_orders_owner_global_binding_invalid")
    expected_routes = expected.get("FIXED_RESOURCE_PATHS")
    actual_routes = getattr(owner, "FIXED_RESOURCE_PATHS", None)
    if type(actual_routes) is not dict or actual_routes != expected_routes:
        _fail("force_orders_owner_route_binding_invalid")
    if (
        getattr(owner, "FixedAccountWindowGetV1", None) is None
        or getattr(owner, "_RootTH01AccountWindowPageV1", None) is None
        or getattr(owner, "_RootTH01AccountWindowAuthV1", None) is None
        or getattr(owner, "_ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL", None) is None
        or getattr(owner, "_ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL", None) is None
    ):
        _fail("force_orders_owner_types_unavailable")
    for name in _BASE_FUNCTION_NAMES:
        actual = getattr(owner, name)
        if Path(actual.__code__.co_filename).resolve() != BASE_OWNER_PATH.resolve():
            _fail("force_orders_owner_code_origin_invalid")
    for class_name, method_name in _BASE_METHOD_NAMES:
        function = getattr(getattr(owner, class_name), method_name)
        if Path(function.__code__.co_filename).resolve() != BASE_OWNER_PATH.resolve():
            _fail("force_orders_owner_code_origin_invalid")
    return owner, expected


def _owner_fail(owner: ModuleType, code: str) -> None:
    fail = getattr(owner, "_account_window_fail", None)
    if not callable(fail):
        _fail("force_orders_owner_failure_api_unavailable")
    fail(code)


def install_force_orders_extension(
    owner_module: object,
    root_wrapper_module: ModuleType | None = None,
) -> ModuleType:
    """Install the one bounded forceOrders GET route into the exact R1 owner.

    The same owner module is returned, with the capability, page validators,
    and exact extension source pin attached. The owner auth, reader, page
    classes and seals are not replaced. The caller must also hold this
    extension module's full source bytes separately.
    """
    if type(owner_module) is not ModuleType:
        _fail("force_orders_owner_binding_invalid")
    if _INSTALL_FAILED_ATTR in owner_module.__dict__:
        _fail("force_orders_extension_install_failed")
    if _INSTALL_STATE_ATTR in owner_module.__dict__:
        _fail("force_orders_extension_already_installed")
    extension_module, extension_digest = _read_extension_source()
    owner, expected = _verify_base_owner(owner_module)
    if owner.__name__ == "__mp_main__":
        if root_wrapper_module is not None:
            _fail("force_orders_root_attempt_binding_invalid")
        root_attempt_contract = None
    else:
        root_attempt_contract = _root_attempt_contract(root_wrapper_module)
        if root_attempt_contract is None:
            _fail("force_orders_root_attempt_binding_invalid")
    if (
        _INSTALL_STATE_ATTR in owner.__dict__
        or "FixedForceOrdersGetV1" in owner.__dict__
        or "verify_force_orders_page" in owner.__dict__
        or "verify_force_orders_owner_binding" in owner.__dict__
        or _PUBLIC_SOURCE_PIN_ATTR in owner.__dict__
    ):
        _fail("force_orders_extension_already_installed")

    base_route = owner._fixed_request_path
    base_dispatch = owner._run_root_fixed_signed_get
    base_worker = owner._root_fixed_signed_get_worker
    base_routes = owner.FIXED_RESOURCE_PATHS
    expected_routes = expected.get("FIXED_RESOURCE_PATHS")
    if type(base_routes) is not dict or type(expected_routes) is not dict:
        _fail("force_orders_owner_route_binding_invalid")
    base_route_items = tuple(sorted(base_routes.items()))
    expected_route_items = tuple(sorted(expected_routes.items()))
    if (
        base_route_items != expected_route_items
        or not _route_mapping_matches(base_routes, base_route_items)
        or not _route_mapping_matches(expected_routes, base_route_items)
    ):
        _fail("force_orders_owner_route_binding_invalid")
    force_route_items = tuple(
        sorted((*base_route_items, (FORCE_ORDERS_RESOURCE, FORCE_ORDERS_PATH)))
    )

    def fixed_request_path(
        resource: str,
        query: Mapping[str, Any],
        history_start_ms: int,
        now_ms: int,
    ) -> tuple[str, dict[str, Any], bool]:
        if state.get("installation_phase") != "installed":
            _owner_fail(owner, "force_orders_extension_not_installed")
        if state.get("dispatch_active"):
            active_routes = state.get("active_routes")
            if (
                resource != FORCE_ORDERS_RESOURCE
                or not _route_mapping_matches(base_routes, base_route_items)
                or not _route_mapping_matches(
                    expected.get("FIXED_RESOURCE_PATHS"), base_route_items
                )
                or type(active_routes) is not dict
                or owner.__dict__.get("FIXED_RESOURCE_PATHS") is not active_routes
                or owner.__dict__.get("_root_fixed_signed_get_worker")
                is not _force_orders_spawn_worker
                or not _route_mapping_matches(active_routes, force_route_items)
                or not _extension_globals_match(
                    state.get("extension_globals"),
                    state.get("extension_global_bindings"),
                    state.get("extension_function_bindings"),
                )
                or not _same_callback_binding_records(
                    _owner_callback_bindings(owner),
                    state.get("callback_bindings"),
                )
            ):
                _owner_fail(owner, "force_orders_owner_binding_lost")
        else:
            require_owner_binding()
            if resource != FORCE_ORDERS_RESOURCE:
                return base_route(resource, query, history_start_ms, now_ms)
        if type(resource) is not str or not isinstance(query, Mapping):
            _owner_fail(owner, "fixed_get_query_rejected")
        if any(type(key) is not str for key in query):
            _owner_fail(owner, "fixed_get_query_rejected")
        values = dict(query)
        if set(values) != {"startTime", "endTime", "limit"}:
            _owner_fail(owner, "fixed_get_query_rejected")
        start, end, limit = values["startTime"], values["endTime"], values["limit"]
        if (
            type(history_start_ms) is not int
            or type(now_ms) is not int
            or history_start_ms <= 0
            or now_ms <= history_start_ms
            or type(start) is not int
            or type(end) is not int
            or not history_start_ms <= start <= end < now_ms
            or end - start >= FORCE_ORDERS_MAX_INTERVAL_MS
            or end - start >= owner.MAX_ACCOUNT_WINDOW_MS
            or type(limit) is not int
            or limit != FORCE_ORDERS_PAGE_LIMIT
        ):
            _owner_fail(owner, "fixed_get_window_rejected")
        return FORCE_ORDERS_PATH, values, True

    def fixed_get_dispatcher(
        resource: str,
        query: dict[str, Any],
        api_key: str,
        secret: str,
        history_start_ms: int,
        deadline_monotonic: float,
    ) -> Any:
        if resource != FORCE_ORDERS_RESOURCE:
            require_owner_binding()
            return base_dispatch(
                resource, query, api_key, secret, history_start_ms, deadline_monotonic
            )
        if (
            owner.FIXED_RESOURCE_PATHS is not base_routes
            or not _route_mapping_matches(base_routes, base_route_items)
            or not _route_mapping_matches(expected.get("FIXED_RESOURCE_PATHS"), base_route_items)
        ):
            _owner_fail(owner, "force_orders_owner_route_binding_invalid")
        path, planned, history = fixed_request_path(
            resource, query, history_start_ms, int(owner.time.time() * 1000)
        )
        if path != FORCE_ORDERS_PATH or history is not True:
            _owner_fail(owner, "fixed_get_route_rejected")
        augmented_routes = dict(base_route_items)
        augmented_routes[FORCE_ORDERS_RESOURCE] = FORCE_ORDERS_PATH
        if owner._root_fixed_signed_get_worker is not base_worker:
            _owner_fail(owner, "force_orders_owner_worker_binding_invalid")
        active_auth = state.get("active_auth")
        active_interval = state.get("active_interval")
        active_ticket = state.get("active_root_attempt")
        reader = getattr(active_auth, "_reader", None)
        root_ledger_type = (
            root_attempt_contract[7]
            if type(root_attempt_contract) is tuple and len(root_attempt_contract) == 12
            else None
        )
        if (
            type(active_auth) is not owner._RootTH01AccountWindowAuthV1
            or active_auth._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
            or type(reader) is not owner.FixedAccountWindowGetV1
            or reader._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
            or type(active_interval) is not tuple
            or active_interval != (planned["startTime"], planned["endTime"])
            or root_ledger_type is None
            or type(active_ticket) is not root_attempt_contract[8]
            or active_ticket.ledger is None
            or type(active_ticket.ledger) is not root_ledger_type
            or active_ticket.auth is not active_auth
            or active_ticket.start_ms != planned["startTime"]
            or active_ticket.end_ms != planned["endTime"]
            or not active_ticket.ledger.verify(
                active_ticket,
                active_auth,
                planned["startTime"],
                planned["endTime"],
                expected_state="dispatching",
            )
        ):
            _owner_fail(owner, "force_orders_auth_binding_invalid")
        state["dispatch_active"] = True
        state["active_routes"] = augmented_routes
        owner.FIXED_RESOURCE_PATHS = augmented_routes
        owner._root_fixed_signed_get_worker = _force_orders_spawn_worker
        try:
            return base_dispatch(
                resource,
                planned,
                api_key,
                secret,
                history_start_ms,
                deadline_monotonic,
            )
        finally:
            worker_lost = owner._root_fixed_signed_get_worker is not _force_orders_spawn_worker
            routes_lost = owner.FIXED_RESOURCE_PATHS is not augmented_routes
            owner._root_fixed_signed_get_worker = base_worker
            owner.FIXED_RESOURCE_PATHS = base_routes
            state["dispatch_active"] = False
            state["active_routes"] = None
            if worker_lost:
                _owner_fail(owner, "force_orders_owner_worker_binding_invalid")
            if routes_lost:
                _owner_fail(owner, "force_orders_owner_route_binding_invalid")

    extension_function_bindings = _extension_function_bindings(globals())
    if extension_function_bindings is None:
        _fail("force_orders_extension_function_binding_invalid")
    state = {
        "owner": owner,
        "base_route": base_route,
        "base_dispatch": base_dispatch,
        "base_worker": base_worker,
        "base_routes": base_routes,
        "base_route_items": base_route_items,
        "candidate_module": owner._CANDIDATE_MODULE,
        "root_wrapper_module": root_wrapper_module,
        "root_attempt_contract": root_attempt_contract,
        "validator": fixed_request_path,
        "dispatcher": fixed_get_dispatcher,
        "extension_module": extension_module,
        "extension_sha256": extension_digest,
        "extension_globals": globals(),
        "extension_global_bindings": tuple(globals().items()),
        "extension_function_bindings": extension_function_bindings,
        "callback_bindings": None,
        "installation_phase": "publishing",
        "dispatch_active": False,
        "active_routes": None,
        "active_auth": None,
        "active_interval": None,
        "active_root_attempt": None,
        "issued_pages": [],
    }

    def _owner_callback_bindings(candidate: ModuleType) -> Any:
        return _callback_binding_records(
            {
                "owner": candidate,
                **{name: candidate.__dict__.get(name) for name in _CALLBACK_FUNCTION_NAMES},
                "FixedForceOrdersGetV1": candidate.__dict__.get("FixedForceOrdersGetV1"),
            }
        )

    def require_owner_binding() -> None:
        if (
            state.get("installation_phase") != "installed"
            or state.get("dispatch_active")
            or state.get("root_wrapper_module") is not root_wrapper_module
            or state.get("root_attempt_contract") is not root_attempt_contract
            or (
                owner.__name__ == "__main__"
                and (
                    root_attempt_contract is None
                    or not _same_root_attempt_contract(
                        root_wrapper_module,
                        root_attempt_contract,
                    )
                )
            )
            or (
                owner.__name__ == "__mp_main__"
                and (root_wrapper_module is not None or root_attempt_contract is not None)
            )
            or owner.__name__ not in {"__main__", "__mp_main__"}
            or not _extension_globals_match(
                state.get("extension_globals"),
                state.get("extension_global_bindings"),
                state.get("extension_function_bindings"),
            )
            or not _same_callback_binding_records(
                _owner_callback_bindings(owner), state.get("callback_bindings")
            )
            or owner is not sys.modules.get("__main__")
            or owner.__package__ != OWNER_PACKAGE_NAME
            or Path(owner.__file__).resolve() != R2_DRIVER_PATH.resolve()
            or owner.ROOT != ROOT
            or owner.__dict__.get("_CANDIDATE_MODULE") is not state["candidate_module"]
            or owner.OWNER_PATH != BASE_OWNER_PATH
            or owner.OWNER_SHA256 != BASE_OWNER_SHA256
            or owner.__dict__.get(_INSTALL_STATE_ATTR) is not state
            or owner.__dict__.get(_INSTALL_MARKER_ATTR) != extension_digest
            or owner.__dict__.get(_PUBLIC_SOURCE_PIN_ATTR) != extension_digest
            or owner.__dict__.get("_fixed_request_path") is not fixed_request_path
            or owner.__dict__.get("_run_root_fixed_signed_get") is not fixed_get_dispatcher
            or owner.__dict__.get("_root_fixed_signed_get_worker") is not base_worker
            or owner.__dict__.get("FixedForceOrdersGetV1") is not FixedForceOrdersGetV1
            or owner.__dict__.get("verify_force_orders_page") is not verify_force_orders_page
            or owner.__dict__.get("verify_force_orders_reader_binding")
            is not verify_force_orders_reader_binding
            or owner.__dict__.get("verify_force_orders_owner_binding")
            is not verify_force_orders_owner_binding
            or owner.__dict__.get("capture_force_orders_callback_bindings")
            is not capture_force_orders_callback_bindings
            or owner.__dict__.get("verify_force_orders_callback_bindings")
            is not verify_force_orders_callback_bindings
            or owner.__dict__.get("FIXED_RESOURCE_PATHS") is not base_routes
            or not _route_mapping_matches(base_routes, base_route_items)
            or not _route_mapping_matches(expected.get("FIXED_RESOURCE_PATHS"), base_route_items)
            or not _same_base_code(base_route, expected["_fixed_request_path"])
            or not _same_base_code(base_dispatch, expected["_run_root_fixed_signed_get"])
            or _read_extension_source() != (extension_module, extension_digest)
        ):
            _owner_fail(owner, "force_orders_owner_binding_lost")
        _verify_candidate_binding(owner)

    def verify_force_orders_owner_binding(candidate: object) -> bool:
        try:
            if candidate is not owner:
                return False
            require_owner_binding()
            return True
        except Exception:
            return False

    class FixedForceOrdersGetV1:
        """One-shot forceOrders capability sharing an R1 account reader."""

        __slots__ = ("_auth", "_reader", "_owner", "_root_attempt_ledger", "_seal")

        def __init__(self, auth: object, root_attempt_ledger: object):
            require_owner_binding()
            root_ledger_type = (
                root_attempt_contract[7]
                if type(root_attempt_contract) is tuple and len(root_attempt_contract) == 12
                else None
            )
            if (
                type(auth) is not owner._RootTH01AccountWindowAuthV1
                or auth._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
                or type(auth._reader) is not owner.FixedAccountWindowGetV1
                or auth._reader._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
                or auth._reader.invocation_id != auth.invocation_id
                or auth._reader.evidence_window_id != auth.evidence_window_id
                or auth._reader._account_binding_ref != auth._account_binding_ref
                or auth._reader.history_start_ms != auth.history_start_ms
                or not any(item is auth for item in owner._ACTIVE_ROOT_ACCOUNT_AUTH)
                or root_ledger_type is None
                or type(root_attempt_ledger) is not root_ledger_type
                or root_attempt_ledger._auth is not auth
                or root_attempt_ledger.verify_snapshot(root_attempt_ledger.snapshot()) is not True
            ):
                _owner_fail(owner, "force_orders_auth_binding_invalid")
            self._auth = auth
            self._reader = auth._reader
            self._owner = owner
            self._root_attempt_ledger = root_attempt_ledger
            self._seal = _FORCE_ORDERS_SEAL

        def __repr__(self) -> str:
            return "FixedForceOrdersGetV1(<same-invocation-fixed-GET>)"

        def _require(self) -> None:
            require_owner_binding()
            if (
                self._owner is not owner
                or self._seal is not _FORCE_ORDERS_SEAL
                or type(self._auth) is not owner._RootTH01AccountWindowAuthV1
                or self._auth._reader is not self._reader
                or type(self._reader) is not owner.FixedAccountWindowGetV1
                or self._reader._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_READER_SEAL
                or not any(item is self._auth for item in owner._ACTIVE_ROOT_ACCOUNT_AUTH)
                or type(self._root_attempt_ledger) is not root_attempt_contract[7]
                or self._root_attempt_ledger._auth is not self._auth
                or self._root_attempt_ledger.verify_snapshot(self._root_attempt_ledger.snapshot())
                is not True
            ):
                _owner_fail(owner, "force_orders_auth_binding_invalid")
            self._reader._require()

        def force_orders(
            self,
            start_ms: int,
            end_ms: int,
            *,
            root_attempt: object,
        ) -> Any:
            self._require()
            auth = self._auth
            ticket_type = root_attempt_contract[8]
            now_ms = int(owner.time.time() * 1000)
            query = {
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": FORCE_ORDERS_PAGE_LIMIT,
            }
            fixed_request_path(
                FORCE_ORDERS_RESOURCE,
                query,
                auth.history_start_ms,
                now_ms,
            )
            ledger = self._root_attempt_ledger
            if (
                type(root_attempt) is not ticket_type
                or root_attempt.ledger is not ledger
                or root_attempt.auth is not auth
                or root_attempt.start_ms != start_ms
                or root_attempt.end_ms != end_ms
                or ledger.verify(
                    root_attempt,
                    auth,
                    start_ms,
                    end_ms,
                    expected_state="reserved",
                )
                is not True
            ):
                _owner_fail(owner, "force_orders_attempt_ledger_invalid")
            progress_key = (FORCE_ORDERS_RESOURCE, None, start_ms, end_ms)
            if progress_key in self._reader._page_progress:
                if self._reader._page_progress.get(progress_key) != (None, 1, True):
                    _owner_fail(owner, "force_orders_reader_progress_invalid")
                self._reader._page_progress.pop(progress_key)
            state["active_auth"] = auth
            state["active_interval"] = (start_ms, end_ms)
            state["active_root_attempt"] = root_attempt
            if not ledger.consume(root_attempt, auth, start_ms, end_ms):
                state["active_auth"] = None
                state["active_interval"] = None
                state["active_root_attempt"] = None
                _owner_fail(owner, "force_orders_attempt_consume_invalid")
            try:
                try:
                    page = self._reader._get(
                        FORCE_ORDERS_RESOURCE,
                        query,
                        start_ms=start_ms,
                        end_ms=end_ms,
                        cursor=None,
                        symbol=None,
                        current=False,
                    )
                except KeyError:
                    _owner_fail(owner, "force_orders_response_overbound")
            finally:
                state["active_auth"] = None
                state["active_interval"] = None
                state["active_root_attempt"] = None
            if type(page) is not owner._RootTH01AccountWindowPageV1:
                _owner_fail(owner, "force_orders_page_binding_invalid")
            if len(page.rows) > FORCE_ORDERS_PAGE_LIMIT:
                _owner_fail(owner, "fixed_get_page_row_limit_reached")
            terminal = (
                "interval_saturated" if len(page.rows) == FORCE_ORDERS_PAGE_LIMIT else "short_page"
            )
            page = replace(
                page,
                row_limit=FORCE_ORDERS_PAGE_LIMIT,
                has_more=False,
                next_cursor=None,
                terminal_proof=terminal,
            )
            state["issued_pages"].append((auth, page, start_ms, end_ms, root_attempt))
            if not verify_force_orders_page(
                auth,
                page,
                start_ms,
                end_ms,
                root_attempt=root_attempt,
            ):
                _owner_fail(owner, "force_orders_page_binding_invalid")
            return page

    FixedForceOrdersGetV1.__name__ = "FixedForceOrdersGetV1"
    FixedForceOrdersGetV1.__qualname__ = "FixedForceOrdersGetV1"
    FixedForceOrdersGetV1.__module__ = __name__

    def verify_force_orders_reader_binding(
        candidate: object,
        auth: object,
        capability: object,
    ) -> bool:
        try:
            if candidate is not owner:
                return False
            require_owner_binding()
            return bool(
                type(auth) is owner._RootTH01AccountWindowAuthV1
                and auth._seal is owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
                and any(item is auth for item in owner._ACTIVE_ROOT_ACCOUNT_AUTH)
                and type(capability) is FixedForceOrdersGetV1
                and capability._seal is _FORCE_ORDERS_SEAL
                and capability._auth is auth
                and capability._owner is owner
                and type(capability._root_attempt_ledger) is root_attempt_contract[7]
                and capability._root_attempt_ledger._auth is auth
                and capability._reader is auth._reader
                and capability._reader._request_count is auth._reader._request_count
                and capability._reader._row_count is auth._reader._row_count
                and capability._reader._response_bytes is auth._reader._response_bytes
                and capability._reader._first_request_ms is auth._reader._first_request_ms
                and capability._reader._last_response_ms is auth._reader._last_response_ms
                and capability._reader._capture_deadline_monotonic
                is auth._reader._capture_deadline_monotonic
            )
        except Exception:
            return False

    def verify_force_orders_page(
        auth: object,
        page: object,
        start_ms: int,
        end_ms: int,
        *,
        root_attempt: object,
    ) -> bool:
        try:
            require_owner_binding()
            if (
                type(auth) is not owner._RootTH01AccountWindowAuthV1
                or auth._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_AUTH_SEAL
                or not any(item is auth for item in owner._ACTIVE_ROOT_ACCOUNT_AUTH)
                or type(page) is not owner._RootTH01AccountWindowPageV1
                or page._seal is not owner._ROOT_TH01_ACCOUNT_WINDOW_PAGE_SEAL
                or type(start_ms) is not int
                or type(end_ms) is not int
                or type(root_attempt) is not root_attempt_contract[8]
                or root_attempt.auth is not auth
                or root_attempt.start_ms != start_ms
                or root_attempt.end_ms != end_ms
                or type(root_attempt.ledger) is not root_attempt_contract[7]
                or root_attempt.ledger._auth is not auth
                or not (
                    root_attempt.ledger.verify(
                        root_attempt,
                        auth,
                        start_ms,
                        end_ms,
                        expected_state="dispatching",
                    )
                    or root_attempt.ledger.verify(
                        root_attempt,
                        auth,
                        start_ms,
                        end_ms,
                        expected_state="terminal",
                    )
                )
                or start_ms < auth.history_start_ms
                or start_ms > end_ms
                or end_ms >= int(owner.time.time() * 1000)
                or end_ms - start_ms >= FORCE_ORDERS_MAX_INTERVAL_MS
                or end_ms - start_ms >= owner.MAX_ACCOUNT_WINDOW_MS
                or page.resource != FORCE_ORDERS_RESOURCE
                or page._invocation_id != auth.invocation_id
                or page._evidence_window_id != auth.evidence_window_id
                or page._account_binding_ref != auth._account_binding_ref
                or page.requested_start_ms != start_ms
                or page.requested_end_ms != end_ms
                or page.request_cursor is not None
                or type(page.request_ref) is not str
                or not page.request_ref
                or type(page.response_ref) is not str
                or not page.response_ref
                or page.next_cursor is not None
                or page.page_index != 0
                or type(page.row_limit) is not int
                or page.row_limit != FORCE_ORDERS_PAGE_LIMIT
                or type(page.rows) is not tuple
                or type(page.row_count) is not int
                or page.row_count != len(page.rows)
                or page.row_count > FORCE_ORDERS_PAGE_LIMIT
                or page.has_more is not False
                or page.truncated is not False
                or page.provider_watermark_ms is not None
                or page.http_status != 200
                or page.transport_complete is not True
                or type(page.response_body) is not bytes
                or len(page.response_body) >= owner.MAX_FIXED_PAGE_BYTES
                or owner._root_parse_page_rows(page.response_body) != page.rows
                or type(page._private_record_ref) is not str
                or not page._private_record_ref
                or page._private_record_ref not in auth._reader._private_record_refs
            ):
                return False
            expected_path, planned, is_history = fixed_request_path(
                FORCE_ORDERS_RESOURCE,
                {
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": FORCE_ORDERS_PAGE_LIMIT,
                },
                auth.history_start_ms,
                int(owner.time.time() * 1000),
            )
            if (
                expected_path != FORCE_ORDERS_PATH
                or is_history is not True
                or planned
                != {
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": FORCE_ORDERS_PAGE_LIMIT,
                }
            ):
                return False
            reader = auth._reader
            counters = (
                reader._request_count,
                reader._row_count,
                reader._response_bytes,
                reader._first_request_ms,
                reader._last_response_ms,
                reader._capture_deadline_monotonic,
            )
            if (
                any(type(item) is not list or len(item) != 1 for item in counters)
                or type(reader._request_count[0]) is not int
                or reader._request_count[0] < 1
                or type(reader._row_count[0]) is not int
                or reader._row_count[0] < page.row_count
                or type(reader._response_bytes[0]) is not int
                or reader._response_bytes[0] < len(page.response_body)
                or type(reader._first_request_ms[0]) is not int
                or type(reader._last_response_ms[0]) is not int
                or type(reader._capture_deadline_monotonic[0]) not in (int, float)
            ):
                return False
            expected_terminal = (
                "interval_saturated" if page.row_count == FORCE_ORDERS_PAGE_LIMIT else "short_page"
            )
            key = (FORCE_ORDERS_RESOURCE, None, start_ms, end_ms)
            state_recorded = any(
                type(item) is tuple
                and len(item) == 5
                and item[0] is auth
                and item[1] is page
                and item[2] == start_ms
                and item[3] == end_ms
                and item[4] is root_attempt
                for item in state["issued_pages"]
            )
            return bool(
                page.terminal_proof == expected_terminal
                and auth._reader._page_progress.get(key) == (None, 1, True)
                and state_recorded
            )
        except Exception:
            return False

    bindings = {
        "_fixed_request_path": fixed_request_path,
        "_run_root_fixed_signed_get": fixed_get_dispatcher,
        "FixedForceOrdersGetV1": FixedForceOrdersGetV1,
        "verify_force_orders_page": verify_force_orders_page,
        "verify_force_orders_reader_binding": verify_force_orders_reader_binding,
        "verify_force_orders_owner_binding": verify_force_orders_owner_binding,
        "capture_force_orders_callback_bindings": capture_force_orders_callback_bindings,
        "verify_force_orders_callback_bindings": verify_force_orders_callback_bindings,
        _INSTALL_STATE_ATTR: state,
        _INSTALL_MARKER_ATTR: extension_digest,
        _PUBLIC_SOURCE_PIN_ATTR: extension_digest,
    }
    state["callback_bindings"] = _callback_binding_records({"owner": owner, **bindings})
    if state["callback_bindings"] is None:
        _fail("force_orders_callback_binding_invalid")
    replaceable = {"_fixed_request_path", "_run_root_fixed_signed_get"}
    if any(name in owner.__dict__ and name not in replaceable for name in bindings):
        _fail("force_orders_extension_already_installed")
    _publish_module_bindings(
        owner.__dict__,
        bindings,
        _INSTALL_FAILED_ATTR,
        extension_digest,
        state,
    )
    return owner


def _force_orders_spawn_worker(
    pipe: Any,
    resource: str,
    query: dict[str, Any],
    api_key: str,
    secret: str,
    history_start_ms: int,
    deadline_monotonic: float,
) -> None:
    """Spawn target that reinstalls the pinned validator in the child first."""
    owner = sys.modules.get("__main__")
    if type(owner) is not ModuleType:
        raise ForceOrdersExtensionBlocked("force_orders_spawn_binding_invalid")
    child_package = getattr(owner, "__package__", None)
    if child_package not in (None, "", OWNER_PACKAGE_NAME):
        raise ForceOrdersExtensionBlocked("force_orders_spawn_binding_invalid")
    owner.__package__ = OWNER_PACKAGE_NAME
    state = owner.__dict__.get(_INSTALL_STATE_ATTR)
    if state is None:
        install_force_orders_extension(owner)
        state = getattr(owner, _INSTALL_STATE_ATTR, None)
    if (
        type(owner) is not ModuleType
        or type(state) is not dict
        or state.get("owner") is not owner
        or resource != FORCE_ORDERS_RESOURCE
        or owner._root_fixed_signed_get_worker
        not in {state.get("base_worker"), _force_orders_spawn_worker}
        or owner._fixed_request_path is not state.get("validator")
    ):
        if type(owner) is ModuleType and callable(getattr(owner, "_account_window_fail", None)):
            owner._account_window_fail("fixed_get_worker_input_invalid")
        raise ForceOrdersExtensionBlocked("force_orders_spawn_binding_invalid")
    state["base_worker"](
        pipe,
        resource,
        query,
        api_key,
        secret,
        history_start_ms,
        deadline_monotonic,
    )


__all__ = [
    "BASE_OWNER_SHA256",
    "FORCE_ORDERS_PAGE_LIMIT",
    "FORCE_ORDERS_PATH",
    "FORCE_ORDERS_RESOURCE",
    "ForceOrdersExtensionBlocked",
    "capture_force_orders_callback_bindings",
    "install_force_orders_extension",
    "verify_force_orders_callback_bindings",
]
