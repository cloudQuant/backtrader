"""MT5 C01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'C01'
CASE_SPEC = CaseSpec(
    action='inspect_authentication',
    event='authenticated',
    risk=Risk.READ,
    required=('source_session_id', 'evidence_window_id'),
    optional=(),
)
PROOF_FIELDS = ('account_id', 'auth_session_id', 'login_session_id', 'authenticated')
