"""Read-only Binance C01 client backed by the normal SDK service runtime.

The venue credentials and provider adapter belong to the account ServiceHost.
This process holds only its explicit client registration and CURVE client key.
The case sees one typed, current account observation and the SDK's typed
provider-configuration/server-time facts; it never falls back to direct HTTP.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from pathlib import Path


_C01_READ_OPERATIONS = frozenset(
    {"account.snapshot", "account.configuration", "account.server_time_probe"}
)
_SERVICE_SETTINGS_FIELDS = frozenset(
    {
        "client_config_path",
        "principal_ref",
        "domain_ref",
        "service_principal_ref",
        "curve_keys",
        "account",
    }
)
_ACCOUNT_SETTINGS_FIELDS = frozenset({"account_ref", "account_key", "required_coverage"})
_ACCOUNT_KEY_FIELDS = frozenset({"provider", "venue", "environment", "account_id", "subaccount_id"})
_COVERAGE_FIELDS = frozenset({"product_type", "margin_pool"})
_CURVE_ENV_FIELDS = frozenset({"server_key_env", "public_key_env", "secret_key_env"})


class BinanceServiceBackendError(RuntimeError):
    """Finite local diagnostics for service-backed C01 setup and reads."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class BinanceServiceClient:
    """Expose C01's existing read methods over one SDK account service mount."""

    def __init__(
        self,
        *,
        host: str,
        runtime,
        account_client,
        certification_client,
        expected_account,
        service_id: str,
        instance_id: str,
        principal_ref: str,
        strategy_ref: str,
        config_fingerprint: str,
    ) -> None:
        self.host = host
        self._runtime = runtime
        self._account_client = account_client
        self._certification_client = certification_client
        self._expected_account = expected_account
        self._service_id = service_id
        self._instance_id = instance_id
        self._principal_ref = principal_ref
        self._strategy_ref = strategy_ref
        self._config_fingerprint = config_fingerprint
        self._owner_thread_id = threading.get_ident()
        self._started = False
        self._closed = False
        self._session_generation: str | None = None
        self._snapshot_view = None
        self._config_observation = None
        self.server_time_ms: int | None = None
        self.time_offset_ms: int | None = None
        self.connect_rtt_ms: float | None = None
        self.frozen = False
        self.frozen_reason = ""
        # This audit list contains operation names and bounded observation
        # metadata only. It never copies provider rows or credential material.
        self.calls: list[dict[str, object]] = []

    def connect(self) -> dict[str, object]:
        self._assert_owner_open()
        if self._started:
            raise BinanceServiceBackendError("CLIENT_ALREADY_CONNECTED")
        self._runtime.start()
        self._started = True

        wall_before_ns = time.time_ns()
        monotonic_before_ns = time.perf_counter_ns()
        try:
            observation = self._certification_client.read_exchange_server_time()
        except Exception:
            raise BinanceServiceBackendError("SERVER_TIME_PROBE_FAILED") from None
        monotonic_after_ns = time.perf_counter_ns()
        wall_after_ns = time.time_ns()
        if monotonic_after_ns < monotonic_before_ns or wall_after_ns < wall_before_ns:
            raise BinanceServiceBackendError("CLOCK_REGRESSED")
        self._session_generation = observation.session_generation
        self.server_time_ms = observation.server_time_ms
        midpoint_ms = (wall_before_ns + wall_after_ns) // 2_000_000
        self.time_offset_ms = observation.server_time_ms - midpoint_ms
        self.connect_rtt_ms = (monotonic_after_ns - monotonic_before_ns) / 1_000_000.0
        self.calls.append(
            {
                "operation": "account.server_time_probe",
                "observation_id": observation.observation_id,
                "session_generation": observation.session_generation,
                "collected_at_utc": observation.collected_at_utc,
                "server_time_ms": observation.server_time_ms,
                "rtt_ms": self.connect_rtt_ms,
            }
        )
        return {
            "host": self.host,
            "server_time_ms": self.server_time_ms,
            "time_offset_ms": self.time_offset_ms,
            "rtt_ms": self.connect_rtt_ms,
        }

    def account_config(self) -> dict[str, object]:
        self._require_connected()
        try:
            observation = self._certification_client.read_account_configuration(
                expected_generation=self._session_generation
            )
        except Exception:
            raise BinanceServiceBackendError("ACCOUNT_CONFIGURATION_READ_FAILED") from None
        self._config_observation = observation
        self.calls.append(
            {
                "operation": "account.configuration",
                "observation_id": observation.observation_id,
                "session_generation": observation.session_generation,
                "collected_at_utc": observation.collected_at_utc,
            }
        )
        # Preserve unknown provider values as None. In particular, C01's
        # existing canTrade and dualSidePosition conditions remain authoritative.
        return {
            "canTrade": observation.can_trade,
            "canDeposit": observation.can_deposit,
            "canWithdraw": observation.can_withdraw,
            "dualSidePosition": observation.dual_side_position,
        }

    def balances(self) -> list[dict[str, object]]:
        observation = self._current_observation()
        self._record_snapshot_projection("balances")
        return [row.to_dict() for row in observation.balances]

    def position_risk(self, symbol: str | None = None) -> list[dict[str, object]]:
        observation = self._current_observation()
        self._record_snapshot_projection("position_risk")
        return [
            row.to_dict()
            for row in observation.positions
            if symbol is None or row.instrument.native_symbol == symbol
        ]

    def open_orders(self, symbol: str | None = None) -> list[dict[str, object]]:
        observation = self._current_observation()
        if observation.open_orders is None or not observation.open_orders_complete:
            raise BinanceServiceBackendError("ACCOUNT_OPEN_ORDERS_INCOMPLETE")
        self._record_snapshot_projection("open_orders")
        return [
            row.to_dict()
            for row in observation.open_orders
            if symbol is None or row.instrument.native_symbol == symbol
        ]

    def describe(self) -> dict[str, object]:
        return {
            "transport": "service",
            "host": self.host,
            "service_id": self._service_id,
            "instance_id": self._instance_id,
            "principal_ref": self._principal_ref,
            "strategy_ref": self._strategy_ref,
            "client_session_id": self._runtime.client_session_id,
            "run_id": self._runtime.run_id,
            "account_key_id": self._expected_account.account_key_id,
            "session_generation": self._session_generation,
            "account_snapshot_id": (
                None if self._snapshot_view is None else self._snapshot_view.snapshot_id
            ),
            "account_snapshot_cursor": (
                None if self._snapshot_view is None else self._snapshot_view.cursor
            ),
            "client_config_fingerprint": self._config_fingerprint,
            "server_time_ms": self.server_time_ms,
            "time_offset_ms": self.time_offset_ms,
            "rtt_ms": self.connect_rtt_ms,
            "frozen": self.frozen,
            "frozen_reason": self.frozen_reason,
            "call_count": len(self.calls),
        }

    def close(self) -> None:
        self._assert_owner()
        if self._closed:
            return
        try:
            self._account_client.close()
        finally:
            try:
                self._certification_client.close()
            finally:
                self._runtime.close()
                self._closed = True

    def _current_observation(self):
        self._require_connected()
        try:
            view = (
                self._account_client.refresh()
                if self._snapshot_view is None
                else self._account_client.snapshot()
            )
        except Exception:
            raise BinanceServiceBackendError("ACCOUNT_SNAPSHOT_READ_FAILED") from None
        if (
            view.session_generation != self._session_generation
            or view.observation.account_key != self._expected_account
        ):
            raise BinanceServiceBackendError("ACCOUNT_SNAPSHOT_IDENTITY_CHANGED")
        if self._snapshot_view is None:
            self._snapshot_view = view
            self.calls.append(
                {
                    "operation": "account.snapshot",
                    "observation_id": view.observation.observation_id,
                    "snapshot_id": view.snapshot_id,
                    "snapshot_cursor": view.cursor,
                    "session_generation": view.session_generation,
                    "observed_at_utc": view.observation.completed_at_utc,
                }
            )
        elif view is not self._snapshot_view:
            raise BinanceServiceBackendError("ACCOUNT_SNAPSHOT_CHANGED_DURING_CASE")
        return view.observation

    def _record_snapshot_projection(self, method: str) -> None:
        self.calls.append(
            {
                "method": method,
                "source": "current_account_snapshot",
                "snapshot_id": self._snapshot_view.snapshot_id,
                "session_generation": self._snapshot_view.session_generation,
            }
        )

    def _require_connected(self) -> None:
        self._assert_owner_open()
        if not self._started or self._session_generation is None:
            raise BinanceServiceBackendError("CLIENT_NOT_CONNECTED")

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            raise BinanceServiceBackendError("OWNER_THREAD_REQUIRED")

    def _assert_owner_open(self) -> None:
        self._assert_owner()
        if self._closed:
            raise BinanceServiceBackendError("CLIENT_CLOSED")


