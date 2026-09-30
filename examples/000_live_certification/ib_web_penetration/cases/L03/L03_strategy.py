"""IB Web L03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'L03'
CASE_SPEC = CaseSpec(
    action='inspect_monitor_log',
    event='monitor_log_correlated',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'trace_ref'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'trace_id', 'metric', 'digest', 'normalized_record')
