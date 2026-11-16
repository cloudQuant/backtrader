"""Explicit, read-only calendar status configuration for direct Stores."""

import re


def parse_direct_calendar_status(
    config, *, config_file, ctp_routes, configured_routes, package_seed_binding=False
):
    """Return the SDK candidate and exact CTP route roots; never read a file.

    ``package_seed_binding`` is an explicit opt-in for a caller that will
    materialize the committed in-package seed before reading (the Store does;
    the example entry gates do not).  Without it, ``root: package_seed`` keeps
    the frozen ``calendar_package_seed_unsupported`` refusal so an entry that
    cannot bind the seed still fails closed instead of silently using it.
    """
    from bt_api_py.trading_calendar_config import parse_trading_calendar_config

    if type(package_seed_binding) is not bool:
        raise ValueError("calendar_package_seed_binding_invalid")
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
        # D67-01: an explicit in-package seed is a valid configuration only for
        # a caller that will install the committed seed store before reading
        # (``bt_api_py.trading_calendar_package_seed``).  This parser still
        # reads nothing.
        if not package_seed_binding:
            raise ValueError("calendar_package_seed_unsupported")
        return candidate, {}
    if candidate.root_kind != "directory":
        if "calendars" in config:
            raise ValueError("calendar_root_unconfigured")
        return candidate, {}
    return candidate, {route: str(candidate.root_path / "ctp") for route in routes}
