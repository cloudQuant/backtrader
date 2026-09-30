"""Hyperliquid EM01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'EM01'
CASE_SPEC = CaseSpec(
    action='inspect_permission_restriction',
    event='permission_rejected',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'operator_ref', 'authorization_ref', 'restriction_ref', 'restoration_ref'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'operator_ref', 'external_authorization_id', 'restriction_id', 'restoration_ref', 'restriction_restored', 'write_guard_active')
