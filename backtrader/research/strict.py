"""Small runtime helpers for the opt-in factor strict-computation policy.

This module deliberately has no import-time dependency on the Backtrader core.
Core modules load it only while a factor context is attached to the current
line-iterator tree.
"""

import math
from contextvars import ContextVar
from collections.abc import Mapping
from contextlib import contextmanager
from numbers import Integral
from typing import NoReturn


_ACTIVE_LIVE_SOURCE_BINDINGS = ContextVar("bt_live_factor_source_bindings", default=None)


class _LiveSourceBindingScope:
    """Temporary, identity-checked source evidence for one factor bind call."""

    __slots__ = ("cohort", "bindings")

    def __init__(self, cohort, bindings):
        from .live_cohort import LiveBarCohort, LiveInputBinding

        if type(cohort) is not LiveBarCohort:
            raise TypeError("live factor binding requires a LiveBarCohort")
        if not isinstance(bindings, (tuple, list)):
            raise TypeError("live factor source bindings must be a sequence")

        indexed = {}
        for item in bindings:
            if not isinstance(item, (tuple, list)) or len(item) != 3:
                raise TypeError("live factor source binding entries must be triples")
            feed, line_name, receipt = item
            if not isinstance(line_name, str) or not line_name:
                raise TypeError("live factor source line names must be non-empty strings")
            if type(receipt) is not LiveInputBinding:
                raise TypeError("live factor source evidence must be a cohort-issued binding")
            if (
                receipt.feed_ref is not feed
                or receipt.line_name != line_name
                or not cohort.owns_factor_binding(receipt)
            ):
                raise ValueError("live factor source evidence does not match its cohort feed")
            member = cohort.member_for_feed(feed)
            if member is None or member.feed_ref is not feed:
                raise ValueError("live factor source feed is not an exact cohort member")
            key = (id(feed), line_name)
            prior = indexed.get(key)
            if prior is not None and (prior[0] is not feed or prior[1] is not receipt):
                raise ValueError("live factor source bindings contain conflicting receipts")
            indexed[key] = (feed, receipt)

        self.cohort = cohort
        self.bindings = indexed

    def validate(self, context, feed, line_name, phase):
        from ..errors import ResearchConfigError

        entry = self.bindings.get((id(feed), line_name))
        if entry is None or entry[0] is not feed:
            _raise_unsupported_source(
                context, feed, line_name, phase, "live_field_not_bound"
            )
        receipt = entry[1]
        if (
            not self.cohort.owns_factor_binding(receipt)
            or receipt.feed_ref is not feed
            or receipt.line_name != line_name
        ):
            raise ResearchConfigError(
                "live factor source evidence is no longer owned by its cohort",
                code="UNSUPPORTED_SOURCE",
                report={
                    "factor": getattr(context, "factor", None),
                    "phase": phase,
                    "field": line_name,
                    "reason": "live_binding_ownership_changed",
                    "feed_type": type(feed).__name__,
                },
            )


@contextmanager
def live_source_binding_scope(cohort, bindings):
    """Temporarily authorize strict binds with exact cohort-issued field receipts.

    This is deliberately separate from the tabular source path. A caller cannot
    assert that data was validated: every token is checked against the exact
    cohort and feed object before the factor graph is built.
    """
    scope = _LiveSourceBindingScope(cohort, bindings)
    token = _ACTIVE_LIVE_SOURCE_BINDINGS.set(scope)
    try:
        yield scope
    finally:
        _ACTIVE_LIVE_SOURCE_BINDINGS.reset(token)


def live_source_binding_active():
    """Return whether this context is currently binding through a live cohort."""
    return _ACTIVE_LIVE_SOURCE_BINDINGS.get() is not None


def validate_bound_live_feed_source(context, feed, field_name, phase="construct"):
    """Validate one live field against the currently scoped cohort receipt.

    Return ``False`` when no live scope is active so the caller can retain the
    existing strict tabular validation path.
    """
    scope = _ACTIVE_LIVE_SOURCE_BINDINGS.get()
    if scope is None:
        return False
    if context is None or not isinstance(field_name, str) or not field_name:
        _raise_unsupported_source(context, feed, field_name, phase, "live_context_missing")
    scope.validate(context, feed, field_name, phase)
    return True


@contextmanager
def computation_scope(context, phase):
    """Expose *context* to line reads while one strict callback is running."""
    from ..linebuffer import _ACTIVE_FACTOR_CONTEXT

    previous_phase = getattr(context, "phase", None)
    context.phase = phase
    token = _ACTIVE_FACTOR_CONTEXT.set(context)
    try:
        yield
    finally:
        _ACTIVE_FACTOR_CONTEXT.reset(token)
        context.phase = previous_phase


def is_factor_computation_error(error):
    """Recognize the public typed error without importing its module."""
    return getattr(error, "code", None) == "FACTOR_COMPUTATION_FAILED"


def wrap_computation_error(context, error, phase, operation=None):
    """Return a typed computation error while preserving existing typed ones."""
    if is_factor_computation_error(error):
        return error

    asset = None
    if operation is not None:
        candidates = [operation]
        owner = getattr(operation, "_owner", None)
        owner_ref = getattr(owner, "_owner_ref", None) if owner is not None else None
        if owner_ref is not None:
            candidates.append(owner_ref)
        elif owner is not None:
            candidates.append(owner)
        for candidate in candidates:
            try:
                asset = context.asset_for(candidate)
            except (AttributeError, TypeError, ValueError):
                asset = None
            if asset is not None:
                break
    return context.wrap(error, phase=phase, asset=asset)


