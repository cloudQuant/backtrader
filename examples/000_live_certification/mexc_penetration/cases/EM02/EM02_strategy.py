"""MEXC EM02 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'EM02'
CASE_SPEC = CaseSpec(
    action='inspect_strategy_pause',
    event='strategy_paused',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'operator_ref', 'authorization_ref', 'strategy_ref'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'operator_ref', 'external_authorization_id', 'strategy_id', 'pause_state', 'write_guard_active')
