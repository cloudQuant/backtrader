"""Production promotion of the Iteration 45 Alpha003 and Alpha009 recipes.

Both classes reuse the already exercised explicit Indicator/Lines algorithms.
The formula identity describes the paper expression and its inputs; the
implementation identity describes this package's native code version.
"""

from dataclasses import dataclass
from typing import Tuple

from ..representative import Alpha003 as _RepresentativeAlpha003
from ..representative import Alpha009 as _RepresentativeAlpha009
from ._base import NativeAlphaBase


@dataclass(frozen=True)
class FormulaIdentity:
    """Formula and input contract, independent of its implementation code."""

    alpha_id: int
    expression: str
    lookback_h: int
    operator_profile: str
    formula_fields: Tuple[str, ...]
    classification_levels: Tuple[str, ...]
    formula_universe_policy: str


@dataclass(frozen=True)
class ImplementationIdentity:
    """Stable identity for one native implementation revision."""

    implementation_id: str
    version: str


class Alpha003Native(_RepresentativeAlpha003, NativeAlphaBase):
    """AF46-003: negative ten-grid correlation of open and volume ranks."""

    lines = ("factor",)
    case_id = "AF46-003"
    formula_identity = FormulaIdentity(
        alpha_id=3,
        expression="(-1 * correlation(rank(open), rank(volume), 10))",
        lookback_h=9,
        operator_profile="alpha101-v1",
        formula_fields=("open", "volume"),
        classification_levels=(),
        formula_universe_policy="ResearchSpec.formula_universe grouped by ResearchSpec.groups",
    )
    implementation_id = "native:003:v1"
    implementation_version = "alpha101-native-v1"
    implementation_identity = ImplementationIdentity(
        implementation_id=implementation_id,
        version=implementation_version,
    )


class Alpha009Native(_RepresentativeAlpha009, NativeAlphaBase):
    """AF46-009: five-grid extrema condition over one-grid close changes."""

    lines = ("factor",)
    case_id = "AF46-009"
    formula_identity = FormulaIdentity(
        alpha_id=9,
        expression=(
            "((0 < ts_min(delta(close, 1), 5)) ? delta(close, 1) : "
            "((ts_max(delta(close, 1), 5) < 0) ? delta(close, 1) : "
            "(-1 * delta(close, 1))))"
        ),
        lookback_h=5,
        operator_profile="alpha101-v1",
        formula_fields=("close",),
        classification_levels=(),
        formula_universe_policy="per-target close history; output eligibility from ResearchSpec.formula_universe",
    )
    implementation_id = "native:009:v1"
    implementation_version = "alpha101-native-v1"
    implementation_identity = ImplementationIdentity(
        implementation_id=implementation_id,
        version=implementation_version,
    )


__all__ = (
    "Alpha003Native",
    "Alpha009Native",
    "FormulaIdentity",
    "ImplementationIdentity",
)
