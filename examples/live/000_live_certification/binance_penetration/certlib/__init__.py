"""Minimal certification helpers for the Binance demo penetration suite.

A case directory only needs `config.yaml`, `<ID>_strategy.py` and `run.py`.
`run.py` (via certlib.runner) reads the config, loads credentials from the
checkout-root `.env` by *name*, enforces the config policy, executes the
strategy against the Binance USD-M demo environment, writes one evidence
JSON, and prints a single-line result. Nothing else is required to run a
case.

Transport and component backends
--------------------------------
Only ``transport="direct"`` is currently implemented by this normal entry.
The retired Optional16 gateway/component bridge is not a supported backend.
Until the normal SDK service runtime is wired here, gateway and component
requests fail before importing either Optional16 or the venue client.
"""

from __future__ import annotations


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


def make_client(config, env, topology):
    """Build the venue client for this suite.

    `config` is the parsed case config.yaml, `env` maps requested credential
    variable names to their values, `topology` is the effective topology
    mapping (transport/execution/risk/monitor).
    """
    transport = topology.get("transport", "direct")
    if transport != "direct":
        raise RuntimeError(f"transport_not_implemented:{transport}")
    for flag in ("execution", "risk", "monitor"):
        if topology.get(flag):
            raise RuntimeError(f"component_not_implemented:{flag}")

    return _direct_client(config, env)
