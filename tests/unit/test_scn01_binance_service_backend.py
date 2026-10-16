from __future__ import annotations

import importlib
import importlib.util
import hashlib
import hmac
import json
import queue
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml
import zmq
from bt_api_binance.account_session_provider import (
    BinanceUsdMAccountSessionProvider,
    BinanceUsdMApiCredentials,
)

from bt_api_base.account_protocol import AccountKey, AccountObservation, AccountResourceKey
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_gateway import GatewayCommandKind, GatewayEventJournal, GatewayPrincipal
from bt_api_gateway.account_session_worker import GatewayAccountSessionWorker
from bt_api_gateway.service_component import GatewayServiceAccountScope
from bt_api_gateway.session_guard import LocalAccountSessionGuard
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant


_REPO = Path(__file__).resolve().parents[2]
_CERTLIB = (
    _REPO
    / "examples"
    / "live"
    / "000_live_certification"
    / "binance_penetration"
    / "certlib"
    / "__init__.py"
)
_CASE_DIR = _REPO / "examples/live/000_live_certification/binance_penetration/cases/C01"
_ACCOUNT_REF = "binance-demo-account"
_ACCOUNT_KEY = AccountKey("binance", "binance", "demo", "synthetic-c01-owner")
_RESOURCE = AccountResourceKey("usdm_perpetual", "cross")
_DOMAIN_REF = "binance-demo-domain"
_STRATEGY_REF = "binance-c01"
_PRINCIPAL_REF = "binance-c01"
_SERVICE_ID = "binance-demo-account-service"
_SERVICE_PRINCIPAL_REF = "binance-account-host"
_INSTANCE_ID = "binance-account-session-gateway"
_SCOPE_REF = "binance-demo-account-v1"
_SECURITY_REF = "binance-c01-account-curve-v1"
_TRANSPORT_REF = "binance-c01-account-rpc-v1"
_SERVICE_OPERATIONS = frozenset(
    {"account.snapshot", "account.configuration", "account.server_time_probe"}
)


