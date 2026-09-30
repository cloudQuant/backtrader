"""IB Web T03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'T03'
CASE_SPEC = CaseSpec(
    action='cancel_order',
    event='order_cancelled',
    risk=Risk.WRITE,
    required=('remote_id', 'symbol', 'order_snapshot_id'),
    optional=(),
)
PROOF_FIELDS = ('order_id', 'accepted', 'terminal_status', 'cancel_request_id')
