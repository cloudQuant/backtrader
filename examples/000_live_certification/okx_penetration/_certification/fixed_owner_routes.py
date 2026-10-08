"""Closed source registry for reviewed OKX same-owner case routes.

Routes are keyed by the exact venue, ordered case selection, and topology.
There are currently no admitted routes.  A source candidate or a configurable
backend target is not a route registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


TopologyKey = tuple[str, bool, bool, bool] | None


@dataclass(frozen=True)
class RouteKey:
    venue: str
    case_ids: tuple[str, ...]
    topology: TopologyKey


@dataclass(frozen=True)
class FixedOwnerRoute:
    """One source-bound route handler registered for an exact route key."""

    key: RouteKey
    identity: str
    dispatch: Callable[..., object]


# No reviewed OKX write owner currently produces the required typed evidence.
# Keep this empty until a venue-native owner and handler pass review.
_FIXED_OWNER_ROUTES: Mapping[RouteKey, FixedOwnerRoute] = MappingProxyType({})


def _topology_key(topology: object | None) -> TopologyKey:
    if topology is None:
        return None
    values = tuple(getattr(topology, name, None) for name in ("transport", "execution", "risk", "monitor"))
    if (
        len(values) != 4
        or type(values[0]) is not str
        or any(type(value) is not bool for value in values[1:])
    ):
        return None
    return values  # type: ignore[return-value]


def resolve_fixed_owner_route(
    venue: str, selected: list[str], topology: object | None
) -> FixedOwnerRoute | None:
    """Resolve only a literal, exact source registration; never import a target."""
    if (
        type(venue) is not str
        or type(selected) is not list
        or any(type(case_id) is not str for case_id in selected)
    ):
        return None
    key = RouteKey(venue, tuple(selected), _topology_key(topology))
    route = _FIXED_OWNER_ROUTES.get(key)
    if (
        type(route) is not FixedOwnerRoute
        or route.key != key
        or type(route.identity) is not str
        or not route.identity
        or not callable(route.dispatch)
    ):
        return None
    return route
