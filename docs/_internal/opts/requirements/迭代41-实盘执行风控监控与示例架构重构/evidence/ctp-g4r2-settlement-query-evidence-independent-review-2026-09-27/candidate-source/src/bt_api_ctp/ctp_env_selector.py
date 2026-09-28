"""Fail-closed SimNow front selection with explicit readiness evidence."""

from __future__ import annotations

import os
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Any, Callable
from urllib.parse import urlsplit

_TRADING_SESSIONS = (
    (time(9, 0), time(11, 30)),
    (time(13, 30), time(15, 0)),
    (time(21, 0), time(23, 59, 59)),
)
_NIGHT_SESSION_AFTER_MIDNIGHT = (time(0, 0), time(2, 30))
_SET1_DEFAULTS = {
    "1": ("tcp://180.168.146.187:10201", "tcp://180.168.146.187:10211"),
    "2": ("tcp://180.168.146.187:10202", "tcp://180.168.146.187:10212"),
}
_SET2_DEFAULT = ("tcp://180.168.146.187:10130", "tcp://180.168.146.187:10131")

# These alternate pairs are deliberately frozen and named.  They mirror the
# root package's ``configs/ctp_fronts.yaml`` entries; selection is based only
# on TCP reachability of a complete TD/MD pair, never on VPN geography or the
# process's public IP address.
_SET1_GROUP1_VPN = ("tcp://182.254.243.31:30001", "tcp://182.254.243.31:30011")
_SET2_7X24_4000X = ("tcp://182.254.243.31:40001", "tcp://182.254.243.31:40011")

# Registered third-party broker simulation environments.
#
# These are exchange-member simulation fronts (a broker's SimNow-equivalent),
# registered for the typed direct-path admission entry
# ``TraderClient.arm_execution_for_registered_sim``.  Admission is granted by
# EXACT frozen endpoint-pair match only, mirroring the official SimNow
# whitelist: a production front can never match, and a renamed or re-pointed
# front invalidates the registration until this frozen table is updated in
# review.  Adding an entry here is an explicit, auditable decision that the
# environment is a non-production simulation.
_REGISTERED_BROKER_SIM_FRONTS = {
    # Hongyuan Futures simulation (BrokerID 3070, v6.7.10_20250422 API).
    "hongyuan_sim_telecom": (
        "tcp://101.230.79.235:32205",
        "tcp://101.230.79.235:32213",
    ),
    "hongyuan_sim_unicom": (
        "tcp://112.65.19.116:32205",
        "tcp://112.65.19.116:32213",
    ),
}
_SIMNOW_PROFILE_FRONTS = {
    "set1_group1": _SET1_DEFAULTS["1"],
    "set1_group1_vpn": _SET1_GROUP1_VPN,
    "set1_group2": _SET1_DEFAULTS["2"],
    "set2_7x24": _SET2_DEFAULT,
    # This is a separate, exact profile rather than a replacement for the
    # historical ``set2_7x24`` pair.  The suffix identifies the frozen port
    # family without deriving a route from VPN geography.
    "set2_7x24_4000x": _SET2_7X24_4000X,
    # Retain the prior public spelling for callers that already persisted it.
    # New Iteration 22 paths use the more precise ``set2_7x24_4000x`` name.
    "set2_7x24_vpn": _SET2_7X24_4000X,
}
_SIMNOW_PROFILE_FAMILIES = {
    "set1_group1": ("set1_group1", "set1_group1_vpn"),
    "set1_group1_vpn": ("set1_group1_vpn", "set1_group1"),
    "set1_group2": ("set1_group2",),
    "set2_7x24": ("set2_7x24", "set2_7x24_vpn"),
    "set2_7x24_4000x": ("set2_7x24_4000x",),
    "set2_7x24_vpn": ("set2_7x24_vpn", "set2_7x24"),
}
_DEFAULT_FRONT_PROBE_TIMEOUT = 3.0

_FrontConnector = Callable[[str, float], bool]