def _load_runner():
    package_name = "certlib"
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == package_name or name.startswith(package_name + ".")
    }
    for name in previous_modules:
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(
        package_name,
        _CERTLIB,
        submodule_search_locations=[str(_CERTLIB.parent)],
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[package_name] = package
    spec.loader.exec_module(package)
    return package_name, importlib.import_module(f"{package_name}.runner"), previous_modules


class _SyntheticBinanceHttpTransport:
    """Local HTTP leaf for the production Demo adapter; never opens a socket."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], float, int]] = []
        self.server_time_ms: int | None = None

    def __call__(self, method, url, headers, timeout, max_bytes):
        self.calls.append((method, url, dict(headers), timeout, max_bytes))
        parsed = urlsplit(url)
        assert parsed.scheme == "https" and parsed.netloc == "demo-fapi.binance.com"
        assert method == "GET" and timeout > 0 and 0 < max_bytes <= 2 * 1024 * 1024
        if parsed.path == "/fapi/v1/time":
            assert "X-MBX-APIKEY" not in headers and parsed.query == ""
            self.server_time_ms = int(time.time() * 1000) + 137
            payload = {"serverTime": self.server_time_ms}
        else:
            assert headers["X-MBX-APIKEY"] == "synthetic-c01-api-key"
            query, signature = parsed.query.rsplit("&signature=", 1)
            expected = hmac.new(
                b"synthetic-c01-api-secret", query.encode("ascii"), hashlib.sha256
            ).hexdigest()
            assert hmac.compare_digest(signature, expected)
            assert parse_qs(query).get("recvWindow") == ["5000"]
            assert "timestamp" in parse_qs(query)
            if parsed.path == "/fapi/v1/accountConfig":
                payload = {
                    "canTrade": True,
                    "canDeposit": False,
                    "canWithdraw": False,
                    "dualSidePosition": True,
                }
            elif parsed.path == "/fapi/v2/account":
                payload = {
                    "multiAssetsMargin": False,
                    "assets": [
                        {
                            "asset": "USDT",
                            "crossWalletBalance": "1000.00",
                            "availableBalance": "900.00",
                        }
                    ],
                    "positions": [
                        {
                            "symbol": "BTCUSDT",
                            "positionSide": "BOTH",
                            "positionAmt": "1.0",
                            "isolated": False,
                            "entryPrice": "100.00",
                        },
                        {
                            "symbol": "ETHUSDT",
                            "positionSide": "LONG",
                            "positionAmt": "0.5",
                            "isolated": False,
                            "entryPrice": "50.00",
                        },
                    ],
                }
            elif parsed.path == "/fapi/v1/openOrders":
                now_ms = int(time.time() * 1000)
                payload = [
                    {
                        "symbol": "BTCUSDT",
                        "orderId": 101,
                        "clientOrderId": "synthetic-c01-order",
                        "side": "BUY",
                        "positionSide": "BOTH",
                        "origType": "LIMIT",
                        "status": "NEW",
                        "origQty": "1.0",
                        "executedQty": "0.0",
                        "price": "99.00",
                        "stopPrice": "0",
                        "time": now_ms - 1_000,
                        "reduceOnly": False,
                    }
                ]
            elif parsed.path == "/fapi/v1/openAlgoOrders":
                payload = []
            else:
                raise AssertionError(f"unexpected provider route: {parsed.path}")
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        assert len(body) <= max_bytes
        return body


class _TrackedBinanceDemoProvider(BinanceUsdMAccountSessionProvider):
    """Observe lifecycle counts while exercising the actual provider adapter."""

    def __init__(self, transport: _SyntheticBinanceHttpTransport) -> None:
        super().__init__(
            BinanceUsdMApiCredentials(
                "synthetic-c01-api-key", "synthetic-c01-api-secret"
            ),
            transport=transport,
        )
        self.transport_leaf = transport
        self.connect_calls = 0
        self.snapshot_calls = 0
        self.configuration_calls = 0
        self.server_time_calls = 0
        self.close_calls = 0
        self.last_observation: AccountObservation | None = None

    @property
    def server_time_ms(self) -> int | None:
        return self.transport_leaf.server_time_ms

    def connect(self, *, account_key: AccountKey, generation: str, timeout: float) -> None:
        self.connect_calls += 1
        super().connect(account_key=account_key, generation=generation, timeout=timeout)

    def read_account(self, *, generation: str, timeout: float):
        self.snapshot_calls += 1
        observation = super().read_account(generation=generation, timeout=timeout)
        assert type(observation) is AccountObservation
        self.last_observation = observation
        return observation

    def read_account_configuration(self, *, generation: str, timeout: float):
        self.configuration_calls += 1
        return super().read_account_configuration(generation=generation, timeout=timeout)

    def read_exchange_server_time(self, *, generation: str, timeout: float):
        self.server_time_calls += 1
        return super().read_exchange_server_time(generation=generation, timeout=timeout)

    def close(self) -> bool:
        self.close_calls += 1
        return super().close()


def _free_endpoint() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"
    finally:
        probe.close()


def _service_config(endpoint: str) -> dict:
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        "service_id": _SERVICE_ID,
        "scope_ref": _SCOPE_REF,
        "transport_ref": "binance-c01-listener-v1",
        "registration_policy_ref": "binance-c01-policy-v1",
        "service_requirements_ref": "binance-c01-requirements-v1",
        "components": {
            "gateway": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": _INSTANCE_ID,
                    "bind_ports": ["service.account_read", "service.provider_session"],
                    "options": {
                        "role": "account_session_worker",
                        "account_session_ref": "binance-c01-session-v1",
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "binance-c01-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": _SECURITY_REF,
                    "options": {"high_water_mark": 32, "max_message_bytes": 65536},
                }
            },
        },
    }


def _client_config(endpoint: str) -> dict:
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY_REF},
        "clients": {
            "gateway": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "store.account",
                            "service_id": _SERVICE_ID,
                            "instance_id": _INSTANCE_ID,
                            "scope_ref": _SCOPE_REF,
                            "account_ref": _ACCOUNT_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "required": True,
                        }
                    ],
                    "options": {
                        "request_timeout_ms": 1000,
                        "heartbeat_interval_seconds": 5,
                    },
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": _SECURITY_REF,
                    "options": {
                        "request_timeout_ms": 1000,
                        "high_water_mark": 32,
                        "max_message_bytes": 65536,
                    },
                }
            },
        },
    }


class _LocalServiceHost:
    def __init__(self, tmp_path: Path) -> None:
        self.endpoint = _free_endpoint()
        self.provider = _TrackedBinanceDemoProvider(_SyntheticBinanceHttpTransport())
        self.client_keys = zmq.curve_keypair()
        self.server_keys = zmq.curve_keypair()
        self.stop = threading.Event()
        self.ready: queue.Queue = queue.Queue()
        self.finished: queue.Queue = queue.Queue()
        self.tmp_path = tmp_path
        self.thread = threading.Thread(target=self._serve, name="scn01-synthetic-service-host")

    def start(self) -> None:
        self.thread.start()
        ready = self.ready.get(timeout=10)
        if ready != ("ready", self.endpoint):
            self.thread.join(timeout=10)
            raise AssertionError(f"local synthetic ServiceHost failed to start: {ready!r}")

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=10)
        assert not self.thread.is_alive(), "local synthetic ServiceHost did not close normally"
        outcome = self.finished.get(timeout=2)
        assert outcome == ("closed",), outcome
        assert self.provider.close_calls == 1

    def _serve(self) -> None:
        host = None
        worker = None
        try:
            config = parse_service_config(_service_config(self.endpoint))
            journal_scope = "journal:binance-demo-account"
            state_scope = "state:binance-demo-account"
            account_scope = GatewayServiceAccountScope(
                account_ref=_ACCOUNT_REF,
                execution_domain_ref=_DOMAIN_REF,
                journal_account_scope=journal_scope,
                account_read_strategy_scope=state_scope,
                shared_account_facts_scope=state_scope,
                shared_fact_strategy_refs=frozenset({_STRATEGY_REF}),
            )
            principal = GatewayPrincipal(
                principal_id=_PRINCIPAL_REF,
                account_scopes=frozenset({journal_scope}),
                strategy_scopes=frozenset({state_scope}),
                allowed_kinds=frozenset({GatewayCommandKind.READ}),
            )
            resources_holder: dict[str, object] = {}

            def resource_provider(component, _instance_id, options, _scope):
                nonlocal worker
                if component != "gateway" or options.get("role") != "account_session_worker":
                    raise AssertionError("only the account session gateway is selected")
                journal = GatewayEventJournal(self.tmp_path / "journal.sqlite")
                (self.tmp_path / "session-guards").mkdir(exist_ok=True)
                guard = LocalAccountSessionGuard(
                    self.tmp_path / "session-guards",
                    _ACCOUNT_KEY.account_key_id,
                    owner_ref="synthetic-c01-host",
                )
                worker = GatewayAccountSessionWorker(
                    self.provider,
                    journal,
                    account_key=_ACCOUNT_KEY,
                    journal_account_scope=journal_scope,
                    state_scope=state_scope,
                    guard=guard,
                    required_coverage=(_RESOURCE,),
                    require_open_orders=True,
                    refresh_interval_seconds=60,
                    max_staleness_seconds=120,
                    request_timeout_seconds=2,
                )
                resources_holder["journal"] = journal
                return ComponentResources.owned(
                    {
                        "journal": journal,
                        "accounts": {_ACCOUNT_REF: account_scope},
                        "principals": {_PRINCIPAL_REF: principal},
                    },
                    ready=lambda: True,
                    close=worker.close,
                    internal_ports={"service.provider_session": worker},
                )

            identity = WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_REF, _STRATEGY_REF)
            rpc_scope = WireScope(
                _DOMAIN_REF,
                account_ref=_ACCOUNT_REF,
                strategy_ref=_STRATEGY_REF,
            )
            grant = ResourceGrant(
                _INSTANCE_ID,
                "service.account_read",
                _SCOPE_REF,
                rpc_scope,
                _SERVICE_OPERATIONS,
            )
            host = ServiceHost(
                config,
                TrustedServiceAuthority(
                    identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL_REF, _SERVICE_ID),
                    scope=WireScope(_DOMAIN_REF),
                    scope_ref=_SCOPE_REF,
                    scope_version="binance-c01-scope-v1",
                    security_ref=_SECURITY_REF,
                    security_version="binance-c01-curve-v1",
                    registration_policy_ref="binance-c01-policy-v1",
                    registration_policy_version="binance-c01-policy-r1",
                    service_requirements_ref="binance-c01-requirements-v1",
                    service_requirements_version="binance-c01-requirements-r1",
                    curve_public_key=self.server_keys[0],
                    curve_secret_key=self.server_keys[1],
                    principals={self.client_keys[0]: _PRINCIPAL_REF},
                    grants={_PRINCIPAL_REF: (PrincipalGrant(identity, (grant,)),)},
                ),
                self.tmp_path / "registry.sqlite",
                resource_provider,
            )
            host.start()
            self.ready.put(("ready", host.endpoint))
            while not self.stop.is_set():
                host.serve_once(20)
            host.close()
            self.finished.put(("closed",))
        except BaseException as exc:
            self.ready.put(("error", type(exc).__name__, str(exc)[:200]))
            if host is not None and host.state not in {"closed", "failed"}:
                try:
                    host.close()
                except BaseException:
                    pass
            self.finished.put(("error", type(exc).__name__, str(exc)[:200]))


def test_normal_c01_entry_uses_service_runtime_and_preserves_case_contract(
    tmp_path, monkeypatch, capsys
):
    package_name, runner, previous_modules = _load_runner()
    host = _LocalServiceHost(tmp_path)
    try:
        host.start()
        endpoint = host.endpoint
        client_config_path = tmp_path / "service-client.yaml"
        client_config_path.write_text(
            yaml.safe_dump(_client_config(endpoint), sort_keys=False), encoding="utf-8"
        )
        case_config = yaml.safe_load((_CASE_DIR / "config.yaml").read_text(encoding="utf-8"))
        case_config["service_client"] = {
            "client_config_path": "service-client.yaml",
            "principal_ref": _PRINCIPAL_REF,
            "domain_ref": _DOMAIN_REF,
            "service_principal_ref": _SERVICE_PRINCIPAL_REF,
            "curve_keys": {
                _SECURITY_REF: {
                    "server_key_env": "C01_SERVER_PUBLIC",
                    "public_key_env": "C01_CLIENT_PUBLIC",
                    "secret_key_env": "C01_CLIENT_SECRET",
                }
            },
            "account": {
                "account_ref": _ACCOUNT_REF,
                "account_key": _ACCOUNT_KEY.to_dict(),
                "required_coverage": [
                    {"product_type": _RESOURCE.product_type, "margin_pool": _RESOURCE.margin_pool}
                ],
            },
        }
        config_path = tmp_path / "C01-service-config.yaml"
        config_path.write_text(yaml.safe_dump(case_config, sort_keys=False), encoding="utf-8")
        values = {
            "C01_SERVER_PUBLIC": host.server_keys[0].decode("ascii"),
            "C01_CLIENT_PUBLIC": host.client_keys[0].decode("ascii"),
            "C01_CLIENT_SECRET": host.client_keys[1].decode("ascii"),
        }
        loaded_names = []

        def load_env(names):
            loaded_names.extend(names)
            return values, []

        monkeypatch.setattr(runner.envfile, "load_env", load_env)
        monkeypatch.setattr(sys, "argv", [str(_CASE_DIR / "run.py")])
        exit_code = runner.main_case(
            [
                "--live",
                "--transport",
                "service",
                "--config",
                str(config_path),
                "--evidence-dir",
                str(tmp_path / "evidence"),
            ]
        )
        output_lines = [
            line for line in capsys.readouterr().out.splitlines() if line.startswith("{")
        ]
        summary = json.loads(output_lines[-1])

        assert exit_code == 0
        assert summary["case"] == "C01"
        assert summary["venue"] == "binance"
        assert summary["status"] == "PASS"
        assert summary["reason"] == ""
        assert summary["facts"]["symbol"] == "BTCUSDT"
        assert type(summary["facts"]["server_time_ms"]) is int
        assert summary["facts"]["server_time_ms"] > 0
        assert type(summary["facts"]["time_offset_ms"]) is int
        assert summary["facts"]["rtt_ms"] >= 0
        assert summary["facts"]["can_trade"] is True
        assert summary["facts"]["can_deposit"] is False
        assert summary["facts"]["can_withdraw"] is False
        assert summary["facts"]["dual_side_position"] is True
        assert summary["facts"]["balance_rows"] == 1
        assert summary["facts"]["position_rows"] == 1
        assert summary["facts"]["open_order_rows"] == 1
        assert set(loaded_names) == {
            "C01_SERVER_PUBLIC",
            "C01_CLIENT_PUBLIC",
            "C01_CLIENT_SECRET",
        }
        assert "BINANCE_DEMO_API_KEY" not in loaded_names
        assert "BINANCE_DEMO_SECRET" not in loaded_names
        assert host.provider.connect_calls == 1
        assert host.provider.server_time_calls == 1
        assert host.provider.configuration_calls == 1
        assert host.provider.snapshot_calls == 1
        assert host.provider.close_calls == 0
        assert type(host.provider.last_observation) is AccountObservation
        assert host.provider.last_observation.consistency == "multi_query"
        assert host.provider.last_observation.balances_complete is True
        assert host.provider.last_observation.positions_complete is True
        assert host.provider.last_observation.open_orders_complete is True
        assert not hasattr(host.provider.last_observation, "account_revision")
        actual_paths = [urlsplit(call[1]).path for call in host.provider.transport_leaf.calls]
        assert actual_paths == [
            "/fapi/v1/time",
            "/fapi/v2/account",
            "/fapi/v1/openOrders",
            "/fapi/v1/openAlgoOrders",
            "/fapi/v1/time",
            "/fapi/v1/accountConfig",
        ], actual_paths
        assert all(call[0] == "GET" for call in host.provider.transport_leaf.calls)
        assert all(
            urlsplit(call[1]).netloc == "demo-fapi.binance.com"
            for call in host.provider.transport_leaf.calls
        )
        evidence_text = Path(summary["evidence"]).read_text(encoding="utf-8")
        evidence = json.loads(evidence_text)
        assert evidence["config_sha256"] == hashlib.sha256(config_path.read_bytes()).hexdigest()
        assert evidence["topology"]["transport"] == "service"
        assert evidence["client"]["transport"] == "service"
        assert evidence["client"]["account_key_id"] == _ACCOUNT_KEY.account_key_id
        assert evidence["client"]["principal_ref"] == _PRINCIPAL_REF
        assert evidence["client"]["strategy_ref"] == _STRATEGY_REF
        assert evidence["client"]["session_generation"]
        assert evidence["client"]["account_snapshot_id"].startswith(
            evidence["client"]["session_generation"] + ":"
        )
        assert evidence["client"]["server_time_ms"] == host.provider.server_time_ms
        assert evidence["client"]["rtt_ms"] >= 0
        assert {entry.get("operation") for entry in evidence["calls"] if "operation" in entry} == {
            "account.snapshot",
            "account.configuration",
            "account.server_time_probe",
        }
        assert evidence["facts"]["can_trade"] is True
        assert evidence["facts"]["dual_side_position"] is True
        assert evidence["facts"]["position_rows"] == 1
        assert evidence["facts"]["open_order_rows"] == 1
        assert "synthetic-c01-api-key" not in evidence_text
        assert "synthetic-c01-api-secret" not in evidence_text
        assert "1000.00" not in evidence_text
        assert "900.00" not in evidence_text
    finally:
        host.close()
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)


def test_service_close_failure_downgrades_pass_to_unknown(tmp_path, monkeypatch, capsys):
    package_name, runner, previous_modules = _load_runner()

    class _PassingStrategy:
        def run(self, ctx):
            return runner.context.CaseResult("C01", "PASS", "", {"synthetic": True})

    class _ClosingFailureClient:
        host = "demo-fapi.binance.com"
        server_time_ms = 1_700_000_000_000
        time_offset_ms = 0
        connect_rtt_ms = 1
        frozen = False
        calls = []

        def connect(self):
            return {"host": self.host, "time_offset_ms": self.time_offset_ms}

        def close(self):
            raise RuntimeError("opaque close detail")

        def describe(self):
            return {"transport": "service", "closed": False}

    client = _ClosingFailureClient()
    monkeypatch.setattr(runner, "make_client", lambda *args, **kwargs: client)
    monkeypatch.setattr(runner, "_load_strategy", lambda *_: (_PassingStrategy(), "READ"))
    monkeypatch.setattr(
        runner.envfile,
        "load_env",
        lambda names: (dict.fromkeys(names, "synthetic"), []),
    )
    monkeypatch.setattr(sys, "argv", [str(_CASE_DIR / "run.py")])
    try:
        exit_code = runner.main_case(
            ["--live", "--transport", "service", "--evidence-dir", str(tmp_path / "evidence")]
        )
        output_lines = [
            line for line in capsys.readouterr().out.splitlines() if line.startswith("{")
        ]
        summary = json.loads(output_lines[-1])

        assert exit_code == 3, summary
        assert summary["case"] == "C01"
        assert summary["status"] == "UNKNOWN"
        assert summary["reason"] == "service_cleanup_unconfirmed"
        assert summary["facts"]["service_cleanup"] == "unconfirmed"
        assert "opaque close detail" not in output_lines[-1]
        evidence = json.loads(Path(summary["evidence"]).read_text(encoding="utf-8"))
        assert evidence["status"] == "UNKNOWN"
        assert evidence["facts"]["service_cleanup"] == "unconfirmed"
    finally:
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
