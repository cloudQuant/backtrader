"""Two-leg extension of the accepted DIM05 Risk Host test fixture.

Derived from the R18 fixture
``_dim05_roll_exit_risk_host_fixture_diagnostic.py`` at SHA-256
``ec2eddf64ce3f17db39e24e4ab2f8cd1d8dadf8cf624d6fcab087ce269a20a94``.
The additive change accepts multiple exact source-leg IDs from an already
persisted group, installs one real closeable Risk allocation per source
instrument, and configures one synthetic full provider fill per source leg.
The group and origin proof must already be persisted by the caller. This
fixture does not fabricate a Risk reply or seed group authority.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import json
import queue
import re
import socket
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import zmq
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution import SqliteOrderGroupStore, risk_account_scope_fingerprint
from bt_api_risk import (
    AccountScope,
    DurableRiskAdmissionAdapter,
    DurableRiskGate,
    InstrumentRiskAdmissionMapper,
    InstrumentRiskRegistry,
)

from bt_api_py.bt_api import BtApi
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_execution_group_client import GroupOriginRunBindingStore
from bt_api_py.service_execution_group_roll_exit_source import (
    GroupRollExitAuthorizationSourceV1,
)
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import (
    PrincipalGrant,
    ResourceGrant,
    TrustedGroupReservationPolicy,
    TrustedGroupWritePolicy,
)
from bt_api_py.service_risk_order_entry import RiskOrderTarget
from bt_api_py.service_risk_order_journal import RiskOrderJournal

_RISK_SERVICE_ID = "dim05-roll-exit-risk-service"
_RISK_INSTANCE = "dim05-roll-exit-risk-owner"
_RISK_PRINCIPAL = "dim05-roll-exit-risk-principal"
_RESERVATION_SERVER_SECURITY_REF = "dim05-roll-exit-reservation-server-curve-v1"
_RESERVATION_CLIENT_SECURITY_REF = "dim05-roll-exit-reservation-client-curve-v1"
_RESERVATION_CLIENT_TRANSPORT_REF = "dim05-roll-exit-reservation-connect-v1"
_RESERVATION_OPERATIONS = frozenset(
    {"reservations.reserve", "reservations.query", "reservations.release"}
)
_SEED_SCOPE_VERSION = "group-service-scope-v1"
_SEED_REGISTRATION_VERSION = "group-registration-v1"
_SEED_REQUIREMENTS_VERSION = "group-requirements-v1"
_ENTRY_SCOPE_REF = "dim05-roll-exit-entry-v1"
_QUERY_SCOPE_REF = "dim05-roll-exit-query-v1"
_SERVER_SECURITY_REF = "dim05-roll-exit-server-curve-v1"
_CLIENT_SECURITY_REF = "dim05-roll-exit-client-curve-v1"
_LISTENER_REF = "dim05-roll-exit-listener-v1"
_CLIENT_TRANSPORT_REF = "dim05-roll-exit-connect-v1"
_SUBMIT = "orders.submit_group_roll_exit"
_PREPARE = "orders.prepare_group_roll_exit"
_QUERY = "orders.query_group_roll_exit"
_SDK_TESTS_ROOT_ENV = "BT_API_PY_TESTS_ROOT"
_DIM05_SOURCE_MODULE = "tests.integration.test_arb03_dim05_group_partial_fill_service"
_DIM05_SOURCE_RELATIVE_PATH = Path(
    "integration/test_arb03_dim05_group_partial_fill_service.py"
)
_DIM05_SOURCE_SHA256 = "d9e516f3b8cbc3cdde4f7e477c3526109603ff0c3a1b01f58be2df9086787887"
_PROVIDER_FIXTURE_MODULE = "tests.unit._service_group_provider_fixtures"
_PROVIDER_FIXTURE_RELATIVE_PATH = Path("unit/_service_group_provider_fixtures.py")
_PROVIDER_FIXTURE_SHA256 = "9bcf021649104243a2b16a93ef159ceca8cacce6ffad9c22afd94eed4ee3b1e2"


def _loaded_sdk_test_module(module_name: str, relative_path: Path, sha256: str):
    """Return a source-pinned SDK support module installed by the R18 loader."""

    root_text = os.environ.get(_SDK_TESTS_ROOT_ENV)
    if type(root_text) is not str or not root_text.strip():
        raise AssertionError(f"{_SDK_TESTS_ROOT_ENV} must name the fixed SDK tests export")
    source_path = (Path(root_text).resolve() / relative_path).resolve()
    source = source_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != sha256:
        raise AssertionError(f"fixed SDK test support pin changed: {source_path.name}")
    module = sys.modules.get(module_name)
    if module is None:
        raise AssertionError("R18 fixed SDK support bootstrap has not loaded the dependency")
    module_path_text = getattr(module, "__file__", None)
    if type(module_path_text) is not str or Path(module_path_text).resolve() != source_path:
        raise AssertionError("loaded SDK test support came from a different source path")
    return module


def _dim05_module():
    return _loaded_sdk_test_module(
        _DIM05_SOURCE_MODULE,
        _DIM05_SOURCE_RELATIVE_PATH,
        _DIM05_SOURCE_SHA256,
    )


def _filled_close_feed_type():
    """Create the close-only provider leaf after R18 pins its SDK base class."""

    provider_fixtures = _loaded_sdk_test_module(
        _PROVIDER_FIXTURE_MODULE,
        _PROVIDER_FIXTURE_RELATIVE_PATH,
        _PROVIDER_FIXTURE_SHA256,
    )
    base = getattr(provider_fixtures, "_V2SyntheticBtApiFeed", None)
    if not isinstance(base, type):
        raise AssertionError("fixed provider fixture omitted its synthetic BT API feed")

    class _FilledCloseFeed(base):
        """A fixed synthetic provider leaf; Risk still creates and submits the order."""

        def __init__(
            self,
            ledger_path: str,
            provider_account: str,
            *,
            seeded_order_count: int,
            close_fill_count: int,
        ) -> None:
            if type(seeded_order_count) is not int or seeded_order_count < 0:
                raise ValueError("seeded_order_count must be a non-negative int")
            if type(close_fill_count) is not int or close_fill_count < 1:
                raise ValueError("close_fill_count must be a positive int")
            states = ("open",) * seeded_order_count + ("filled",) * close_fill_count
            super().__init__(ledger_path, states, provider_account)
            self.calls: list[tuple[str, Decimal, Decimal, str, str]] = []

        def make_order(
            self,
            symbol: str,
            volume: float,
            price: float,
            order_type: str,
            *,
            client_order_id: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            quantity = Decimal(str(volume))
            price_value = Decimal(str(price))
            if kwargs != {
                "offset": "close",
                "post_only": False,
                "reduce_only": True,
                "time_in_force": "GTC",
            }:
                raise AssertionError(
                    "Risk close must reach the synthetic provider as CLOSE/reduce-only/GTC"
                )
            self.calls.append((symbol, quantity, price_value, order_type, client_order_id))
            return super().make_order(
                symbol,
                volume,
                price,
                order_type,
                client_order_id=client_order_id,
                **kwargs,
            )

    _FilledCloseFeed.__module__ = __name__
    return _FilledCloseFeed


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _component(instance_id: str, ports: tuple[str, ...], role: str) -> dict[str, Any]:
    return {
        "config_schema_version": 2,
        "settings": {
            "instance_id": instance_id,
            "bind_ports": list(ports),
            "options": {
                "role": role,
                "account_policy_ref": _dim05_module()._risk_policy().policy_id,
            },
        },
    }


def _risk_host_config(endpoint: str) -> dict[str, Any]:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _RISK_SERVICE_ID,
        "scope_ref": "dim05-roll-exit-risk-root-v1",
        "transport_ref": _LISTENER_REF,
        "registration_policy_ref": "dim05-roll-exit-registration-v1",
        "service_requirements_ref": "dim05-roll-exit-requirements-v1",
        "components": {
            "risk": _component(
                _RISK_INSTANCE,
                ("service.order_entry", "service.order_query"),
                "account_owner",
            )
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _LISTENER_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SERVER_SECURITY_REF,
                    "options": {"high_water_mark": 32, "max_message_bytes": 1_000_000},
                }
            },
        },
    }


def _group_reservations_host_config(
    endpoint: str,
    account_ref: str,
    seed_fixture: Any,
) -> dict[str, Any]:
    """Reuse the persisted owner's registration identity, with only its Risk role."""

    seed_config = seed_fixture._account_service_config(
        account_ref, endpoint, _RESERVATION_SERVER_SECURITY_REF
    )
    route_refs = seed_fixture._route_refs(account_ref)
    if type(route_refs) is not tuple or len(route_refs) != 3:
        raise AssertionError("pinned seed fixture omitted its account route references")
    if route_refs[0] != _reservation_scope_ref(account_ref):
        raise AssertionError("reservation route differs from the persisted accepted binding")
    components = seed_config.get("components")
    risk_component = components.get("risk") if isinstance(components, Mapping) else None
    if not isinstance(risk_component, Mapping):
        raise AssertionError("pinned seed fixture omitted its registered Risk owner")
    settings = risk_component.get("settings")
    if (
        not isinstance(settings, Mapping)
        or "service.group_reservations" not in settings.get("bind_ports", ())
        or settings.get("options", {}).get("role") != "group_reservations"
    ):
        raise AssertionError("pinned seed Risk owner does not declare group reservations")
    config = dict(seed_config)
    config["components"] = {"risk": dict(risk_component)}
    return config


