"""MT5 M05 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'M05'
CASE_SPEC = CaseSpec(
    action='monitor_cancel',
    event='monitor_cancelled',
    risk=Risk.WRITE,
    required=('symbol', 'side', 'quantity', 'price'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('order_id', 'submit_monitor_id', 'cancel_monitor_id', 'submit_count', 'cancel_count', 'provider_order_status')
