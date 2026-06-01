from backtrader.brokers.hft import Recorder


def test_recorder_records_snapshots_and_respects_maxlen():
    recorder = Recorder(maxlen=2)
    recorder.record(1.0, "BTC/USDT", {"status": "submitted"})
    recorder.record(2.0, "BTC/USDT", {"status": "filled"})
    recorder.record(3.0, "ETH/USDT", {"status": "filled"})

    events = recorder.snapshot()

    assert len(events) == 2
    assert events[0]["timestamp"] == 2.0
    assert events[1]["symbol"] == "ETH/USDT"


def test_recorder_clear_resets_events():
    recorder = Recorder()
    recorder.record(1.0, "BTC/USDT", {"status": "filled"})
    recorder.clear()

    assert recorder.snapshot() == []
