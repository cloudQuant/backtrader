"""D67-01 calendar gate shared by the 22 iteration-67 ``007_ctp`` live entries.

Frozen decision (iteration 67 plan/design, D67-01, user decision C on
2026-11-11): a Gateway entry, or a direct entry with SDK write admission
enabled, must declare ``calendars.root`` explicitly; when it is missing the
start is refused with ``calendar_root_unconfigured``.  ``root: package_seed``
is accepted as an explicit selection: a direct entry's Store installs the
committed synthetic in-package seed at live start (``SYNTHETIC_MOCK``, not
exchange truth), and a Gateway entry only declares the root for the separately
operated Gateway process, which must install or read it itself.  The gate never
installs, reads or creates anything.  The offline ``--dry-run`` only reports
configuration problems: it never creates a Store or Broker, and it does not
refuse a merely unconfigured entry.

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
    """``kind`` is ``directory`` or ``package_seed`` (parsed), ``declared`` (Gateway live)
    or ``unconfigured``.

    ``code`` is set only for an unconfigured result, which the caller reports:
    the dry-run passes with that code and the live start refuses it.
    """

    kind: str
    code: str | None = None
    reason: str | None = None


def _section(config):
    return config.get("calendars") if isinstance(config, Mapping) else None


def _parser_config(config):
    """Drop only the consumer-side ``feed_scope`` before the SDK parser sees it.

    ``feed_scope`` is validated separately by ``calendar_feed_scope`` and wired
    into the Feed; every other ``calendars`` key still reaches the parser, so
    an unknown or malformed key keeps its original finite refusal instead of
    being hidden by this gate.
    """
    if not isinstance(config, Mapping) or "calendars" not in config:
        return config
    section = config["calendars"]
    if type(section) is dict:
        section = {key: value for key, value in section.items() if key != "feed_scope"}
    return {**config, "calendars": section}


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
            _parser_config(config),
            config_file=config_file,
            ctp_routes=ctp_routes,
            configured_routes=configured_routes,
            # The direct Store materializes the committed synthetic seed before
            # reading; the gate itself still reads and creates nothing.
            package_seed_binding=True,
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
    if candidate.root_kind not in ("directory", "package_seed"):
        raise CalendarGateRefusal(CALENDAR_CONFIG_INVALID)
    return CalendarGateResult(candidate.root_kind)


def check_gateway_calendar(config, *, config_file, dry_run):
    """Classify a Gateway entry's ``calendars`` section.

    Both paths parse the declaration without reading the target directory.
    A live Gateway start is refused when no root is declared. ``package_seed``
    is a declaration only; this strategy process neither installs nor reads it.
    """
    section = _section(config)
    if section is None:
        return CalendarGateResult(
            "unconfigured", CALENDAR_ROOT_UNCONFIGURED, _REASONS[CALENDAR_ROOT_UNCONFIGURED]
        )
    from bt_api_py.trading_calendar_config import parse_trading_calendar_config

    try:
        calendar = parse_trading_calendar_config(
            _parser_config(config),
            config_file=config_file,
            gateway_enabled=True,
            direct_write_enabled=False,
        )
    except Exception as exc:
        if (not dry_run and isinstance(section, Mapping) and section.get("root") is None
                and getattr(exc, "code", None) == "calendar_root_invalid"):
            raise CalendarGateRefusal(CALENDAR_ROOT_UNCONFIGURED) from None
        raise CalendarGateRefusal(GATEWAY_CALENDAR_CONFIG_INVALID) from None
    if calendar.root_kind == "unconfigured" and not dry_run:
        raise CalendarGateRefusal(
            CALENDAR_ROOT_UNCONFIGURED,
            "calendars.root is not configured (the declared calendars section is "
            "invalid); the live start is refused",
        )
    if calendar.root_kind not in ("directory", "package_seed"):
        raise CalendarGateRefusal(GATEWAY_CALENDAR_CONFIG_INVALID)
    return CalendarGateResult(calendar.root_kind if dry_run else "declared")
