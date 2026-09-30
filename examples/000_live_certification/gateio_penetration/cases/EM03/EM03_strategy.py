"""Gate.io EM03 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'EM03'
CASE_SPEC = CaseSpec(
    action='inspect_logout',
    event='disconnected',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'operator_ref', 'authorization_ref', 'source_session_id'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'operator_ref', 'external_authorization_id', 'session_id', 'disconnect_state', 'release_event_id', 'write_guard_active')
