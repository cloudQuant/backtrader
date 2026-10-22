"""Metadata identities for native Alpha101 implementations."""

from dataclasses import dataclass
from typing import Tuple, Type, TypeVar, cast

from ..factor_indicator import FactorIndicator

DEFAULT_FORMULA_UNIVERSE_POLICY = (
    "ResearchSpec.formula_universe; cross-sectional steps grouped by ResearchSpec.groups"
)
DEFAULT_PIT_POLICY = (
    "ResearchSpec.close_time; causal prealigned inputs; classification availability enforced"
)
DEFAULT_OPERATOR_PROFILE = "alpha101-v1"
IMPLEMENTATION_VERSION = "alpha101-native-v1"


@dataclass(frozen=True)
class FormulaIdentity:
    """Immutable identity for the equation and its declared data contract."""

    alpha_id: int
    expression: str
    lookback_h: int
    operator_profile: str
    formula_fields: Tuple[str, ...]
    classification_fields: Tuple[str, ...]
    classification_levels: Tuple[str, ...]
    formula_universe_policy: str
    pit_policy: str


@dataclass(frozen=True)
class ImplementationIdentity:
    """Immutable identity for a particular native implementation revision."""

    implementation_id: str
    version: str


_FactorClass = TypeVar("_FactorClass", bound=Type[FactorIndicator])


def _field_tuple(value, label: str) -> Tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise TypeError("%s must be a tuple or list of field names" % label)
    fields = tuple(value)
    if any(not isinstance(field, str) or not field for field in fields):
        raise ValueError("%s must contain non-empty strings" % label)
    return fields


def native_alpha(cls: _FactorClass) -> _FactorClass:
    """Bind immutable formula/implementation metadata to a native factor class."""
    if not isinstance(cls, type):
        raise TypeError("native_alpha decorates a factor class")
    if not issubclass(cls, FactorIndicator):
        raise TypeError("native_alpha classes must inherit FactorIndicator")

    alpha_id = cls.__dict__.get("alpha_id")
    if type(alpha_id) is not int or not 1 <= alpha_id <= 101:
        raise ValueError("native factor must define an exact Alpha101 integer ID")

    expression = getattr(cls, "formula", None)
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("native factor must define a non-empty formula expression")

    lookback_h = getattr(cls, "lookback_h", None)
    if type(lookback_h) is not int or lookback_h < 0:
        raise ValueError("native factor lookback_h must be a non-negative integer")

    profile = getattr(cls, "operator_profile", DEFAULT_OPERATOR_PROFILE)
    if not isinstance(profile, str) or not profile:
        raise ValueError("native factor must define an operator profile")

    formula_fields = _field_tuple(getattr(cls, "formula_fields", None), "formula_fields")
    classification_fields = _field_tuple(
        getattr(cls, "classification_fields", ()), "classification_fields"
    )
    classification_levels = _field_tuple(
        getattr(cls, "classification_levels", ()), "classification_levels"
    )

    formula_universe_policy = getattr(
        cls, "formula_universe_policy", DEFAULT_FORMULA_UNIVERSE_POLICY
    )
    pit_policy = getattr(cls, "pit_policy", DEFAULT_PIT_POLICY)
    if not isinstance(formula_universe_policy, str) or not formula_universe_policy:
        raise ValueError("native factor formula_universe_policy must be non-empty")
    if not isinstance(pit_policy, str) or not pit_policy:
        raise ValueError("native factor pit_policy must be non-empty")

    setattr(cls, "operator_profile", profile)
    setattr(cls, "formula_fields", formula_fields)
    setattr(cls, "classification_fields", classification_fields)
    setattr(cls, "classification_levels", classification_levels)
    setattr(cls, "formula_universe_policy", formula_universe_policy)
    setattr(cls, "pit_policy", pit_policy)
    setattr(
        cls,
        "formula_identity",
        FormulaIdentity(
            alpha_id=alpha_id,
            expression=expression,
            lookback_h=lookback_h,
            operator_profile=profile,
            formula_fields=formula_fields,
            classification_fields=classification_fields,
            classification_levels=classification_levels,
            formula_universe_policy=formula_universe_policy,
            pit_policy=pit_policy,
        ),
    )

    implementation_id = "native:%03d:v1" % alpha_id
    setattr(cls, "implementation_id", implementation_id)
    setattr(cls, "implementation_version", IMPLEMENTATION_VERSION)
    setattr(
        cls,
        "implementation_identity",
        ImplementationIdentity(
            implementation_id=implementation_id,
            version=IMPLEMENTATION_VERSION,
        ),
    )
    return cast(_FactorClass, cls)


__all__ = (
    "DEFAULT_FORMULA_UNIVERSE_POLICY",
    "DEFAULT_PIT_POLICY",
    "FormulaIdentity",
    "ImplementationIdentity",
    "native_alpha",
)
