"""Iteration 62 (62.08): managed order records speak the Broker's order vocabulary.

``ServiceExecutionAdapter`` projects the execution owner's durable order record
into the update the Broker applies. A CANCELLED record used to be projected as
``status="cancelled"``, which the SDK's canonical Broker vocabulary reads as
``"unknown"``; every cancelled managed order therefore became UNKNOWN instead of
Canceled. UNIT.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.broker_event_envelope")

from bt_api_py.broker_event_envelope import canonical_broker_order_status  # noqa: E402

from backtrader.service.service_execution_adapter import _submission_projection  # noqa: E402


def _record(state: str) -> SimpleNamespace:
    return SimpleNamespace(
        state=state,
        intent_id="intent-1",
        provider_order_id="provider-intent-1",
        updated_at_ns=1,
        dispatch_attempts=1,
        filled_quantity=None,
        average_price=None,
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("ACKED", "accepted"),
        ("CANCELLED", "canceled"),
        ("REJECTED", "rejected"),
        ("UNKNOWN", "unknown"),
    ],
)
def test_order_record_status_maps_onto_the_canonical_broker_vocabulary(state, expected):
    projection = _submission_projection(_record(state), data_name="BTC-USDT")
    assert canonical_broker_order_status(projection["status"]) == expected


def test_accepted_record_carries_the_provider_order_identity_for_cancels():
    projection = _submission_projection(_record("ACKED"), data_name="BTC-USDT")
    # The Broker binds this id (``_bind_managed_external_order_id``); the
    # adapter's cancel refuses without it.
    assert projection["external_order_id"] == "provider-intent-1"
