"""MT5 L01 strict live certification contract."""

from __future__ import annotations

from _certification.cases import CaseSpec
from _certification.models import Risk


CASE_ID = 'L01'
CASE_SPEC = CaseSpec(
    action='inspect_trade_log',
    event='trade_log_correlated',
    risk=Risk.READ,
    required=('external_ref', 'evidence_window_id', 'trace_ref', 'order_ref', 'trade_ref'),
    optional=(),
)
PROOF_FIELDS = ('external_ref', 'trace_id', 'order_ref', 'trade_id', 'submission_log_id', 'execution_log_id', 'submission_log', 'execution_log')
