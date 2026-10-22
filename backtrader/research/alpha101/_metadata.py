"""Declaration validation for native Alpha101 implementations."""

from typing import Tuple, Type, TypeVar

from ..factor_indicator import FactorIndicator

DEFAULT_INPUT_POLICY = (
    "aligned ordinary feed lines; cross-sectional membership follows real bars; "
    "ResearchSpec.groups partition grouped operators"
)
DEFAULT_OPERATOR_PROFILE = "alpha101-v2"


_FactorClass = TypeVar("_FactorClass", bound=Type[FactorIndicator])


def _field_tuple(value, label: str) -> Tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (tuple, list)):
        raise TypeError("%s must be a tuple or list of field names" % label)
    fields = tuple(value)
    if any(not isinstance(field, str) or not field for field in fields):
        raise ValueError("%s must contain non-empty strings" % label)
    return fields


def native_alpha(cls: _FactorClass) -> _FactorClass:
    """Validate and canonicalize metadata declared on a native factor class."""
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

    input_policy = getattr(cls, "input_policy", DEFAULT_INPUT_POLICY)
    if not isinstance(input_policy, str) or not input_policy:
        raise ValueError("native factor input_policy must be non-empty")

    setattr(cls, "operator_profile", profile)
    setattr(cls, "formula_fields", formula_fields)
    setattr(cls, "input_policy", input_policy)
    return cls


__all__ = (
    "DEFAULT_INPUT_POLICY",
    "DEFAULT_OPERATOR_PROFILE",
    "native_alpha",
)
