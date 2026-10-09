"""Minimal certification helpers for the OKX demo penetration suite.

A case directory only needs `config.yaml`, `<ID>_strategy.py` and `run.py`.
`run.py` (via certlib.runner) reads the config, loads credentials from the
checkout-root `.env` by *name*, enforces the config policy, executes the
strategy against the OKX demo environment, writes one evidence JSON, and
prints a single-line result.
"""

from __future__ import annotations


def make_client(config, env, topology):
    """Build the venue client for this suite."""
    from .okx_client import OkxDemoClient

    transport = topology.get("transport", "direct")
    if transport != "direct":
        raise RuntimeError(f"transport_not_implemented:{transport}")
    for flag in ("execution", "risk", "monitor"):
        if topology.get(flag):
            raise RuntimeError(f"component_not_implemented:{flag}")
    environment = config.get("environment", {})
    creds = config.get("credentials", {})
    return OkxDemoClient(
        env[creds["api_key_env"]],
        env[creds["secret_env"]],
        env[creds["passphrase_env"]],
        host=environment.get("base_url", "www.okx.com"),
        simulated=bool(environment.get("simulated", True)),
        timeout=float(config.get("timeouts", {}).get("request_seconds", 10.0)),
    )
