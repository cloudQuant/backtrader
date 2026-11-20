"""Safe, contextual logging for Bokeh RecorderAnalyzer line fallbacks."""

import logging
from unittest.mock import Mock

import pytest

from backtrader.bokeh.analyzers import recorder
from backtrader.lineiterator import LineIterator


class _BrokenLine:
    def __len__(self):
        return 1

    def __getitem__(self, index):
        raise RuntimeError("api_secret=synthetic-recorder-secret")


class _Lines:
    def getlinealiases(self):
        return ("close",)

    @property
    def close(self):
        return _BrokenLine()


class _BrokenIndicator:
    def __init__(self):
        self.lines = _Lines()


class _GoodLine:
    def __len__(self):
        return 1

    def __getitem__(self, index):
        return 12.5


class _GoodLines:
    def getlinealiases(self):
        return ("close",)

    @property
    def close(self):
        return _GoodLine()


class _RecorderHarness:
    _record_lineiterators = recorder.RecorderAnalyzer._record_lineiterators

    def __init__(self, obj):
        self.obj = obj

    def _iter_lineiterators(self, ltype):
        yield self.obj


class _MemoryHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def test_line_fallback_logs_lazy_object_and_line_context_without_exception_payload():
    obj = _BrokenIndicator()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"_BrokenIndicator#{id(obj)}"
    assert store[obj_name]["close"] == [None]
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.levelno == logging.WARNING
    assert record.msg == "Failed to record object '%s' line[%d] '%s'; storing None"
    assert record.args == ("_BrokenIndicator#" + str(id(obj)), 0, "close")
    assert record.exc_info is None
    assert "close" in record.getMessage()
    assert "_BrokenIndicator#" + str(id(obj)) in record.getMessage()
    assert "api_secret" not in record.getMessage()
    assert "synthetic-recorder-secret" not in record.getMessage()


class _UnformattableName:
    def __init__(self):
        self.calls = []

    def __str__(self):
        self.calls.append("str")
        raise AssertionError("name must not be stringified")

    def __format__(self, format_spec):
        self.calls.append("format")
        raise AssertionError("name must not be formatted")

    def __repr__(self):
        self.calls.append("repr")
        raise AssertionError("name must not be represented")


def test_line_fallback_sanitizes_control_names_and_does_not_format_custom_names():
    unformattable_name = _UnformattableName()

    class _NameMeta(type):
        def __getattribute__(cls, name):
            if name == "__name__":
                return unformattable_name
            return super().__getattribute__(name)

    raw_type_name = "Custom\nIndicator" + ("T" * 80)
    raw_line_alias = "close\nalias" + ("L" * 80)
    custom_indicator_type = _NameMeta(raw_type_name, (_BrokenIndicator,), {})
    obj = custom_indicator_type()

    class _ControlLines:
        def getlinealiases(self):
            return (raw_line_alias,)

        def __getattr__(self, name):
            raise RuntimeError("sensitive line failure")

    obj.lines = _ControlLines()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"{raw_type_name}#{id(obj)}"
    assert store[obj_name][raw_line_alias] == [None]
    assert len(handler.records) == 1
    record = handler.records[0]
    safe_type_name = "Custom?Indicator" + ("T" * (64 - len("Custom\nIndicator"))) + "…"
    safe_line_alias = "close?alias" + ("L" * (64 - len("close\nalias"))) + "…"
    safe_object_label = safe_type_name + "#" + str(id(obj))
    assert record.args == (safe_object_label, 0, safe_line_alias)
    message = record.getMessage()
    assert safe_object_label in message
    assert safe_line_alias in message
    assert len(record.args[0].split("#", 1)[0]) == 65
    assert len(record.args[2]) == 65
    assert "\n" not in message
    assert "sensitive line failure" not in message
    assert unformattable_name.calls == []


def test_line_fallback_uses_index_for_non_string_alias_without_stringifying_it():
    class _UnstringifiableAlias:
        def __init__(self):
            self.calls = []

        def __str__(self):
            self.calls.append("str")
            raise AssertionError("alias must not be stringified")

        def __repr__(self):
            self.calls.append("repr")
            raise AssertionError("alias must not be represented")

    alias = _UnstringifiableAlias()

    class _NonStringAliasLines:
        def getlinealiases(self):
            return (alias,)

    obj = _BrokenIndicator()
    obj.lines = _NonStringAliasLines()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"_BrokenIndicator#{id(obj)}"
    assert store[obj_name][alias] == [None]
    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.args == ("_BrokenIndicator#" + str(id(obj)), 0, "non-string")
    assert "line[0] 'non-string'" in record.getMessage()
    assert alias.calls == []


