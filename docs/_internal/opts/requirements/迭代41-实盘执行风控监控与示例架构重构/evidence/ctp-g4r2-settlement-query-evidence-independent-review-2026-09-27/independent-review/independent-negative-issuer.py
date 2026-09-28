import runpy
import pytest

from bt_api_ctp import CtpSettlementConfirmationEvidenceBuilder
from bt_api_ctp.containers.ctp.ctp_native_query_certificate import CtpNativeQueryCertificateError

helpers = runpy.run_path("tests/test_ctp_settlement_query_evidence.py")
monkeypatch = pytest.MonkeyPatch()
try:
    producer, _api = helpers["make_logged_in_client"](monkeypatch)
    result = producer.query_settlement_confirmation_result(timeout=0.2)
    other, _api = helpers["make_logged_in_client"](monkeypatch)
    try:
        CtpSettlementConfirmationEvidenceBuilder(other).build(result)
    except CtpNativeQueryCertificateError as exc:
        print(f"wrong_issuer_rejected={exc.code}")
    else:
        raise SystemExit("wrong issuer was accepted")
finally:
    monkeypatch.undo()
