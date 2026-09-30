"""MT5 V02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'V02'
CASE_SPEC = CaseSpec(
    action='inspect_validation',
    event='invalid_price_tick_rejected',
    risk=Risk.READ,
    required=('source_request_id', 'evidence_window_id', 'rule_ref'),
    optional=(),
)
PROOF_FIELDS = ('source_request_id', 'validation_type', 'validation_rule', 'rule_snapshot_id', 'rejection_code', 'dispatch_absent')
