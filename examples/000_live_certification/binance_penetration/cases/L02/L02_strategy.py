"""Binance L02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'L02'
CASE_SPEC = CaseSpec(
    action='inspect_system_log',
    event='system_log_correlated',
    risk=Risk.READ,
    required=('source_session_id', 'evidence_window_id'),
    optional=(),
)
PROOF_FIELDS = ('connection_session_id', 'readiness_session_id', 'connection_log_id', 'readiness_log_id')
