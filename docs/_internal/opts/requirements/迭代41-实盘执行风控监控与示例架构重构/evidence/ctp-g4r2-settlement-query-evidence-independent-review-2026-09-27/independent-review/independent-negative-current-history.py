from dataclasses import replace
import runpy
import pytest

from bt_api_ctp import CtpSettlementConfirmationEvidenceBuilder
from bt_api_ctp.containers.ctp.ctp_native_query_certificate import CtpNativeQueryCertificateError

helpers = runpy.run_path("tests/test_ctp_settlement_query_evidence.py")
monkeypatch = pytest.MonkeyPatch()
try:
    client, _api = helpers["make_logged_in_client"](monkeypatch)
    result = client.query_settlement_confirmation_result(timeout=0.2)
    original = client.get_query_result

    def mismatched_current(request_id):
        current = original(request_id)
        return replace(current, request_id=request_id + 1)

    monkeypatch.setattr(client, "get_query_result", mismatched_current)
    try:
        CtpSettlementConfirmationEvidenceBuilder(client).build(result)
    except CtpNativeQueryCertificateError as exc:
        print(f"current_history_mismatch_rejected={exc.code}")
    else:
        raise SystemExit("mismatched current query history was accepted")
finally:
    monkeypatch.undo()
