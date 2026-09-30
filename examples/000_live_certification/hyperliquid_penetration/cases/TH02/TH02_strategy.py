"""Hyperliquid TH02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'TH02'
CASE_SPEC = CaseSpec(
    action='probe_submit_threshold',
    event='submit_threshold_triggered',
    risk=Risk.DANGEROUS,
    required=('symbol', 'side', 'quantity', 'price', 'repeat_count', 'expected_threshold', 'config_snapshot_id', 'baseline_count'),
    optional=('order_type', 'reduce_only'),
)
PROOF_FIELDS = ('threshold_value', 'config_snapshot_id', 'baseline_count', 'observed_count', 'warning_id', 'warning_count', 'request_ids')
