"""Bounded LRU and copy/concurrency semantics for StoreBarHistoryCache."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from backtrader.stores._bar_history_cache import StoreBarHistoryCache


def _make_cache(*, preserve_raw_bars=False, max_query_entries=None):
    kwargs = {
        "preserve_raw_bars": preserve_raw_bars,
        "normalize_bar": lambda bar: dict(bar),
    }
    if max_query_entries is not None:
        kwargs["max_query_entries"] = max_query_entries
    return StoreBarHistoryCache(**kwargs)


def _request(cache, dataname, cursor):
    timeframe = "minutes"
    compression = 1
    since = f"cursor-{cursor}"
    limit = None
    key = cache.request_key(dataname, timeframe, compression, since, limit)
    return key, (dataname, timeframe, compression, since, limit)


def _cache_request(cache, dataname, cursor):
    key, args = _request(cache, dataname, cursor)
    cache.cache_result(dataname, key, False, [{"cursor": cursor, "nested": [cursor]}])
    return key, args


def test_existing_constructor_defaults_to_bounded_query_cache():
    cache = _make_cache()
    assert cache._max_query_entries == StoreBarHistoryCache.DEFAULT_MAX_QUERY_ENTRIES
    assert cache._max_query_entries > 0


def test_query_cache_is_lru_bounded_without_evicting_default_history():
    cache = _make_cache(max_query_entries=2)
    cache.set_history("DEFAULT", [{"close": 7.0}])
    key_a, args_a = _cache_request(cache, "A", "a")
    key_b, args_b = _cache_request(cache, "B", "b")

    # A hit refreshes A, so inserting C evicts B, the least-recently-used row.
    assert cache.lookup(*args_a)[0] is True
    key_c, args_c = _cache_request(cache, "C", "c")

    assert len(cache._query_cache) == 2
    assert key_a in cache._query_cache
    assert key_c in cache._query_cache
    assert key_b not in cache._query_cache
    assert cache.lookup(*args_b)[0] is False
    assert cache.lookup(*args_a)[0] is True
    assert cache.lookup(*args_c)[0] is True
    assert cache.cached_default_history("DEFAULT") == [{"close": 7.0}]


def test_query_hits_return_independent_copies_across_eviction():
    for preserve_raw_bars in (False, True):
        cache = _make_cache(
            preserve_raw_bars=preserve_raw_bars,
            max_query_entries=1,
        )
        key_a, args_a = _cache_request(cache, "A", "a")

        hit, _key, _default, first = cache.lookup(*args_a)
        assert hit is True
        first[0]["nested"].append("caller mutation")
        hit, _key, _default, second = cache.lookup(*args_a)
        assert hit is True
        assert second == [{"cursor": "a", "nested": ["a"]}]
        assert second[0] is not first[0]

        _cache_request(cache, "B", "b")
        assert key_a not in cache._query_cache
        assert first[0]["nested"] == ["a", "caller mutation"]


def test_concurrent_lru_access_and_default_snapshots_are_safe():
    cache = _make_cache(max_query_entries=8)
    cache.set_history(
        "DEFAULT",
        [{"generation": 0, "index": index} for index in range(20)],
    )

    def exercise(worker):
        for step in range(250):
            cursor = (worker * 13 + step) % 24
            dataname = f"SYM-{cursor % 5}"
            key, args = _request(cache, dataname, cursor)
            if step % 2 == 0:
                cache.cache_result(
                    dataname,
                    key,
                    False,
                    [{"cursor": cursor, "nested": [worker, step]}],
                )
            hit, _key, _default, rows = cache.lookup(*args)
            if hit:
                assert len(rows) == 1
                assert rows[0]["cursor"] == cursor
                assert len(rows[0]["nested"]) == 2
                rows[0]["nested"].append("private")

            if step % 7 == 0:
                generation = worker * 1000 + step
                cache.set_history(
                    "DEFAULT",
                    [
                        {"generation": generation, "index": index}
                        for index in range(20)
                    ],
                )
            snapshot = cache.cached_default_history("DEFAULT")
            if snapshot:
                generation = snapshot[0]["generation"]
                assert all(row["generation"] == generation for row in snapshot)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(exercise, range(8)))

    with cache._lock:
        assert len(cache._query_cache) <= cache._max_query_entries


def test_query_cache_capacity_requires_positive_exact_integer():
    for invalid in (0, -1):
        try:
            _make_cache(max_query_entries=invalid)
        except ValueError as exc:
            assert str(exc) == "max_query_entries must be positive"
        else:
            raise AssertionError("nonpositive query capacity was accepted")

    for invalid in (True, 1.0, "2"):
        try:
            _make_cache(max_query_entries=invalid)
        except TypeError as exc:
            assert str(exc) == "max_query_entries must be an exact integer"
        else:
            raise AssertionError("non-integer query capacity was accepted")
