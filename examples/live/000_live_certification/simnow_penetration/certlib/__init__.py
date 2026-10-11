"""Minimal certification helpers for the SimNow penetration suite.

A case directory only needs `config.yaml`, `<ID>_strategy.py` and `run.py`.
`run.py` (via certlib.runner) reads the config, loads credentials from the
checkout-root `.env` by *name*, enforces the config policy, runs the strategy
against the SimNow simulation environment through the dev bt_api_ctp source
(CPython 3.11), writes one evidence JSON, and prints a single-line result.
"""

from __future__ import annotations


def make_client(config, env, topology):
    """Build the venue session for this suite."""
    from .ctp_client import SimNowSession, ensure_sdk_importable, select_front_pair

    sdk = config.get("sdk", {})
    sdk_root = env.get(sdk.get("root_env", ""), "") or sdk.get("default_root")
    provenance = ensure_sdk_importable(sdk_root)
    transport = topology.get("transport", "direct")
    if transport != "direct":
        raise RuntimeError(f"transport_not_implemented:{transport}")
    for flag in ("execution", "risk", "monitor"):
        if topology.get(flag):
            raise RuntimeError(f"component_not_implemented:{flag}")
    pair, attempts = select_front_pair(config.get("fronts", {}), env)
    credentials = config.get("credentials", {})
    return SimNowSession(
        broker_id=env[credentials["broker_id_env"]],
        user_id=env[credentials["user_id_env"]],
        password=env[credentials["password_env"]],
        app_id=env[credentials["app_id_env"]],
        auth_code=env[credentials["auth_code_env"]],
        pair=pair,
        login_timeout=float(config.get("timeouts", {}).get("login_seconds", 30.0)),
        query_timeout=float(config.get("timeouts", {}).get("query_seconds", 8.0)),
        stop_timeout=float(config.get("timeouts", {}).get("stop_seconds", 12.0)),
        sdk_provenance=provenance,
        front_selection=attempts,
    )
