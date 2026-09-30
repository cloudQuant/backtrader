"""Bybit T02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'T02'
CASE_SPEC = CaseSpec(
    action='close_position',
    event='close_observed',
    risk=Risk.WRITE,
    required=('symbol', 'side', 'quantity', 'price', 'position_id', 'position_snapshot_id'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('position_id', 'close_order_id', 'accepted', 'closed_quantity', 'terminal_status')
