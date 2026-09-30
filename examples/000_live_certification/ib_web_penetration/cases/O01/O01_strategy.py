"""IB Web O01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'O01'
CASE_SPEC = CaseSpec(
    action='repeated_open',
    event='repeated_open_observed',
    risk=Risk.DANGEROUS,
    required=('symbol', 'side', 'quantity', 'price', 'repeat_count'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('order_ids', 'request_ids', 'repetition_count', 'monitor_event_id', 'terminal_order_ids')