def _client_service_config(
    endpoint: str,
    account_ref: str,
    reservation_endpoint: str,
    reservation_service_config: Mapping[str, Any],
) -> dict[str, Any]:
    dim05 = _dim05_module()
    reservation_component = reservation_service_config["components"]["risk"]
    reservation_instance_id = reservation_component["settings"]["instance_id"]
    options = {"request_timeout_ms": 2500, "high_water_mark": 32, "max_message_bytes": 1_000_000}
    execution_bindings = [
        {
            "mount": "upstream.group_roll_exit_orders",
            "service_id": _RISK_SERVICE_ID,
            "instance_id": _RISK_INSTANCE,
            "scope_ref": _ENTRY_SCOPE_REF,
            "account_ref": account_ref,
            "portfolio_ref": dim05._PORTFOLIO,
            "transport_ref": _CLIENT_TRANSPORT_REF,
        },
        {
            "mount": "upstream.group_roll_exit_order_query",
            "service_id": _RISK_SERVICE_ID,
            "instance_id": _RISK_INSTANCE,
            "scope_ref": _QUERY_SCOPE_REF,
            "account_ref": account_ref,
            "portfolio_ref": dim05._PORTFOLIO,
            "transport_ref": _CLIENT_TRANSPORT_REF,
        },
    ]
    reservation_binding = {
        "mount": "upstream.account_reservations",
        "service_id": reservation_service_config["service_id"],
        "instance_id": reservation_instance_id,
        "scope_ref": _reservation_scope_ref(account_ref),
        "account_ref": account_ref,
        "transport_ref": _RESERVATION_CLIENT_TRANSPORT_REF,
    }
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": "dim05-roll-exit-coordinator-runtime",
        "scope_ref": "dim05-roll-exit-coordinator-runtime-scope-v1",
        "transport_ref": "dim05-roll-exit-runtime-listener-v1",
        "registration_policy_ref": "dim05-roll-exit-runtime-registration-v1",
        "service_requirements_ref": "dim05-roll-exit-runtime-requirements-v1",
        "components": {
            "monitor": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": "dim05-roll-exit-unused-monitor",
                    "bind_ports": ["service.monitor_query"],
                    "options": {},
                },
            }
        },
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": execution_bindings,
                    "options": {"request_timeout_ms": 2500, "heartbeat_interval_seconds": 5},
                },
            },
            "risk": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [reservation_binding],
                    "options": {"request_timeout_ms": 2500, "heartbeat_interval_seconds": 5},
                },
            },
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "dim05-roll-exit-runtime-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": "tcp://127.0.0.1:9"},
                    "security_profile_ref": _CLIENT_SECURITY_REF,
                    "options": dict(options),
                },
                _CLIENT_TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": _CLIENT_SECURITY_REF,
                    "options": dict(options),
                },
                _RESERVATION_CLIENT_TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": reservation_endpoint},
                    "security_profile_ref": _RESERVATION_CLIENT_SECURITY_REF,
                    "options": dict(options),
                },
            },
        },
    }


def _reservation_scope_ref(account_ref: str) -> str:
    return _dim05_module()._route_refs(account_ref)[0]


@dataclass(frozen=True, slots=True)
class Dim05RiskSourcePosition:
    leg_id: str
    instrument: str
    filled_quantity: Decimal


