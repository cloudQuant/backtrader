"""Bybit V03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'V03'
CASE_SPEC = CaseSpec(
    action='inspect_validation',
    event='oversized_order_rejected',
    risk=Risk.READ,
    required=('source_request_id', 'evidence_window_id', 'rule_ref'),
    optional=(),
)
PROOF_FIELDS = ('source_request_id', 'validation_type', 'validation_rule', 'rule_snapshot_id', 'rejection_code', 'dispatch_absent')