def make_service_client(config: Mapping[str, object], env: Mapping[str, str], *, config_dir=None):
    """Resolve one explicit read-only account binding into the SDK runtime."""

    settings = config.get("service_client")
    if not isinstance(settings, Mapping) or set(settings) != _SERVICE_SETTINGS_FIELDS:
        raise BinanceServiceBackendError("SERVICE_CLIENT_CONFIGURATION_REQUIRED")

    from bt_api_base.account_protocol import AccountKey, AccountResourceKey
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_py.service_account import ServiceAccountClient
    from bt_api_py.service_account_certification import ServiceAccountCertificationClient
    from bt_api_py.service_config_io import load_client_config
    from bt_api_py.service_runtime import (
        ClientCurveKeys,
        ServiceClientRuntime,
        ZmqTransportFactory,
    )

    config_path = settings.get("client_config_path")
    if type(config_path) is not str or not config_path or config_path != config_path.strip():
        raise BinanceServiceBackendError("CLIENT_CONFIG_PATH_INVALID")
    path = Path(config_path)
    if not path.is_absolute():
        if config_dir is None:
            raise BinanceServiceBackendError("CLIENT_CONFIG_BASE_REQUIRED")
        path = Path(config_dir) / path
    try:
        client_config = load_client_config(path)
        public = client_config.to_public_dict()
    except Exception:
        raise BinanceServiceBackendError("CLIENT_CONFIG_INVALID") from None

    strategy_ref = _required_public_text(
        public.get("registration", {}).get("strategy_ref")
        if isinstance(public.get("registration"), Mapping)
        else None,
        "STRATEGY_REF_INVALID",
    )
    clients = public.get("clients")
    if not isinstance(clients, Mapping) or set(clients) != {"gateway"}:
        raise BinanceServiceBackendError("ACCOUNT_CLIENT_BINDING_INVALID")
    client_block = clients["gateway"]
    block_settings = client_block.get("settings") if isinstance(client_block, Mapping) else None
    bindings = block_settings.get("bindings") if isinstance(block_settings, Mapping) else None
    if type(bindings) is not list or len(bindings) != 1:
        raise BinanceServiceBackendError("ACCOUNT_CLIENT_BINDING_INVALID")
    binding = bindings[0]
    if not isinstance(binding, Mapping) or binding.get("mount") != "store.account":
        raise BinanceServiceBackendError("ACCOUNT_CLIENT_BINDING_INVALID")
    if binding.get("required", True) is not True:
        raise BinanceServiceBackendError("ACCOUNT_CLIENT_BINDING_NOT_REQUIRED")

    account_settings = settings.get("account")
    if (
        not isinstance(account_settings, Mapping)
        or set(account_settings) != _ACCOUNT_SETTINGS_FIELDS
    ):
        raise BinanceServiceBackendError("ACCOUNT_IDENTITY_CONFIGURATION_INVALID")
    account_ref = _required_public_text(account_settings.get("account_ref"), "ACCOUNT_REF_INVALID")
    if binding.get("account_ref") != account_ref:
        raise BinanceServiceBackendError("ACCOUNT_REF_MISMATCH")
    scope_ref = _required_public_text(binding.get("scope_ref"), "SCOPE_REF_INVALID")
    service_id = _required_public_text(binding.get("service_id"), "SERVICE_ID_INVALID")
    instance_id = _required_public_text(binding.get("instance_id"), "INSTANCE_ID_INVALID")
    transport_ref = _required_public_text(binding.get("transport_ref"), "TRANSPORT_REF_INVALID")

    account_key_raw = account_settings.get("account_key")
    if not isinstance(account_key_raw, Mapping) or set(account_key_raw) != _ACCOUNT_KEY_FIELDS:
        raise BinanceServiceBackendError("ACCOUNT_IDENTITY_CONFIGURATION_INVALID")
    try:
        expected_account = AccountKey(**account_key_raw)
    except Exception:
        raise BinanceServiceBackendError("ACCOUNT_IDENTITY_CONFIGURATION_INVALID") from None
    environment = config.get("environment")
    environment_name = environment.get("name") if isinstance(environment, Mapping) else None
    if (
        expected_account.provider != "binance"
        or expected_account.venue != "binance"
        or expected_account.environment != environment_name
    ):
        raise BinanceServiceBackendError("ACCOUNT_IDENTITY_CONFIGURATION_MISMATCH")

    coverage_raw = account_settings.get("required_coverage")
    if type(coverage_raw) is not list or not coverage_raw:
        raise BinanceServiceBackendError("ACCOUNT_COVERAGE_CONFIGURATION_INVALID")
    try:
        required_coverage = tuple(
            AccountResourceKey(**_exact_mapping(item, _COVERAGE_FIELDS)) for item in coverage_raw
        )
    except Exception:
        raise BinanceServiceBackendError("ACCOUNT_COVERAGE_CONFIGURATION_INVALID") from None
    if len(set(required_coverage)) != len(required_coverage):
        raise BinanceServiceBackendError("ACCOUNT_COVERAGE_CONFIGURATION_INVALID")

    principal_ref = _required_public_text(settings.get("principal_ref"), "CLIENT_PRINCIPAL_INVALID")
    domain_ref = _required_public_text(settings.get("domain_ref"), "DOMAIN_REF_INVALID")
    service_principal_ref = _required_public_text(
        settings.get("service_principal_ref"), "SERVICE_PRINCIPAL_INVALID"
    )
    try:
        identity = WireIdentity(WireRole.STRATEGY_CLIENT, principal_ref, strategy_ref)
        peer = WireIdentity(WireRole.SERVICE, service_principal_ref, service_id)
        scope = WireScope(domain_ref, account_ref=account_ref, strategy_ref=strategy_ref)
    except Exception:
        raise BinanceServiceBackendError("SERVICE_IDENTITY_CONFIGURATION_INVALID") from None

    curve_env = settings.get("curve_keys")
    if not isinstance(curve_env, Mapping) or not curve_env:
        raise BinanceServiceBackendError("CURVE_KEYS_CONFIGURATION_INVALID")
    communication = public.get("communication")
    profiles = communication.get("profiles") if isinstance(communication, Mapping) else None
    profile = profiles.get(transport_ref) if isinstance(profiles, Mapping) else None
    security_ref = profile.get("security_profile_ref") if isinstance(profile, Mapping) else None
    security_ref = _required_public_text(security_ref, "SECURITY_REF_INVALID")
    key_env = curve_env.get(security_ref)
    if not isinstance(key_env, Mapping) or set(key_env) != _CURVE_ENV_FIELDS:
        raise BinanceServiceBackendError("CURVE_KEYS_CONFIGURATION_INVALID")
    try:
        key_values = [
            env[key_env[name]] for name in ("server_key_env", "public_key_env", "secret_key_env")
        ]
        key_bytes = [value.encode("ascii", errors="strict") for value in key_values]
    except Exception:
        raise BinanceServiceBackendError("CURVE_KEYS_UNAVAILABLE") from None
    if any(len(value) != 40 for value in key_bytes):
        raise BinanceServiceBackendError("CURVE_KEYS_INVALID")
    transport_factory = ZmqTransportFactory({security_ref: ClientCurveKeys(*key_bytes)})

    scope_map = {scope_ref: scope}
    peer_map = {service_id: peer}
    runtime = ServiceClientRuntime(
        client_config,
        identity=identity,
        scope_resolver=lambda requested: _resolve_exact(scope_map, requested),
        peer_resolver=lambda requested: _resolve_exact(peer_map, requested),
        transport_factory=transport_factory,
        requested_operations={"store.account": _C01_READ_OPERATIONS},
    )
    account_client = ServiceAccountClient(
        runtime,
        "store.account",
        account_ref=account_ref,
        expected_account=expected_account,
        required_coverage=required_coverage,
        require_open_orders=True,
        expected_scope_ref=scope_ref,
    )
    certification_client = ServiceAccountCertificationClient(
        runtime,
        "store.account",
        account_ref=account_ref,
        expected_account=expected_account,
        expected_scope_ref=scope_ref,
    )
    host_config = config.get("environment")
    host = host_config.get("base_url") if isinstance(host_config, Mapping) else None
    host = _required_public_text(host, "HOST_INVALID")
    return BinanceServiceClient(
        host=host,
        runtime=runtime,
        account_client=account_client,
        certification_client=certification_client,
        expected_account=expected_account,
        service_id=service_id,
        instance_id=instance_id,
        principal_ref=principal_ref,
        strategy_ref=strategy_ref,
        config_fingerprint=client_config.fingerprint(),
    )


def _required_public_text(value: object, code: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise BinanceServiceBackendError(code)
    return value


def _exact_mapping(value: object, fields: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("invalid mapping")
    return value


def _resolve_exact(directory: Mapping[str, object], key: str):
    try:
        return directory[key]
    except Exception:
        raise BinanceServiceBackendError("TRUSTED_REFERENCE_UNAVAILABLE") from None


__all__ = ["BinanceServiceBackendError", "BinanceServiceClient", "make_service_client"]
