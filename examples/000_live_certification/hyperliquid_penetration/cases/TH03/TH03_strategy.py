"""Hyperliquid TH03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'TH03'
CASE_SPEC = CaseSpec(
    action='inspect_combined_threshold',
    event='combined_threshold_observed',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'expected_threshold', 'config_snapshot_id'),
    optional=(),
)
PROOF_FIELDS = ('threshold_value', 'config_snapshot_id')
