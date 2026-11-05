"""Spawned-process worker for the cross-process sequence test."""

import os


def allocate_many(strategy_dir, strategy_uuid, count, barrier, results):
    from backtrader.live_state import SequenceAllocator

    allocator = SequenceAllocator(strategy_dir, strategy_uuid, lock_timeout=60.0)
    barrier.wait(timeout=60)
    allocated = [allocator.allocate(ref=1000 + index) for index in range(count)]
    results.put((os.getpid(), allocated))
