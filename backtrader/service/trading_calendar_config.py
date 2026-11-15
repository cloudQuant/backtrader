"""Explicit, read-only calendar status configuration for direct Stores."""

import re


def parse_direct_calendar_status(config, *, config_file, ctp_routes, configured_routes):
    """Return the SDK candidate and exact CTP route roots; never read a file."""
    from bt_api_py.trading_calendar_config import parse_trading_calendar_config

    candidate = parse_trading_calendar_config(
        config, config_file=config_file, gateway_enabled=False, direct_write_enabled=True
    )
    if not isinstance(ctp_routes, (tuple, list)):
        raise ValueError("calendar_ctp_routes_invalid")
    routes = tuple(ctp_routes)
    if (not routes or any(type(route) is not str or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", route) for route in routes)
            or len(set(routes)) != len(routes) or not set(routes).issubset(configured_routes)):
        raise ValueError("calendar_ctp_routes_invalid")
    if candidate.root_kind == "package_seed":
        raise ValueError("calendar_package_seed_unsupported")
    if candidate.root_kind != "directory":
        if "calendars" in config:
            raise ValueError("calendar_root_unconfigured")
        return candidate, {}
    return candidate, {route: str(candidate.root_path / "ctp") for route in routes}
