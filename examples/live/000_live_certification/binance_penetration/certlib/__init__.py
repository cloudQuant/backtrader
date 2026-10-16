"""Minimal certification helpers for the Binance demo penetration suite.

A case directory only needs `config.yaml`, `<ID>_strategy.py` and `run.py`.
`run.py` (via certlib.runner) reads the config, loads credentials from the
checkout-root `.env` by *name*, enforces the config policy, executes the
strategy against the Binance USD-M demo environment, writes one evidence
JSON, and prints a single-line result. Nothing else is required to run a
case.

Transport and component backends
---------------------------------
The direct venue client and the normal SDK ``ServiceClientRuntime`` read path
are supported for the read-only C01 entry. The retired Optional16 bridge is
not a supported backend. Execution, Risk, and Monitor component mounts remain
fail-closed until their normal SDK-backed case paths are implemented.
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


def make_client(config, env, topology, *, config_dir=None):
    """Build the venue client for this suite.

    `config` is the parsed case config.yaml, `env` maps requested credential
    variable names to their values, `topology` is the effective topology
    mapping (transport/execution/risk/monitor).
    """
    transport = topology.get("transport", "direct")
    if transport not in {"direct", "service"}:
        raise RuntimeError(f"transport_not_implemented:{transport}")
    for flag in ("execution", "risk", "monitor"):
        if topology.get(flag):
            raise RuntimeError(f"component_not_implemented:{flag}")

    if transport == "service":
        from .service_backend import make_service_client

        return make_service_client(config, env, config_dir=config_dir)
    return _direct_client(config, env)
