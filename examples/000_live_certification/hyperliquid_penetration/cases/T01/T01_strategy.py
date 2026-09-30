"""Hyperliquid T01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'T01'
CASE_SPEC = CaseSpec(
    action='open_order',
    event='order_accepted',
    risk=Risk.WRITE,
    required=('symbol', 'side', 'quantity', 'price'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('order_id', 'accepted', 'terminal_status', 'cancel_request_id')
