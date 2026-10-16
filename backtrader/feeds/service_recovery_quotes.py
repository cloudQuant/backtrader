#!/usr/bin/env python
"""Trusted quote-to-bar binding for managed-paper recovery V2 feeds.

The managed-paper V2 consumer never derives a quote revision from a bar
index, a timestamp, a fill, or a recovery receipt.  The Broker asks the feed
itself through ``service_execution_recovery_quote_binding()`` for the exact
quote revision that was in force for the *current* decision bar.

This module implements that contract as a feed mixin plus the fail-closed
admission rules around it:

* A trusted quote observation may only enter the feed through
  :meth:`ServiceRecoveryQuoteBindingMixin.note_service_recovery_quote` (an
  explicit caller/stream assertion) or through the raw tick stream this
  feed itself ingested.  Nothing here reads a recovery journal, receipt or
  fill to reconstruct an expected value.
* Each delivered bar freezes the quote observation that was current at the
  moment the bar became visible.  The frozen record is keyed by the bar
  index and the exact bar datetime, so a binding can never silently float
  to a later bar.
* :meth:`ServiceRecoveryQuoteBindingMixin.service_execution_recovery_quote_binding`
  returns the frozen observation only while it matches the currently
  visible bar.  Every other situation raises
  :class:`ServiceRecoveryQuoteBindingError`, which makes the Broker fence
  the intent instead of admitting it against an invented revision.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

__all__ = [
    "ServiceRecoveryQuoteBindingError",
    "ServiceRecoveryQuoteBindingMixin",
]


class ServiceRecoveryQuoteBindingError(ValueError):
    """The feed cannot prove a trusted quote revision for the current bar."""


class ServiceRecoveryQuoteBindingMixin:
    """Track and expose the trusted quote-to-bar correspondence of one feed.

    Subclasses deliver bars through a line series (``len(self)`` and
    ``self.datetime[0]`` must reflect the delivered bar) and call
    :meth:`_record_service_recovery_quote_bar` once per delivered bar.
    """

    _SERVICE_RECOVERY_QUOTE_FIELDS: Tuple[str, ...] = (
        "source_ref",
        "generation",
        "cursor",
        "instrument",
        "as_of_ns",
    )

    # -- trusted ingestion --------------------------------------------------

    @classmethod
    def _service_recovery_quote_normalized(
        cls,
        *,
        source_ref: Any,
        generation: Any,
        cursor: Any,
        instrument: Any,
        as_of_ns: Any,
    ) -> Optional[Dict[str, Any]]:
        """Validate one raw observation; return None when it is not usable."""

        if (
            type(source_ref) is not str
            or not source_ref
            or type(generation) is not str
            or not generation
            or type(instrument) is not str
            or not instrument
            or type(cursor) is not int
            or isinstance(cursor, bool)
            or cursor < 0
            or type(as_of_ns) is not int
            or isinstance(as_of_ns, bool)
            or as_of_ns <= 0
        ):
            return None
        return {
            "source_ref": source_ref,
            "generation": generation,
            "cursor": cursor,
            "instrument": instrument,
            "as_of_ns": as_of_ns,
        }

    def _service_recovery_quote_state(self) -> Dict[str, Any]:
        state = getattr(self, "_service_recovery_quote_binding_state", None)
        if state is None:
            state = {
                "latest": None,
                "bar_record": None,
                "streams": {},
            }
            self._service_recovery_quote_binding_state = state
        return state

    def note_service_recovery_quote(
        self,
        *,
        source_ref: Any,
        generation: Any,
        cursor: Any,
        instrument: Any,
        as_of_ns: Any,
    ) -> Dict[str, Any]:
        """Note one trusted quote observation from the feed's own source.

        The observation must be strictly newer than every previous note on
        the same ``(source_ref, generation, instrument)`` stream: the cursor
        must advance and the as-of time must not move backwards.  A caller
        asserting a stale, duplicated or malformed revision is a contract
        violation and raises instead of degrading the binding.
        """

        normalized = self._service_recovery_quote_normalized(
            source_ref=source_ref,
            generation=generation,
            cursor=cursor,
            instrument=instrument,
            as_of_ns=as_of_ns,
        )
        if normalized is None:
            raise ServiceRecoveryQuoteBindingError(
                "trusted recovery quote observation is invalid"
            )
        state = self._service_recovery_quote_state()
        stream_key = (source_ref, generation, instrument)
        previous = state["streams"].get(stream_key)
        if previous is not None and (
            cursor <= previous[0] or as_of_ns < previous[1]
        ):
            raise ServiceRecoveryQuoteBindingError(
                "trusted recovery quote observation is not strictly newer"
            )
        state["streams"][stream_key] = (cursor, as_of_ns)
        state["latest"] = normalized
        return dict(normalized)

    def try_note_service_recovery_quote(
        self,
        *,
        source_ref: Any,
        generation: Any,
        cursor: Any,
        instrument: Any,
        as_of_ns: Any,
    ) -> bool:
        """Ingest one raw-stream observation, skipping anything unusable.

        This is the feed-internal entry point for its own tick stream.  A
        malformed, stale or duplicated observation is dropped instead of
        entering the trusted state; the per-bar read then fails closed if no
        usable observation covered the bar.
        """

        normalized = self._service_recovery_quote_normalized(
            source_ref=source_ref,
            generation=generation,
            cursor=cursor,
            instrument=instrument,
            as_of_ns=as_of_ns,
        )
        if normalized is None:
            return False
        state = self._service_recovery_quote_state()
        stream_key = (source_ref, generation, instrument)
        previous = state["streams"].get(stream_key)
        if previous is not None and (
            cursor <= previous[0] or as_of_ns < previous[1]
        ):
            return False
        state["streams"][stream_key] = (cursor, as_of_ns)
        state["latest"] = normalized
        return True

    # -- per-bar freezing ---------------------------------------------------

    def _record_service_recovery_quote_bar(
        self, *, bar_index: int, datetime_hex: str
    ) -> None:
        """Freeze the current trusted quote onto one delivered bar.

        Called by the feed immediately after a bar becomes visible.  Only the
        most recent bar record is retained: recovery admission always reads
        the binding of the feed's current bar, and older records are dead
        weight in a live process.
        """

        if type(bar_index) is not int or bar_index < 1:
            raise ServiceRecoveryQuoteBindingError(
                "recovery quote binding bar index is invalid"
            )
        if type(datetime_hex) is not str or not datetime_hex:
            raise ServiceRecoveryQuoteBindingError(
                "recovery quote binding bar datetime is invalid"
            )
        state = self._service_recovery_quote_state()
        latest = state["latest"]
        state["bar_record"] = {
            "bar_index": bar_index,
            "datetime_hex": datetime_hex,
            "binding": None if latest is None else dict(latest),
        }

    def service_execution_recovery_quote_binding(self) -> Mapping[str, Any]:
        """Return the trusted quote revision frozen for the current bar.

        The reader is only answerable for the bar the feed is currently
        showing.  A missing quote, a bar whose delivery was never recorded,
        or a record that belongs to a different bar all raise so the caller
        can fail closed.
        """

        state = getattr(self, "_service_recovery_quote_binding_state", None)
        record = state.get("bar_record") if isinstance(state, dict) else None
        if not isinstance(record, dict) or record.get("binding") is None:
            raise ServiceRecoveryQuoteBindingError(
                "recovery feed observed no trusted quote for the current bar"
            )
        try:
            bar_index = len(self)
            datetime_value = float(self.datetime[0])
        except (AttributeError, IndexError, TypeError, ValueError) as error:
            raise ServiceRecoveryQuoteBindingError(
                "recovery feed has no visible decision bar"
            ) from error
        if (
            type(bar_index) is not int
            or bar_index < 1
            or record.get("bar_index") != bar_index
            or record.get("datetime_hex") != datetime_value.hex()
        ):
            raise ServiceRecoveryQuoteBindingError(
                "recovery feed quote binding does not match the current bar"
            )
        return dict(record["binding"])
