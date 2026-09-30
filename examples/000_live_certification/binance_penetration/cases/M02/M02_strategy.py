"""Binance M02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'M02'
CASE_SPEC = CaseSpec(
    action='inspect_monitor_disconnect',
    event='monitor_disconnected',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'operator_ref', 'authorization_ref', 'source_session_id'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'operator_ref', 'external_authorization_id', 'old_session_id', 'disconnect_event_id', 'disconnect_generation', 'native_disconnect')
