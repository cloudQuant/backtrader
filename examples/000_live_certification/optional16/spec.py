"""Topology specification for the Iteration-41 optional-component matrix.

`optional16` is the 2 x 2 x 2 x 2 grid of one transport choice
(`direct` | `gateway_zmq`) and three optional components (execution, risk,
monitor), i.e. exactly the sixteen combinations the acceptance matrix tracks.

`TopologySpec` is the frozen, validated description of one combination;
`from_config` derives it from a case `config.yaml` plus an optional override,
and `combo_id` renders the stable identifier used in evidence and reports
(for example ``gateway_zmq-e1-r0-m1``).

Nothing in this module talks to a network, a provider or the SDK; it is pure
validation so a matrix runner can reject an unsupported combination before any
client is constructed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence, Tuple

TRANSPORTS: Tuple[str, ...] = ("direct", "gateway_zmq")
COMPONENT_FLAGS: Tuple[str, ...] = ("execution", "risk", "monitor")


class TopologyError(ValueError):
    """The requested topology is not one of the matrix's defined combinations."""


@dataclass(frozen=True)
class TopologySpec:
    """One validated matrix combination."""

    transport: str = "direct"
    execution: bool = False
    risk: bool = False
    monitor: bool = False

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise TopologyError("transport_not_supported:" + str(self.transport))
        for flag in COMPONENT_FLAGS:
            value = getattr(self, flag)
            if not isinstance(value, bool):
                raise TopologyError("component_flag_not_bool:" + flag)

    # ------------------------------------------------------------------ views
    def as_dict(self) -> dict:
        """Return the plain mapping the certification runner already uses."""
        return {
            "transport": self.transport,
            "execution": self.execution,
            "risk": self.risk,
            "monitor": self.monitor,
        }

    @property
    def enabled_components(self) -> Tuple[str, ...]:
        return tuple(flag for flag in COMPONENT_FLAGS if getattr(self, flag))

    @property
    def uses_gateway(self) -> bool:
        return self.transport == "gateway_zmq"

    def replace(self, **changes: Any) -> "TopologySpec":
        values = self.as_dict()
        unknown = sorted(set(changes) - set(values))
        if unknown:
            raise TopologyError("topology_override_unknown:" + ",".join(unknown))
        values.update(changes)
        return TopologySpec(**values)


def _coerce_flag(flag: str, value: Any, origin: str) -> bool:
    if not isinstance(value, bool):
        raise TopologyError(f"component_flag_not_bool:{origin}:{flag}")
    return value


def from_config(
    config: Mapping[str, Any], topology_override: Optional[Mapping[str, Any]] = None
) -> TopologySpec:
    """Build a `TopologySpec` from a case config and an optional override.

    ``topology_override`` is the runner's effective transport/component choice
    (CLI flags or an orchestrator decision). Every override key must be one of
    transport/execution/risk/monitor; unknown keys and non-boolean flags are
    rejected instead of silently ignored.
    """
    if not isinstance(config, Mapping):
        raise TopologyError("config_not_a_mapping")
    section = config.get("topology") or {}
    if not isinstance(section, Mapping):
        raise TopologyError("topology_section_invalid")

    values: dict = {"transport": section.get("transport", "direct")}
    for flag in COMPONENT_FLAGS:
        values[flag] = _coerce_flag(flag, section.get(flag, False), "config")

    if topology_override is not None:
        if not isinstance(topology_override, Mapping):
            raise TopologyError("topology_override_invalid")
        for key, value in topology_override.items():
            if key not in values:
                raise TopologyError("topology_override_unknown:" + str(key))
            if key == "transport":
                values["transport"] = value
            else:
                values[key] = _coerce_flag(key, value, "override")

    return TopologySpec(**values)


def combo_id(spec: TopologySpec) -> str:
    """Return the stable identifier for one combination, e.g. ``direct-e0-r0-m0``."""
    if not isinstance(spec, TopologySpec):
        raise TopologyError("TopologySpec_required")
    return "{}-e{}-r{}-m{}".format(
        spec.transport, int(spec.execution), int(spec.risk), int(spec.monitor)
    )


def matrix_specs() -> Tuple[TopologySpec, ...]:
    """Return all sixteen combinations in a deterministic order."""
    specs: list = []
    for transport in TRANSPORTS:
        for execution in (False, True):
            for risk in (False, True):
                for monitor in (False, True):
                    specs.append(
                        TopologySpec(
                            transport=transport, execution=execution, risk=risk, monitor=monitor
                        )
                    )
    return tuple(specs)


def matrix_ids() -> Sequence[str]:
    """The sixteen `combo_id` values, in `matrix_specs()` order."""
    return tuple(combo_id(spec) for spec in matrix_specs())