@dataclass(frozen=True)
class CtpEnvironmentSelection:
    td_front: str
    md_front: str
    environment: str
    profile: str
    readiness: str
    reason: str
    calendar_verified: bool
    explicit: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CtpFrontProbe:
    """Read-only TCP probe result for one named TD/MD profile.

    The result intentionally identifies a configured profile rather than
    echoing endpoints or connection exceptions.  That keeps failure evidence
    useful without making it an address-discovery or error-leak channel.
    """

    profile: str
    td_reachable: bool
    md_reachable: bool

    @property
    def reachable(self) -> bool:
        return self.td_reachable and self.md_reachable


def _in_trading_session(now: datetime) -> bool:
    current = now.time()
    if _NIGHT_SESSION_AFTER_MIDNIGHT[0] <= current <= _NIGHT_SESSION_AFTER_MIDNIGHT[1]:
        return True
    return any(start <= current <= end for start, end in _TRADING_SESSIONS)


def _get_set1_selection(*, explicit: bool, calendar_verified: bool) -> CtpEnvironmentSelection:
    group = str(os.environ.get("CTP_SET1_GROUP") or "1").strip()
    if group not in _SET1_DEFAULTS:
        raise ValueError(f"unsupported CTP_SET1_GROUP {group!r}; expected '1' or '2'")
    default_td, default_md = _SET1_DEFAULTS[group]
    td = str(os.environ.get(f"CTP_SET1_TD_FRONT_{group}") or default_td).strip()
    md = str(os.environ.get(f"CTP_SET1_MD_FRONT_{group}") or default_md).strip()
    if not td or not md:
        raise ValueError("selected SimNow set1 profile has an empty front")
    official = (td, md) == (default_td, default_md)
    return CtpEnvironmentSelection(
        td_front=td,
        md_front=md,
        environment="simnow" if official else "custom",
        profile=f"set1_group{group}",
        readiness=(
            ("profile_selected" if explicit else "calendar_verified_session")
            if official
            else "custom_front_override"
        ),
        reason="explicit_set1" if explicit else "verified_trading_day_and_session",
        calendar_verified=calendar_verified,
        explicit=explicit,
    )


def _get_set2_selection(*, explicit: bool, calendar_verified: bool) -> CtpEnvironmentSelection:
    td = str(os.environ.get("CTP_SET2_TD_FRONT") or _SET2_DEFAULT[0]).strip()
    md = str(os.environ.get("CTP_SET2_MD_FRONT") or _SET2_DEFAULT[1]).strip()
    if not td or not md:
        raise ValueError("selected SimNow set2 profile has an empty front")
    official = (td, md) == _SET2_DEFAULT
    if explicit:
        readiness = "profile_selected"
        reason = "explicit_set2"
    elif calendar_verified:
        readiness = "calendar_verified_off_session"
        reason = "verified_non_trading_day_or_off_session"
    else:
        readiness = "calendar_unverified"
        reason = "auto_requires_exchange_calendar_for_set1"
    if not official:
        readiness = "custom_front_override"
    return CtpEnvironmentSelection(
        td_front=td,
        md_front=md,
        environment="simnow" if official else "custom",
        profile="set2_7x24",
        readiness=readiness,
        reason=reason,
        calendar_verified=calendar_verified,
        explicit=explicit,
    )


