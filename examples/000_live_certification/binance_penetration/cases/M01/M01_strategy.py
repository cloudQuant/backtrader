"""Binance M01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'M01'
CASE_SPEC = CaseSpec(
    action='inspect_monitor_connect',
    event='monitor_ready',
    risk=Risk.READ,
    required=('source_session_id', 'evidence_window_id'),
    optional=(),
)
PROOF_FIELDS = ('connection_session_id', 'readiness_session_id', 'connection_event_id', 'readiness_event_id')
