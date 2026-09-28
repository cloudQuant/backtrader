"""Reviewed mode/preset policy definitions for the Iteration 41 runtime.

This module contains data only.  In particular it must never import an SDK,
provider, gateway, execution package, risk package, or monitoring package.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Optional, Tuple


CAPABILITY_EXECUTION = "execution"
CAPABILITY_RISK = "risk"
CAPABILITY_MONITOR = "monitor"
CAPABILITY_GATEWAY = "gateway"
CAPABILITY_TRANSPORT_ZMQ = "transport_zmq"

MANAGED_WRITE_CAPABILITIES = (
    CAPABILITY_EXECUTION,
    CAPABILITY_RISK,
    CAPABILITY_MONITOR,
)


@dataclass(frozen=True)
class PresetPolicy:
    """A sealed policy selected by a schema-v4 mode/preset pair."""

    name: str
    mode: str
    environment: str
    order_route: Optional[str]
    account_access: Optional[str]
    allows_network: bool
    allows_external_writes: bool
    allows_production_writes: bool
    allows_hypothetical_fills: bool
    required_capabilities: Tuple[str, ...]
    accepts_provider_secrets: bool
    requires_approval: bool
    requires_live_confirmation: bool


# The public schema has exactly these seven preset names.  A runtime registry
# must still explicitly bind a preset to each registered strategy directory;
# possessing a valid name is not authorization to use it.
_PRESET_POLICIES = {
    "local_backtest": PresetPolicy(
        name="local_backtest",
        mode="backtest",
        environment="local",
        order_route=None,
        account_access=None,
        allows_network=False,
        allows_external_writes=False,
        allows_production_writes=False,
        allows_hypothetical_fills=False,
        required_capabilities=(),
        accepts_provider_secrets=False,
        requires_approval=False,
        requires_live_confirmation=False,
    ),
    "replay": PresetPolicy(
        name="replay",
        mode="simulation",
        environment="offline",
        order_route=None,
        account_access=None,
        allows_network=False,
        allows_external_writes=False,
        allows_production_writes=False,
        allows_hypothetical_fills=False,
        required_capabilities=(),
        accepts_provider_secrets=False,
        requires_approval=False,
        requires_live_confirmation=False,
    ),
    "shadow": PresetPolicy(
        name="shadow",
        mode="simulation",
        environment="public_read",
        order_route="read_only",
        account_access="public_read",
        allows_network=True,
        allows_external_writes=False,
        allows_production_writes=False,
        allows_hypothetical_fills=False,
        required_capabilities=(),
        accepts_provider_secrets=False,
        requires_approval=False,
        requires_live_confirmation=False,
    ),
    "paper": PresetPolicy(
        name="paper",
        mode="simulation",
        environment="public_read",
        order_route="local_simulation",
        account_access="public_read",
        allows_network=True,
        allows_external_writes=False,
        allows_production_writes=False,
        allows_hypothetical_fills=True,
        required_capabilities=(),
        accepts_provider_secrets=False,
        requires_approval=False,
        requires_live_confirmation=False,
    ),
    "sandbox": PresetPolicy(
        name="sandbox",
        mode="simulation",
        environment="sandbox",
        order_route=None,
        account_access="sandbox_private_read",
        allows_network=True,
        allows_external_writes=False,
        allows_production_writes=False,
        allows_hypothetical_fills=False,
        required_capabilities=(),
        accepts_provider_secrets=True,
        requires_approval=False,
        requires_live_confirmation=False,
    ),
    "managed_live_direct": PresetPolicy(
        name="managed_live_direct",
        mode="live",
        environment="production",
        order_route="managed_execution",
        account_access="direct_provider",
        allows_network=True,
        allows_external_writes=True,
        allows_production_writes=True,
        allows_hypothetical_fills=False,
        required_capabilities=MANAGED_WRITE_CAPABILITIES,
        accepts_provider_secrets=True,
        requires_approval=True,
        requires_live_confirmation=True,
    ),
    "managed_live_gateway": PresetPolicy(
        name="managed_live_gateway",
        mode="live",
        environment="production",
        order_route="managed_execution",
        account_access="gateway",
        allows_network=True,
        allows_external_writes=True,
        allows_production_writes=True,
        allows_hypothetical_fills=False,
        required_capabilities=MANAGED_WRITE_CAPABILITIES
        + (CAPABILITY_GATEWAY, CAPABILITY_TRANSPORT_ZMQ),
        accepts_provider_secrets=True,
        requires_approval=True,
        requires_live_confirmation=True,
    ),
}

PRESET_REGISTRY = MappingProxyType(_PRESET_POLICIES)


def get_preset_policy(name: str) -> Optional[PresetPolicy]:
    """Return the sealed policy for *name*, or ``None`` when it is unknown."""

    return PRESET_REGISTRY.get(name)


def preset_names() -> Tuple[str, ...]:
    """Return the stable, sorted public preset names."""

    return tuple(sorted(PRESET_REGISTRY))
