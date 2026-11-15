"""D67-01 calendar gate shared by the 22 iteration-67 ``007_ctp`` live entries.

Frozen decision (iteration 67 plan/design, D67-01, user decision C on
2026-11-11): a Gateway entry, or a direct entry with SDK write admission
enabled, must declare ``calendars.root`` explicitly; when it is missing the
start is refused with ``calendar_root_unconfigured``.  ``root: package_seed``
may be declared, but these entries do not implement the package-seed runtime
binding, so they refuse it with ``calendar_package_seed_unsupported`` instead
of silently falling back to the old built-in constants.  The offline
``--dry-run`` only reports configuration problems: it never creates a Store or
Broker, and it does not refuse a merely unconfigured entry.

D67-01 leaves the unconfigured behaviour outside Gateway or direct write
admission undecided ("67.01 另行冻结").  These example entries are live
trading entries and fail closed in every case: an explicit
``direct.write_admission: false`` is not an opt-out here.  The gate is
configuration-only: it never reads the calendar directory, never creates a
Store/Broker, never contacts a provider or account, and never prints a path.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

CALENDAR_ROOT_UNCONFIGURED = "calendar_root_unconfigured"
CALENDAR_PACKAGE_SEED_UNSUPPORTED = "calendar_package_seed_unsupported"
CALENDAR_CONFIG_INVALID = "calendar_config_invalid"
# The Gateway example already reported this exact upper-case code for an invalid
# calendars section and its frozen offline test asserts it; keep that surface.
GATEWAY_CALENDAR_CONFIG_INVALID = "CALENDAR_CONFIG_INVALID"

_REASONS = {
    CALENDAR_ROOT_UNCONFIGURED: (
        "calendars.root is not configured; configure an explicit root (D67-01); "
        "the live start is refused"
    ),
    CALENDAR_PACKAGE_SEED_UNSUPPORTED: (
        "package_seed is not supported by this entry; configure an external "
        "directory instead (D67-01)"
    ),
    CALENDAR_CONFIG_INVALID: "the calendar configuration is invalid or unusable",
    GATEWAY_CALENDAR_CONFIG_INVALID: "the calendar configuration is invalid or unusable",
}


class CalendarGateRefusal(ValueError):
    """A finite gate refusal; ``code`` and ``reason`` never contain a path."""

    def __init__(self, code, reason=None):
        if code not in _REASONS:
            raise ValueError("unknown calendar gate code")
        super().__init__(code)
        self.code = code
        self.reason = reason or _REASONS[code]


@dataclass(frozen=True)
class CalendarGateResult:
    """``kind`` is ``directory`` (parsed), ``declared`` (Gateway live) or ``unconfigured``.

    ``code`` is set only for an unconfigured result, which the caller reports:
    the dry-run passes with that code and the live start refuses it.
    """

    kind: str
    code: str | None = None
    reason: str | None = None


def _section(config):
    return config.get("calendars") if isinstance(config, Mapping) else None


def check_direct_calendar(config, *, config_file, ctp_routes, configured_routes):
    """Classify a direct entry's ``calendars`` section without touching the directory.

    An absent section returns an ``unconfigured`` result without importing or
    calling the SDK parser, so an offline dry-run of such an entry stays free of
    the new SDK dependency.  A declared but unusable section raises
    :class:`CalendarGateRefusal` with a finite code.
    """
    if _section(config) is None:
        return CalendarGateResult(
            "unconfigured", CALENDAR_ROOT_UNCONFIGURED, _REASONS[CALENDAR_ROOT_UNCONFIGURED]
        )
    from backtrader.service.trading_calendar_config import parse_direct_calendar_status

    try:
        candidate, _roots = parse_direct_calendar_status(
            config,
            config_file=config_file,
            ctp_routes=ctp_routes,
            configured_routes=configured_routes,
        )
    except ValueError as exc:
        code = exc.args[0] if exc.args else ""
        if code == CALENDAR_PACKAGE_SEED_UNSUPPORTED:
            raise CalendarGateRefusal(CALENDAR_PACKAGE_SEED_UNSUPPORTED) from None
        if code == CALENDAR_ROOT_UNCONFIGURED:
            # ``calendars`` is declared but carries no root: the section is
            # invalid and the required root is still unconfigured.
            raise CalendarGateRefusal(
                CALENDAR_ROOT_UNCONFIGURED,
                "calendars.root is not configured (the declared calendars section "
                "is invalid); the live start is refused",
            ) from None
        raise CalendarGateRefusal(CALENDAR_CONFIG_INVALID) from None
    except Exception:  # pragma: no cover - defensive: parser import/shape failure
        raise CalendarGateRefusal(CALENDAR_CONFIG_INVALID) from None
    if candidate.root_kind != "directory":
        raise CalendarGateRefusal(CALENDAR_CONFIG_INVALID)
    return CalendarGateResult("directory")


def check_gateway_calendar(config, *, config_file, dry_run):
    """Classify a Gateway entry's ``calendars`` section.

    ``--dry-run`` parses the declared section with the SDK parser, as before.
    A live Gateway start is refused when no root is declared or when
    ``package_seed`` is declared; the root itself is read by the Gateway
    (iteration 63), not by this strategy process, so a live start does not
    parse the section again.
    """
    section = _section(config)
    if section is None:
        return CalendarGateResult(
            "unconfigured", CALENDAR_ROOT_UNCONFIGURED, _REASONS[CALENDAR_ROOT_UNCONFIGURED]
        )
    if dry_run:
        from bt_api_py.trading_calendar_config import parse_trading_calendar_config

        try:
            calendar = parse_trading_calendar_config(
                config, config_file=config_file, gateway_enabled=True, direct_write_enabled=False
            )
        except Exception:
            raise CalendarGateRefusal(GATEWAY_CALENDAR_CONFIG_INVALID) from None
        if calendar.root_kind == "package_seed":
            raise CalendarGateRefusal(CALENDAR_PACKAGE_SEED_UNSUPPORTED)
        if calendar.root_kind != "directory":
            raise CalendarGateRefusal(GATEWAY_CALENDAR_CONFIG_INVALID)
        return CalendarGateResult("directory")
    if not isinstance(section, Mapping):
        raise CalendarGateRefusal(CALENDAR_CONFIG_INVALID)
    root = section.get("root")
    if root == "package_seed":
        raise CalendarGateRefusal(CALENDAR_PACKAGE_SEED_UNSUPPORTED)
    if root is None:
        raise CalendarGateRefusal(
            CALENDAR_ROOT_UNCONFIGURED,
            "calendars.root is not configured (the declared calendars section is "
            "invalid); the live start is refused",
        )
    return CalendarGateResult("declared")