def test_line_fallback_preserves_string_class_name_alias_from_metaclass():
    class _PublicNameMeta(type):
        def __getattribute__(cls, name):
            if name == "__name__":
                return "PublicIndicatorName"
            return super().__getattribute__(name)

    custom_indicator_type = _PublicNameMeta(
        "InternalIndicatorName", (_BrokenIndicator,), {}
    )
    obj = custom_indicator_type()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"PublicIndicatorName#{id(obj)}"
    assert store[obj_name]["close"] == [None]
    assert handler.records[0].args == (obj_name, 0, "close")


def test_line_fallback_normalizes_str_subclass_class_name_without_user_formatting():
    class _UnformattableString(str):
        def __new__(cls, value, calls):
            result = super().__new__(cls, value)
            result.calls = calls
            return result

        def __str__(self):
            self.calls.append("str")
            raise AssertionError("name must not be stringified")

        def __format__(self, format_spec):
            self.calls.append("format")
            raise AssertionError("name must not be formatted")

        def __repr__(self):
            self.calls.append("repr")
            raise AssertionError("name must not be represented")

        def __len__(self):
            self.calls.append("len")
            raise AssertionError("name length must use the base str method")

        def __getitem__(self, index):
            self.calls.append("getitem")
            raise AssertionError("name slicing must use the base str method")

    class _SubclassNamedIndicator(_BrokenIndicator):
        pass

    calls = []
    _SubclassNamedIndicator.__name__ = _UnformattableString("PublicIndicator", calls)
    obj = _SubclassNamedIndicator()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"PublicIndicator#{id(obj)}"
    assert store[obj_name]["close"] == [None]
    assert handler.records[0].args == (obj_name, 0, "close")
    assert calls == []


def test_line_fallback_sanitizes_str_subclass_alias_without_user_formatting():
    class _UnformattableAlias(str):
        def __new__(cls, value, calls):
            result = super().__new__(cls, value)
            result.calls = calls
            return result

        def __str__(self):
            self.calls.append("str")
            raise AssertionError("alias must not be stringified")

        def __format__(self, format_spec):
            self.calls.append("format")
            raise AssertionError("alias must not be formatted")

        def __repr__(self):
            self.calls.append("repr")
            raise AssertionError("alias must not be represented")

        def __len__(self):
            self.calls.append("len")
            raise AssertionError("alias length must use the base str method")

        def __getitem__(self, index):
            self.calls.append("getitem")
            raise AssertionError("alias slicing must use the base str method")

    calls = []
    alias = _UnformattableAlias("close", calls)

    class _SubclassAliasLines:
        def getlinealiases(self):
            return (alias,)

        @property
        def close(self):
            return _BrokenLine()

    obj = _BrokenIndicator()
    obj.lines = _SubclassAliasLines()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"_BrokenIndicator#{id(obj)}"
    assert store[obj_name][alias] == [None]
    assert handler.records[0].args == (obj_name, 0, "close")
    assert calls == []


def test_successful_line_recording_does_not_build_log_identifiers(monkeypatch):
    obj = _BrokenIndicator()
    obj.lines = _GoodLines()
    recorder_harness = _RecorderHarness(obj)

    def unexpected_log_identifier(*args):
        pytest.fail("log identifier was built on the successful path")

    monkeypatch.setattr(recorder, "_safe_log_identifier", unexpected_log_identifier)
    store = {}
    recorder_harness._record_lineiterators(store, LineIterator.IndType)

    obj_name = f"_BrokenIndicator#{id(obj)}"
    assert store[obj_name]["close"] == [12.5]


def test_mock_spec_str_name_and_alias_use_real_type_checks():
    mock_name = Mock(spec=str)
    alias = Mock(spec=str)
    assert isinstance(mock_name, str)
    assert isinstance(alias, str)
    assert not issubclass(type(mock_name), str)
    assert not issubclass(type(alias), str)

    class _MockNameMeta(type):
        def __getattribute__(cls, name):
            if name == "__name__":
                return mock_name
            return super().__getattribute__(name)

    custom_indicator_type = _MockNameMeta(
        "InternalMockNameIndicator", (_BrokenIndicator,), {}
    )
    obj = custom_indicator_type()

    class _MockAliasLines:
        def getlinealiases(self):
            return (alias,)

    obj.lines = _MockAliasLines()
    recorder_harness = _RecorderHarness(obj)
    store = {}
    logger = recorder.logger
    handler = _MemoryHandler()
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        recorder_harness._record_lineiterators(store, LineIterator.IndType)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    obj_name = f"InternalMockNameIndicator#{id(obj)}"
    assert store[obj_name][alias] == [None]
    assert len(handler.records) == 1
    assert handler.records[0].args == (obj_name, 0, "non-string")
    assert alias.mock_calls == []
    assert mock_name.mock_calls == []