def select_ctp_environment(
    env: str = "",
    now: datetime | None = None,
    *,
    is_trading_day: bool | None = None,
    require_profile: str | None = None,
) -> CtpEnvironmentSelection:
    """Select a profile without pretending weekdays are an exchange calendar.

    ``auto`` only selects set1 when the caller supplies verified trading-day
    evidence and the time is in a configured session. Without that evidence it
    selects the 7x24 profile and marks the result ``calendar_unverified``.
    """
    selected_env = str(env or os.environ.get("CTP_ENV") or "auto").strip().lower()
    if selected_env not in {"auto", "set1", "set2"}:
        raise ValueError(f"unsupported CTP_ENV {selected_env!r}; expected auto, set1, or set2")
    current = now or datetime.now()
    if selected_env == "set1":
        selection = _get_set1_selection(explicit=True, calendar_verified=is_trading_day is True)
    elif selected_env == "set2":
        selection = _get_set2_selection(explicit=True, calendar_verified=is_trading_day is not None)
    elif is_trading_day is True and _in_trading_session(current):
        selection = _get_set1_selection(explicit=False, calendar_verified=True)
    else:
        selection = _get_set2_selection(
            explicit=False, calendar_verified=is_trading_day is not None
        )

    required = str(require_profile or "").strip().lower()
    if required:
        matches = (
            selection.profile == required
            or (required == "set1" and selection.profile.startswith("set1_"))
            or (required == "set2" and selection.profile.startswith("set2_"))
        )
        if not matches:
            raise RuntimeError(
                f"required CTP profile {required!r}, selected {selection.profile!r} "
                f"({selection.readiness})"
            )
    return selection


def _profile_group(profile: str) -> str:
    name = str(profile or "").strip().lower()
    if name in {"set1", "set2"}:
        return name
    if name in _SIMNOW_PROFILE_FRONTS:
        return "set1" if name.startswith("set1_") else "set2"
    raise ValueError(f"unsupported CTP profile {profile!r}")


def _optional_profile_group(profile: str | None, *, label: str) -> tuple[str, str] | None:
    name = str(profile or "").strip().lower()
    if not name:
        return None
    try:
        return name, _profile_group(name)
    except ValueError as exc:
        raise ValueError(f"unsupported CTP {label} {profile!r}") from exc


def _configured_environment(env: str) -> str:
    selected_env = str(env or os.environ.get("CTP_ENV") or "auto").strip().lower()
    if selected_env not in {"auto", "set1", "set2"}:
        raise ValueError(f"unsupported CTP_ENV {selected_env!r}; expected auto, set1, or set2")
    return selected_env


def _front_probe_timeout(timeout: float) -> float:
    if isinstance(timeout, bool):
        raise ValueError("CTP front probe timeout must be a positive number")
    try:
        value = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("CTP front probe timeout must be a positive number") from exc
    if value <= 0:
        raise ValueError("CTP front probe timeout must be a positive number")
    return value


def _tcp_address(endpoint: str) -> tuple[str, int]:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "tcp" or not parsed.hostname:
        raise ValueError("invalid configured CTP front")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid configured CTP front") from exc
    if port is None:
        raise ValueError("invalid configured CTP front")
    return parsed.hostname, port


def _socket_connector(endpoint: str, timeout: float) -> bool:
    """Attempt one TCP connect without surfacing endpoint or socket errors."""
    try:
        host, port = _tcp_address(endpoint)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def probe_ctp_environment_pair(
    profile: str,
    *,
    connector: _FrontConnector | None = None,
    timeout: float = _DEFAULT_FRONT_PROBE_TIMEOUT,
) -> CtpFrontProbe:
    """Probe the frozen TD and MD fronts for one named profile.

    ``connector`` is injectable for deterministic offline tests.  It receives
    ``(endpoint, timeout)`` and must return a truthy value only after a TCP
    connection was established.  Connector failures are treated as an
    unreachable front and do not leak endpoint or exception details.
    """
    name = str(profile or "").strip().lower()
    fronts = _SIMNOW_PROFILE_FRONTS.get(name)
    if fronts is None:
        raise ValueError(f"unsupported CTP profile {profile!r}")
    effective_connector = connector or _socket_connector
    effective_timeout = _front_probe_timeout(timeout)

    def reachable(endpoint: str) -> bool:
        try:
            return bool(effective_connector(endpoint, effective_timeout))
        except Exception:
            return False

    td_front, md_front = fronts
    return CtpFrontProbe(
        profile=name,
        td_reachable=reachable(td_front),
        md_reachable=reachable(md_front),
    )


