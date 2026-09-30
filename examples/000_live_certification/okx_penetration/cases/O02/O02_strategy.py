"""OKX O02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'O02'
CASE_SPEC = CaseSpec(
    action='repeated_close',
    event='repeated_close_observed',
    risk=Risk.DANGEROUS,
    required=('symbol', 'side', 'quantity', 'price', 'repeat_count', 'position_id', 'position_snapshot_id'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('order_ids', 'request_ids', 'position_id', 'repetition_count', 'monitor_event_id', 'terminal_order_ids')
