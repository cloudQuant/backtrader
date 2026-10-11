"""Minimal certification helpers for the Binance demo penetration suite.

A case directory only needs `config.yaml`, `<ID>_strategy.py` and `run.py`.
`run.py` (via certlib.runner) reads the config, loads credentials from the
checkout-root `.env` by *name*, enforces the config policy, executes the
strategy against the Binance USD-M demo environment, writes one evidence
JSON, and prints a single-line result. Nothing else is required to run a
case.

Transport wiring
----------------
`make_client` honours the effective topology:

* ``transport="direct"`` — the in-process `BinanceDemoClient` (unchanged).
* ``transport="gateway_zmq"`` — an `optional16.GatewayServer` owns the provider
  session and the returned `optional16.GatewayClient` forwards every command
  over the localhost ZMQ transport. If the environment variable
  ``BT_CERT_GATEWAY`` holds ``[zmq|stdlib@]host:port:token`` the client reuses
  that already-running server instead of starting an embedded one; the
  embedded server's JSONL journal directory can be pinned with
  ``BT_CERT_GATEWAY_JOURNAL`` (default: a fresh temp dir, reported through
  ``GatewayClient.describe()["journal"]`` in the evidence file).
* Enabled components (execution/risk/monitor) are wrapped only when the
  sibling ``optional16.components`` module provides
  ``wrap_client(client, config, topology, env)``; otherwise the historical
  ``component_not_implemented:<flag>`` error is raised.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def _optional16_root() -> Path:
    # certlib/__init__.py -> certlib -> binance_penetration -> 000_live_certification
    return Path(__file__).resolve().parents[2]


def _import_optional16():
    """Import the `optional16` sibling package (it sits next to this venue)."""
    try:
        return importlib.import_module("optional16")
    except ImportError:
        pass
    root = _optional16_root()
    if root.is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module("optional16")


def _component_wrapper(topology):
    """Return the sibling `wrap_client` callable, or None when none is asked for."""
    requested = [flag for flag in ("execution", "risk", "monitor") if topology.get(flag)]
    if not requested:
        return None
    try:
        package = _import_optional16()
        module = importlib.import_module(package.__name__ + ".components")
        wrapper = getattr(module, "wrap_client")
    except ImportError as exc:
        raise RuntimeError(f"component_not_implemented:{requested[0]}") from exc
    if not callable(wrapper):
        raise RuntimeError(f"component_not_implemented:{requested[0]}")
    return wrapper


def _request_timeout(config) -> float:
    return float(config.get("timeouts", {}).get("request_seconds", 10.0))


def _direct_client(config, env):
    from .binance_client import BinanceDemoClient

    env_section = config.get("credentials", {})
    key_name = env_section.get("api_key_env", "BINANCE_DEMO_API_KEY")
    secret_name = env_section.get("secret_env", "BINANCE_DEMO_SECRET")
    environment = config.get("environment", {})
    return BinanceDemoClient(
        env[key_name],
        env[secret_name],
        host=environment.get("base_url", "demo-fapi.binance.com"),
        timeout=_request_timeout(config),
    )


def _gateway_client(config, env):
    """Start (or connect to) the optional16 gateway that owns the session."""
    package = _import_optional16()
    timeout = _request_timeout(config)
    reuse = os.environ.get("BT_CERT_GATEWAY", "").strip()
    if reuse:
        return package.GatewayClient.from_connection_string(reuse, timeout=timeout)
    journal_dir = os.environ.get("BT_CERT_GATEWAY_JOURNAL", "").strip() or None
    server = package.GatewayServer(
        config=config,
        env=env,
        journal_dir=journal_dir or tempfile.mkdtemp(prefix="bt-cert-gateway-journal-"),
    )
    return package.GatewayClient.embedded(server, timeout=timeout)


def make_client(config, env, topology):
    """Build the venue client for this suite.

    `config` is the parsed case config.yaml, `env` maps requested credential
    variable names to their values, `topology` is the effective topology
    mapping (transport/execution/risk/monitor).
    """
    # Components are resolved first: an unimplemented combination must fail
    # before any provider session or gateway process is created.
    wrapper = _component_wrapper(topology)

    transport = topology.get("transport", "direct")
    if transport == "direct":
        client = _direct_client(config, env)
    elif transport == "gateway_zmq":
        client = _gateway_client(config, env)
    else:
        raise RuntimeError(f"transport_not_implemented:{transport}")

    if wrapper is not None:
        client = wrapper(client, config, topology, env)
    return client
