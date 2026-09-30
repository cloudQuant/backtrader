"""dYdX B01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'B01'
CASE_SPEC = CaseSpec(
    action='batch_cancel_partial',
    event='batch_cancelled_partial',
    risk=Risk.DANGEROUS,
    required=('symbol', 'side', 'quantity', 'price', 'order_count'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('orders', 'batch_cancel_id', 'partial_fill_count')
