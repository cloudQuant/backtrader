"""Production promotion of the accepted Iteration 45 Alpha101 recipes.

Each native class reuses one reviewed, explicit Indicator/Lines formula tree.
The identities bound by :func:`native_alpha` distinguish the Appendix A
formula contract from the versioned implementation.
"""

from ..representative import Alpha001 as _RepresentativeAlpha001
from ..representative import Alpha002 as _RepresentativeAlpha002
from ..representative import Alpha003 as _RepresentativeAlpha003
from ..representative import Alpha004 as _RepresentativeAlpha004
from ..representative import Alpha007 as _RepresentativeAlpha007
from ..representative import Alpha009 as _RepresentativeAlpha009
from ..representative import Alpha013 as _RepresentativeAlpha013
from ..representative import Alpha029 as _RepresentativeAlpha029
from ..representative import Alpha048 as _RepresentativeAlpha048
from ..representative import Alpha056 as _RepresentativeAlpha056
from ..representative import Alpha058 as _RepresentativeAlpha058
from ..representative import Alpha062 as _RepresentativeAlpha062
from ..representative import Alpha063 as _RepresentativeAlpha063
from ..representative import Alpha067 as _RepresentativeAlpha067
from ..representative import Alpha081 as _RepresentativeAlpha081
from ..representative import Alpha084 as _RepresentativeAlpha084
from ..representative import Alpha092 as _RepresentativeAlpha092
from ..representative import Alpha096 as _RepresentativeAlpha096
from ..representative import Alpha100 as _RepresentativeAlpha100
from ..representative import Alpha101 as _RepresentativeAlpha101
from ._base import FormulaIdentity, ImplementationIdentity, NativeAlphaBase, native_alpha


@native_alpha
class Alpha001Native(_RepresentativeAlpha001, NativeAlphaBase):
    """Native Alpha001 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 1
    case_id = "AF46-001"


@native_alpha
class Alpha002Native(_RepresentativeAlpha002, NativeAlphaBase):
    """Native Alpha002 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 2
    case_id = "AF46-002"


@native_alpha
class Alpha003Native(_RepresentativeAlpha003, NativeAlphaBase):
    """Native Alpha003 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 3
    case_id = "AF46-003"


@native_alpha
class Alpha004Native(_RepresentativeAlpha004, NativeAlphaBase):
    """Native Alpha004 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 4
    case_id = "AF46-004"


@native_alpha
class Alpha007Native(_RepresentativeAlpha007, NativeAlphaBase):
    """Native Alpha007 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 7
    case_id = "AF46-007"


@native_alpha
class Alpha009Native(_RepresentativeAlpha009, NativeAlphaBase):
    """Native Alpha009 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 9
    case_id = "AF46-009"
    formula_universe_policy = (
        "per-target close history; output eligibility from ResearchSpec.formula_universe"
    )


@native_alpha
class Alpha013Native(_RepresentativeAlpha013, NativeAlphaBase):
    """Native Alpha013 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 13
    case_id = "AF46-013"


@native_alpha
class Alpha029Native(_RepresentativeAlpha029, NativeAlphaBase):
    """Native Alpha029 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 29
    case_id = "AF46-029"


@native_alpha
class Alpha048Native(_RepresentativeAlpha048, NativeAlphaBase):
    """Native Alpha048 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 48
    case_id = "AF46-048"


@native_alpha
class Alpha056Native(_RepresentativeAlpha056, NativeAlphaBase):
    """Native Alpha056 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 56
    case_id = "AF46-056"


@native_alpha
class Alpha058Native(_RepresentativeAlpha058, NativeAlphaBase):
    """Native Alpha058 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 58
    case_id = "AF46-058"


@native_alpha
class Alpha062Native(_RepresentativeAlpha062, NativeAlphaBase):
    """Native Alpha062 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 62
    case_id = "AF46-062"


@native_alpha
class Alpha063Native(_RepresentativeAlpha063, NativeAlphaBase):
    """Native Alpha063 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 63
    case_id = "AF46-063"


@native_alpha
class Alpha067Native(_RepresentativeAlpha067, NativeAlphaBase):
    """Native Alpha067 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 67
    case_id = "AF46-067"


@native_alpha
class Alpha081Native(_RepresentativeAlpha081, NativeAlphaBase):
    """Native Alpha081 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 81
    case_id = "AF46-081"


@native_alpha
class Alpha084Native(_RepresentativeAlpha084, NativeAlphaBase):
    """Native Alpha084 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 84
    case_id = "AF46-084"


@native_alpha
class Alpha092Native(_RepresentativeAlpha092, NativeAlphaBase):
    """Native Alpha092 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 92
    case_id = "AF46-092"


@native_alpha
class Alpha096Native(_RepresentativeAlpha096, NativeAlphaBase):
    """Native Alpha096 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 96
    case_id = "AF46-096"


@native_alpha
class Alpha100Native(_RepresentativeAlpha100, NativeAlphaBase):
    """Native Alpha100 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 100
    case_id = "AF46-100"


@native_alpha
class Alpha101Native(_RepresentativeAlpha101, NativeAlphaBase):
    """Native Alpha101 using the accepted Iteration 45 formula tree."""

    lines = ("factor",)
    alpha_id = 101
    case_id = "AF46-101"
    formula_universe_policy = (
        "per-target pointwise evaluation; output eligibility from ResearchSpec.formula_universe"
    )


__all__ = (
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
    "FormulaIdentity",
    "ImplementationIdentity",
)
