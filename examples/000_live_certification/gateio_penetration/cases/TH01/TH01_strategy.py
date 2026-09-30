"""Gate.io TH01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'TH01'
CASE_SPEC = CaseSpec(
    action='inspect_submit_threshold',
    event='submit_threshold_observed',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'expected_threshold', 'config_snapshot_id'),
    optional=(),
)
PROOF_FIELDS = ('threshold_value', 'config_snapshot_id')
