"""Iteration 63 (SimNow 63.09, 2026-11-10): validated-content cache for pending.json.

A 0.5 MB Gateway pending state was re-validated on every read (~0.13 s each)
and the broker reads it several times per bar, so one bar took seconds and
every feed went stale. Validation is now skipped only for bytes identical to
the last validated content of the same path and strategy.
"""

import json
import os
import uuid

import pytest

from backtrader.live_state import StrategyStateDir
from backtrader.live_state import pending as pending_module
from backtrader.live_state.atomic import LiveStateCorrupt, LiveStateIdentityMismatch
from backtrader.live_state.pending import PendingCommandStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "strategy"
    root.mkdir()
    state = StrategyStateDir.initialize(root)
    calls = []
    real = pending_module.validate_pending_state

    def counting(raw, path, strategy_uuid):
        calls.append(path)
        return real(raw, path, strategy_uuid)

    monkeypatch.setattr(pending_module, "validate_pending_state", counting)
    monkeypatch.setattr(pending_module, "_VALIDATED_DIGESTS", {})
    return PendingCommandStore(state.strategy_dir, state.strategy_uuid), calls


def test_identical_bytes_are_validated_once_and_each_load_is_independent(store):
    pending, calls = store
    first = pending._load()
    second = pending._load()
    assert len(calls) == 1
    assert first == second and first is not second
    first["history"].append({"mutated": True})
    assert pending._load() == second  # a caller's mutation never leaks into later loads


def test_changed_bytes_are_validated_again(store):
    pending, calls = store
    pending._load()
    path = pending.paths.pending
    data = json.loads(open(path, encoding="utf-8").read())
    with open(path, "w", encoding="utf-8") as handle:  # same content, different bytes
        json.dump(data, handle, indent=2)
    pending._load()
    assert len(calls) == 2
    pending._load()
    assert len(calls) == 2


def test_tampered_content_still_fails_after_a_cached_valid_load(store):
    pending, calls = store
    pending._load()
    path = pending.paths.pending
    data = json.loads(open(path, encoding="utf-8").read())
    data["unexpected"] = 1
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    with pytest.raises(LiveStateCorrupt):
        pending._load()
    with pytest.raises(LiveStateCorrupt):
        pending._load()  # an invalid digest is never cached


def test_cache_is_keyed_by_strategy_identity(store):
    pending, calls = store
    pending._load()
    strategy_dir = os.path.dirname(os.path.dirname(pending.paths.pending))
    other = PendingCommandStore(strategy_dir, str(uuid.uuid4()))
    with pytest.raises(LiveStateIdentityMismatch):
        other._load()
    assert len(calls) == 2