@dataclass(frozen=True, slots=True)
class Dim05RiskHostCase:
    endpoint: str
    risk_identity: WireIdentity
    coordinator_identity: WireIdentity
    service_scope: WireScope
    owner_scope: WireScope
    account_scope: AccountScope
    account_ref: str
    provider_account_id: str
    venue: str
    environment: str
    coordinator_principal_ref: str
    coordinator_service_id: str
    coordinator_instance_id: str
    run_id: str
    entry_scope_ref: str
    query_scope_ref: str
    reservation_scope_ref: str
    server_public_key: bytes
    server_secret_key: bytes
    client_public_key: bytes
    client_secret_key: bytes
    reservation_endpoint: str
    reservation_identity: WireIdentity
    reservation_server_public_key: bytes
    reservation_server_secret_key: bytes
    reservation_client_public_key: bytes
    reservation_client_secret_key: bytes
    reservation_service_config: Mapping[str, Any]
    reservation_client_binding: Mapping[str, Any]
    reservation_instance_id: str
    reservation_grant: ResourceGrant
    reservation_security_ref: str
    reservation_authority_versions: Mapping[str, str]
    risk_service_config: Mapping[str, Any]
    risk_client_service_config: Mapping[str, Any]
    entry_client_binding: Mapping[str, Any]
    query_client_binding: Mapping[str, Any]
    account_paths: Mapping[str, str]
    coordinator_paths: Mapping[str, str]
    metadata_reference_ns: int
    group_id: str
    source_leg_id: str
    source_instrument: str
    source_positions: tuple[Dim05RiskSourcePosition, ...]
    source_strategy_ref: str
    peer_strategy_ref: str
    risk_scope_fingerprint: str
    source_filled_quantity: Decimal
    peer_quantity: Decimal
    _owner_call: Callable[[Callable[[], Any]], Any]
    _reservation_capability_reader: Callable[[], tuple[dict[str, Any], ...]]
    _available_reader: Callable[[str, str], Decimal]
    _provider_reader: Callable[[], tuple[tuple[str, Decimal, Decimal, str, str], ...]]

    def available(self, strategy_ref: str, instrument: str | None = None) -> Decimal:
        if strategy_ref not in {self.source_strategy_ref, self.peer_strategy_ref}:
            raise KeyError("unknown strategy in DIM05 synthetic fixture")
        instrument_ref = self.source_instrument if instrument is None else instrument
        known_instruments = {row.instrument for row in self.source_positions}
        if instrument_ref not in known_instruments:
            raise KeyError("unknown instrument in DIM05 synthetic fixture")
        return self._owner_call(lambda: self._available_reader(strategy_ref, instrument_ref))

    def provider_calls(self) -> tuple[tuple[str, Decimal, Decimal, str, str], ...]:
        return self._owner_call(self._provider_reader)

    def reservation_component_capabilities(self) -> tuple[dict[str, Any], ...]:
        return self._reservation_capability_reader()


_HOST_START_ERROR_DESCRIPTOR = vars(ServiceHost).get("_start_error_code")
if type(_HOST_START_ERROR_DESCRIPTOR) is not staticmethod:
    raise RuntimeError("ServiceHost._start_error_code must remain a staticmethod")
_ORIGINAL_START_ERROR_CODE = _HOST_START_ERROR_DESCRIPTOR.__func__
_ORIGINAL_START_ERROR_SIGNATURE = inspect.signature(_ORIGINAL_START_ERROR_CODE)
if tuple(_ORIGINAL_START_ERROR_SIGNATURE.parameters) != ("exc",):
    raise RuntimeError("ServiceHost._start_error_code signature changed")
_SERVICE_HOST_SOURCE = Path(sys.modules[ServiceHost.__module__].__file__).resolve()
_FIXTURE_SOURCE_ROOT = Path(__file__).resolve().parent
_PUBLIC_SOURCE_PACKAGE_NAMES = (
    "bt_api_py",
    "bt_api_base",
    "bt_api_execution",
    "bt_api_gateway",
    "bt_api_monitor",
    "bt_api_risk",
    "bt_api_transport_zmq",
)
_SAFE_START_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,95}")
_SAFE_EXCEPTION_CLASS = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_SAFE_TRACE_FUNCTION = re.compile(r"[A-Za-z_][A-Za-z0-9_<>.]{0,127}")


