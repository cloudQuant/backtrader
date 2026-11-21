"""Dynamic strict-context and owner lookup must retain normal Python semantics."""

import pytest

from backtrader.linebuffer import LineBuffer, _factor_context_for_line
from backtrader.lineiterator import LineIteratorMixin


def _old_line_lookup(line):
    """Reference the committed owner-walk semantics for an inactive context."""
    try:
        context = getattr(line, "_factor_strict_context", None)
        if context is not None:
            return context
        current, seen, first = line, set(), True
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if not first:
                context = getattr(current, "_factor_strict_context", None)
                if context is not None:
                    return context
            first = False
            owner = getattr(current, "_owner", None)
            ref = getattr(owner, "_owner_ref", None) if owner is not None else None
            current = ref if ref is not None else owner
    except ReferenceError:
        pass
    return None


def _old_callback_lookup(current):
    """Reference the committed callback walk, including object lifetimes."""
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        context = getattr(current, "_factor_strict_context", None)
        if context is not None:
            return context
        owner = getattr(current, "_owner", None)
        if owner is None:
            lines = getattr(current, "lines", None)
            owner = getattr(lines, "_owner_ref", None) if lines is not None else None
        if owner is not None:
            ref = getattr(owner, "_owner_ref", None)
            current = ref if ref is not None else owner
        else:
            current = None
    return None


def test_context_added_to_class_or_parent_after_lookup():
    class Base:
        pass

    class Child(Base):
        pass

    node = Child()
    assert _factor_context_for_line(node) is None
    marker = object()
    Base._factor_strict_context = marker
    assert _factor_context_for_line(node) is _old_line_lookup(node) is marker
    del Base._factor_strict_context
    assert _factor_context_for_line(node) is None


def test_linebuffer_class_context_after_instance_creation():
    class LateLine(LineBuffer):
        pass

    line = LateLine()
    assert _factor_context_for_line(line) is None
    marker = object()
    LateLine._factor_strict_context = marker
    assert _factor_context_for_line(line) is _old_line_lookup(line) is marker


@pytest.mark.parametrize("attribute", ["_owner", "_owner_ref"])
def test_late_owner_descriptor_and_dynamic_owner_hops(attribute):
    class Node:
        pass

    line, intermediary, target = Node(), Node(), Node()
    marker = object()
    target._factor_strict_context = marker
    if attribute == "_owner_ref":
        line._owner = intermediary
        assert _factor_context_for_line(line) is None
        Node._owner_ref = property(lambda self: target if self is intermediary else None)
    else:
        assert _factor_context_for_line(line) is None
        Node._owner = property(lambda self: target if self is line else None)
    assert _factor_context_for_line(line) is _old_line_lookup(line) is marker


def test_late_context_descriptor_and_getattribute_changes():
    class Node:
        pass

    node = Node()
    assert _factor_context_for_line(node) is None
    marker = object()
    Node._factor_strict_context = property(lambda self: marker)
    assert _factor_context_for_line(node) is marker
    del Node._factor_strict_context
    Node.__getattr__ = lambda self, name: marker if name == "_factor_strict_context" else None
    assert _factor_context_for_line(node) is marker


def test_data_descriptor_overrides_existing_instance_context():
    class Node:
        pass

    node = Node()
    node._factor_strict_context = old = object()
    assert _factor_context_for_line(node) is old
    marker = object()
    Node._factor_strict_context = property(lambda self: marker)
    assert _factor_context_for_line(node) is _old_line_lookup(node) is marker


def test_runtime_getattribute_is_rechecked():
    class Node:
        pass

    node = Node()
    assert _factor_context_for_line(node) is None
    marker = object()

    def getattribute(self, name):
        if name == "_factor_strict_context":
            return marker
        return object.__getattribute__(self, name)

    Node.__getattribute__ = getattribute
    assert _factor_context_for_line(node) is _old_line_lookup(node) is marker


def test_callback_sees_late_class_and_owner_changes():
    class Callback(LineIteratorMixin):
        pass

    class Owner:
        pass

    callback, owner = Callback(), Owner()
    callback._owner = owner
    assert callback._factor_strict_context_for_callback() is None
    marker = object()
    Owner._factor_strict_context = property(lambda self: marker)
    assert callback._factor_strict_context_for_callback() is marker
    del Owner._factor_strict_context
    Callback._factor_strict_context = marker
    assert callback._factor_strict_context_for_callback() is marker


def test_callback_lines_owner_ref_is_read_dynamically():
    class Callback(LineIteratorMixin):
        pass

    class Lines:
        pass

    class Owner:
        pass

    callback, lines, owner = Callback(), Lines(), Owner()
    callback.lines = lines
    owner._factor_strict_context = marker = object()
    assert callback._factor_strict_context_for_callback() is None
    Lines._owner_ref = property(lambda self: owner)
    assert callback._factor_strict_context_for_callback() is marker


def test_callback_sees_owner_ref_descriptor_after_first_lookup():
    class Callback(LineIteratorMixin):
        pass

    class Owner:
        pass

    callback, owner, target = Callback(), Owner(), Owner()
    callback._owner = owner
    target._factor_strict_context = marker = object()
    assert callback._factor_strict_context_for_callback() is None
    Owner._owner_ref = property(lambda self: target if self is owner else None)
    assert callback._factor_strict_context_for_callback() is marker


@pytest.mark.parametrize("depth", range(5))
def test_callback_matches_committed_lookup_order_and_cycles(depth):
    events = []

    class Callback(LineIteratorMixin):
        def __getattribute__(self, name):
            if name in ("_factor_strict_context", "_owner", "_owner_ref", "lines"):
                events.append((id(self), name))
            return object.__getattribute__(self, name)

    nodes = [Callback() for _ in range(depth + 1)]
    for node, owner in zip(nodes, nodes[1:]):
        node._owner = owner
    nodes[-1]._owner = nodes[0]

    assert _old_callback_lookup(nodes[0]) is None
    expected = events[:]
    events.clear()
    assert nodes[0]._factor_strict_context_for_callback() is None
    assert events == expected


def test_runtime_descriptor_exception_propagates():
    class Node:
        @property
        def _factor_strict_context(self):
            raise ValueError("context failure")

    with pytest.raises(ValueError, match="context failure"):
        _factor_context_for_line(Node())


@pytest.mark.parametrize("callback", [False, True])
def test_temporary_owner_lifetime_preserves_context_resolution(callback):
    released = []
    marker = object()

    class Second:
        @property
        def _factor_strict_context(self):
            return marker if released else None

    second = Second()

    class First:
        @property
        def _owner(self):
            return second

        def __del__(self):
            released.append(True)

    class Start(LineIteratorMixin):
        @property
        def _owner(self):
            return First()

    node = Start()
    if callback:
        assert _old_callback_lookup(node) is marker
        released.clear()
        assert node._factor_strict_context_for_callback() is marker
    else:
        assert _old_line_lookup(node) is marker
        released.clear()
        assert _factor_context_for_line(node) is marker
