"""Regression tests for releasing a Bokeh document after client updates."""

from types import SimpleNamespace

import pytest

from backtrader.bokeh.live import client as client_module


class _DocFake:
    def __init__(self, events):
        self.events = events
        self.held = False
        self.hold_calls = 0
        self.unhold_calls = 0
        self.unhold_error = None

    def hold(self):
        self.events.append("hold")
        self.hold_calls += 1
        self.held = True

    def unhold(self):
        self.events.append("unhold")
        self.unhold_calls += 1
        if self.unhold_error is not None:
            raise self.unhold_error
        self.held = False

    def reset(self):
        self.events.clear()
        self.held = False
        self.hold_calls = 0
        self.unhold_calls = 0
        self.unhold_error = None


class _TabsFake:
    name = "tabs"

    def __init__(self, app, events):
        self.app = app
        self.events = events
        self._tabs = []

    @property
    def tabs(self):
        return self._tabs

    @tabs.setter
    def tabs(self, value):
        self.events.append("tabs_assignment")
        self.app.fail_if("tabs_assignment")
        self._tabs = value


class _DataHandlerFake:
    def __init__(self, app, events):
        self.app = app
        self.events = events

    def stop(self):
        self.events.append("old_handler_stop")
        self.app.fail_if("old_handler_stop")


class _AppFake:
    def __init__(self, events):
        self.events = events
        self.p = SimpleNamespace(use_default_tabs=False)
        self.tabs = []
        self.fail_step = None
        self.error = None

    def fail_if(self, step):
        if self.fail_step == step:
            raise self.error

    def create_figurepage(self, strategy, filldata=False):
        return 7, object()

    def update_figurepage(self, filter):
        self.events.append("update_figurepage")
        self.fail_if("update_figurepage")

    def generate_model_panels(self):
        self.events.append("generate_model_panels")
        self.fail_if("generate_model_panels")
        return [None]


def _build_client(monkeypatch):
    events = []
    doc = _DocFake(events)
    app = _AppFake(events)
    tabs = _TabsFake(app, events)
    model = SimpleNamespace(children=[[tabs]])

    class TabFake:
        def __init__(self, tab_app, figurepage, client):
            events.append("tab_constructor")
            app.fail_if("tab_constructor")

        def is_useable(self):
            events.append("tab_is_useable")
            app.fail_if("tab_is_useable")
            return True

        def get_panel(self):
            events.append("tab_get_panel")
            app.fail_if("tab_get_panel")
            return "panel"

    app.tabs = [TabFake]

    def create_model(self):
        def refresh():
            events.append("refresh")
            app.fail_if("refresh")

        return model, refresh

    def data_handler_factory(doc, app, figid, lookback, fill_gaps):
        events.append("handler_constructor")
        app.fail_if("handler_constructor")
        return _DataHandlerFake(app, events)

    monkeypatch.setattr(client_module, "BOKEH_AVAILABLE", True)
    monkeypatch.setattr(client_module.LiveClient, "_createmodel", create_model)
    monkeypatch.setattr(client_module, "LiveDataHandler", data_handler_factory)
    client = client_module.LiveClient(doc, app, strategy=object(), lookback=20)
    return client, doc, app, tabs, events


def test_live_client_updatemodel_preserves_success_order_and_unholds(monkeypatch):
    client, doc, _, tabs, events = _build_client(monkeypatch)

    assert not doc.held
    assert doc.hold_calls == 1
    assert doc.unhold_calls == 1
    assert events == [
        "hold",
        "update_figurepage",
        "generate_model_panels",
        "tab_constructor",
        "tab_is_useable",
        "tab_get_panel",
        "tabs_assignment",
        "handler_constructor",
        "refresh",
        "unhold",
    ]
    assert tabs.tabs == ["panel"]
    assert isinstance(client._datahandler, _DataHandlerFake)


@pytest.mark.parametrize(
    "fail_step",
    [
        "update_figurepage",
        "generate_model_panels",
        "tab_constructor",
        "tab_is_useable",
        "tab_get_panel",
        "tabs_assignment",
        "old_handler_stop",
        "handler_constructor",
        "refresh",
    ],
)
def test_live_client_updatemodel_unholds_and_reraises_original_error(
    monkeypatch, fail_step
):
    client, doc, app, _, events = _build_client(monkeypatch)
    doc.reset()
    error = RuntimeError("original update failure")
    app.fail_step = fail_step
    app.error = error

    with pytest.raises(RuntimeError) as raised:
        client.updatemodel()

    assert raised.value is error
    assert doc.hold_calls == 1
    assert doc.unhold_calls == 1
    assert not doc.held
    assert events[0] == "hold"
    assert events[-1] == "unhold"


def test_live_client_updatemodel_keeps_update_error_when_unhold_also_fails(
    monkeypatch,
):
    client, doc, app, _, events = _build_client(monkeypatch)
    doc.reset()
    update_error = RuntimeError("original update failure")
    unhold_error = ValueError("secondary unhold failure")
    app.fail_step = "update_figurepage"
    app.error = update_error
    doc.unhold_error = unhold_error

    with pytest.raises(RuntimeError) as raised:
        client.updatemodel()

    assert raised.value is update_error
    assert raised.value.__cause__ is unhold_error
    assert doc.hold_calls == 1
    assert doc.unhold_calls == 1
    assert events[-1] == "unhold"


def test_live_client_updatemodel_propagates_unhold_error_after_success(monkeypatch):
    client, doc, _, _, _ = _build_client(monkeypatch)
    doc.reset()
    unhold_error = ValueError("unhold failed after successful update")
    doc.unhold_error = unhold_error

    with pytest.raises(ValueError) as raised:
        client.updatemodel()

    assert raised.value is unhold_error
    assert doc.hold_calls == 1
    assert doc.unhold_calls == 1