def _roll_exit_submit_diagnostic_projection(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the startup receipt's optional submit observation finite and payload-free."""

    if not isinstance(value, Mapping):
        return None
    attempts = value.get("rpc_attempts")
    if type(attempts) is not int or not 0 <= attempts <= 100:
        attempts = None
    categories = {
        "not_called",
        "no_reply",
        "not_observed",
        "success_reply",
        "refusal_reply",
        "malformed_reply",
    }
    reply_category = value.get("reply_category")
    if type(reply_category) is not str or reply_category not in categories:
        reply_category = "not_observed"
    valid_reply_phases = {
        "UNSTARTED",
        "PREPARED",
        "SUBMIT_STARTED",
        "STATUS_OBSERVED",
        "UNKNOWN",
        "RESOLVED",
        "NOT_FOUND",
    }
    reply_phase = value.get("reply_phase")
    if type(reply_phase) is not str or reply_phase not in valid_reply_phases:
        reply_phase = None

    def safe_code(candidate: object) -> str | None:
        return (
            candidate
            if type(candidate) is str and _SAFE_START_CODE.fullmatch(candidate) is not None
            else None
        )

    failure = value.get("first_failure")
    if type(failure) is not dict:
        safe_failure = None
    else:
        phases = {
            "risk_submit_transport",
            "risk_submit_reply_validation",
            "risk_submit_pre_rpc",
            "risk_submit_rpc_reply",
            "risk_group_roll_exit_owner_exception",
        }
        phase = failure.get("phase")
        if type(phase) is not str or phase not in phases:
            phase = "unknown"
        reply = failure.get("transport_reply_category")
        if type(reply) is not str or reply not in categories:
            reply = "not_observed"
        transport_phase = failure.get("transport_reply_phase")
        if type(transport_phase) is not str or transport_phase not in valid_reply_phases:
            transport_phase = None
        exception_class = failure.get("exception_class")
        if (
            type(exception_class) is not str
            or _SAFE_EXCEPTION_CLASS.fullmatch(exception_class) is None
        ):
            exception_class = None
        public_frames: list[dict[str, Any]] = []
        frame_rows = failure.get("public_frames")
        if type(frame_rows) is list:
            safe_sources = {
                "bt_api_py",
                "bt_api_base",
                "bt_api_execution",
                "bt_api_gateway",
                "bt_api_monitor",
                "bt_api_risk",
                "bt_api_transport_zmq",
                "fixture",
            }
            for frame in frame_rows[-8:]:
                if type(frame) is not dict:
                    continue
                source = frame.get("source")
                relative_file = frame.get("file")
                line = frame.get("line")
                function = frame.get("function")
                if (
                    type(source) is not str
                    or source not in safe_sources
                    or type(relative_file) is not str
                    or not relative_file
                    or len(relative_file) > 512
                    or relative_file.startswith("/")
                    or "\\" in relative_file
                    or any(part in {"", ".", ".."} for part in relative_file.split("/"))
                    or type(line) is not int
                    or line <= 0
                    or type(function) is not str
                    or _SAFE_TRACE_FUNCTION.fullmatch(function) is None
                ):
                    continue
                public_frames.append(
                    {
                        "source": source,
                        "file": relative_file,
                        "line": line,
                        "function": function,
                    }
                )
        safe_failure = {
            "phase": phase,
            "exception_class": exception_class,
            "code": safe_code(failure.get("code")),
            "transport_reply_category": reply,
            "transport_reply_code": safe_code(failure.get("transport_reply_code")),
            "transport_reply_phase": transport_phase,
            "public_frames": public_frames,
        }
    return {
        "schema": "arb06-risk-submit-diagnostic-v1",
        "operation": _SUBMIT,
        "rpc_attempts": attempts,
        "reply_category": reply_category,
        "reply_code": safe_code(value.get("reply_code")),
        "reply_phase": reply_phase,
        "first_failure": safe_failure,
    }


def _fixed_public_source_roots() -> tuple[tuple[str, Path], ...]:
    roots: list[tuple[str, Path]] = []
    for package_name in _PUBLIC_SOURCE_PACKAGE_NAMES:
        package = sys.modules.get(package_name)
        source = getattr(package, "__file__", None) if package is not None else None
        if type(source) is str and source:
            try:
                roots.append((package_name, Path(source).resolve().parent))
            except (OSError, RuntimeError):
                continue
    roots.append(("fixture", _FIXTURE_SOURCE_ROOT))
    return tuple(roots)


def _public_exception_projection(error: BaseException) -> dict[str, Any]:
    """Project only type and bounded frames under fixed SDK/fixture source roots."""

    error_type = type(error)
    module_name = getattr(error_type, "__module__", "")
    qualified_name = getattr(error_type, "__qualname__", error_type.__name__)
    type_name = f"{module_name}.{qualified_name}" if module_name else qualified_name
    frames: list[dict[str, Any]] = []
    frame_count = 0
    current = error.__traceback__
    roots = _fixed_public_source_roots()
    while current is not None:
        code = current.tb_frame.f_code
        try:
            filename = Path(code.co_filename).resolve()
        except (OSError, RuntimeError):
            filename = None
        if filename is not None:
            for label, source_root in roots:
                try:
                    relative = filename.relative_to(source_root)
                except ValueError:
                    continue
                frames.append(
                    {
                        "source": label,
                        "file": relative.as_posix(),
                        "line": int(current.tb_lineno),
                        "function": code.co_name,
                    }
                )
                frame_count += 1
                if len(frames) > 24:
                    del frames[0]
                break
        current = current.tb_next
    return {"exception_type": type_name, "frame_count": frame_count, "frames": frames}


def _diagnostic_service_host_type(observations: list[dict[str, Any]]) -> type[ServiceHost]:
    """Subclass Host only in this fixture and preserve its exact static API."""

    def start_error_code(exc: BaseException) -> str:
        code = _ORIGINAL_START_ERROR_CODE(exc)
        try:
            row = _public_exception_projection(exc)
            if type(code) is str and _SAFE_START_CODE.fullmatch(code):
                row["start_error_code"] = code
            observations.append(row)
        except BaseException:
            # Diagnostics must never change ServiceHost's original error code.
            pass
        return code

    if inspect.signature(start_error_code) != _ORIGINAL_START_ERROR_SIGNATURE:
        raise RuntimeError("diagnostic _start_error_code signature differs from ServiceHost")
    descriptor = staticmethod(start_error_code)
    if type(descriptor) is not staticmethod:
        raise RuntimeError("diagnostic _start_error_code descriptor changed")
    return type("_DiagnosticServiceHost", (ServiceHost,), {"_start_error_code": descriptor})


def _component_summary_projection(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    components = summary.get("components")
    if not isinstance(components, (tuple, list)):
        return rows
    for component in components:
        if not isinstance(component, Mapping):
            continue
        capabilities = component.get("capabilities", ())
        projected_capabilities: list[dict[str, Any]] = []
        if isinstance(capabilities, (tuple, list)):
            for capability in capabilities:
                if isinstance(capability, Mapping):
                    projected_capabilities.append(
                        {
                            "port": capability.get("port"),
                            "operations": list(capability.get("operations", ())),
                        }
                    )
        rows.append(
            {
                "component": component.get("component"),
                "instance_id": component.get("instance_id"),
                "declared_ports": list(component.get("declared_ports", ())),
                "capabilities": projected_capabilities,
                "internal_ports": list(component.get("internal_ports", ())),
            }
        )
    return rows


class _OwnerLoop:
    """Run Host, store access and fixture observations on one owner thread."""

    def __init__(
        self,
        host: ServiceHost,
        cleanup: list[Callable[[], None]],
        *,
        diagnostic_receipt_path: Path,
        require_cleanup_approval: bool = False,
    ) -> None:
        self.host = host
        self.cleanup = cleanup
        self.diagnostic_receipt_path = diagnostic_receipt_path
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.commands: queue.Queue[tuple[Callable[[], Any], threading.Event, list[Any]]] = (
            queue.Queue()
        )
        self.error: BaseException | None = None
        self.cleanup_errors: list[BaseException] = []
        self.thread = threading.Thread(target=self._run, name="dim05-roll-exit-risk-fixture")
        self._cleanup_callbacks_run = False
        self.cleanup_skipped = False
        self._cleanup_approval = threading.Event() if require_cleanup_approval else None
        self._cleanup_authorized = not require_cleanup_approval
        self._joined = False

    def authorize_cleanup(self, *, allow: bool) -> None:
        if self._cleanup_approval is None:
            raise RuntimeError("cleanup approval is not configured for this owner loop")
        if self._cleanup_approval.is_set():
            raise RuntimeError("cleanup approval was already decided")
        self._cleanup_authorized = bool(allow)
        self._cleanup_approval.set()

    def _run_cleanup_callbacks(self) -> None:
        if self._cleanup_callbacks_run:
            return
        self._cleanup_callbacks_run = True
        for callback in reversed(self.cleanup):
            try:
                callback()
            except BaseException as error:
                self.cleanup_errors.append(error)

    def _finish_cleanup_callbacks(self) -> None:
        approval = self._cleanup_approval
        if approval is not None:
            if not approval.wait(20):
                self.cleanup_skipped = True
                return
            if not self._cleanup_authorized:
                self.cleanup_skipped = True
                return
        self._run_cleanup_callbacks()

    def _run(self) -> None:
        try:
            self.host.start()
            self.ready.set()
            while not self.stop.is_set():
                try:
                    callback, done, result = self.commands.get_nowait()
                except queue.Empty:
                    self.host.serve_once(timeout_ms=15)
                    continue
                try:
                    result.append((True, callback()))
                except BaseException as error:
                    result.append((False, error))
                finally:
                    done.set()
        except BaseException as error:
            self.error = error
        finally:
            self.ready.set()
            if self.host.state != "closed":
                try:
                    self.host.close()
                except BaseException as error:
                    self.cleanup_errors.append(error)
            self._finish_cleanup_callbacks()
            self.finished.set()

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(10):
            raise TimeoutError("DIM05 Risk Host fixture startup timed out")
        if self.error is not None:
            add_note = getattr(self.error, "add_note", None)
            if callable(add_note):
                add_note(f"fixture diagnostic receipt: {self.diagnostic_receipt_path}")
            raise self.error
        if self.host.state != "started":
            raise RuntimeError("DIM05 Risk Host fixture did not reach started state")

    def call(self, callback: Callable[[], Any]) -> Any:
        if self.error is not None or self.stop.is_set():
            raise RuntimeError("DIM05 Risk Host fixture is not serving")
        done = threading.Event()
        result: list[Any] = []
        self.commands.put((callback, done, result))
        assert done.wait(5), "DIM05 Risk Host owner-thread observation timed out"
        succeeded, value = result[0]
        if not succeeded:
            raise value
        return value

    def close(self) -> dict[str, Any]:
        self.stop.set()
        thread_started = self.thread.ident is not None
        if thread_started:
            finished = self.finished.wait(10)
            self.thread.join(1)
            self._joined = not self.thread.is_alive()
        else:
            finished = True
            if self.host.state != "closed":
                try:
                    self.host.close()
                except BaseException as error:
                    self.cleanup_errors.append(error)
            self._finish_cleanup_callbacks()
            self.finished.set()
            self._joined = True
        return {
            "thread_started": thread_started,
            "finished": bool(finished and self.finished.is_set()),
            "joined": self._joined,
            "thread_alive": self.thread.is_alive(),
            "host_state": self.host.state,
        }


@contextmanager
def dim05_roll_exit_risk_host(
    tmp_path: Path,
    *,
    account_paths: Mapping[str, Mapping[str, str]],
    coordinator_paths: Mapping[str, str],
    metadata_reference_ns: int,
    group_id: str,
    source_leg_ids: tuple[str, ...],
    seed_fixture: Any,
    peer_quantity: Decimal = Decimal("0.75"),
    submit_diagnostic: Mapping[str, Any] | None = None,
) -> Iterator[Dim05RiskHostCase]:
    """Start the real registered Risk Host for an already-persisted DIM05 group.

    The caller owns the group setup and its SQLite paths.  The only simulated
    edge is the final provider response, fixed to a full fill for a valid CLOSE.
    """

    dim05 = _dim05_module()

    assert type(metadata_reference_ns) is int and metadata_reference_ns > 0
    assert type(group_id) is str and group_id
    assert type(source_leg_ids) is tuple and len(source_leg_ids) >= 2
    assert all(type(leg_id) is str and leg_id for leg_id in source_leg_ids)
    assert len(set(source_leg_ids)) == len(source_leg_ids)
    assert type(peer_quantity) is Decimal and peer_quantity.is_finite() and peer_quantity > 0
    assert "groups" in coordinator_paths and "run_bindings" in coordinator_paths

    group_store = SqliteOrderGroupStore(coordinator_paths["groups"])
    try:
        snapshot = group_store.get(dim05._PORTFOLIO, group_id)
    finally:
        group_store.close()
    assert snapshot is not None, "caller must persist the accepted group before starting Risk Host"
    request = snapshot.request
    requested_ids = set(source_leg_ids)
    progress_by_id = {row.leg_id: row for row in snapshot.legs}
    plans_by_id = {row.leg_id: row for row in request.legs}
    if requested_ids != set(source_leg_ids) or not requested_ids.issubset(plans_by_id):
        raise AssertionError("source leg IDs must identify persisted group request legs")
    if not requested_ids.issubset(progress_by_id):
        raise AssertionError("source leg IDs must identify persisted group progress rows")
    persisted_order = tuple(row.leg_id for row in request.legs if row.leg_id in requested_ids)
    if persisted_order != source_leg_ids:
        raise AssertionError("source leg IDs must preserve persisted group order")
    source_positions_list: list[Dim05RiskSourcePosition] = []
    for leg_id in source_leg_ids:
        source_plan = plans_by_id[leg_id]
        source_progress = progress_by_id[leg_id]
        if source_plan.maximum_intent.position_effect.value != "OPEN":
            raise AssertionError("only persisted OPEN group legs can seed source positions")
        if source_progress.child_status is None:
            raise AssertionError("source OPEN leg must have a persisted terminal fill projection")
        source_quantity = source_progress.child_status.filled_quantity
        if type(source_quantity) is not Decimal or source_quantity <= 0:
            raise AssertionError("source OPEN leg must have a positive persisted fill")
        source_positions_list.append(
            Dim05RiskSourcePosition(
                leg_id=leg_id,
                instrument=source_plan.maximum_intent.instrument,
                filled_quantity=source_quantity,
            )
        )
    source_positions = tuple(source_positions_list)
    if len({row.instrument for row in source_positions}) != len(source_positions):
        raise AssertionError("this fixture requires distinct source instruments")
    source_leg_id = source_positions[0].leg_id
    source_plan = plans_by_id[source_leg_id]
    source_quantity = source_positions[0].filled_quantity
    account_ref = source_plan.account_ref
    assert set(account_paths) == {account_ref}, "this fixture currently supports one owner account"
    instrument = source_positions[0].instrument
    instruments = tuple(dict.fromkeys(leg.maximum_intent.instrument for leg in request.legs))
    assert all(leg.account_ref == account_ref for leg in request.legs)
    assert type(request.strategy_id) is str and request.strategy_id == dim05._STRATEGY

    provider_account = f"provider-{account_ref}"
    endpoint = _endpoint()
    reservation_endpoint = _endpoint()
    while reservation_endpoint == endpoint:
        reservation_endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    reservation_server_public, reservation_server_secret = zmq.curve_keypair()
    reservation_client_public, reservation_client_secret = zmq.curve_keypair()
    owner_scope = dim05._owner_scope(account_ref)
    peer_strategy = "strategy-dim05-peer"
    if peer_strategy == request.strategy_id:
        peer_strategy = "strategy-dim05-peer-other"
    peer_scope = replace(owner_scope, strategy_ref=peer_strategy)
    coordinator_identity = WireIdentity(
        WireRole.SERVICE, dim05._COORDINATOR_PRINCIPAL, dim05._COORDINATOR_SERVICE_ID
    )
    risk_identity = WireIdentity(WireRole.SERVICE, _RISK_PRINCIPAL, _RISK_SERVICE_ID)
    reservation_service_config = _group_reservations_host_config(
        reservation_endpoint, account_ref, seed_fixture
    )
    reservation_instance_id = reservation_service_config["components"]["risk"]["settings"][
        "instance_id"
    ]
    reservation_identity = WireIdentity(
        WireRole.SERVICE,
        f"group-owner-service-principal-{account_ref}",
        reservation_service_config["service_id"],
    )
    reservation_scope_ref = _reservation_scope_ref(account_ref)

    risk_gate_path = str(tmp_path / "dim05-roll-exit-risk-gate.sqlite3")
    risk_journal_path = str(tmp_path / "dim05-roll-exit-risk-journal.sqlite3")
    risk_store_path = str(tmp_path / "dim05-roll-exit-risk-registry.sqlite3")
    state: dict[str, Any] = {}
    cleanup: list[Callable[[], None]] = []
    provider_failure: list[dict[str, Any]] = []
    start_error_observations: list[dict[str, Any]] = []
    resource_cleanup_errors: list[dict[str, Any]] = []
    resource_cleanup_invocations = [0]
    old_mapper = None
    mapper_original_captured = False
    mapper_installed = False
    from bt_api_py._venue_mappers import MAPPERS

    def close_resources() -> None:
        nonlocal mapper_installed
        resource_cleanup_invocations[0] += 1
        for key in ("bt_api", "risk_gate", "origin_store", "group_store", "graph"):
            resource = state.get(key)
            if resource is None:
                continue
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                close()
            except BaseException as error:
                resource_cleanup_errors.append(_public_exception_projection(error))
        if mapper_installed:
            try:
                if old_mapper is None:
                    MAPPERS.pop("FIXTURE___SPOT", None)
                else:
                    MAPPERS["FIXTURE___SPOT"] = old_mapper
            except BaseException as error:
                resource_cleanup_errors.append(_public_exception_projection(error))
            mapper_installed = False

    # Register before the builder starts so every successfully assigned resource
    # is covered if a later constructor or Host startup step fails.
    cleanup.append(close_resources)

    def resource_provider_inner(component, instance_id, options, _scope):
        nonlocal old_mapper, mapper_original_captured, mapper_installed
        assert (component, instance_id, options["role"]) == (
            "risk",
            _RISK_INSTANCE,
            "account_owner",
        )
        if not mapper_original_captured:
            old_mapper = MAPPERS.get("FIXTURE___SPOT")
            mapper_original_captured = True
        # The accepted account graph builder also assigns this synthetic mapper;
        # mark before entering it so the early cleanup callback can restore the
        # exact pre-fixture binding even if a later builder step raises.
        mapper_installed = True
        graph = dim05._new_account_resource_graph(
            account_ref,
            account_paths[account_ref],
            ("open", "open", "filled"),
            metadata_reference_ns,
            instruments,
            (),
        )
        state["graph"] = graph
        risk_scope = graph.risk_scope
        risk_scope_fingerprint = risk_account_scope_fingerprint(risk_scope.key)
        local_group_store = SqliteOrderGroupStore(coordinator_paths["groups"])
        state["group_store"] = local_group_store
        origin_store = GroupOriginRunBindingStore(coordinator_paths["run_bindings"])
        state["origin_store"] = origin_store
        graph.authority.guard.bind_reconciliation_source(graph.bundle.proof_source)
        source = GroupRollExitAuthorizationSourceV1(
            graph.accepted_store,
            origin_store,
            local_group_store,
            graph.execution_store,
            graph.bundle.proof_source,
            graph.authority.guard,
            coordinator_principal_ref=dim05._COORDINATOR_PRINCIPAL,
        )
        assert source.ready is True
        feed_type = _filled_close_feed_type()
        feed = feed_type(
            account_paths[account_ref]["provider"],
            provider_account,
            seeded_order_count=len(snapshot.legs),
            close_fill_count=len(source_positions),
        )
        state["feed"] = feed
        bt_api = BtApi(debug=False)
        state["bt_api"] = bt_api
        MAPPERS["FIXTURE___SPOT"] = MAPPERS["BINANCE___SPOT"]
        bt_api.exchange_feeds["FIXTURE___SPOT"] = feed
        journal = RiskOrderJournal(risk_journal_path, writer_id="dim05-roll-exit-risk")
        state["risk_journal"] = journal
        gate = DurableRiskGate(
            risk_gate_path,
            dim05._risk_policy(),
            execution_journal_authority=journal,
            gross_exposure_authority=journal,
        )
        state["risk_gate"] = gate
        proof_source = graph.bundle.proof_source
        registry = proof_source.targets[graph.owner_scope].risk_target.registry
        targets: dict[WireScope, RiskOrderTarget] = {}
        admissions: dict[WireScope, DurableRiskAdmissionAdapter] = {}
        contracts = {}
        strategy_scopes = ((request.strategy_id, owner_scope), (peer_strategy, peer_scope))
        for strategy_id, wire_scope in strategy_scopes:
            gate.set_strategy_allocation(
                risk_scope,
                strategy_id,
                f"dim05-roll-exit-allocation-{strategy_id}",
                max_notional=Decimal("100000"),
                notional_unit="USD",
            )
            targets[wire_scope] = RiskOrderTarget(
                account_scope=risk_scope,
                strategy_id=strategy_id,
                exchange_name="FIXTURE___SPOT",
                provider_account_id=provider_account,
                registry=registry,
            )
            mapper = InstrumentRiskAdmissionMapper(
                risk_scope,
                registry,
                clock_ns=time.time_ns,
                allocation_reader=lambda routed_scope: gate.get_strategy_allocation(
                    risk_scope, routed_scope.strategy_id
                ),
                wire_account_ref=account_ref,
            )
            admissions[wire_scope] = DurableRiskAdmissionAdapter(gate, mapper)
            contracts[wire_scope] = replace(
                proof_source.targets[graph.owner_scope].provider_contract,
                supported_time_in_force=("GTC", "IOC"),
                supported_position_effects=("OPEN", "CLOSE"),
            )
        for source_position in source_positions:
            gate.set_closable_position(
                risk_scope,
                source_position.instrument,
                request.strategy_id,
                f"dim05-roll-exit-source-position-v1:{source_position.leg_id}",
                closable_quantity=source_position.filled_quantity,
                quantity_unit="base",
            )
        gate.set_closable_position(
            risk_scope,
            instrument,
            peer_strategy,
            "dim05-roll-exit-peer-position-v1",
            closable_quantity=peer_quantity,
            quantity_unit="base",
        )
        policy = TrustedGroupWritePolicy(
            _RISK_INSTANCE,
            dim05._COORDINATOR_PRINCIPAL,
            coordinator_identity,
            _ENTRY_SCOPE_REF,
            owner_scope,
            dim05._RUN,
            operation=_SUBMIT,
        )
        state.update(
            {
                "graph": graph,
                "group_store": local_group_store,
                "origin_store": origin_store,
                "source": source,
                "risk_journal": journal,
                "risk_gate": gate,
                "feed": feed,
                "bt_api": bt_api,
            }
        )

        return ComponentResources.borrowed(
            {
                "bt_api": bt_api,
                "targets": targets,
                "admission": admissions,
                "journal": journal,
                "gate": gate,
                "provider_contracts": contracts,
                "group_roll_exit_authorization_source": source,
            },
            ready=lambda: source.ready is True,
        )

    def resource_provider(component, instance_id, options, scope):
        try:
            return resource_provider_inner(component, instance_id, options, scope)
        except BaseException as error:
            provider_failure.append(_public_exception_projection(error))
            raise

    entry_grant = ResourceGrant(
        _RISK_INSTANCE,
        "service.order_entry",
        _ENTRY_SCOPE_REF,
        owner_scope,
        frozenset({_SUBMIT}),
    )
    query_grant = ResourceGrant(
        _RISK_INSTANCE,
        "service.order_query",
        _QUERY_SCOPE_REF,
        owner_scope,
        frozenset({"orders.prepare_group_roll_exit", "orders.query_group_roll_exit"}),
    )
    reservation_policy = TrustedGroupReservationPolicy(
        reservation_instance_id,
        dim05._COORDINATOR_PRINCIPAL,
        coordinator_identity,
        reservation_scope_ref,
        owner_scope,
        dim05._RUN,
        account_ref,
    )
    reservation_grant = ResourceGrant(
        reservation_instance_id,
        "service.group_reservations",
        reservation_scope_ref,
        owner_scope,
        _RESERVATION_OPERATIONS,
    )
    config = parse_service_config(_risk_host_config(endpoint))
    diagnostic_host_type = _diagnostic_service_host_type(start_error_observations)
    host = diagnostic_host_type(
        config,
        TrustedServiceAuthority(
            identity=risk_identity,
            scope=WireScope(dim05._DOMAIN),
            scope_ref=config.scope_ref,
            scope_version="dim05-roll-exit-service-scope-v1",
            security_ref=_SERVER_SECURITY_REF,
            security_version="dim05-roll-exit-curve-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version="dim05-roll-exit-registration-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version="dim05-roll-exit-requirements-v1",
            curve_public_key=server_public,
            curve_secret_key=server_secret,
            principals={client_public: dim05._COORDINATOR_PRINCIPAL},
            grants={
                dim05._COORDINATOR_PRINCIPAL: (
                    PrincipalGrant(coordinator_identity, (entry_grant, query_grant)),
                )
            },
            group_write_policies=(
                TrustedGroupWritePolicy(
                    _RISK_INSTANCE,
                    dim05._COORDINATOR_PRINCIPAL,
                    coordinator_identity,
                    _ENTRY_SCOPE_REF,
                    owner_scope,
                    dim05._RUN,
                    operation=_SUBMIT,
                ),
            ),
        ),
        risk_store_path,
        resource_provider,
    )
    reservation_config = parse_service_config(reservation_service_config)

    def reservation_resource_provider(component, instance_id, _options, _scope):
        if component != "risk" or instance_id != reservation_instance_id:
            raise AssertionError("unexpected group reservations resource request")
        graph = state.get("graph")
        if graph is None:
            raise AssertionError("Risk account graph must exist before reservation Host startup")
        return ComponentResources.borrowed(
            {
                "accepted_group_store": graph.accepted_store,
                "group_runtime_bundle": graph.bundle,
            },
            ready=lambda: graph.bundle.reservation_target_for(owner_scope)
            is not None,
        )

    reservation_host = ServiceHost(
        reservation_config,
        TrustedServiceAuthority(
            identity=reservation_identity,
            scope=WireScope(dim05._DOMAIN),
            scope_ref=reservation_config.scope_ref,
            scope_version=_SEED_SCOPE_VERSION,
            security_ref=_RESERVATION_SERVER_SECURITY_REF,
            security_version=f"curve-keys-{account_ref}-v1",
            registration_policy_ref=reservation_config.registration_policy_ref,
            registration_policy_version=_SEED_REGISTRATION_VERSION,
            service_requirements_ref=reservation_config.service_requirements_ref,
            service_requirements_version=_SEED_REQUIREMENTS_VERSION,
            curve_public_key=reservation_server_public,
            curve_secret_key=reservation_server_secret,
            principals={reservation_client_public: dim05._COORDINATOR_PRINCIPAL},
            grants={
                dim05._COORDINATOR_PRINCIPAL: (
                    PrincipalGrant(coordinator_identity, (reservation_grant,)),
                )
            },
            group_reservation_policies=(reservation_policy,),
        ),
        tmp_path / "dim05-roll-exit-reservations-registry.sqlite3",
        reservation_resource_provider,
    )
    receipt_text = os.environ.get("ARB06_STARTUP_DIAGNOSTIC_RECEIPT")
    diagnostic_receipt_path = (
        Path(receipt_text).resolve()
        if type(receipt_text) is str and receipt_text.strip()
        else tmp_path / "dim05-risk-host-start-diagnostic.json"
    )
    if diagnostic_receipt_path.exists():
        raise AssertionError("fresh fixture diagnostic receipt path already exists")
    loop = _OwnerLoop(
        host,
        cleanup,
        diagnostic_receipt_path=diagnostic_receipt_path,
        require_cleanup_approval=True,
    )
    reservation_loop = _OwnerLoop(
        reservation_host,
        [],
        diagnostic_receipt_path=tmp_path / "dim05-reservations-host-start-diagnostic.json",
    )
    primary_error: BaseException | None = None
    try:
        client_config = _client_service_config(
            endpoint, account_ref, reservation_endpoint, reservation_service_config
        )
        binding_rows = client_config["clients"]["execution"]["settings"]["bindings"]
        risk_binding_rows = client_config["clients"]["risk"]["settings"]["bindings"]
        entry_binding = next(
            row for row in binding_rows if row["mount"] == "upstream.group_roll_exit_orders"
        )
        query_binding = next(
            row for row in binding_rows if row["mount"] == "upstream.group_roll_exit_order_query"
        )
        reservation_binding = next(
            row
            for row in risk_binding_rows
            if row["mount"] == "upstream.account_reservations"
        )
        loop.start()
        reservation_loop.start()
        if provider_failure:
            raise AssertionError(("resource_provider", provider_failure[-1]))
        risk_scope = state["graph"].risk_scope
        risk_scope_fingerprint = risk_account_scope_fingerprint(risk_scope.key)
        case = Dim05RiskHostCase(
            endpoint=endpoint,
            risk_identity=risk_identity,
            coordinator_identity=coordinator_identity,
            service_scope=WireScope(dim05._DOMAIN),
            owner_scope=owner_scope,
            account_scope=risk_scope,
            account_ref=account_ref,
            provider_account_id=provider_account,
            venue="fixture",
            environment="simulation",
            coordinator_principal_ref=dim05._COORDINATOR_PRINCIPAL,
            coordinator_service_id=dim05._COORDINATOR_SERVICE_ID,
            coordinator_instance_id=dim05._COORDINATOR_INSTANCE_ID,
            run_id=dim05._RUN,
            entry_scope_ref=_ENTRY_SCOPE_REF,
            query_scope_ref=_QUERY_SCOPE_REF,
            reservation_scope_ref=reservation_scope_ref,
            server_public_key=server_public,
            server_secret_key=server_secret,
            client_public_key=client_public,
            client_secret_key=client_secret,
            reservation_endpoint=reservation_endpoint,
            reservation_identity=reservation_identity,
            reservation_instance_id=reservation_instance_id,
            reservation_grant=reservation_grant,
            reservation_security_ref=_RESERVATION_SERVER_SECURITY_REF,
            reservation_authority_versions={
                "scope": _SEED_SCOPE_VERSION,
                "registration": _SEED_REGISTRATION_VERSION,
                "requirements": _SEED_REQUIREMENTS_VERSION,
            },
            reservation_server_public_key=reservation_server_public,
            reservation_server_secret_key=reservation_server_secret,
            reservation_client_public_key=reservation_client_public,
            reservation_client_secret_key=reservation_client_secret,
            reservation_service_config=dict(reservation_service_config),
            reservation_client_binding=dict(reservation_binding),
            risk_service_config=_risk_host_config(endpoint),
            risk_client_service_config=client_config,
            entry_client_binding=dict(entry_binding),
            query_client_binding=dict(query_binding),
            account_paths=dict(account_paths[account_ref]),
            coordinator_paths=dict(coordinator_paths),
            metadata_reference_ns=metadata_reference_ns,
            group_id=group_id,
            source_leg_id=source_leg_id,
            source_instrument=instrument,
            source_positions=source_positions,
            source_strategy_ref=request.strategy_id,
            peer_strategy_ref=peer_strategy,
            risk_scope_fingerprint=risk_scope_fingerprint,
            source_filled_quantity=source_quantity,
            peer_quantity=peer_quantity,
            _owner_call=loop.call,
            _reservation_capability_reader=lambda: reservation_loop.call(
                lambda: tuple(_component_summary_projection(reservation_host.summary))
            ),
            _available_reader=lambda strategy_ref, instrument_ref: (
                state["risk_gate"]
                .get_closable_position(
                    risk_scope,
                    instrument_ref,
                    strategy_ref,
                    position_side="NET",
                    position_bucket="ALL",
                )
                .available_quantity
            ),
            _provider_reader=lambda: tuple(state["feed"].calls),
        )
        yield case
    except BaseException as error:
        primary_error = error
        raise
    finally:
        reservation_close_error = None
        try:
            reservation_loop_status = reservation_loop.close()
        except BaseException as error:
            reservation_close_error = _public_exception_projection(error)
            reservation_loop_status = {
                "thread_started": reservation_loop.thread.ident is not None,
                "finished": reservation_loop.finished.is_set(),
                "joined": reservation_loop._joined,
                "thread_alive": reservation_loop.thread.is_alive(),
                "host_state": reservation_host.state,
            }
        reservation_owner_stopped = bool(
            reservation_close_error is None
            and reservation_loop_status["finished"]
            and reservation_loop_status["joined"]
            and not reservation_loop_status["thread_alive"]
            and reservation_host.state == "closed"
        )
        # Risk owns the graph borrowed by the reservation Host. Release that
        # graph only after the borrower is closed and its owner thread joined.
        loop.authorize_cleanup(allow=reservation_owner_stopped)
        loop_status = loop.close()
        summary = host.summary
        host_state = host.state
        start_failure = summary.get("start_failure")
        if type(start_failure) is not str or _SAFE_START_CODE.fullmatch(start_failure) is None:
            start_failure = None
        summary_cleanup = summary.get("cleanup_failures", ())
        safe_summary_cleanup = [
            item
            for item in summary_cleanup
            if type(item) is str and _SAFE_START_CODE.fullmatch(item) is not None
        ]
        reservation_summary = reservation_host.summary
        reservation_host_state = reservation_host.state
        reservation_start_failure = reservation_summary.get("start_failure")
        if (
            type(reservation_start_failure) is not str
            or _SAFE_START_CODE.fullmatch(reservation_start_failure) is None
        ):
            reservation_start_failure = None
        reservation_summary_cleanup = reservation_summary.get("cleanup_failures", ())
        safe_reservation_summary_cleanup = [
            item
            for item in reservation_summary_cleanup
            if type(item) is str and _SAFE_START_CODE.fullmatch(item) is not None
        ]
        receipt = {
            "schema": "arb06-risk-host-fixture-start-cleanup-v1",
            "host": {
                "state": host_state,
                "start_failure": start_failure,
                "components": _component_summary_projection(summary),
                "cleanup_failures": safe_summary_cleanup,
            },
            "owner_loop": loop_status,
            "group_reservations_host": {
                "state": reservation_host_state,
                "start_failure": reservation_start_failure,
                "components": _component_summary_projection(reservation_summary),
                "cleanup_failures": safe_reservation_summary_cleanup,
            },
            "group_reservations_owner_loop": reservation_loop_status,
            "reservation_owner_close_error": reservation_close_error,
            "shared_resource_cleanup_authorized": reservation_owner_stopped,
            "shared_resource_cleanup_skipped": loop.cleanup_skipped,
            "owner_error": (
                _public_exception_projection(loop.error) if loop.error is not None else None
            ),
            "group_reservations_owner_error": (
                _public_exception_projection(reservation_loop.error)
                if reservation_loop.error is not None
                else None
            ),
            "start_error_observations": list(start_error_observations),
            "resource_provider_failures": list(provider_failure),
            "resource_cleanup_invocations": resource_cleanup_invocations[0],
            "resource_cleanup_errors": list(resource_cleanup_errors),
            "owner_cleanup_errors": [
                _public_exception_projection(error) for error in loop.cleanup_errors
            ],
            "group_reservations_owner_cleanup_errors": [
                _public_exception_projection(error)
                for error in reservation_loop.cleanup_errors
            ],
            "roll_exit_submit_diagnostic": _roll_exit_submit_diagnostic_projection(
                submit_diagnostic
            ),
        }
        receipt["cleanup_verified"] = bool(
            loop_status["finished"]
            and loop_status["joined"]
            and not loop_status["thread_alive"]
            and host_state == "closed"
            and reservation_loop_status["finished"]
            and reservation_loop_status["joined"]
            and not reservation_loop_status["thread_alive"]
            and reservation_host_state == "closed"
            and reservation_close_error is None
            and reservation_owner_stopped
            and not loop.cleanup_skipped
            and resource_cleanup_invocations[0] == 1
            and not resource_cleanup_errors
            and not loop.cleanup_errors
            and not reservation_loop.cleanup_errors
            and not safe_summary_cleanup
            and not safe_reservation_summary_cleanup
        )
        receipt_error: BaseException | None = None
        try:
            diagnostic_receipt_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostic_receipt_path.write_text(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
        except BaseException as error:
            receipt_error = error
        if primary_error is not None:
            add_note = getattr(primary_error, "add_note", None)
            if callable(add_note):
                add_note(f"fixture diagnostic receipt: {diagnostic_receipt_path}")
                if receipt_error is not None:
                    add_note(f"fixture receipt write error type: {type(receipt_error).__name__}")
                elif not receipt["cleanup_verified"]:
                    add_note("fixture cleanup verification failed; see the finite receipt")
        elif receipt_error is not None:
            raise AssertionError(
                ("fixture diagnostic receipt write failed", type(receipt_error).__name__)
            ) from receipt_error
        elif not receipt["cleanup_verified"]:
            raise AssertionError(("fixture cleanup verification failed", receipt))
