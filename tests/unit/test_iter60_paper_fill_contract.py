"""Backtrader validates managed paper fills against the single Base contract.

Iteration 60 (60.06): the ``managed_paper_fill.v2`` field set is owned by
``bt_api_base.paper_fill_protocol``; Backtrader no longer keeps its own copy.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

paper_fill_protocol = pytest.importorskip("bt_api_base.paper_fill_protocol")

from backtrader.strategy import Strategy  # noqa: E402

FIELDS = paper_fill_protocol.MANAGED_PAPER_FILL_V2_FIELDS
_HEX = "a" * 64


def _fill(**overrides):
    fill = {name: "x" for name in FIELDS}
    fill.update(
        schema="managed_paper_fill.v2",
        time_source="MANAGED_PAPER_MATCH",
        commission_model_id="quote_notional_rate",
        commission_model_version="1",
        match_time_ns=1,
        event_sequence=1,
        quote_cursor=0,
        journal_generation="g",
        event_id="e",
        fill_id="paper:g:e",
        intent_fingerprint=_HEX,
        receipt_sha256=_HEX,
        account_ref="acct",
        strategy_ref="strategy-a",
        intent_id="intent-1",
    )
    fill.update(overrides)
    return fill


def _call(fill):
    owner = SimpleNamespace(
        broker=SimpleNamespace(bind_service_execution_recovery_strategy=lambda strategy: None)
    )
    projection = {
        "status": "READY",
        "reason": None,
        "fill": fill,
        "intent_context": {},
        "event_context": {},
    }
    order = SimpleNamespace(info={})
    return Strategy._service_execution_recovery_v2_trade(owner, order, "receipt-1", projection)


def test_extra_field_is_rejected_by_the_shared_contract():
    with pytest.raises(ValueError, match="source binding"):
        _call(_fill(unexpected="x"))


def test_exact_shared_field_set_passes_the_shape_check():
    # Passes the fill contract and fails later on the (empty) order state.
    with pytest.raises(ValueError, match="order state"):
        _call(_fill())


def test_missing_contract_fails_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "bt_api_base.paper_fill_protocol", None)
    with pytest.raises(ValueError, match="contract is unavailable"):
        _call(_fill())
