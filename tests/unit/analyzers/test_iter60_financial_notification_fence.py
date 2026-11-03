"""Financial callback trees must not cross a strategy-account rebinding."""

from types import SimpleNamespace

import pytest

from backtrader.analyzer import Analyzer


@pytest.mark.parametrize("method,args", [
    ("_notify_cashvalue", (1, 2)),
    ("_notify_fund", (1, 2, 3, 4)),
])
def test_child_scope_change_stops_next_child_and_parent(method, args):
    strategy = SimpleNamespace(account_book=None)
    calls = []
    root = Analyzer.__new__(Analyzer)
    root.strategy = strategy
    first = Analyzer.__new__(Analyzer)
    first.strategy = strategy
    first._children = []
    second = Analyzer.__new__(Analyzer)
    second.strategy = strategy
    second._children = []
    root._children = [first, second]
    callback = method[len("_notify_"):]

    def change_scope(*_args):
        calls.append("first")
        strategy.account_book = object()

    setattr(first, "notify_" + callback, change_scope)
    setattr(second, "notify_" + callback, lambda *_args: calls.append("second"))
    setattr(root, "notify_" + callback, lambda *_args: calls.append("parent"))

    with pytest.raises(RuntimeError, match="STRATEGY_FINANCIAL_SCOPE_CHANGED"):
        getattr(root, method)(*args)
    assert calls == ["first"]


@pytest.mark.parametrize("method,args", [
    ("_notify_cashvalue", (1, 2)),
    ("_notify_fund", (1, 2, 3, 4)),
])
def test_unchanged_scope_keeps_child_then_parent_callback_order(method, args):
    strategy = SimpleNamespace(account_book=object())
    calls = []
    root = Analyzer.__new__(Analyzer)
    root.strategy = strategy
    child = Analyzer.__new__(Analyzer)
    child.strategy = strategy
    child._children = []
    root._children = [child]
    callback = method[len("_notify_"):]
    setattr(child, "notify_" + callback, lambda *_args: calls.append("child"))
    setattr(root, "notify_" + callback, lambda *_args: calls.append("parent"))

    getattr(root, method)(*args)
    assert calls == ["child", "parent"]


@pytest.mark.parametrize("method,args", [
    ("_notify_cashvalue", (900, 1000)),
    ("_notify_fund", (900, 1000, 1, 2)),
])
@pytest.mark.parametrize("parent_has_strategy", [True, False])
def test_child_of_different_or_unknown_strategy_never_receives_values(method, args, parent_has_strategy):
    root = Analyzer.__new__(Analyzer)
    root.strategy = SimpleNamespace(account_book=None) if parent_has_strategy else None
    child = Analyzer.__new__(Analyzer)
    child.strategy = SimpleNamespace(account_book=object())
    child._children = []
    root._children = [child]
    calls = []
    callback = method[len("_notify_"):]
    setattr(child, "notify_" + callback, lambda *_args: calls.append("child"))
    setattr(root, "notify_" + callback, lambda *_args: calls.append("parent"))

    with pytest.raises(RuntimeError, match="STRATEGY_FINANCIAL_SCOPE_CHANGED"):
        getattr(root, method)(*args)
    assert calls == []


@pytest.mark.parametrize("method,args", [
    ("_notify_cashvalue", (1, 2)),
    ("_notify_fund", (1, 2, 3, 4)),
])
def test_uninitialized_parent_and_child_keep_callback_order(method, args):
    root = Analyzer.__new__(Analyzer)
    root.strategy = None
    child = Analyzer.__new__(Analyzer)
    child.strategy = None
    child._children = []
    root._children = [child]
    calls = []
    callback = method[len("_notify_"):]
    setattr(child, "notify_" + callback, lambda *_args: calls.append("child"))
    setattr(root, "notify_" + callback, lambda *_args: calls.append("parent"))

    getattr(root, method)(*args)
    assert calls == ["child", "parent"]


@pytest.mark.parametrize("method,args", [
    ("_notify_cashvalue", (1, 2)),
    ("_notify_fund", (1, 2, 3, 4)),
])
def test_child_owner_change_is_detected_before_parent_callback(method, args):
    strategy = SimpleNamespace(account_book=None)
    root = Analyzer.__new__(Analyzer)
    root.strategy = strategy
    child = Analyzer.__new__(Analyzer)
    child.strategy = strategy
    child._children = []
    root._children = [child]
    calls = []
    callback = method[len("_notify_"):]

    def change_owner(*_args):
        calls.append("child")
        child.strategy = SimpleNamespace(account_book=object())

    setattr(child, "notify_" + callback, change_owner)
    setattr(root, "notify_" + callback, lambda *_args: calls.append("parent"))
    with pytest.raises(RuntimeError, match="STRATEGY_FINANCIAL_SCOPE_CHANGED"):
        getattr(root, method)(*args)
    assert calls == ["child"]