def select_reachable_ctp_environment(
    env: str = "",
    now: datetime | None = None,
    *,
    is_trading_day: bool | None = None,
    profile: str | None = None,
    require_profile: str | None = None,
    connector: _FrontConnector | None = None,
    timeout: float = _DEFAULT_FRONT_PROBE_TIMEOUT,
    front_probe_timeout: float | None = None,
) -> CtpEnvironmentSelection:
    """Select a reachable frozen SimNow TD/MD pair without geo inference.

    This is deliberately separate from :func:`select_ctp_environment`: callers
    opt in to TCP I/O by calling this function.  A named ``profile`` and a
    ``require_profile`` constrain selection to their logical set1/set2 group.
    The selector can switch only between a profile and its registered alternate
    pair; it never substitutes a set1 pair for set2 or vice versa.  ``timeout``
    is retained for compatibility, while ``front_probe_timeout`` names the same
    runtime setting explicitly when supplied.
    """
    configured_env = _configured_environment(env)
    requested = _optional_profile_group(profile, label="profile")
    required = _optional_profile_group(require_profile, label="required profile")
    required_is_exact = required is not None and required[0] in _SIMNOW_PROFILE_FRONTS
    if (
        requested is not None
        and required is not None
        and (
            requested[1] != required[1]
            or (
                required_is_exact
                and requested[0] in _SIMNOW_PROFILE_FRONTS
                and requested[0] != required[0]
            )
        )
    ):
        raise RuntimeError("configured CTP profile conflicts with required CTP profile")
    if requested is not None and configured_env != "auto" and requested[1] != configured_env:
        raise RuntimeError("configured CTP profile conflicts with selected CTP environment")

    if requested is not None:
        # Explicit named profiles retain their existing role as an intentional
        # set selection.  Detection may use only its immutable local/alternate
        # family, never the other logical set.
        base_selection = select_ctp_environment(requested[1], now, is_trading_day=is_trading_day)
        base_profile = (
            requested[0] if requested[0] in _SIMNOW_PROFILE_FRONTS else base_selection.profile
        )
    else:
        # Keep the existing calendar policy intact.  In particular, ``auto``
        # does not turn an unverified trading-day assumption into set1 merely
        # because a network path happens to be open.
        base_selection = select_ctp_environment(env, now, is_trading_day=is_trading_day)
        base_group = _profile_group(base_selection.profile)
        if required is not None and required[1] != base_group:
            raise RuntimeError(
                "required CTP profile group is not selected by the configured environment"
            )
        base_profile = required[0] if required_is_exact else base_selection.profile

    effective_timeout = timeout if front_probe_timeout is None else front_probe_timeout
    if required_is_exact:
        base_profile = required[0]
        candidates = (base_profile,)
    else:
        candidates = _SIMNOW_PROFILE_FAMILIES[base_profile]
    for candidate in candidates:
        probe = probe_ctp_environment_pair(
            candidate, connector=connector, timeout=effective_timeout
        )
        if probe.reachable:
            td_front, md_front = _SIMNOW_PROFILE_FRONTS[candidate]
            return CtpEnvironmentSelection(
                td_front=td_front,
                md_front=md_front,
                environment="simnow",
                profile=candidate,
                readiness="tcp_pair_reachable",
                reason="tcp_pair_reachable",
                calendar_verified=base_selection.calendar_verified,
                explicit=base_selection.explicit or requested is not None,
            )

    # Do not include fronts, socket errors, or connector details in this
    # fail-closed error.  Callers can retain only the named requested group.
    raise RuntimeError("no reachable CTP front pair for the selected profile group")


def verify_official_simnow_profile(td_front: str, md_front: str, profile: str) -> bool:
    """Verify that a claimed profile uses its frozen endpoint pair exactly."""
    name = str(profile or "").strip().lower()
    expected = _SIMNOW_PROFILE_FRONTS.get(name)
    return expected is not None and (str(td_front).strip(), str(md_front).strip()) == expected


