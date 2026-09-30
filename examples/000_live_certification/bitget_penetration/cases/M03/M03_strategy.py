"""Bitget M03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'M03'
CASE_SPEC = CaseSpec(
    action='inspect_monitor_recovery',
    event='monitor_recovered',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'operator_ref', 'authorization_ref', 'source_session_id', 'new_session_id'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'operator_ref', 'external_authorization_id', 'old_session_id', 'new_session_id', 'disconnect_event_id', 'recovery_event_id', 'disconnect_generation', 'recovery_generation', 'native_disconnect', 'auth_success', 'login_success', 'subscription_restored')
