"""Coinbase O03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'O03'
CASE_SPEC = CaseSpec(
    action='repeated_cancel',
    event='repeated_cancel_observed',
    risk=Risk.DANGEROUS,
    required=('remote_id', 'symbol', 'order_snapshot_id', 'repeat_count'),
    optional=(),
)
PROOF_FIELDS = ('order_id', 'request_ids', 'cancel_attempt_count', 'monitor_event_id', 'terminal_status')