def official_simnow_fronts(profile: str) -> tuple[str, str]:
    """Return the immutable endpoint pair for a named SimNow profile."""
    name = str(profile or "").strip().lower()
    expected = _SIMNOW_PROFILE_FRONTS.get(name)
    if expected is None:
        raise ValueError(f"unsupported CTP profile {profile!r}")
    return expected


def registered_broker_sim_fronts(profile: str) -> tuple[str, str]:
    """Return the immutable endpoint pair of a registered broker simulation."""
    name = str(profile or "").strip().lower()
    expected = _REGISTERED_BROKER_SIM_FRONTS.get(name)
    if expected is None:
        raise ValueError(f"unsupported registered broker simulation {profile!r}")
    return expected


def verify_registered_broker_sim_profile(td_front: str, md_front: str, profile: str) -> bool:
    """Verify a claimed registered-sim profile uses its frozen endpoint pair."""
    name = str(profile or "").strip().lower()
    expected = _REGISTERED_BROKER_SIM_FRONTS.get(name)
    return expected is not None and (
        str(td_front or "").strip(),
        str(md_front or "").strip(),
    ) == expected


def registered_broker_sim_profile_for_td_front(td_front: str) -> str:
    """Return the registered-sim profile whose TD front matches exactly."""
    front = str(td_front or "").strip()
    for name, (td_expected, _md_expected) in _REGISTERED_BROKER_SIM_FRONTS.items():
        if front == td_expected:
            return name
    return ""


def get_ctp_fronts(
    env: str = "",
    now: datetime | None = None,
    *,
    is_trading_day: bool | None = None,
    require_profile: str | None = None,
) -> tuple[str, str, str]:
    selection = select_ctp_environment(
        env,
        now,
        is_trading_day=is_trading_day,
        require_profile=require_profile,
    )
    return selection.td_front, selection.md_front, selection.profile


def apply_ctp_env(**kwargs: Any) -> tuple[str, str, str]:
    """Apply an explicit environment selection to compatibility variables.

    TCP probing remains opt-in: callers must pass ``auto_detect_fronts=True``.
    A reachable selection writes the exact selected profile so later CTP feed
    construction can verify the environment-provided pair rather than treating
    it as an unverified custom override.
    """
    selection_kwargs = dict(kwargs)
    raw_auto_detect_fronts = selection_kwargs.pop("auto_detect_fronts", False)
    auto_detect_fronts = raw_auto_detect_fronts is True or str(
        raw_auto_detect_fronts
    ).strip().lower() in {"1", "true", "yes", "on"}
    profile = selection_kwargs.pop("profile", None)
    connector = selection_kwargs.pop("connector", None)
    timeout = selection_kwargs.pop("front_probe_timeout", None)
    if timeout is None:
        timeout = selection_kwargs.pop("timeout", _DEFAULT_FRONT_PROBE_TIMEOUT)
    if auto_detect_fronts:
        selection = select_reachable_ctp_environment(
            profile=profile,
            connector=connector,
            timeout=timeout,
            **selection_kwargs,
        )
    else:
        if profile is not None:
            raise ValueError("profile requires auto_detect_fronts=True")
        selection = select_ctp_environment(**selection_kwargs)
    os.environ["CTP_TD_FRONT"] = selection.td_front
    os.environ["CTP_MD_FRONT"] = selection.md_front
    if auto_detect_fronts:
        os.environ["CTP_ENV_PROFILE"] = selection.profile
    return selection.td_front, selection.md_front, selection.profile


__all__ = [
    "CtpFrontProbe",
    "CtpEnvironmentSelection",
    "apply_ctp_env",
    "get_ctp_fronts",
    "official_simnow_fronts",
    "probe_ctp_environment_pair",
    "registered_broker_sim_fronts",
    "registered_broker_sim_profile_for_td_front",
    "select_ctp_environment",
    "select_reachable_ctp_environment",
    "verify_official_simnow_profile",
    "verify_registered_broker_sim_profile",
]
