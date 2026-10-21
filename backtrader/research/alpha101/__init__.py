"""Native Alpha101 formula registry.

Only individually promoted and accepted formulas belong in this registry.
Formula IDs identify Appendix A equations; each class carries a separate
implementation identity for its native code revision.
"""

from types import MappingProxyType
from typing import Mapping, Tuple, Type

from ..factor_indicator import FactorIndicator
from ._base import (
    DEFAULT_FORMULA_UNIVERSE_POLICY,
    DEFAULT_PIT_POLICY,
    FormulaIdentity,
    ImplementationIdentity,
    NativeAlphaBase,
    native_alpha,
)
from .promoted import (
    Alpha001Native,
    Alpha002Native,
    Alpha003Native,
    Alpha004Native,
    Alpha007Native,
    Alpha009Native,
    Alpha013Native,
    Alpha029Native,
    Alpha048Native,
    Alpha056Native,
    Alpha058Native,
    Alpha062Native,
    Alpha063Native,
    Alpha067Native,
    Alpha081Native,
    Alpha084Native,
    Alpha092Native,
    Alpha096Native,
    Alpha100Native,
    Alpha101Native,
)


ALPHA_REGISTRY: Mapping[int, Type[FactorIndicator]] = MappingProxyType(
    {
        1: Alpha001Native,
        2: Alpha002Native,
        3: Alpha003Native,
        4: Alpha004Native,
        7: Alpha007Native,
        9: Alpha009Native,
        13: Alpha013Native,
        29: Alpha029Native,
        48: Alpha048Native,
        56: Alpha056Native,
        58: Alpha058Native,
        62: Alpha062Native,
        63: Alpha063Native,
        67: Alpha067Native,
        81: Alpha081Native,
        84: Alpha084Native,
        92: Alpha092Native,
        96: Alpha096Native,
        100: Alpha100Native,
        101: Alpha101Native,
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
    "Alpha001Native",
    "Alpha002Native",
    "Alpha003Native",
    "Alpha004Native",
    "Alpha007Native",
    "Alpha009Native",
    "Alpha013Native",
    "Alpha029Native",
    "Alpha048Native",
    "Alpha056Native",
    "Alpha058Native",
    "Alpha062Native",
    "Alpha063Native",
    "Alpha067Native",
    "Alpha081Native",
    "Alpha084Native",
    "Alpha092Native",
    "Alpha096Native",
    "Alpha100Native",
    "Alpha101Native",
    "DEFAULT_FORMULA_UNIVERSE_POLICY",
    "DEFAULT_PIT_POLICY",
    "FormulaIdentity",
    "ImplementationIdentity",
    "NativeAlphaBase",
    "get_alpha",
    "list_alphas",
    "native_alpha",
)
