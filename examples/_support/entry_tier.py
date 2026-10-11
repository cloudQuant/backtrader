"""Config-selected entry tier resolution for the unified examples.

The repository's examples used to pick their channel from command-line flags
only.  These examples additionally declare ``entry.tier`` in their own
``config.yaml``, so this helper resolves the requested tier and the CLI override
into one deterministic decision.  It is deliberately dependency-free: each
example keeps a byte-identical copy so that a folder copied out of the
repository still resolves its own tier.

A write grant (``--allow-write``) is not a tier and is never consulted here; the
caller keeps applying its own write admission after this decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

TIERS = ("dry", "replay", "live")
TIER_ALIASES = {"backtest": "replay"}
# A CLI mode flag may keep or lower the declared tier, never raise it.
_RANK = {"dry": 0, "replay": 1, "live": 2}

REASON_CONFIG_DEFAULT = "config_default"
REASON_CLI_REQUESTED = "cli_requested"
REASON_DEFAULT_DRY = "default_dry"
REASON_CLI_OVERRIDE = "cli_override"
REASON_CONFLICT = "config_tier_conflict"
REASON_INVALID = "config_tier_invalid"


@dataclass(frozen=True)
class TierDecision:
    """Resolved tier plus the fields an example must record as evidence."""

    config_tier: Optional[str]
    cli_tier: Optional[str]
    effective_tier: str
    reason: str

    def as_evidence(self) -> dict:
        return {
            "config_tier": self.config_tier,
            "cli_tier": self.cli_tier,
            "effective_tier": self.effective_tier,
            "tier_selection_reason": self.reason,
        }


def config_tier(config: Any) -> Optional[str]:
    """Return the declared tier, or ``None`` when the example declares none.

    Raises:
        ValueError: if ``entry`` is present but malformed or the tier is unknown.
    """

    if not isinstance(config, Mapping):
        raise ValueError("config must be a mapping to read entry.tier")
    if "tier" not in _entry_view(config):
        return None
    declared = _entry_view(config)["tier"]
    if not isinstance(declared, str):
        raise ValueError("entry.tier must be a string")
    normalized = declared.strip().lower()
    if normalized not in TIERS and normalized not in TIER_ALIASES:
        raise ValueError(f"entry.tier {declared!r} is not one of {TIERS}")
    return normalized


def decide(config: Any, cli_tier: Optional[str]) -> TierDecision:
    """Resolve ``entry.tier`` against the CLI request without ever escalating it.

    A CLI mode flag may keep or lower the declared tier; raising it above an
    explicit declaration is a configuration conflict, and a malformed
    declaration is rejected rather than silently defaulted.
    """

    try:
        declared = config_tier(config)
    except ValueError:
        return TierDecision(None, cli_tier, "dry", REASON_INVALID)
    canonical = TIER_ALIASES.get(declared, declared) if declared else None

    if canonical is None:
        if cli_tier is None:
            return TierDecision(None, None, "dry", REASON_DEFAULT_DRY)
        return TierDecision(None, cli_tier, cli_tier, REASON_CLI_REQUESTED)

    if cli_tier is None:
        return TierDecision(declared, None, canonical, REASON_CONFIG_DEFAULT)
    if cli_tier == canonical:
        return TierDecision(declared, cli_tier, canonical, REASON_CONFIG_DEFAULT)
    if _RANK[cli_tier] > _RANK[canonical]:
        return TierDecision(declared, cli_tier, canonical, REASON_CONFLICT)
    return TierDecision(declared, cli_tier, cli_tier, REASON_CLI_OVERRIDE)


def invalid(decision: TierDecision) -> bool:
    return decision.reason == REASON_INVALID


def conflict(decision: TierDecision) -> bool:
    return decision.reason == REASON_CONFLICT


def _entry_view(config: Mapping) -> Any:
    entry = config.get("entry")
    if "entry" in config and entry is None:
        raise ValueError("entry must be a mapping when present")
    if entry is None:
        return {}
    if not isinstance(entry, Mapping):
        raise ValueError("entry must be a mapping")
    return entry
