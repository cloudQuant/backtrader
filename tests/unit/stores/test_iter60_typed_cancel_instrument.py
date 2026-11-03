"""Iteration 60 R2-B: the BT service adapter names the typed cancel instrument.

Typed ``orders.cancel`` commands carry the order's ``MarketInstrumentKey``.
Under a multi-instrument command binding the SDK client must be told which
instrument the cancelled order belongs to; the adapter forwards the order's
``managed_instrument`` so the cancel also works after a process restart. UNIT:
the SDK workflow is replaced by a recorder; no service, provider or network.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_py.service_execution_workflow")

from bt_api_py.service_execution_workflow import (  # noqa: E402
    ServiceExecutionCancelRequestV1,
    ServiceExecutionOutcomeV1,
)

from backtrader.service.service_execution_adapter import ServiceExecutionAdapter  # noqa: E402


class _RecordingWorkflow:
    def __init__(self) -> None:
        self.requests: list[ServiceExecutionCancelRequestV1] = []

    def cancel(self, request):
        self.requests.append(request)
        return ServiceExecutionOutcomeV1("cancel", "UNKNOWN", "REQUEST", code="RECORDED")


def _adapter() -> tuple[ServiceExecutionAdapter, _RecordingWorkflow]:
    adapter = object.__new__(ServiceExecutionAdapter)
    workflow = _RecordingWorkflow()
    adapter._workflow = workflow
    adapter._workflow_cancel_request_type = ServiceExecutionCancelRequestV1
    adapter._workflow_outcome_type = ServiceExecutionOutcomeV1
    adapter._metadata_version = "metadata-v1"
    adapter._recovery_flow = None
    return adapter, workflow


def _order(**info):
    base = {
        "managed_intent_id": "intent-1",
        "external_order_id": "provider-intent-1",
        "managed_metadata_version": "metadata-v1",
    }
    base.update(info)
    return SimpleNamespace(info=base)


def test_cancel_forwards_the_managed_instrument_to_the_typed_cancel():
    adapter, workflow = _adapter()
    adapter.cancel_order(_order(managed_instrument="ETH-USDT"), "ETH-USDT", None)
    (request,) = workflow.requests
    assert request.instrument == "ETH-USDT"
    assert request.target_intent_id == "intent-1"
    assert request.cancel_id == "cancel.intent-1"


def test_cancel_without_a_valid_managed_instrument_leaves_it_to_the_client():
    adapter, workflow = _adapter()
    adapter.cancel_order(_order(), "BTC-USDT", None)
    adapter.cancel_order(_order(managed_instrument=" bad id "), "BTC-USDT", None)
    assert [request.instrument for request in workflow.requests] == [None, None]
