"""Bitget E01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'E01'
CASE_SPEC = CaseSpec(
    action='inspect_rejection',
    event='provider_rejection',
    risk=Risk.READ,
    required=('source_request_id', 'evidence_window_id', 'reason_code'),
    optional=(),
)
PROOF_FIELDS = ('source_request_id', 'rejection_code', 'rejection_category', 'provider_reason', 'classification_rule_id')
