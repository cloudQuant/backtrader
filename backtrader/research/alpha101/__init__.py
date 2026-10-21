"""Native Alpha101 formula registry.

Only individually promoted and accepted formulas belong in this registry.
Formula IDs identify Appendix A equations; each class carries a separate
implementation identity for its native code revision.
"""

from types import MappingProxyType
from typing import Mapping, Tuple, Type

from ..factor_indicator import FactorIndicator
from .promoted import (
    Alpha003Native,
    Alpha009Native,
    FormulaIdentity,
    ImplementationIdentity,
)


ALPHA_REGISTRY: Mapping[int, Type[FactorIndicator]] = MappingProxyType(
    {
        3: Alpha003Native,
        9: Alpha009Native,
    }
)


def get_alpha(alpha_id: int) -> Type[FactorIndicator]:
    """Return the promoted native class for an exact, non-bool Alpha ID."""

    if type(alpha_id) is not int:
        raise TypeError("alpha_id must be an integer Alpha101 ID; bool is not accepted")
    try:
        return ALPHA_REGISTRY[alpha_id]
    except KeyError:
        raise KeyError("Alpha%d is not registered as a native formula" % alpha_id) from None


def list_alphas() -> Tuple[int, ...]:
    """Return the registered native formula IDs in ascending order."""

    return tuple(ALPHA_REGISTRY)


__all__ = (
    "ALPHA_REGISTRY",
    "Alpha003Native",
    "Alpha009Native",
    "FormulaIdentity",
    "ImplementationIdentity",
    "get_alpha",
    "list_alphas",
)
