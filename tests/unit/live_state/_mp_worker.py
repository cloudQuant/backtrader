"""Spawned-process worker for the cross-process sequence test."""

import os


def allocate_many(strategy_dir, strategy_uuid, count, barrier, results):
    from backtrader.live_state import SequenceAllocator

    allocator = SequenceAllocator(strategy_dir, strategy_uuid, lock_timeout=60.0)
    barrier.wait(timeout=60)
    allocated = [allocator.allocate(ref=1000 + index) for index in range(count)]
    results.put((os.getpid(), allocated))


def hold_coordination(strategy_dir, held, release, crash):
    """E020: hold the strategy-root coordination lock from another process."""
    from backtrader.live_state._common import StatePaths
    from backtrader.live_state.coordination import coordinated

    with coordinated(StatePaths(strategy_dir), timeout=30.0):
        held.set()
        release.wait(30)
        if crash:
            os._exit(3)  # the OS releases the lock with the process
