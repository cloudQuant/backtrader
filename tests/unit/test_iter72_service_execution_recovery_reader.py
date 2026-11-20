"""Preserve lazy owner-book reader adaptation in service recovery."""

import pytest

pytest.importorskip("bt_api_py", reason="needs the bt_api_py SDK")

from backtrader.service import _service_execution_recovery as recovery


class _RecoveryFlow:
    def __init__(self):
        self.namespace = object()
        self.received_reader = None
        self.page_limit = None
        self.max_pages = None

    def initialize(self, *, owner_book_reader=None, page_limit=128, max_pages=64):
        self.received_reader = owner_book_reader
        self.page_limit = page_limit
        self.max_pages = max_pages
        return {"initialized": True}


class _RecoveryAdapter(recovery.ServiceExecutionRecoveryMixin):
    def __init__(self, flow):
        self._recovery_flow = flow


def test_initialize_recovery_keeps_owner_book_reader_lazy_and_bound(monkeypatch):
    source_snapshot = {"source": "fixture"}
    owner_payload = {"owner": "normalized"}
    calls = []

    def source_reader():
        calls.append("source")
        return source_snapshot

    def normalize(snapshot):
        calls.append(("normalize", snapshot))
        return owner_payload

    monkeypatch.setattr(recovery, "_owner_book_payload", normalize)
    flow = _RecoveryFlow()
    adapter = _RecoveryAdapter(flow)

    result = adapter.initialize_recovery(
        owner_book_reader=source_reader,
        page_limit=7,
        max_pages=3,
    )

    assert result == {"initialized": True}
    assert calls == []
    assert flow.received_reader is not source_reader
    assert flow.page_limit == 7
    assert flow.max_pages == 3
    assert flow.received_reader() is owner_payload
    assert calls == ["source", ("normalize", source_snapshot)]


def test_initialize_recovery_forwards_missing_owner_book_reader_unchanged():
    flow = _RecoveryFlow()
    adapter = _RecoveryAdapter(flow)

    assert adapter.initialize_recovery() == {"initialized": True}
    assert flow.received_reader is None