def fail_computation(context, error, phase, operation=None):
    """Raise a typed strict-computation error with its original cause."""
    wrapped = wrap_computation_error(context, error, phase, operation)
    # FactorStrategy performs success-only completeness checks during stop().
    # Cerebro runs stop after capturing a failed run-loop exception, so
    # sys.exc_info() is empty there; leave an instance-local marker on the
    # factor's shared context so cleanup does not replace the original error.
    try:
        context.failed = True
        context.error = wrapped
    except (AttributeError, TypeError):
        # Older/custom context implementations may expose only the minimum
        # wrapping protocol. They still receive the typed error below.
        pass
    if wrapped is error:
        raise error
    raise wrapped from error


def reject_infinity(context, value, phase, operation=None):
    """Raise for infinite numeric values; explicit NaN remains a valid sentinel."""
    if value is None:
        return value
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return value

    if numeric == float("inf") or numeric == float("-inf"):
        fail_computation(
            context,
            ArithmeticError("non-finite infinity encountered during factor computation"),
            phase,
            operation,
        )
    return value


def validate_bound_feed_source(context, feed, field_name, phase="construct"):
    """Reject source infinities before a native feed can sanitize them.

    ``LineBuffer`` keeps legacy infinity-to-zero behavior for ordinary
    backtests.  Research feeds must retain an inspectable tabular input on
    ``feed.p.dataname``; inspect the actual source column selected by the
    feed's line mapping before the bound factor is constructed.  A source
    whose raw field cannot be inspected is rejected because preload may erase
    infinity evidence.  Explicit NaNs remain valid missing-value sentinels.
    """
    if context is None or not isinstance(field_name, str) or not field_name:
        return

    live_source_bound = validate_bound_live_feed_source(context, feed, field_name, phase)

    params = getattr(feed, "p", None)
    source = getattr(params, "dataname", None)
    columns = getattr(source, "columns", None)
    mapping = getattr(feed, "_colmapping", None)
    if source is None or columns is None:
        if live_source_bound:
            # Streaming sources have no retained table to scan. The exact live
            # scope proves the feed/field schema; the cohort's per-bar capture
            # path must validate and seal each raw event before it is written.
            return
        _raise_unsupported_source(context, feed, field_name, phase, "raw_table_unavailable")
    if not isinstance(mapping, Mapping):
        _raise_unsupported_source(context, feed, field_name, phase, "feed_line_mapping_unavailable")

    if field_name not in mapping:
        _raise_unsupported_source(context, feed, field_name, phase, "feed_line_unmapped")

    column = mapping[field_name]
    positional_column = None
    if column is None:
        _raise_unsupported_source(context, feed, field_name, phase, "feed_line_unmapped")

    if isinstance(column, bool):
        _raise_unsupported_source(context, feed, field_name, phase, "invalid_column_mapping")
    if isinstance(column, Integral):
        column_index = int(column)
        if column_index < 0 or column_index >= len(columns):
            _raise_unsupported_source(context, feed, field_name, phase, "invalid_column_mapping")
        positional_column = column_index
    elif isinstance(column, str):
        if column not in columns:
            nocase = bool(getattr(params, "nocase", False))
            candidate = column.lower() if nocase else column
            matches = [
                name
                for name in columns
                if (name.lower() if nocase and isinstance(name, str) else name) == candidate
            ]
            if len(matches) != 1:
                _raise_unsupported_source(
                    context, feed, field_name, phase, "source_column_unmapped"
                )
            column = matches[0]
    else:
        _raise_unsupported_source(context, feed, field_name, phase, "invalid_column_mapping")

    try:
        source_iloc = getattr(source, "iloc", None)
        if positional_column is not None and source_iloc is not None:
            values = source_iloc[:, positional_column]
        else:
            selected_column = (
                columns[positional_column] if positional_column is not None else column
            )
            values = source[selected_column]
    except (AttributeError, KeyError, IndexError, TypeError):
        _raise_unsupported_source(context, feed, field_name, phase, "source_column_unmapped")

    to_numpy = getattr(values, "to_numpy", None)
    if callable(to_numpy):
        try:
            values = to_numpy()
        except (TypeError, ValueError):
            _raise_unsupported_source(context, feed, field_name, phase, "raw_values_unavailable")
    if getattr(values, "ndim", 1) != 1:
        _raise_unsupported_source(
            context, feed, field_name, phase, "raw_values_not_one_dimensional"
        )

    try:
        iterator = iter(values)
    except TypeError:
        iterator = (values,)

    for value in iterator:
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isinf(numeric):
            from .operators import OperatorInputError

            fail_computation(
                context,
                OperatorInputError("source line contains infinity"),
                phase,
                operation=feed,
            )


def _raise_unsupported_source(context, feed, field_name, phase, reason) -> NoReturn:
    """Reject strict factor inputs whose pre-sanitized source is unavailable."""
    from ..errors import ResearchConfigError

    asset = None
    try:
        asset = context.asset_for(feed)
    except (AttributeError, TypeError, ValueError):
        pass
    raise ResearchConfigError(
        "strict research requires an inspectable tabular source for bound feed fields",
        code="UNSUPPORTED_SOURCE",
        report={
            "factor": getattr(context, "factor", None),
            "asset": asset,
            "phase": phase,
            "field": field_name,
            "reason": reason,
            "feed_type": type(feed).__name__,
        },
    )
