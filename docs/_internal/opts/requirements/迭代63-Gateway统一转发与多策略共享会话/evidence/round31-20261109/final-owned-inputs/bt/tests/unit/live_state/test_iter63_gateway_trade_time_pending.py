"""Synthetic same-trade time consistency in the durable pending stream."""
from dataclasses import replace
from pathlib import Path

import pytest

from backtrader.live_state import LiveStateCorrupt
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.live_state.test_gateway_execution_checkpoint import make_event
from tests.unit.live_state.test_gateway_execution_checkpoint import ready as ready
from tests.unit.live_state.test_gateway_pending import inputs as inputs
from tests.unit.live_state.test_iter63_gateway_trade_date_pending import dated, result


@pytest.mark.parametrize("metadata_only", [True, False])
def test_conflicting_time_rejects_whole_page_and_preserves_file(state, ready, metadata_only):
    host, binding, consumer = ready
    original = make_event(host)
    assert original.observation.trade_time == "09:00:00"
    checkpoint = host.ingest_execution_result(result(binding, consumer, [original]),
                                               expected_revision=0)
    unrelated = make_event(host, 6, fact="1" * 64, trade="2" * 64)
    conflict = dated(original, 8, fact="3" * 64, trade_time="10:00:00",
                     metadata=metadata_only, date="20261107" if metadata_only else None)
    before = Path(state.pending.path).read_bytes()
    with pytest.raises(ValueError, match="EXECUTION_TRADE_TIME_CONFLICT"):
        host.ingest_execution_result(result(binding, consumer, [unrelated, conflict], after=3),
                                     expected_revision=checkpoint.revision)
    assert Path(state.pending.path).read_bytes() == before
    reopened = GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding)
    assert reopened.load_execution_checkpoint() == checkpoint
    assert reopened.read_execution_events(after_sequence=0) == (original,)


@pytest.mark.parametrize("missing_first", [True, False])
def test_missing_time_is_not_synthesized_and_known_values_must_agree(state, ready, missing_first):
    host, binding, consumer = ready
    original = make_event(host)
    if missing_first:
        original = replace(original, observation=replace(original.observation, trade_time=None))
    checkpoint = host.ingest_execution_result(result(binding, consumer, [original]),
                                               expected_revision=0)
    metadata = dated(original, 6, trade_time="09:00:00" if missing_first else None)
    checkpoint = host.ingest_execution_result(result(binding, consumer, [metadata], after=3),
                                               expected_revision=checkpoint.revision)
    saved = host.read_execution_events(after_sequence=0)
    assert saved[0].observation.trade_time == (None if missing_first else "09:00:00")
    assert saved[1].observation.trade_time == ("09:00:00" if missing_first else None)
    equal = dated(original, 8, fact="4" * 64, trade_time="09:00:00")
    checkpoint = host.ingest_execution_result(result(binding, consumer, [equal], after=6),
                                               expected_revision=checkpoint.revision)
    before = Path(state.pending.path).read_bytes()
    conflict = dated(original, 9, fact="5" * 64, trade_time="10:00:00")
    with pytest.raises(ValueError, match="EXECUTION_TRADE_TIME_CONFLICT"):
        host.ingest_execution_result(result(binding, consumer, [conflict], after=8),
                                     expected_revision=checkpoint.revision)
    assert Path(state.pending.path).read_bytes() == before


def test_corrupted_stored_trade_times_fail_on_reopen(state, ready):
    import json

    host, binding, consumer = ready
    original = make_event(host)
    checkpoint = host.ingest_execution_result(result(binding, consumer, [original]),
                                               expected_revision=0)
    metadata = dated(original, 6, trade_time="09:00:00")
    host.ingest_execution_result(result(binding, consumer, [metadata], after=3),
                                 expected_revision=checkpoint.revision)
    path = Path(state.pending.path)
    raw = json.loads(path.read_bytes())
    raw["gateway"]["execution"]["events"][1]["observation"]["trade_time"] = "10:00:00"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(LiveStateCorrupt):
        GatewayPendingHost(state.strategy_dir, state.strategy_uuid, binding).load_execution_checkpoint()
