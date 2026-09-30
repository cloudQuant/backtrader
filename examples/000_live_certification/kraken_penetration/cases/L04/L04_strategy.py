"""Kraken L04 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'L04'
CASE_SPEC = CaseSpec(
    action='inspect_validation_log',
    event='validation_rejected',
    risk=Risk.READ,
    required=('source_request_id', 'evidence_window_id', 'rule_ref'),
    optional=(),
)
PROOF_FIELDS = ('source_request_id', 'validation_rule', 'rejection_code', 'dispatch_absent')
