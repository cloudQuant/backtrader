"""Unregistered typed port contract for offline SimNow settlement pairing.

This module does not import the CTP SDK and never submits native requests.
It describes the missing high-level adapter seam and verifies supplied result
shapes only. A future SDK adapter must provide independent request results for
``ReqQrySettlementInfo`` and ``ReqQrySettlementInfoConfirm``; the former row
supplies ``TradingDay``/``SettlementID`` while the latter supplies
``ConfirmDate``/``SettlementID`` and has no native ``TradingDay`` field.
Results must be refreshed by request ID after native close so late callbacks
are included before the pair is considered shape-complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .ctp_simnow_settlement_callback_candidate import (
    CtpSimNowSettlementJoinShapeObservation,
    CtpSimNowSettlementQueryCandidate,
    CtpSimNowSettlementScopeCandidate,
    join_ctp_simnow_settlement_queries_candidate,
)


class CtpSimNowSettlementQueryPortCandidateError(ValueError):
    """Redacted contract failure from the unregistered offline port candidate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CtpSimNowSettlementQueryPortCloseCandidate:
    """Normalized close receipt plus callback-quiescence obligation.

    The native receipt fields match the pinned SDK's ``CtpNativeStopReceipt``
    shape. ``callbacks_quiescent`` additionally says that the adapter waited
    until the callback path could no longer mutate either request result.
    """

    connection_generation: Any
    native_released: Any
    join_required: Any
    join_completed: Any
    thread_alive: Any
    timed_out: Any
    callbacks_quiescent: Any

    @property
    def complete(self) -> bool:
        return bool(
            self.native_released is True
            and self.join_required in (True, False)
            and (self.join_required is False or self.join_completed is True)
            and self.thread_alive is False
            and self.timed_out is False
        )


@dataclass(frozen=True)
class CtpSimNowSettlementQueryPairPortObservationCandidate:
    """Two post-close request snapshots and their same-session close receipt."""

    settlement_info_result: Any
    settlement_confirmation_result: Any
    close_receipt: Any
    results_refreshed_after_close: Any


@dataclass(frozen=True)
class CtpSimNowSettlementQueryPortShapeObservation:
    """Offline completeness only; it carries no trust or readiness authority."""

    joined_query_shape: CtpSimNowSettlementJoinShapeObservation
    close_generation: int
    native_close_complete: bool = True
    callbacks_quiescent: bool = True
    results_refreshed_after_close: bool = True
    provider_source_trusted: bool = False
    settlement_readiness_established: bool = False
    execution_authorized: bool = False


@runtime_checkable
class CtpSimNowSettlementQueryPortAdapterCandidate(Protocol):
    """Expected typed surface for a future SDK adapter; methods are not called here."""

    def query_settlement_info_result(
        self, timeout: float = 5.0
    ) -> CtpSimNowSettlementQueryCandidate:
        """Return the per-request SettlementInfo result and callback provenance."""

    def query_settlement_confirmation_result(
        self, timeout: float = 5.0
    ) -> CtpSimNowSettlementQueryCandidate:
        """Return the per-request SettlementInfoConfirm result and provenance."""

    def get_query_result(self, request_id: int) -> CtpSimNowSettlementQueryCandidate | None:
        """Refresh a request snapshot after close to include late callbacks."""

    def stop_and_wait(self, timeout: float = 2.0) -> CtpSimNowSettlementQueryPortCloseCandidate:
        """Stop, Release, and Join the exact generation; prove callbacks quiescent."""


def _reject(reason: str) -> None:
    raise CtpSimNowSettlementQueryPortCandidateError(reason)


def _validate_close(
    expected_generation: int,
    close_receipt: Any,
) -> CtpSimNowSettlementQueryPortCloseCandidate:
    if type(close_receipt) is not CtpSimNowSettlementQueryPortCloseCandidate:
        _reject("settlement_port_close_receipt_type_invalid")
    if (
        type(close_receipt.connection_generation) is not int
        or close_receipt.connection_generation != expected_generation
        or type(close_receipt.native_released) is not bool
        or type(close_receipt.join_required) is not bool
        or type(close_receipt.join_completed) is not bool
        or type(close_receipt.thread_alive) is not bool
        or type(close_receipt.timed_out) is not bool
        or type(close_receipt.callbacks_quiescent) is not bool
        or close_receipt.complete is not True
        or close_receipt.callbacks_quiescent is not True
    ):
        _reject("settlement_port_close_incomplete_or_mismatched")
    return close_receipt


def validate_ctp_simnow_settlement_query_port_candidate(
    port: CtpSimNowSettlementQueryPortAdapterCandidate,
    scope: CtpSimNowSettlementScopeCandidate,
    observation: CtpSimNowSettlementQueryPairPortObservationCandidate,
) -> CtpSimNowSettlementQueryPortShapeObservation:
    """Validate a fakeable typed port snapshot without invoking any port method."""

    if not isinstance(port, CtpSimNowSettlementQueryPortAdapterCandidate):
        _reject("settlement_port_candidate_surface_incomplete")
    if type(observation) is not CtpSimNowSettlementQueryPairPortObservationCandidate:
        _reject("settlement_port_observation_type_invalid")
    if type(observation.results_refreshed_after_close) is not bool or (
        observation.results_refreshed_after_close is not True
    ):
        _reject("settlement_port_results_not_refreshed_after_close")
    joined = join_ctp_simnow_settlement_queries_candidate(
        scope,
        observation.settlement_info_result,
        observation.settlement_confirmation_result,
    )
    close_receipt = _validate_close(joined.connection_generation, observation.close_receipt)
    return CtpSimNowSettlementQueryPortShapeObservation(
        joined_query_shape=joined,
        close_generation=close_receipt.connection_generation,
    )


__all__ = [
    "CtpSimNowSettlementQueryPairPortObservationCandidate",
    "CtpSimNowSettlementQueryPortAdapterCandidate",
    "CtpSimNowSettlementQueryPortCandidateError",
    "CtpSimNowSettlementQueryPortCloseCandidate",
    "CtpSimNowSettlementQueryPortShapeObservation",
    "validate_ctp_simnow_settlement_query_port_candidate",
]
